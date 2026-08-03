import logging
from fastapi import Request
from app.config import settings
from WeaviateGeminiInterface.gemini_handler import configure_gemini, generate_answer, generate_answer_stream, rewrite_query
from WeaviateGeminiInterface.weaviate_handler import (
    connect_to_weaviate,
    get_or_create_collection,
    ingest_incrementally,
    retrieve_chunks,
)
from WeaviateGeminiInterface.pdf_processor import process_single_pdf

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        """
        Initializes the RAG Service singleton.
        Connects to Gemini and Weaviate, and runs incremental ingestion.
        """
        self.weaviate_client = None
        self.collection = None
        self._initialize()

    def _initialize(self):
        # Configure Gemini
        gemini_configured = configure_gemini(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model
        )
        if not gemini_configured:
            logger.error("Failed to configure Gemini API in RAGService.")
            
        # Connect to Weaviate
        self.weaviate_client = connect_to_weaviate(
            url=settings.weaviate_url,
            api_key=settings.weaviate_api_key
        )
        if not self.weaviate_client:
            logger.error("Failed to connect to Weaviate in RAGService.")
            return

        # Setup Collection & Run Ingestion
        try:
            self.collection = get_or_create_collection(
                self.weaviate_client, 
                settings.collection_name, 
                fresh_start=False
            )
            if self.collection:
                ingest_incrementally(
                    client=self.weaviate_client,
                    collection=self.collection,
                    pdf_directory=settings.pdf_directory,
                    process_fn=process_single_pdf,
                )
                logger.info("✅ RAGService initialized successfully.")
            else:
                logger.error("Failed to get/create Weaviate collection.")
        except Exception as e:
            logger.exception(f"Error during RAGService initialization: {e}")

    def query(self, user_query: str) -> dict:
        """
        Executes the RAG pipeline to generate a final answer.
        """
        if not self.weaviate_client or not self.collection:
            logger.error("RAGService is not fully initialized. Cannot process query.")
            return {"answer": "Service unavailable due to internal initialization error.", "sources": []}

        # Query rewriting
        rewritten = rewrite_query(user_query)
        retrieval_query = rewritten if (rewritten and rewritten.strip() != user_query.strip()) else user_query
        
        # Retrieve chunks
        chunks = retrieve_chunks(self.collection, retrieval_query, limit=3)
        
        # Generate Answer
        result = generate_answer(chunks, user_query)
        
        # Format the result correctly
        if isinstance(result, dict):
            return result
        return {"answer": result, "sources": []}

    def query_stream(self, user_query: str):
        """
        Executes the RAG pipeline and yields an SSE stream of the generated answer.
        """
        if not self.weaviate_client or not self.collection:
            logger.error("RAGService is not fully initialized. Cannot process stream query.")
            yield "data: {\"error\": \"Service unavailable\"}\n\n"
            return

        # Query rewriting
        rewritten = rewrite_query(user_query)
        retrieval_query = rewritten if (rewritten and rewritten.strip() != user_query.strip()) else user_query
        
        # Retrieve chunks
        chunks = retrieve_chunks(self.collection, retrieval_query, limit=3)
        
        # Stream Generation
        yield from generate_answer_stream(chunks, user_query)

    def close(self):
        """
        Cleans up the Weaviate client connection on application shutdown.
        """
        if self.weaviate_client and self.weaviate_client.is_connected():
            self.weaviate_client.close()
            logger.info("Connection to Weaviate closed.")

def get_rag_service(request: Request) -> RAGService:
    """
    FastAPI dependency to retrieve the singleton RAGService.
    """
    return request.app.state.rag_service
