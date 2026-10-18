from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import chat_service, config, rag_service
from backend.rag_service import _build_llm

DATASET_PATH = Path(__file__).with_name("dataset.json")
RESULTS_PATH = Path(__file__).with_name("results.json")
FALLBACK_ANSWER = "I couldn't find that information in this video."
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "was", "were", "with",
}


def _load_dataset(path: Path = DATASET_PATH) -> list[dict[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Evaluation dataset must be a JSON array.")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not {"video_id", "question", "expected_answer", "type"} <= row.keys():
            raise ValueError(f"Dataset row {index + 1} is missing required fields.")
        if row["type"] not in {"answerable", "unanswerable"}:
            raise ValueError(f"Dataset row {index + 1} has an invalid type.")
    return rows


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"\b[\w.-]+\b", text)
        if len(token) > 1 and token.lower() not in _STOP_WORDS
    }


def _retrieval_hit(expected_answer: str, excerpts: list[str]) -> bool:
    expected_terms = _tokens(expected_answer)
    if not expected_terms:
        return False
    retrieved_terms = _tokens(" ".join(excerpts))
    return bool(expected_terms & retrieved_terms)


def _judge_answer(question: str, expected_answer: str, answer: str) -> str:
    prompt = (
        "You are evaluating a video transcript-grounded answer. Compare the response to the reference answer "
        "and classify semantic correctness. Output exactly one label: correct, partially correct, or incorrect.\n"
        f"Question: {question}\nReference answer: {expected_answer}\nResponse: {answer}"
    )
    response = _build_llm().invoke(prompt)
    content = getattr(response, "content", response)
    label = str(content).strip().lower()
    for accepted in ("partially correct", "correct", "incorrect"):
        if label.startswith(accepted):
            return accepted
    raise ValueError(f"LLM judge returned an unexpected label: {content!r}")


def _configure_retrieval(mode: str, rerank: bool) -> None:
    settings = replace(
        config.get_settings(),
        retrieval_mode=mode,
        rerank_enabled=rerank,
    )
    rag_service.get_settings = lambda: settings
    chat_service.get_settings = lambda: settings


def run_evaluation(
    rows: list[dict[str, str]],
    mode: str,
    rerank: bool,
) -> dict[str, Any]:
    _configure_retrieval(mode, rerank)
    results: list[dict[str, Any]] = []
    answerable_count = 0
    retrieval_hits = 0
    unanswerable_count = 0
    hallucinations = 0
    correct_count = 0
    total_latency = 0.0

    for row in rows:
        started = time.perf_counter()
        error: str | None = None
        try:
            response = chat_service.answer_question(
                video_id=row["video_id"],
                question=row["question"],
                session_id="eval-session",
            )
            answer = response.answer
            excerpts = [source.excerpt or "" for source in response.sources]
            if not response.success:
                error = response.message
        except Exception as exc:
            answer = ""
            excerpts = []
            error = str(exc)
        latency = time.perf_counter() - started
        total_latency += latency

        if row["type"] == "unanswerable":
            unanswerable_count += 1
            exact_fallback = answer == FALLBACK_ANSWER
            hallucinations += not exact_fallback
            grade = "correct" if exact_fallback else "incorrect"
        else:
            answerable_count += 1
            hit = _retrieval_hit(row["expected_answer"], excerpts)
            retrieval_hits += hit
            grade = _judge_answer(row["question"], row["expected_answer"], answer) if not error else "incorrect"

        correct_count += grade == "correct"
        results.append({
            "video_id": row["video_id"],
            "question": row["question"],
            "type": row["type"],
            "expected_answer": row["expected_answer"],
            "answer": answer,
            "grade": grade,
            "retrieval_hit": row["type"] == "answerable" and bool(
                _retrieval_hit(row["expected_answer"], excerpts)
            ),
            "latency_seconds": round(latency, 4),
            "error": error,
        })

    total_count = len(rows)
    metrics = {
        "accuracy": correct_count / total_count if total_count else 0.0,
        "hallucination_rate_unanswerable": hallucinations / unanswerable_count if unanswerable_count else 0.0,
        "retrieval_hit_rate": retrieval_hits / answerable_count if answerable_count else 0.0,
        "average_latency_seconds": total_latency / total_count if total_count else 0.0,
    }
    return {
        "mode": mode,
        "rerank": rerank,
        "total_questions": total_count,
        "metrics": metrics,
        "results": results,
    }


def _print_results(result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    print("| Metric | Result |")
    print("|---|---:|")
    print(f"| Accuracy | {metrics['accuracy']:.1%} |")
    print(f"| Hallucination rate (unanswerable) | {metrics['hallucination_rate_unanswerable']:.1%} |")
    print(f"| Retrieval hit rate | {metrics['retrieval_hit_rate']:.1%} |")
    print(f"| Average latency | {metrics['average_latency_seconds']:.2f}s |")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate transcript-grounded video chat answers.")
    parser.add_argument("--mode", choices=("vector", "hybrid"), default="vector")
    parser.add_argument("--rerank", choices=("on", "off"), default="off")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    args = parser.parse_args()

    result = run_evaluation(_load_dataset(args.dataset), args.mode, args.rerank == "on")
    RESULTS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_results(result)


if __name__ == "__main__":
    main()
