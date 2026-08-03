# VITC Chatbot RAG Evaluation Harness

This directory contains a standalone evaluation harness for measuring the quality of the VIT Chennai chatbot's Retrieval-Augmented Generation (RAG) pipeline.

---

## Setup

**Install eval-only dependencies** (do NOT add these to the main backend `requirements.txt`):

```bash
# From the project root
cd /path/to/VITC_ChatBot

# Create a separate venv for eval (recommended), or reuse the backend one
pip install -r eval/requirements.txt
```

> **Note:** The eval harness requires both Weaviate and Gemini to be live. Ensure the backend `.env` is populated with `GEMINI_API_KEY`, `GEMINI_MODEL`, `WEAVIATE_URL`, and `WEAVIATE_API_KEY`.

---

## Running the Evaluation

```bash
# From the project root:
python eval/run_eval.py
```

The script will:
1. Connect to Weaviate and run incremental ingestion (a no-op if PDFs are unchanged).
2. Loop through all 25 questions in `golden_set.json`, running retrieval + generation for each.
3. Score results using RAGAS (powered by your existing Gemini key — no extra LLM API cost).
4. Write a timestamped CSV to `eval/results/eval_YYYYMMDD_HHMMSS.csv`.
5. Print a summary table to the terminal.

---

## Files

| File | Description |
|---|---|
| `golden_set.json` | 25 hand-written Q&A pairs drawn directly from the 4 ingested PDFs |
| `run_eval.py` | Main evaluation script |
| `requirements.txt` | Eval-only dependencies (RAGAS, datasets, langchain-google-genai) |
| `results/` | Timestamped CSV output from each eval run |

---

## Understanding the Three Metrics

### 1. Faithfulness (0.0 – 1.0, higher is better)
**"Is the answer supported by what the RAG retrieved?"**

RAGAS decomposes the model's answer into individual claims and checks whether each claim can be inferred from the retrieved context chunks. A score of **1.0** means every sentence the model produced is grounded in the retrieved documents. A low score means the model is hallucinating or drawing on general knowledge outside the retrieved context.

> **Good score:** ≥ 0.80. If this falls below 0.60, the model is likely ignoring the context and inventing answers.

---

### 2. Answer Relevancy (0.0 – 1.0, higher is better)
**"Does the answer actually address the question asked?"**

RAGAS uses an embedding-based approach: it generates several hypothetical questions from the model's answer and measures how similar they are to the original question. A high score means the answer is directly on-topic. A low score means the answer drifts (e.g., answering a related but different question, or being too verbose/vague).

> **Good score:** ≥ 0.75. If this is low while faithfulness is high, the retrieved context was correct but the model answered tangentially.

---

### 3. Context Recall (0.0 – 1.0, higher is better)
**"Did the retriever actually fetch the chunks needed to answer the question?"**

RAGAS compares the `ground_truth` answer against the retrieved context and measures how much of the ground-truth information was present in the retrieved chunks. A score of **1.0** means the retriever fetched all the information needed to answer correctly. A low score means the hybrid search + re-ranker is missing relevant chunks — the failure is in retrieval, not generation.

> **Good score:** ≥ 0.70. If this is low, consider tuning the hybrid alpha, the number of retrieved chunks (`limit`), or the re-ranker threshold.

---

## Interpreting the Results Together

| Faithfulness | Answer Relevancy | Context Recall | Diagnosis |
|:---:|:---:|:---:|:---|
| High | High | High | ✅ Pipeline is working well |
| Low | High | High | ⚠️ Model is hallucinating despite good context |
| High | Low | High | ⚠️ Model is using the context but answering off-topic |
| Any | Any | Low | 🔴 Retrieval is failing — fix hybrid search or re-ranker |
| High | High | Low | 🤔 Model is answering correctly using partial context (sometimes OK) |

---

## Adding More Golden Questions

Edit `golden_set.json`. Each entry must have:
```json
{
  "id": "unique_id",
  "source": "filename.pdf",
  "question": "...",
  "ground_truth": "The exact answer drawn from the document text."
}
```

Do **not** invent plausible-sounding ground truths — they must be verbatim or closely paraphrased from the actual PDFs to make the context_recall metric meaningful.
