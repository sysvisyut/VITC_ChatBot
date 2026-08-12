import collections
import json
import logging
import time

import app.metrics_store as metrics_store
from app.config import settings
from fastapi import Request
from WeaviateGeminiInterface.gemini_handler import (
    configure_gemini,
    generate_answer,
    generate_answer_stream,
    rewrite_query,
)
from WeaviateGeminiInterface.pdf_processor import process_single_pdf
from WeaviateGeminiInterface.weaviate_handler import (
    connect_to_weaviate,
    get_or_create_cache_collection,
    get_or_create_collection,
    ingest_incrementally,
    retrieve_chunks,
    semantic_cache_search,
    semantic_cache_store,
)

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        """
        Initializes the RAG Service singleton.
        Connects to Gemini and Weaviate, runs incremental ingestion, and sets up caching.
        """
        self.weaviate_client = None
        self.collection = None
        self.cache_collection = None

        # Exact match In-Memory LRU Cache (max 200 items)
        self._lru_cache = collections.OrderedDict()
        self._lru_capacity = 200

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

            self.cache_collection = get_or_create_cache_collection(
                self.weaviate_client,
                collection_name="VIT_QueryCache"
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

    def _normalize_query(self, query: str) -> str:
        return query.strip().lower()

    def _check_cache(self, user_query: str):
        """
        Checks the LRU cache, then the Semantic Cache.
        Returns a dict {"answer": str, "sources": list} if hit, else None.
        """
        norm_q = self._normalize_query(user_query)

        # 1. Exact LRU Cache check
        if norm_q in self._lru_cache:
            logger.info(f"[CACHE HIT - EXACT] Query: '{user_query[:50]}...'")
            # Move to end (most recently used)
            self._lru_cache.move_to_end(norm_q)
            return self._lru_cache[norm_q]

        # 2. Semantic Cache check
        if self.cache_collection:
            res = semantic_cache_search(self.cache_collection, user_query, threshold=0.95)
            if res:
                # Also populate local LRU so next time it's instant
                self._save_to_lru(norm_q, res["answer"], res["sources"])
                return res

        return None

    def _save_to_lru(self, norm_q: str, answer: str, sources: list):
        """Helper to save to the LRU dictionary."""
        self._lru_cache[norm_q] = {"answer": answer, "sources": sources}
        self._lru_cache.move_to_end(norm_q)
        if len(self._lru_cache) > self._lru_capacity:
            self._lru_cache.popitem(last=False)

    def _save_cache(self, user_query: str, answer: str, sources: list):
        """
        Saves the query, answer, and sources to both caches.
        """
        # Skip caching empty or fallback answers
        if not answer or answer.strip() == "" or "could not find any relevant information" in answer:
            return

        norm_q = self._normalize_query(user_query)
        self._save_to_lru(norm_q, answer, sources)

        if self.cache_collection:
            semantic_cache_store(self.cache_collection, user_query, answer, sources)

    def query(self, user_query: str) -> dict:
        """
        Executes the RAG pipeline to generate a final answer.
        """
        if not self.weaviate_client or not self.collection:
            logger.error("RAGService is not fully initialized. Cannot process query.")
            return {"answer": "Service unavailable due to internal initialization error.", "sources": []}

        # --- Cache Check ---
        _t_total_start = time.perf_counter()
        cached_result = self._check_cache(user_query)
        if cached_result:
            metrics_store.record(
                query=user_query,
                cache_hit=True,
                retrieval_ms=None,
                generation_ms=None,
                total_ms=(time.perf_counter() - _t_total_start) * 1000,
                chunks_retrieved=0,
                answer_length=len(cached_result.get("answer", "")),
                endpoint="/retrieve/",
            )
            return cached_result

        logger.info(f"[CACHE MISS] Query: '{user_query[:50]}...'")

        # --- Normal Pipeline ---
        _t0 = time.perf_counter()

        # Query rewriting
        rewritten = rewrite_query(user_query)
        retrieval_query = rewritten if (rewritten and rewritten.strip() != user_query.strip()) else user_query

        # Retrieve chunks — timed
        _tr0 = time.perf_counter()
        chunks = retrieve_chunks(self.collection, retrieval_query, limit=3)
        retrieval_ms = (time.perf_counter() - _tr0) * 1000

        # Generate Answer — timed
        _tg0 = time.perf_counter()
        result = generate_answer(chunks, user_query)
        generation_ms = (time.perf_counter() - _tg0) * 1000

        total_ms = (time.perf_counter() - _t0) * 1000

        # Format the result correctly
        final_res = result if isinstance(result, dict) else {"answer": result, "sources": []}

        # --- Metrics ---
        metrics_store.record(
            query=user_query,
            cache_hit=False,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            chunks_retrieved=len(chunks),
            answer_length=len(final_res.get("answer", "")),
            endpoint="/retrieve/",
        )

        # --- Cache Save ---
        self._save_cache(user_query, final_res.get("answer", ""), final_res.get("sources", []))

        return final_res

    def query_stream(self, user_query: str):
        """
        Executes the RAG pipeline and yields an SSE stream of the generated answer.
        """
        if not self.weaviate_client or not self.collection:
            logger.error("RAGService is not fully initialized. Cannot process stream query.")
            yield 'data: {"type": "error", "error": "Service unavailable"}\n\n'
            return

        # --- Cache Check ---
        _t_stream_start = time.perf_counter()
        cached_result = self._check_cache(user_query)
        if cached_result:
            # Yield cached output in SSE format instantly
            answer = cached_result["answer"]
            sources = cached_result["sources"]
            metrics_store.record(
                query=user_query,
                cache_hit=True,
                retrieval_ms=None,
                generation_ms=None,
                total_ms=(time.perf_counter() - _t_stream_start) * 1000,
                chunks_retrieved=0,
                answer_length=len(answer),
                endpoint="/stream/",
            )
            # To simulate streaming, just send the whole chunk at once (or chunk it, but once is fine)
            yield f'data: {json.dumps({"type": "text", "text": answer})}\n\n'
            yield f'data: {json.dumps({"type": "metadata", "sources": sources, "confidence": "high (cached)"})}\n\n'
            return

        logger.info(f"[CACHE MISS] Stream Query: '{user_query[:50]}...'")

        # --- Normal Pipeline ---
        # Query rewriting
        rewritten = rewrite_query(user_query)
        retrieval_query = rewritten if (rewritten and rewritten.strip() != user_query.strip()) else user_query

        # Retrieve chunks — timed
        _tr0 = time.perf_counter()
        chunks = retrieve_chunks(self.collection, retrieval_query, limit=3)
        retrieval_ms = (time.perf_counter() - _tr0) * 1000

        # Stream Generation — timed across all chunks
        stream_gen = generate_answer_stream(chunks, user_query)

        accumulated_text = []
        final_sources = []
        _tg0 = time.perf_counter()

        for sse_chunk in stream_gen:
            yield sse_chunk

            # Parse the SSE chunk to accumulate the final answer for caching
            try:
                # sse_chunk looks like: data: {"type": "text", "text": "..."}\n\n
                if sse_chunk.startswith("data: "):
                    payload = json.loads(sse_chunk[6:].strip())
                    if payload.get("type") == "text":
                        accumulated_text.append(payload.get("text", ""))
                    elif payload.get("type") == "metadata":
                        final_sources = payload.get("sources", [])
            except Exception:
                pass

        generation_ms = (time.perf_counter() - _tg0) * 1000
        total_ms = (time.perf_counter() - _t_stream_start) * 1000
        full_answer = "".join(accumulated_text)

        # --- Metrics ---
        metrics_store.record(
            query=user_query,
            cache_hit=False,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            total_ms=total_ms,
            chunks_retrieved=len(chunks),
            answer_length=len(full_answer),
            endpoint="/stream/",
        )

        # --- Cache Save ---
        self._save_cache(user_query, full_answer, final_sources)

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
