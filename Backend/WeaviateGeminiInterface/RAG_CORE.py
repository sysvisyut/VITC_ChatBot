import sys
from pathlib import Path

# Add parent directory to path so WeaviateGeminiInterface can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Always load .env from the Backend directory (parent of this file's directory)
_ENV_PATH = Path(__file__).parent.parent / ".env"

# Import functions from our modules
from WeaviateGeminiInterface.pdf_processor import process_pdfs_in_directory
from WeaviateGeminiInterface.weaviate_handler import (
    connect_to_weaviate, 
    get_or_create_collection, 
    ingest_data,
    retrieve_chunks
)
from WeaviateGeminiInterface.gemini_handler import configure_gemini, generate_answer


def query(user_query : str):
    """
    Main function to orchestrate the PDF ingestion and RAG workflow.
    """
    load_dotenv(dotenv_path=_ENV_PATH, override=True)

    # --- Configuration ---
    # ⚠️  IMPORTANT: Set to True ONLY for first-time setup or when you add new PDFs.
    # After a successful ingestion, change this to False so PDFs aren't re-uploaded on every restart.
    PERFORM_INGESTION = False
    PDF_DIRECTORY = str(Path(__file__).parent.parent / "data")  # Points to Backend/data/
    
    # --- API and DB Setup ---
    if not configure_gemini():
        return # Exit if Gemini config fails
    client = connect_to_weaviate()
    if not client:
        return # Exit if Weaviate connection fails

    try:
        collection_name = "VIT_docs"
        # Get or create the collection, deleting it first if PERFORM_INGESTION is True
        documents_collection = get_or_create_collection(
            client, 
            collection_name, 
            fresh_start=PERFORM_INGESTION
        )
        if documents_collection is None:
            return 

        # --- Data Ingestion Step ---
        if PERFORM_INGESTION:
            # Process all PDFs in the specified directory
            data_to_ingest = process_pdfs_in_directory(PDF_DIRECTORY)
            # Ingest the processed data into Weaviate
            ingest_data(documents_collection, data_to_ingest)

        # --- RAG (Retrieval-Augmented Generation) Workflow ---
        print("\n--- Ready to answer questions ---")
        
        # Example Query
        print(f"\nUser Query: '{user_query}'")

        # 1. Retrieve relevant context from Weaviate
        retrieved_chunks = retrieve_chunks(documents_collection, user_query, limit=5)
        
        # 2. Generate an answer using Gemini with the retrieved context
        final_answer = generate_answer(retrieved_chunks, user_query)
        
        return final_answer
    except Exception as e:
        print(f"❌ An unexpected error occurred in the main workflow: {e}")

    finally:
        # Always close the connection
        if client and client.is_connected():
            client.close()
            print("\nConnection to Weaviate closed.")


if __name__ == "__main__":
    # Run the RAG workflow with a sample query
    result = query("What is VITC?")
    if result:
        print(f"\n✅ Final Answer: {result}")

