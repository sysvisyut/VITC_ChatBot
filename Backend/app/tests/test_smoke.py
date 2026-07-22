"""
Smoke tests for the VITC ChatBot API.

These are REAL end-to-end tests — no mocks. They require:
  - A running Weaviate cloud instance (credentials in Backend/.env)
  - A valid Gemini API key (in Backend/.env)
  - The VIT_docs collection already populated (run ingestion first)

Run with:
    cd Backend/
    source .venv/bin/activate
    pytest app/tests/test_smoke.py -v
"""

import sys
import os
import pytest

# Ensure 'Backend/' is on sys.path so 'app' and 'WeaviateGeminiInterface' are importable,
# regardless of the directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test 1 — Import sanity
# ---------------------------------------------------------------------------

def test_app_imports_without_error():
    """The FastAPI app must be importable with no exceptions."""
    from app.main import app  # noqa: F401 — import is the assertion
    assert app is not None


# ---------------------------------------------------------------------------
# Test 2 — Health check
# ---------------------------------------------------------------------------

def test_health_endpoint_returns_ok():
    """GET / must return 200 with status='ok'."""
    from app.main import app
    client = TestClient(app, raise_server_exceptions=True)

    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok", f"Unexpected body: {body}"


# ---------------------------------------------------------------------------
# Test 3 — End-to-end RAG smoke test (real Weaviate + real Gemini)
# ---------------------------------------------------------------------------

def test_retrieve_returns_non_empty_answer():
    """
    POST /retrieve/ with a question that has a clear answer in the ingested PDFs.
    Asserts:
      - HTTP 200
      - Response body has an 'answer' key
      - 'answer' is a non-empty string (Gemini generated something)
      - 'sources' is a non-empty list; each item has document_name and page_number

    This test will fail if:
      - The Weaviate collection is empty (run ingestion first)
      - .env credentials are missing or wrong
      - Gemini API is unreachable
    Any of those failures are real problems we want to catch.
    """
    from app.main import app
    client = TestClient(app, raise_server_exceptions=True)

    payload = {"query": "What is the minimum attendance requirement at VIT Chennai?"}
    response = client.post("/retrieve/", json=payload)

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. Body: {response.text}"
    )

    body = response.json()

    # --- answer checks ---
    assert "answer" in body, f"'answer' key missing from response: {body}"
    assert isinstance(body["answer"], str), f"'answer' is not a string: {body}"
    assert len(body["answer"].strip()) > 0, (
        f"'answer' is empty or whitespace-only. "
        f"Check Weaviate collection is populated. Body: {body}"
    )

    # Sanity: the answer should not be the generic fallback string
    fallback = "I could not find any relevant information to answer your question."
    assert body["answer"] != fallback, (
        "RAG returned the no-results fallback. "
        "Weaviate collection may be empty or retrieval is broken."
    )

    # --- sources checks (now authoritative from retrieval metadata) ---
    assert "sources" in body, f"'sources' key missing from response: {body}"
    sources = body["sources"]
    assert isinstance(sources, list), f"'sources' should be a list, got: {type(sources)}"
    assert len(sources) > 0, (
        "'sources' is empty — retrieval returned chunks but no provenance metadata."
    )
    for src in sources:
        assert "document_name" in src, f"Source missing 'document_name': {src}"
        assert "page_number"   in src, f"Source missing 'page_number': {src}"
        assert isinstance(src["document_name"], str) and src["document_name"], (
            f"'document_name' is empty or not a string: {src}"
        )
