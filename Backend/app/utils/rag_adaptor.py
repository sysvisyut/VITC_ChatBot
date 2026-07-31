# this is an adaptor to bridge the gemini RAG app with the backend
from typing import Any, Dict, List, Optional

from WeaviateGeminiInterface.RAG_CORE import query as core_query, query_stream as core_query_stream

def query_rag(query: str):
    """
    Calls your RAG core and returns a normalized dict:
      { "answer": str, "sources": List[dict] }
    Edit here if your RAG return shape differs.
    """
    # Option B: class-based RAG core (uncomment and adjust if needed)
    # from WeaviateGeminiInterface.RAG_CORE import RAGCore
    # core = RAGCore()  # pass any constructor args your core needs

    
    result = core_query(user_query=query)

    # Normalize result


    return result

def query_rag_stream(query: str):
    """
    Calls the streaming RAG core and yields SSE data chunks.
    """
    return core_query_stream(user_query=query)