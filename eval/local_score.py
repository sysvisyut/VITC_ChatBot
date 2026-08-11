"""
eval/local_score.py
====================
Offline scoring script that reads the pipeline_cache.json (already generated
answers + contexts) and computes proxy metrics using local models only —
zero Gemini API calls required.

Metrics computed:
  - answer_similarity:  cosine similarity between answer and ground truth
                        (via sentence-transformers/all-MiniLM-L6-v2)
  - context_relevance:  max cosine sim between question and any retrieved context chunk
  - answer_groundedness: max cosine sim between answer and any retrieved context chunk
                        (proxy for faithfulness — does the answer overlap with context?)

Usage:
    cd /path/to/VITC_ChatBot
    source Backend/.venv/bin/activate
    python3 eval/local_score.py
"""

import json
import csv
import sys
import logging
from pathlib import Path
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("local_score")

RESULTS_DIR  = Path(__file__).parent / "results"
CACHE_PATH   = RESULTS_DIR / "pipeline_cache.json"
RESULTS_DIR.mkdir(exist_ok=True)

def cosine(a, b):
    a, b = np.array(a), np.array(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0

def main():
    if not CACHE_PATH.exists():
        logger.error(f"No pipeline cache found at {CACHE_PATH}. Run run_eval.py first.")
        sys.exit(1)

    with open(CACHE_PATH) as f:
        rows = json.load(f)
    logger.info(f"Loaded {len(rows)} cached pipeline results.")

    # Load sentence-transformer (already installed in venv)
    logger.info("Loading sentence-transformer model (all-MiniLM-L6-v2)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    logger.info("Model loaded.")

    scored_rows = []
    for i, row in enumerate(rows, 1):
        q          = row["question"]
        answer     = row["answer"].strip()
        gt         = row["ground_truth"].strip()
        ctx_raw    = row.get("contexts", "")
        contexts   = [c.strip() for c in ctx_raw.split(" ||| ") if c.strip()] if ctx_raw else []

        logger.info(f"[{i}/{len(rows)}] Scoring: {q[:70]}...")

        # Encode all texts
        texts_to_encode = [q, answer, gt] + contexts
        embeddings = model.encode(texts_to_encode, normalize_embeddings=True)

        q_emb      = embeddings[0]
        ans_emb    = embeddings[1]
        gt_emb     = embeddings[2]
        ctx_embs   = embeddings[3:] if contexts else []

        # 1. Answer similarity to ground truth (0-1, higher is better)
        answer_similarity = cosine(ans_emb, gt_emb)

        # 2. Context relevance: how well does the best retrieved chunk match the question?
        if len(ctx_embs) > 0:
            context_relevance = max(cosine(q_emb, c) for c in ctx_embs)
        else:
            context_relevance = 0.0

        # 3. Answer groundedness: does the answer come from the retrieved context?
        if len(ctx_embs) > 0 and answer:
            answer_groundedness = max(cosine(ans_emb, c) for c in ctx_embs)
        else:
            answer_groundedness = 0.0

        has_answer = 1 if answer and "could not find" not in answer.lower() else 0

        scored_rows.append({
            "id":                   row.get("id", f"q{i}"),
            "source":               row.get("source", ""),
            "question":             q,
            "ground_truth":         gt,
            "answer":               answer,
            "has_answer":           has_answer,
            "answer_similarity":    round(answer_similarity, 4),
            "context_relevance":    round(context_relevance, 4),
            "answer_groundedness":  round(answer_groundedness, 4),
        })

        logger.info(
            f"  → similarity={answer_similarity:.3f}  "
            f"ctx_relevance={context_relevance:.3f}  "
            f"groundedness={answer_groundedness:.3f}"
        )

    # Compute averages
    n = len(scored_rows)
    avg_sim   = sum(r["answer_similarity"]   for r in scored_rows) / n
    avg_ctx   = sum(r["context_relevance"]   for r in scored_rows) / n
    avg_grnd  = sum(r["answer_groundedness"] for r in scored_rows) / n
    answered  = sum(r["has_answer"]          for r in scored_rows)

    print("\n" + "="*60)
    print("  VITC RAG BASELINE — LOCAL EVALUATION SCORES")
    print("="*60)
    print(f"  Questions evaluated : {n}")
    print(f"  Non-empty answers   : {answered}/{n}")
    print(f"  Answer Similarity   : {avg_sim:.4f}  (vs ground truth)")
    print(f"  Context Relevance   : {avg_ctx:.4f}  (question ↔ context)")
    print(f"  Answer Groundedness : {avg_grnd:.4f}  (answer ↔ context)")
    print("="*60 + "\n")

    # Per-question breakdown
    print(f"{'ID':<10} {'Similarity':>10} {'Ctx Rel':>10} {'Grounded':>10}  Question")
    print("-"*80)
    for r in scored_rows:
        mark = "✅" if r["has_answer"] else "❌"
        print(
            f"{r['id']:<10} {r['answer_similarity']:>10.4f} "
            f"{r['context_relevance']:>10.4f} {r['answer_groundedness']:>10.4f}  "
            f"{mark} {r['question'][:55]}"
        )

    # Save to timestamped CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"local_eval_{ts}.csv"
    fieldnames = list(scored_rows[0].keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored_rows)

    # Append summary row
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow({
            "id": "AVERAGE", "source": "", "question": "", "ground_truth": "",
            "answer": "", "has_answer": f"{answered}/{n}",
            "answer_similarity": round(avg_sim, 4),
            "context_relevance": round(avg_ctx, 4),
            "answer_groundedness": round(avg_grnd, 4),
        })

    logger.info(f"Results saved → {csv_path}")

if __name__ == "__main__":
    main()
