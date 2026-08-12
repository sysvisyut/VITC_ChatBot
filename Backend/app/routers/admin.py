"""
app/routers/admin.py
====================
Read-only admin / observability endpoints.
All routes are protected by the same X-API-Key check used by /retrieve/.
"""

import logging

from fastapi import APIRouter, Depends

from app.auth import get_api_key
from app.metrics_store import snapshot

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_api_key)],
)


@router.get(
    "/metrics",
    summary="RAG pipeline telemetry (rolling window)",
    description=(
        "Returns retrieval_ms, generation_ms, total_ms, chunks_retrieved, "
        "cache hit/miss counts and p50/p95 latency stats for the last "
        "100 requests. Protected by X-API-Key."
    ),
)
def get_metrics() -> dict:
    """
    Returns a snapshot of the in-memory rolling metrics window.

    Example response shape::

        {
          "window_size": 100,
          "records_captured": 42,
          "aggregates": {
            "cache_hit_rate": 0.286,
            "retrieval_ms": {"min": 210, "max": 950, "mean": 430, "p50": 410, "p95": 880},
            "generation_ms": {"min": 800, "max": 5200, "mean": 2100, "p50": 1900, "p95": 4700},
            "total_ms":      {"min": 220, "max": 6100, "mean": 2600, "p50": 2400, "p95": 5500},
            "avg_chunks_retrieved": 2.7
          },
          "recent": [ ... last 20 requests, newest first ... ]
        }
    """
    logger.info("Admin /metrics endpoint called")
    return snapshot()
