import os
import json
import weaviate
import weaviate.classes as wvc
from pathlib import Path
from typing import List, Callable
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
from weaviate.exceptions import WeaviateQueryError, WeaviateConnectionError
from weaviate.classes.query import Filter

import threading
import os
import logging
logger = logging.getLogger(__name__)

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
                logger.info("Loading cross-encoder model (first call only)...")
                _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                logger.info("✅ Cross-encoder ready.")
    return _cross_encoder


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect_to_weaviate(url: str, api_key: str):
    """
    Connects to the Weaviate Cloud instance using the provided credentials.
    """
    if not url or not api_key:
        logger.error("❌ Weaviate URL or API KEY not provided.")
        return None

    try:
        # Initialize the Weaviate client using the official v4 pattern
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=url,
            auth_credentials=Auth.api_key(api_key)
        )
        # Note: In Weaviate v4, client.is_connected() is available directly
        if client.is_connected():
            logger.info("✅ Connected to Weaviate Cloud successfully!")
            return client
        else:
            logger.error("❌ Failed to connect to Weaviate Cloud (client not connected).")
            return None
    except Exception as e:
        logger.error(f"❌ Error connecting to Weaviate: {e}")
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
            logger.error(f"❌ Error creating collection: {e}f")
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
        logger.warning("Warning: No data provided for ingestion.")
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
        logger.error(f"❌ Error during data ingestion: {e}f")
        return

    success = len(data_objects) - failed
    logger.info(f"✅ Ingestion done — {success} succeeded, {failed} failed.")


def delete_chunks_from_source(collection, source_filename):
    """Deletes all chunks belonging to a specific source file.
    Used by incremental ingestion to replace stale chunks without wiping
    the whole collection.
    """
    if not source_filename:
        logger.warning("Warning: No source filename provided for deletion.")
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
        logger.info(f"  ↳ Matched {matched}, deleted {successful}.")
        if failed:
            logger.info(f"  ⚠️  Failed to delete {failed} object(s).")
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
        logger.error(f"❌ PDF directory not found: {pdf_directory}f")
        return

    manifest = _load_manifest()
    new_manifest = dict(manifest)  # start from previous state
    total_ingested = 0
    skipped = 0

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logger.info("No PDF files found in directory.")
        return

    logger.info(f"\n🔍 Checking {len(pdf_files)} PDF(s) for changes...")

    for pdf_path in pdf_files:
        filename = pdf_path.name
        fingerprint = _file_mtime(str(pdf_path))

        if manifest.get(filename) == fingerprint:
            logger.info(f"  ⏭️  {filename} — unchanged, skipping.")
            skipped += 1
            continue

        logger.info(f"  🔄 {filename} — new or changed, re-ingesting...")
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
        logger.info("Retrieving candidates via hybrid search...")
        response = collection.query.hybrid(
            query=query_text,
            alpha=0.75,          # 75% vector, 25% BM25
            limit=CANDIDATE_LIMIT,
            return_properties=["text_chunk", "source_file", "page_number", "doc_type", "section_name"],
        )

        if not response.objects:
            logger.info("No relevant documents found in Weaviate for your query.")
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
        logger.info(f"  → {len(candidates)} candidate(s) from hybrid search.")

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
            logger.info(f"  ↳ Dropped {dropped} chunk(s) below score threshold ({SCORE_THRESHOLD}).")

        if not filtered:
            logger.info("  ↳ All candidates below threshold — returning empty (will use fallback).")
            return []

        logger.info(f"✅ Re-ranked top {len(filtered)} result(s):")
        for i, r in enumerate(filtered):
            print(f"  [{i+1}] score={r['score']:+.3f}  src={r['source_file']}  pg={r['page_number']}")
            print(f"       {r['text'][:100]}...")

        return filtered

    except WeaviateQueryError as e:
        logger.error(f"❌ Weaviate query error: {e}")
        return []


# ---------------------------------------------------------------------------
# Semantic Caching Layer
# ---------------------------------------------------------------------------

def get_or_create_cache_collection(client, collection_name: str = "VIT_QueryCache"):
    """
    Retrieves or creates the Weaviate collection used for semantic caching.
    """
    try:
        if client.collections.exists(collection_name):
            logger.info(f"Cache collection '{collection_name}' exists.")
            return client.collections.get(collection_name)
            
        logger.info(f"Creating cache collection '{collection_name}'...")
        collection = client.collections.create(
            name=collection_name,
            description="Caches previous RAG queries and their answers.",
            properties=[
                wvc.config.Property(name="query", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="answer", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                wvc.config.Property(name="sources", data_type=wvc.config.DataType.TEXT, skip_vectorization=True),
                wvc.config.Property(name="timestamp", data_type=wvc.config.DataType.DATE, skip_vectorization=True)
            ]
        )
        return collection
    except Exception as e:
        logger.error(f"❌ Error getting/creating cache collection: {e}")
        return None

def semantic_cache_search(cache_collection, user_query: str, threshold: float = 0.95):
    """
    Searches the cache collection for a semantically similar query.
    Returns a dict with 'answer' and 'sources' if a match is found above the threshold.
    """
    try:
        response = cache_collection.query.near_text(
            query=user_query,
            limit=1,
            return_metadata=wvc.query.MetadataQuery(certainty=True)
        )
        if response.objects:
            best_match = response.objects[0]
            certainty = best_match.metadata.certainty
            if certainty >= threshold:
                logger.info(f"[CACHE HIT - SEMANTIC] Found match (certainty {certainty:.4f})")
                props = best_match.properties
                
                # Parse sources if it's a valid JSON string
                sources = []
                if "sources" in props and props["sources"]:
                    try:
                        sources = json.loads(props["sources"])
                    except json.JSONDecodeError:
                        pass
                
                return {
                    "answer": props.get("answer", ""),
                    "sources": sources
                }
            else:
                logger.info(f"[CACHE MISS - SEMANTIC] Top match below threshold (certainty {certainty:.4f} < {threshold})")
        else:
            logger.info("[CACHE MISS - SEMANTIC] No matches found.")
    except Exception as e:
        logger.warning(f"Semantic cache search error: {e}")
    
    return None

def semantic_cache_store(cache_collection, user_query: str, answer: str, sources: list):
    """
    Stores a query and its answer into the semantic cache.
    """
    from datetime import datetime, timezone
    try:
        sources_json = json.dumps(sources)
        cache_collection.data.insert(
            properties={
                "query": user_query.strip(),
                "answer": answer,
                "sources": sources_json,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        logger.info(f"Stored query in semantic cache: '{user_query[:50]}...'")
    except Exception as e:
        logger.warning(f"Semantic cache store error: {e}")
