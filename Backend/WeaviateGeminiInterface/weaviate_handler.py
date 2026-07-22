import os
import json
import hashlib
import weaviate
from pathlib import Path
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
from weaviate.exceptions import WeaviateQueryError, WeaviateConnectionError
from weaviate.classes.query import Filter


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
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_chunks(collection, query_text, limit=5):
    """Retrieves relevant text chunks from the Weaviate collection."""
    try:
        print("Retrieving relevant documents from Weaviate...")
        response = collection.query.near_text(
            query=query_text,
            limit=limit,
            return_properties=["text_chunk", "source_file", "page_number", "doc_type", "section_name"],
        )

        retrieved_chunks = []
        if response.objects:
            retrieved_chunks = [obj.properties["text_chunk"] for obj in response.objects]

        if not retrieved_chunks:
            print("No relevant documents found in Weaviate for your query.")
            return []

        print(f"✅ Retrieved {len(retrieved_chunks)} document(s):")
        for i, chunk in enumerate(retrieved_chunks):
            print(f"  - Chunk {i+1}: {chunk[:100]}...")
        return retrieved_chunks

    except WeaviateQueryError as e:
        print(f"❌ Weaviate query error: {e}")
        return []
