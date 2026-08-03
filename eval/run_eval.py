"""
eval/run_eval.py
================
RAG evaluation harness for the VITC Chatbot.

Design choice: We import RAG_CORE directly rather than hitting the HTTP API.
Reason: The API adds latency from HTTP overhead, auth middleware, and rate limiting
(10 req/min would make a 25-question eval take >2.5 min just throttling).
Direct import is faster, more stable for batch eval, and gives us access to the
raw retrieved_chunks list that RAGAS needs for context_recall.

Usage:
    # From the project root:
    source Backend/.venv/bin/activate
    python3 eval/run_eval.py

    # To skip the pipeline step and only re-score cached results:
    python3 eval/run_eval.py --score-only

Quota note:
    The Gemini free tier allows 20 requests/day for gemini-2.5-flash.
    25 questions × 2 calls each (rewrite + generate) = ~50 calls.
    If you hit the daily limit, run again the next day — the cache file
    (eval/results/pipeline_cache.json) preserves already-computed answers.
"""

# ── asyncio fix: Python 3.12+ / 3.14 removed implicit event loop creation ────
import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import sys
import json
import csv
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "Backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=True)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval")

# ── RAG pipeline imports ──────────────────────────────────────────────────────
from WeaviateGeminiInterface.gemini_handler import configure_gemini, generate_answer, rewrite_query
from WeaviateGeminiInterface.weaviate_handler import (
    connect_to_weaviate,
    get_or_create_collection,
    ingest_incrementally,
    retrieve_chunks,
)
from WeaviateGeminiInterface.pdf_processor import process_single_pdf

# ── RAGAS imports ─────────────────────────────────────────────────────────────
try:
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_recall
    from datasets import Dataset
except ImportError as e:
    logger.error(f"Missing eval dependency: {e}\nRun: pip install ragas==0.1.21 datasets")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
CACHE_PATH = RESULTS_DIR / "pipeline_cache.json"   # intermediate save
PDF_DIR = str(BACKEND_DIR / "data")
COLLECTION_NAME = "VIT_docs"
# Free tier: 20 RPD / 5 RPM for gemini-2.5-flash.
# Each question uses up to 2 calls (rewrite + generate) → 13s gap is safe for RPM.
# If you have a paid plan, reduce this.
SLEEP_BETWEEN_QUESTIONS = 13


# ── RAG Pipeline ─────────────────────────────────────────────────────────────
def run_rag_for_question(collection, question: str) -> dict:
    """Retrieval + generation for one question. Returns answer + contexts."""
    rewritten = rewrite_query(question)
    query = (
        rewritten if (rewritten and rewritten.strip() != question.strip())
        else question
    )
    chunks = retrieve_chunks(collection, query, limit=3)
    context_strings = [c.get("text", "") for c in chunks] if chunks else []

    result = generate_answer(chunks, question)
    answer_text = (
        result.get("answer", "") if isinstance(result, dict) else (result or "")
    )
    return {"answer": answer_text, "contexts": context_strings}


