import os
import google.generativeai as genai
from typing import List, Literal

# gemini config
global GEMINI_MODEL
def configure_gemini():
    """Configures the Gemini API and initializes the model."""
    global GEMINI_MODEL
    GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL   = os.getenv("GEMINI_MODEL")
    if not GOOGLE_API_KEY or not GEMINI_MODEL:
        print("❌ GOOGLE_API_KEY/MODEL SELECTION not found in .env file.")
        return False
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        GEMINI_MODEL = genai.GenerativeModel(GEMINI_MODEL)
        print("✅ Gemini API configured successfully.")
        return True
    except Exception as e:
        print(f"❌ Error configuring Gemini API: {e}")
        return False


# ---------------------------------------------------------------------------
# Confidence heuristic
# ---------------------------------------------------------------------------

def _compute_confidence(chunks: list) -> Literal["high", "medium", "low"]:
    """
    Simple heuristic based on the top re-ranker score and chunk count.

    Score ranges (empirically observed with ms-marco-MiniLM-L-6-v2):
      high   → top score ≥ 5.0  (direct, specific answer found)
      medium → top score ≥ 1.0  (related context found, some inference needed)
      low    → top score <  1.0  (weak relevance; Gemini may not answer well)

    Having ≥2 chunks that cleared the threshold also upgrades low→medium,
    since multiple corroborating pieces reduce the risk of a bad answer.
    """
    if not chunks:
        return "low"

    top_score = chunks[0]["score"]  # already sorted descending by retrieve_chunks()

    if top_score >= 5.0:
        return "high"
    if top_score >= 1.0:
        return "medium"
    # Below 1.0 — but if ≥2 chunks cleared threshold, bump to medium
    if len(chunks) >= 2:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def generate_answer(context_chunks: List[dict], query_text: str) -> dict:
    """
    Generates an answer using Gemini based on retrieved context chunks.

    Args:
        context_chunks: List[dict] from retrieve_chunks(), each with keys:
                        text, source_file, page_number, doc_type,
                        section_name, score
        query_text:     The user's original question.

    Returns:
        dict with keys:
          answer     (str)
          sources    (list of dicts: document_name, page_number, doc_type, section_name)
          confidence ("high" | "medium" | "low")
    """
    global GEMINI_MODEL

    confidence = _compute_confidence(context_chunks)

    if not GEMINI_MODEL:
        print("❌ Gemini model is not configured. Please call configure_gemini() first.")
        return {"answer": "Error: Gemini model not configured.", "sources": [], "confidence": "low"}

    if not context_chunks:
        return {
            "answer":     "I could not find any relevant information to answer your question.",
            "sources":    [],
            "confidence": "low",
        }

    # ── Build attributed context blocks ─────────────────────────────────────
    # Each block is labelled with its provenance so Gemini can cite accurately.
    context_blocks = []
    for chunk in context_chunks:
        label = f"[Source: {chunk['source_file']}, Page {chunk['page_number']}]"
        context_blocks.append(f"{label}\n{chunk['text']}")
    context = "\n\n".join(context_blocks)

    # ── Build deduplicated sources list from real retrieval metadata ─────────
    # Keyed by (source_file, page_number) — Gemini no longer invents citations.
    seen_sources: set = set()
    sources: list = []
    for chunk in context_chunks:
        key = (chunk.get("source_file", ""), chunk.get("page_number"))
        if key not in seen_sources:
            seen_sources.add(key)
            sources.append({
                "document_name": chunk.get("source_file", ""),
                "page_number":   chunk.get("page_number"),
                "doc_type":      chunk.get("doc_type", ""),
                "section_name":  chunk.get("section_name"),
            })

    # ── Prompt ───────────────────────────────────────────────────────────────
    prompt = f"""You are a helpful assistant for VIT Chennai campus information.

CONTEXT (from official campus documents — each block is labelled with its source):
---
{context}
---

Rules you MUST follow:
1. Answer ONLY using information present in the context above. Do not use external knowledge.
2. For every claim or fact in your answer, cite the source and page number in brackets immediately after that sentence, like: [academic_regulations.pdf, p.26]
3. If the context does not contain enough information to fully answer the question, say so explicitly rather than guessing.
4. Be concise and direct. Do not repeat the question.

QUESTION: {query_text}
"""

    try:
        print("\nGenerating answer with Gemini...")
        response = GEMINI_MODEL.generate_content(prompt)
        answer_text = response.text.strip()

        return {
            "answer":     answer_text,
            "sources":    sources,
            "confidence": confidence,
        }

    except Exception as e:
        print(f"❌ Error generating content with Gemini: {e}")
        return {
            "answer":     "Sorry, I encountered an error while generating the answer.",
            "sources":    [],
            "confidence": "low",
        }