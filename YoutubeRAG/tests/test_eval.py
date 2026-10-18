from __future__ import annotations

from backend.models import ChatResponse, SourceReference
from eval import run_eval


def test_load_dataset_rejects_invalid_rows(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text('[{"video_id":"abc"}]', encoding="utf-8")

    try:
        run_eval._load_dataset(dataset)
    except ValueError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("invalid dataset row should be rejected")


def test_run_evaluation_calculates_answer_and_fallback_metrics(monkeypatch):
    rows = [
        {
            "video_id": "J5_-l7WIO_w",
            "question": "What does RAG mean?",
            "expected_answer": "Retrieval Augmented Generation",
            "type": "answerable",
        },
        {
            "video_id": "J5_-l7WIO_w",
            "question": "What color is the speaker's car?",
            "expected_answer": "I couldn't find that information in this video.",
            "type": "unanswerable",
        },
    ]
    responses = iter([
        ChatResponse(
            success=True,
            video_id="J5_-l7WIO_w",
            session_id="eval-session",
            answer="Retrieval Augmented Generation",
            sources=[SourceReference(start_time=0, end_time=4, excerpt="RAG means Retrieval Augmented Generation.")],
        ),
        ChatResponse(
            success=True,
            video_id="J5_-l7WIO_w",
            session_id="eval-session",
            answer="I couldn't find that information in this video.",
        ),
    ])
    monkeypatch.setattr(run_eval, "_configure_retrieval", lambda mode, rerank: None)
    monkeypatch.setattr(run_eval.chat_service, "answer_question", lambda **kwargs: next(responses))
    monkeypatch.setattr(run_eval, "_judge_answer", lambda question, expected, answer: "correct")

    result = run_eval.run_evaluation(rows, "hybrid", True)

    assert result["metrics"]["accuracy"] == 1.0
    assert result["metrics"]["hallucination_rate_unanswerable"] == 0.0
    assert result["metrics"]["retrieval_hit_rate"] == 1.0
    assert [row["grade"] for row in result["results"]] == ["correct", "correct"]
