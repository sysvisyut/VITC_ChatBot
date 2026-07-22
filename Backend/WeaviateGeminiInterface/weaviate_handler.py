import os
import json
import weaviate
from pathlib import Path
from typing import List
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
from weaviate.exceptions import WeaviateQueryError, WeaviateConnectionError
from weaviate.classes.query import Filter

import threading
import os

# Fix HuggingFace tokenizers crashing in FastAPI threadpools
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ---------------------------------------------------------------------------
# Cross-encoder singleton — loaded once, reused across all queries
# ---------------------------------------------------------------------------

_cross_encoder = None
_encoder_lock = threading.Lock()
_inference_lock = threading.Lock()

def _get_cross_encoder():
    """Lazy-load the cross-encoder model (downloads ~80 MB on first call)."""
    global _cross_encoder
    if _cross_encoder is None:
        with _encoder_lock:
            if _cross_encoder is None:
                from sentence_transformers import CrossEncoder
                print("Loading cross-encoder model (first call only)...")
                _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                print("✅ Cross-encoder ready.")
    return _cross_encoder


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect_to_weaviate():
    """Connects to Weaviate Cloud and returns the client object."""
    try:
        WEAVIATE_URL = os.getenv("WEAVIATE_URL")
        WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
        if not WEAVIATE_URL or not WEAVIATE_API_KEY:
            print("❌ WEAVIATE_URL / WEAVIATE_API_KEY not set in environment.")
            return None
        print("Connecting to Weaviate Cloud...")
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=WEAVIATE_URL,
            auth_credentials=Auth.api_key(WEAVIATE_API_KEY),
            skip_init_checks=True,  # gRPC health-check DNS issues on some networks
        )
        if not client.is_ready():
            print("❌ Could not connect to Weaviate. Check your credentials.")
            return None
        print("✅ Weaviate connection successful.")
        return client
    except WeaviateConnectionError as e:
        print(f"❌ Weaviate connection error: {e}")
        return None


# ---------------------------------------------------------------------------
# Schema / collection management
# ---------------------------------------------------------------------------

def get_or_create_collection(client, collection_name="VIT_docs", fresh_start=False):
    """
    Gets or creates the Weaviate collection.
    If fresh_start=True the collection is wiped and recreated (full re-ingestion).
    """
    if fresh_start and client.collections.exists(collection_name):
        print(f"Deleting existing collection '{collection_name}'...")
        client.collections.delete(collection_name)

    if not client.collections.exists(collection_name):
        print(f"Collection '{collection_name}' not found. Creating with full schema...")
        try:
            client.collections.create(
                name=collection_name,
                vector_config=Configure.Vectors.text2vec_weaviate(),
                properties=[
                    # Core content
                    Property(name="text_chunk",    data_type=DataType.TEXT),
                    # Provenance / metadata
                    Property(name="source_file",   data_type=DataType.TEXT),
                    Property(name="page_number",   data_type=DataType.INT),
                    Property(name="doc_type",      data_type=DataType.TEXT),
                    # Best-effort heading extracted from PDF font sizes; nullable
                    Property(name="section_name",  data_type=DataType.TEXT),
                ],
            )
            print(f"✅ Collection '{collection_name}' created.")
        except Exception as e:
            print(f"❌ Error creating collection: {e}")
            return None
    else:
        print(f"Collection '{collection_name}' already exists.")

    return client.collections.get(collection_name)


# ---------------------------------------------------------------------------
# Ingestion helpers
# ---------------------------------------------------------------------------

def ingest_data(collection, data_objects):
    """Bulk-ingests a list of chunk dicts into the collection."""
    if not data_objects:
        print("Warning: No data provided for ingestion.")
        return

    print(f"Ingesting {len(data_objects)} objects into '{collection.name}'...")
    failed = 0
    try:
        with collection.batch.dynamic() as batch:
            for obj in data_objects:
                batch.add_object(properties=obj)
        # batch.__exit__ flushes; check for errors reported by the server
        if collection.batch.failed_objects:
            failed = len(collection.batch.failed_objects)
    except Exception as e:
        print(f"❌ Error during data ingestion: {e}")
        return

    success = len(data_objects) - failed
    print(f"✅ Ingestion done — {success} succeeded, {failed} failed.")


def delete_chunks_from_source(collection, source_filename):
    """Deletes all chunks belonging to a specific source file.
    Used by incremental ingestion to replace stale chunks without wiping
    the whole collection.
    """
    if not source_filename:
        print("Warning: No source filename provided for deletion.")
        return 0

    print(f"  Deleting stale chunks for '{source_filename}'...")
    try:
        response = collection.data.delete_many(
            where=Filter.by_property("source_file").equal(source_filename)
        )
        # Weaviate v4 client renamed these attrs; handle both for resilience.
        matched    = getattr(response, "matches",         getattr(response, "matched_count",    "?"))
        successful = getattr(response, "successful",      getattr(response, "successful_count", "?"))
        failed     = getattr(response, "failed",          getattr(response, "failed_count",     0))
        print(f"  ↳ Matched {matched}, deleted {successful}.")
        if failed:
            print(f"  ⚠️  Failed to delete {failed} object(s).")
        return successful if isinstance(successful, int) else 0
    except Exception as e:
        print(f"❌ Deletion error for '{source_filename}': {e}")
        return 0


# ---------------------------------------------------------------------------
# Incremental ingestion
# ---------------------------------------------------------------------------

