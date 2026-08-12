"""
app/metrics_store.py
====================
In-memory rolling window for per-request RAG telemetry.

Stores the last MAX_RECORDS requests in a thread-safe deque.
No external dependencies — just the standard library.

Schema for each record:
    {
        "ts":                float,   # unix timestamp of the request
        "query_preview":     str,     # first 80 chars of the query
        "cache_hit":         bool,    # True if served from LRU/semantic cache
        "retrieval_ms":      float | None,   # weaviate round-trip in ms
        "generation_ms":     float | None,   # gemini generation in ms
        "total_ms":          float,   # wall-clock end-to-end latency in ms
        "chunks_retrieved":  int,     # number of chunks returned by retrieval
        "answer_length":     int,     # char count of the final answer
        "endpoint":          str,     # "/retrieve/" or "/stream/"
    }
"""

import collections
import statistics
import threading
import time

MAX_RECORDS = 100

_lock = threading.Lock()
_window: collections.deque = collections.deque(maxlen=MAX_RECORDS)


def record(
    *,
    query: str,
    cache_hit: bool,
    retrieval_ms: float | None,
    generation_ms: float | None,
    total_ms: float,
    chunks_retrieved: int,
    answer_length: int,
    endpoint: str,
) -> None:
    """Append one request record to the rolling window."""
    entry = {
        "ts": time.time(),
        "query_preview": query[:80],
        "cache_hit": cache_hit,
        "retrieval_ms": round(retrieval_ms, 1) if retrieval_ms is not None else None,
        "generation_ms": round(generation_ms, 1) if generation_ms is not None else None,
        "total_ms": round(total_ms, 1),
        "chunks_retrieved": chunks_retrieved,
        "answer_length": answer_length,
        "endpoint": endpoint,
    }
    with _lock:
        _window.append(entry)


def snapshot() -> dict:
    """
    Return a read-only summary of the rolling window suitable for JSON serialisation.
    Includes per-request records plus aggregate statistics.
    """
    with _lock:
        records = list(_window)  # copy under lock

    n = len(records)
    if n == 0:
        return {
            "window_size": MAX_RECORDS,
            "records_captured": 0,
            "aggregates": {},
            "recent": [],
        }

    cache_hits = sum(1 for r in records if r["cache_hit"])
    retrieval_times = [r["retrieval_ms"] for r in records if r["retrieval_ms"] is not None]
    gen_times = [r["generation_ms"] for r in records if r["generation_ms"] is not None]
    total_times = [r["total_ms"] for r in records]
    chunks = [r["chunks_retrieved"] for r in records]

    def _stats(values: list[float]) -> dict:
        if not values:
            return {}
        return {
            "min": round(min(values), 1),
            "max": round(max(values), 1),
            "mean": round(statistics.mean(values), 1),
            "p50": round(statistics.median(values), 1),
            "p95": round(sorted(values)[int(len(values) * 0.95)], 1),
        }

    return {
        "window_size": MAX_RECORDS,
        "records_captured": n,
        "aggregates": {
            "cache_hit_rate": round(cache_hits / n, 3),
            "cache_hits": cache_hits,
            "cache_misses": n - cache_hits,
            "retrieval_ms": _stats(retrieval_times),
            "generation_ms": _stats(gen_times),
            "total_ms": _stats(total_times),
            "avg_chunks_retrieved": round(statistics.mean(chunks), 2) if chunks else None,
        },
        # Most recent 20 requests, newest first
        "recent": list(reversed(records[-20:])),
    }
