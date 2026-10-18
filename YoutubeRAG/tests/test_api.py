from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.models import ChatResponse, SourceReference, VideoLoadResponse, VideoSummaryResponse
from backend.transcript_service import TranscriptNotFoundError


client = TestClient(main.app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "retrieval_mode": main.settings.retrieval_mode,
        "groq_configured": main.settings.groq_enabled,
    }


def test_health_endpoint_returns_request_id():
    response = client.get("/api/health", headers={"X-Request-ID": "test-request-123"})

    assert response.headers["X-Request-ID"] == "test-request-123"


def test_video_load_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "load_video_for_video_id",
        lambda video_id: VideoLoadResponse(
            success=True,
            video_id=video_id,
            language="hi",
            normalized_language="en",
            translated=True,
            message="Video loaded successfully",
        ),
    )

    response = client.post("/api/video/load", json={"video_id": "J5_-l7WIO_w"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["video_id"] == "J5_-l7WIO_w"
    assert payload["translated"] is True


def test_chat_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "answer_question",
        lambda video_id, question, session_id: ChatResponse(
            success=True,
            video_id=video_id,
            session_id=session_id,
            answer="RAG stands for Retrieval Augmented Generation.",
            sources=[SourceReference(start_time=12.0, end_time=16.0, excerpt="RAG ...", language="en")],
            language="hi",
            normalized_language="en",
            translated=True,
            message="Answer generated successfully",
        ),
    )

    response = client.post(
        "/api/chat",
        json={"video_id": "J5_-l7WIO_w", "question": "What is RAG?", "session_id": "session-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["answer"].startswith("RAG stands for")
    assert payload["sources"][0]["start_time"] == 12.0


def test_video_load_endpoint_with_full_url(monkeypatch):
    monkeypatch.setattr(
        main,
        "load_video_for_video_id",
        lambda video_id: VideoLoadResponse(
            success=True,
            video_id=video_id,
            language="en",
            normalized_language="en",
            translated=False,
            message="Video loaded successfully",
        ),
    )

    response = client.post("/api/video/load", json={"video_id": "https://www.youtube.com/watch?v=J5_-l7WIO_w"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["video_id"] == "J5_-l7WIO_w"


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/video/load", {"video_id": "../secret"}),
    ("/api/chat", {"video_id": "../secret", "question": "Question", "session_id": "session-1"}),
])
def test_endpoints_reject_path_traversal_video_ids(endpoint, payload):
    response = client.post(endpoint, json=payload)

    assert response.status_code == 400
    assert "invalid characters" in response.json()["detail"]


def test_rate_limit_rejects_excess_requests(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, rate_limit_per_minute=1))
    main._rate_limit_requests.pop(("/api/chat", "testclient"), None)
    monkeypatch.setattr(
        main,
        "answer_question",
        lambda video_id, question, session_id: ChatResponse(
            success=True,
            video_id=video_id,
            session_id=session_id,
            answer="Answer",
        ),
    )
    payload = {"video_id": "J5_-l7WIO_w", "question": "Question", "session_id": "rate-limit-test"}

    assert client.post("/api/chat", json=payload).status_code == 200
    response = client.post("/api/chat", json=payload)

    assert response.status_code == 429


def test_video_summary_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "summarize_video",
        lambda video_id: VideoSummaryResponse(
            success=True,
            video_id=video_id,
            summary="A full-video summary.",
        ),
    )

    response = client.post("/api/video/summary", json={"video_id": "J5_-l7WIO_w"})

    assert response.status_code == 200
    assert response.json()["summary"] == "A full-video summary."


def test_api_key_is_required_on_api_routes_when_configured(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, api_key="test-api-key"))
    monkeypatch.setattr(
        main,
        "load_video_for_video_id",
        lambda video_id: VideoLoadResponse(
            success=True,
            video_id=video_id,
            message="Video loaded successfully",
        ),
    )
    payload = {"video_id": "J5_-l7WIO_w"}

    assert client.get("/api/health").status_code == 200
    assert client.post("/api/video/load", json=payload).status_code == 401
    response = client.post("/api/video/load", json=payload, headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200


def test_chat_endpoint_rejects_too_long_question():
    response = client.post(
        "/api/chat",
        json={
            "video_id": "J5_-l7WIO_w",
            "question": "q" * 2001,
            "session_id": "long-question",
        },
    )

    assert response.status_code == 422


def test_chat_endpoint_surfaces_missing_transcript(monkeypatch):
    def raise_transcript_error(video_id, question, session_id):
        raise TranscriptNotFoundError("Transcript unavailable")

    monkeypatch.setattr(main, "answer_question", raise_transcript_error)

    response = client.post(
        "/api/chat",
        json={
            "video_id": "J5_-l7WIO_w",
            "question": "A question",
            "session_id": "missing-transcript",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "Transcript unavailable" in response.json()["message"]


def test_chat_endpoint_surfaces_groq_failure(monkeypatch):
    monkeypatch.setattr(
        main,
        "answer_question",
        lambda video_id, question, session_id: ChatResponse(
            success=False,
            video_id=video_id,
            session_id=session_id,
            message="Unable to generate an answer right now: Groq is unavailable",
        ),
    )

    response = client.post(
        "/api/chat",
        json={
            "video_id": "J5_-l7WIO_w",
            "question": "A question",
            "session_id": "groq-failure",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "Groq is unavailable" in response.json()["message"]


def test_summary_endpoint_rejects_invalid_video_id():
    response = client.post("/api/video/summary", json={"video_id": "../private"})

    assert response.status_code == 400
