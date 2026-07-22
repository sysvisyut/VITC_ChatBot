import os
import google.generativeai as genai
import json
from typing import List

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


def generate_answer(context_chunks: List[dict], query_text: str) -> dict:
    """
    Generates an answer using Gemini based on retrieved context chunks.

    Args:
        context_chunks: List[dict] from retrieve_chunks(), each with keys:
                        text, source_file, page_number, doc_type, section_name, score
        query_text:     The user's original question.

    Returns:
        dict with keys 'answer' (str) and 'sources' (list of dicts).
    """
    global GEMINI_MODEL
    if not GEMINI_MODEL:
        print("❌ Gemini model is not configured. Please call configure_gemini() first.")
        return {"answer": "Error: Gemini model not configured.", "sources": []}

    if not context_chunks:
        return {"answer": "I could not find any relevant information to answer your question.", "sources": []}

    # Build the context block Gemini sees — plain text only, no metadata noise
    context_lines = []
    for i, chunk in enumerate(context_chunks, 1):
        context_lines.append(f"[{i}] {chunk['text']}")
    context = "\n\n".join(context_lines)

    # Build the deduplicated sources list from real retrieval metadata,
    # keyed by (source_file, page_number) to avoid duplicate citations.
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

    # Prompt: Gemini only generates the answer text; sources are authoritative
    # from our retrieval layer — no more asking Gemini to hallucinate citations.
    prompt = f"""You are a helpful assistant for VIT Chennai campus information.

CONTEXT (from official campus documents):
---
{context}
---

Based ONLY on the context provided above, answer the following question clearly and concisely.
Do not invent information not present in the context.
If the context does not contain enough information to answer, say so explicitly.

QUESTION: {query_text}

Respond with only the answer text — no JSON, no preamble.
"""

    try:
        print("\nGenerating answer with Gemini...")
        response = GEMINI_MODEL.generate_content(prompt)
        answer_text = response.text.strip()

        return {
            "answer":  answer_text,
            "sources": sources,
        }

    except Exception as e:
        print(f"❌ Error generating content with Gemini: {e}")
        return {"answer": "Sorry, I encountered an error while generating the answer.", "sources": []}