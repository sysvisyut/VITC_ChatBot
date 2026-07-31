import sys
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Add parent directory to path so WeaviateGeminiInterface can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Always load .env from the Backend directory (parent of this file's directory)
_ENV_PATH = Path(__file__).parent.parent / ".env"

# Import functions from our modules
from WeaviateGeminiInterface.pdf_processor import process_single_pdf, process_pdfs_in_directory
from WeaviateGeminiInterface.weaviate_handler import (
    connect_to_weaviate,
    get_or_create_collection,
    ingest_data,
    ingest_incrementally,
    retrieve_chunks,
)
from WeaviateGeminiInterface.gemini_handler import configure_gemini, generate_answer, generate_answer_stream, rewrite_query


def query(user_query: str):
    """
    Main RAG entry point.

    On every call the function runs incremental ingestion — a no-op when
    no PDFs have changed since the last run.  This replaces the old manual
    PERFORM_INGESTION flag.
    """
    load_dotenv(dotenv_path=_ENV_PATH, override=True)

    PDF_DIRECTORY = str(Path(__file__).parent.parent / "data")  # Backend/data/

    # --- API and DB Setup ---
    if not configure_gemini():
        return
    client = connect_to_weaviate()
    if not client:
        return

    try:
        collection_name = "VIT_docs"
        # fresh_start=False: we let incremental ingestion handle changes.
        # Pass fresh_start=True once manually (e.g. via CLI) when the schema changes.
        documents_collection = get_or_create_collection(client, collection_name, fresh_start=False)
        if documents_collection is None:
            return

        # --- Incremental ingestion (safe no-op when nothing has changed) ---
        ingest_incrementally(
            client=client,
            collection=documents_collection,
            pdf_directory=PDF_DIRECTORY,
            process_fn=process_single_pdf,   # processes one file at a time
        )

        # --- RAG Workflow ---
        logger.info(f"--- Ready to answer questions ---")
        logger.info(f"[query] Original : '{user_query}'")

        # --- Query rewriting (cheap Gemini Flash call, 3s timeout) ---
        rewritten = rewrite_query(user_query)
        if rewritten and rewritten.strip() != user_query.strip():
            retrieval_query = rewritten
            logger.info(f"[query] Rewritten : '{retrieval_query}'")
        else:
            retrieval_query = user_query
            logger.info("[query] Rewrite unchanged or skipped — using original.")

        # Retrieve using the rewritten query; answer using the ORIGINAL so the
        # user's phrasing is preserved in the final response.
        t0 = time.perf_counter()
        retrieved_chunks = retrieve_chunks(documents_collection, retrieval_query, limit=3)
        t1 = time.perf_counter()
        
        final_answer = generate_answer(retrieved_chunks, user_query)  # original query
        t2 = time.perf_counter()

        retrieval_ms = int((t1 - t0) * 1000)
        generation_ms = int((t2 - t1) * 1000)
        logger.info(f"RAG workflow completed in {retrieval_ms + generation_ms}ms "
                    f"(retrieval_ms={retrieval_ms}, generation_ms={generation_ms}, "
                    f"chunks_retrieved={len(retrieved_chunks)})")

        return final_answer

    except Exception as e:
        logger.exception(f"An unexpected error occurred in the main workflow: {e}")

    finally:
        if client and client.is_connected():
            client.close()
            logger.info("Connection to Weaviate closed.")

if __name__ == "__main__":
    result = query("What is VITC?")
    if result:
        logger.info(f"Final Answer: {result}")

def query_stream(user_query: str):
    """
    Streaming version of the RAG entry point.
    Yields SSE strings from generate_answer_stream.
    """
    load_dotenv(dotenv_path=_ENV_PATH, override=True)

    PDF_DIRECTORY = str(Path(__file__).parent.parent / "data")

    # --- API and DB Setup ---
    if not configure_gemini():
        import json
        yield f'data: {json.dumps({"type": "error", "error": "Gemini configuration failed"})}\n\n'
        return
        
    client = connect_to_weaviate()
    if not client:
        import json
        yield f'data: {json.dumps({"type": "error", "error": "Weaviate connection failed"})}\n\n'
        return

    try:
        collection_name = "VIT_docs"
        documents_collection = get_or_create_collection(client, collection_name, fresh_start=False)
        if documents_collection is None:
            return

        ingest_incrementally(
            client=client,
            collection=documents_collection,
            pdf_directory=PDF_DIRECTORY,
            process_fn=process_single_pdf,
        )

        logger.info(f"--- Ready to answer questions (Streaming) ---")
        rewritten = rewrite_query(user_query)
        if rewritten and rewritten.strip() != user_query.strip():
            retrieval_query = rewritten
        else:
            retrieval_query = user_query

        t0 = time.perf_counter()
        retrieved_chunks = retrieve_chunks(documents_collection, retrieval_query, limit=3)
        t1 = time.perf_counter()
        
        logger.info(f"RAG retrieval completed in {int((t1 - t0) * 1000)}ms")

        # Yield from the generator
        yield from generate_answer_stream(retrieved_chunks, user_query)

    except Exception as e:
        logger.exception(f"An unexpected error occurred in the streaming workflow: {e}")
        import json
        yield f'data: {json.dumps({"type": "error", "error": "An unexpected error occurred."})}\n\n'

    finally:
        if client and client.is_connected():
            client.close()
            logger.info("Connection to Weaviate closed.")
