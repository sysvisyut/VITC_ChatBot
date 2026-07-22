import os
import google.generativeai as genai
from typing import List, Literal, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

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
# Query rewriting  (cheap, fast, isolated from the main answer model)
# ---------------------------------------------------------------------------

# Use the same model family as the main answer model (read from env at call
# time so we pick up whatever the user has configured).  We create a fresh
# GenerativeModel instance so state is fully isolated from GEMINI_MODEL.
_REWRITE_TIMEOUT_S = 3          # wall-clock seconds before we give up

_REWRITE_PROMPT = """\
You are a search-query optimizer for a VIT Chennai campus documentation chatbot.
Your ONLY job is to rewrite the user's input into a clear, specific, self-contained question
that will retrieve the most relevant information from VIT Chennai's official documents.

Rules:
- Output ONLY the rewritten question — no preamble, no explanation, no quotes.
- Keep the rewritten question under 50 words.
- If the input is already clear and specific, return it unchanged.
- Expand abbreviations and vague terms (e.g. "hostel rules" → full question about hostel regulations).
- Always include "VIT Chennai" or "VITC" if the context is campus-specific.

User input: {query}
"""


def rewrite_query(original_query: str) -> Optional[str]:
    """
    Rewrites a vague/short user query into a fuller, unambiguous question
    using a lightweight Gemini Flash model.

    Returns:
        The rewritten query string, or None if the call failed / timed out.
        Callers MUST fall back to the original query when None is returned.

    This function is intentionally isolated:
      - Uses its OWN model instance (not GEMINI_MODEL) so config failures are
        independent of the main answer pipeline.
      - Has a hard wall-clock timeout so it can NEVER block the main pipeline.
    """
    def _call() -> str:
        # Read model name at call time — picks up configure_gemini()'s env load.
        model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
        model  = genai.GenerativeModel(model_name)
        prompt = _REWRITE_PROMPT.format(query=original_query)
        resp   = model.generate_content(
            prompt,
            generation_config={"max_output_tokens": 512, "temperature": 0.1},
        )
        return resp.text.strip()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call)
            rewritten = future.result(timeout=_REWRITE_TIMEOUT_S)

        # Sanity guard: if the model returned something very long or empty,
        # treat it as a failure and fall back.
        if not rewritten or len(rewritten) > 400:
            print("  [rewrite] Output out of bounds — falling back to original.")
            return None

        # Sentence-completion guard: if the text ends without sentence-ending
        # punctuation the model ran out of tokens mid-sentence. Attempt to
        # truncate at the last clean sentence boundary; if none found, fall back.
        if rewritten[-1] not in ('.', '?', '!'):
            for punct in ('?', '.', '!'):
                last = rewritten.rfind(punct)
                if last > len(rewritten) // 2:  # at least half the text is usable
                    rewritten = rewritten[:last + 1]
                    break
            else:
                print("  [rewrite] Incomplete sentence, no clean boundary — falling back to original.")
                return None

        return rewritten

    except FuturesTimeoutError:
        print(f"  [rewrite] Timed out after {_REWRITE_TIMEOUT_S}s — falling back to original.")
        return None
    except Exception as e:
        print(f"  [rewrite] Failed ({e}) — falling back to original.")
        return None


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