# Manifest is stored next to this file so it survives server restarts.
_MANIFEST_PATH = Path(__file__).parent / ".ingestion_manifest.json"


def _file_mtime(path: str) -> str:
    """Return a stable fingerprint for a file (mtime + size)."""
    stat = os.stat(path)
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _load_manifest() -> dict:
    if _MANIFEST_PATH.exists():
        try:
            return json.loads(_MANIFEST_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_manifest(manifest: dict):
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def ingest_incrementally(client, collection, pdf_directory: str, process_fn):
    """
    Compares file mtimes against a local manifest.  Only files that are
    new or changed since the last run get re-processed; unchanged files are
    skipped entirely.  This is safe to call on every startup.

    Args:
        client:         connected Weaviate client (for delete_many access)
        collection:     Weaviate collection object
        pdf_directory:  path to the folder containing PDF files
        process_fn:     callable(file_path) -> list[dict] (one file at a time)
    """
    pdf_dir = Path(pdf_directory)
    if not pdf_dir.is_dir():
        print(f"❌ PDF directory not found: {pdf_directory}")
        return

    manifest = _load_manifest()
    new_manifest = dict(manifest)  # start from previous state
    total_ingested = 0
    skipped = 0

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print("No PDF files found in directory.")
        return

    print(f"\n🔍 Checking {len(pdf_files)} PDF(s) for changes...")

    for pdf_path in pdf_files:
        filename = pdf_path.name
        fingerprint = _file_mtime(str(pdf_path))

        if manifest.get(filename) == fingerprint:
            print(f"  ⏭️  {filename} — unchanged, skipping.")
            skipped += 1
            continue

        print(f"  🔄 {filename} — new or changed, re-ingesting...")
        # Delete stale chunks before inserting fresh ones
        delete_chunks_from_source(collection, filename)

        # Process this single file
        chunks = process_fn(str(pdf_path))
        if chunks:
            ingest_data(collection, chunks)
            total_ingested += len(chunks)

        # Update manifest entry for this file
        new_manifest[filename] = fingerprint

    _save_manifest(new_manifest)
    print(
        f"\n✅ Incremental ingestion complete — "
        f"{total_ingested} new chunk(s) ingested, {skipped} file(s) skipped."
    )


# ---------------------------------------------------------------------------
# Retrieval — hybrid search + cross-encoder re-ranking
# ---------------------------------------------------------------------------

# Empirical threshold based on observed cross-encoder score distribution:
#   strong match  ≈ +6 to +8   (direct definition/rule)
#   good match    ≈ +1 to +3   (related context)
#   weak/noise    ≈  0 to −2   (barely relevant)
# Anything below −0.5 is unlikely to add signal and risks confusing Gemini.
SCORE_THRESHOLD = -0.5


def retrieve_chunks(collection, query_text: str, limit: int = 3) -> List[dict]:
    """
    Two-stage retrieval:
      1. Hybrid search (vector + BM25, alpha=0.75) → 10 candidates
      2. Cross-encoder re-ranking → top `limit` results
      3. Threshold filter (SCORE_THRESHOLD) — drops noise chunks

    Returns List[dict] with keys:
      text, source_file, page_number, doc_type, section_name, score, confidence

    'confidence' is attached to every chunk ('high'/'medium'/'low') and also
    computed at the batch level so callers can surface it to the user.
    """
    CANDIDATE_LIMIT = 10

    try:
        print("Retrieving candidates via hybrid search...")
        response = collection.query.hybrid(
            query=query_text,
            alpha=0.75,          # 75% vector, 25% BM25
            limit=CANDIDATE_LIMIT,
            return_properties=["text_chunk", "source_file", "page_number", "doc_type", "section_name"],
        )

        if not response.objects:
            print("No relevant documents found in Weaviate for your query.")
            return []

        candidates = [
            {
                "text":         obj.properties.get("text_chunk", ""),
                "source_file":  obj.properties.get("source_file", ""),
                "page_number":  obj.properties.get("page_number"),
                "doc_type":     obj.properties.get("doc_type", ""),
                "section_name": obj.properties.get("section_name"),
                "score":        0.0,
            }
            for obj in response.objects
        ]
        print(f"  → {len(candidates)} candidate(s) from hybrid search.")

        # ── Cross-encoder re-ranking ──────────────────────────────────────
        encoder = _get_cross_encoder()
        pairs   = [(query_text, c["text"]) for c in candidates]
        with _inference_lock:
            scores  = encoder.predict(pairs).tolist()

        for candidate, score in zip(candidates, scores):
            candidate["score"] = round(float(score), 4)

        reranked = sorted(candidates, key=lambda c: c["score"], reverse=True)[:limit]

        # ── Threshold filter ─────────────────────────────────────────────
        filtered = [c for c in reranked if c["score"] >= SCORE_THRESHOLD]
        dropped  = len(reranked) - len(filtered)
        if dropped:
            print(f"  ↳ Dropped {dropped} chunk(s) below score threshold ({SCORE_THRESHOLD}).")

        if not filtered:
            print("  ↳ All candidates below threshold — returning empty (will use fallback).")
            return []

        print(f"✅ Re-ranked top {len(filtered)} result(s):")
        for i, r in enumerate(filtered):
            print(f"  [{i+1}] score={r['score']:+.3f}  src={r['source_file']}  pg={r['page_number']}")
            print(f"       {r['text'][:100]}...")

        return filtered

    except WeaviateQueryError as e:
        print(f"❌ Weaviate query error: {e}")
        return []
