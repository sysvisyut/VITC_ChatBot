import sys
from pathlib import Path

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
from WeaviateGeminiInterface.gemini_handler import configure_gemini, generate_answer


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
        print("\n--- Ready to answer questions ---")
        print(f"\nUser Query: '{user_query}'")

        retrieved_chunks = retrieve_chunks(documents_collection, user_query, limit=3)
        final_answer = generate_answer(retrieved_chunks, user_query)
        return final_answer

    except Exception as e:
        print(f"❌ An unexpected error occurred in the main workflow: {e}")

    finally:
        if client and client.is_connected():
            client.close()
            print("\nConnection to Weaviate closed.")


if __name__ == "__main__":
    result = query("What is VITC?")
    if result:
        print(f"\n✅ Final Answer: {result}")