# ── Configure RAGAS to use Gemini via OpenAI-compat endpoint ─────────────────
def configure_ragas_llm():
    """
    ragas 0.1.x uses langchain's ChatOpenAI via llm_factory().
    Gemini exposes an OpenAI-compatible REST endpoint, so we point ChatOpenAI
    at it. This sidesteps all langchain-google-genai version conflicts.
    """
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").replace("models/", "")

    os.environ["OPENAI_API_KEY"] = gemini_api_key
    os.environ["OPENAI_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"

    try:
        import ragas.llms.base as _ragas_llms
        import functools

        _orig = _ragas_llms.llm_factory

        @functools.wraps(_orig)
        def _gemini_factory(model=gemini_model, *args, **kwargs):
            return _orig(model=model, *args, **kwargs)

        _ragas_llms.llm_factory = _gemini_factory
        logger.info(f"RAGAS → Gemini OpenAI-compat endpoint (model={gemini_model}).")
    except Exception as e:
        logger.warning(f"Could not patch ragas llm_factory: {e}")
    return True


# ── Pipeline phase: run all questions, save cache ─────────────────────────────
def run_pipeline_phase(golden: list, score_only: bool, weaviate_url: str, weaviate_api_key: str) -> list:
    """
    Runs the retrieval+generation step for all golden questions.
    If --score-only is set, loads from cache instead.
    Returns list of row dicts with keys: id, source, question, ground_truth,
    answer, contexts (pipe-joined string).
    """
    if score_only and CACHE_PATH.exists():
        logger.info(f"--score-only: loading pipeline results from {CACHE_PATH}")
        with open(CACHE_PATH) as f:
            return json.load(f)

    if score_only:
        logger.warning("--score-only requested but no cache found. Running pipeline anyway.")

    client = connect_to_weaviate(url=weaviate_url, api_key=weaviate_api_key)
    if not client:
        logger.error("Failed to connect to Weaviate. Is the cluster running?")
        sys.exit(1)

    rows = []
    try:
        collection = get_or_create_collection(client, COLLECTION_NAME, fresh_start=False)
        if collection is None:
            logger.error("Could not get Weaviate collection.")
            sys.exit(1)

        ingest_incrementally(
            client=client, collection=collection,
            pdf_directory=PDF_DIR, process_fn=process_single_pdf,
        )

        # Load existing cache to resume from if partially complete
        existing_cache = {}
        if CACHE_PATH.exists():
            with open(CACHE_PATH) as f:
                for row in json.load(f):
                    existing_cache[row["id"]] = row
            logger.info(f"Resuming: found {len(existing_cache)} cached answers.")

        for i, item in enumerate(golden, 1):
            qid = item.get("id", f"q{i}")
            q = item["question"]
            gt = item["ground_truth"]

            # Skip if already cached
            if qid in existing_cache:
                logger.info(f"[{i:02d}/{len(golden)}] CACHED — skipping: {q[:60]}...")
                rows.append(existing_cache[qid])
                continue

            logger.info(f"[{i:02d}/{len(golden)}] {q[:80]}...")
            try:
                result = run_rag_for_question(collection, q)
                ans = result["answer"]
                ctx = result["contexts"]
            except Exception as e:
                logger.warning(f"  Pipeline error: {e}. Using empty answer.")
                ans = ""
                ctx = []

            row = {
                "id": qid,
                "source": item.get("source", ""),
                "question": q,
                "ground_truth": gt,
                "answer": ans,
                "contexts": " ||| ".join(ctx),
            }
            rows.append(row)

            # Save incremental cache after each question
            all_rows = list(existing_cache.values()) + [
                r for r in rows if r["id"] not in existing_cache
            ]
            with open(CACHE_PATH, "w") as f:
                json.dump(rows, f, indent=2)

            time.sleep(SLEEP_BETWEEN_QUESTIONS)

    finally:
        if client and client.is_connected():
            client.close()
            logger.info("Weaviate connection closed.")

    return rows


# ── RAGAS scoring phase ────────────────────────────────────────────────────────
def run_ragas_phase(rows: list) -> dict:
    """Builds RAGAS Dataset from rows and runs evaluate(). Returns scored rows."""
    questions, answers, contexts, ground_truths = [], [], [], []
    for row in rows:
        questions.append(row["question"])
        answers.append(row["answer"])
        ctx_list = [c for c in row["contexts"].split(" ||| ") if c.strip()]
        contexts.append(ctx_list if ctx_list else [""])
        ground_truths.append(row["ground_truth"])

    ragas_ds = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    })

    logger.info("Running RAGAS evaluation (may take a few minutes)...")
    eval_result = evaluate(
        ragas_ds,
        metrics=[faithfulness, answer_relevancy, context_recall],
    )

    score_df = eval_result.to_pandas()
    scored_rows = []
    for i, row in enumerate(rows):
        r = dict(row)
        r["faithfulness"] = round(float(score_df.iloc[i].get("faithfulness", float("nan"))), 4)
        r["answer_relevancy"] = round(float(score_df.iloc[i].get("answer_relevancy", float("nan"))), 4)
        r["context_recall"] = round(float(score_df.iloc[i].get("context_recall", float("nan"))), 4)
        scored_rows.append(r)

    return scored_rows, eval_result


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="VITC RAG Evaluation Harness")
    parser.add_argument(
        "--score-only", action="store_true",
        help="Skip pipeline, load from cache and only re-run RAGAS scoring."
    )
    args = parser.parse_args()

    logger.info("=== VITC Chatbot RAG Evaluation Harness ===")

    # 1. Configure Gemini for RAG pipeline
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
    if not configure_gemini(api_key=gemini_api_key, model_name=gemini_model):
        logger.error("Failed to configure Gemini. Check GEMINI_API_KEY in Backend/.env")
        sys.exit(1)

    # 2. Configure RAGAS LLM
    configure_ragas_llm()

    # 3. Connect to Weaviate
    weaviate_url = os.getenv("WEAVIATE_URL")
    weaviate_api_key = os.getenv("WEAVIATE_API_KEY")
    client = connect_to_weaviate(url=weaviate_url, api_key=weaviate_api_key)

    with open(GOLDEN_SET_PATH) as f:
        golden = json.load(f)
    logger.info(f"Loaded {len(golden)} golden Q&A pairs.")

    # Phase 1: pipeline
    rows = run_pipeline_phase(golden, score_only=args.score_only, weaviate_url=weaviate_url, weaviate_api_key=weaviate_api_key)
    answered = sum(1 for r in rows if r["answer"].strip())
    logger.info(f"Pipeline complete: {answered}/{len(rows)} questions have non-empty answers.")

    if answered == 0:
        logger.error(
            "All answers are empty — likely daily quota exhausted. "
            "Wait for quota reset (midnight UTC) and re-run."
        )
        sys.exit(1)

    # Phase 2: RAGAS scoring
    scored_rows, eval_result = run_ragas_phase(rows)

    # Write CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"eval_{timestamp}.csv"
    fieldnames = [
        "id", "source", "question", "ground_truth", "answer",
        "contexts", "faithfulness", "answer_relevancy", "context_recall"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored_rows)

    print("\n" + "=" * 60)
    print("  VITC RAG Evaluation — Baseline Results")
    print("=" * 60)
    print(f"  Questions evaluated : {len(golden)}")
    print(f"  Answers non-empty   : {answered}/{len(golden)}")
    print(f"  Faithfulness        : {float(eval_result['faithfulness']):.4f}")
    print(f"  Answer Relevancy    : {float(eval_result['answer_relevancy']):.4f}")
    print(f"  Context Recall      : {float(eval_result['context_recall']):.4f}")
    print("=" * 60)
    print(f"  Full results saved  : {csv_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
