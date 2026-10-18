from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from backend import chat_service
from backend.models import (
    PreparedTranscript,
    SummarySection,
    TranscriptSegment,
    VideoSummaryResponse,
)
from backend.transcript_service import TranscriptNotFoundError


def test_classify_question_routes_global_and_specific_questions():
    assert chat_service.classify_question("What is this video about?") == "global"
    assert chat_service.classify_question("Give me the key takeaways") == "global"
    assert chat_service.classify_question("Give me a summary") == "global"
    assert chat_service.classify_question("What number did the speaker mention?") == "specific"


def test_global_question_returns_cached_summary_and_timestamped_sources(monkeypatch):
    prepared = PreparedTranscript(
        video_id="J5_-l7WIO_w",
        source_language="en",
        segments=[TranscriptSegment(text="Video content", start=0, duration=10, language="en")],
    )
    summary = VideoSummaryResponse(
        success=True,
        video_id="J5_-l7WIO_w",
        summary="Full video overview",
        sections=[SummarySection(start_time=0, end_time=10, summary="Opening section")],
    )
    stored_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(chat_service, "get_chat_history", lambda session_id, video_id: [])
    monkeypatch.setattr(chat_service, "summarize_video", lambda video_id: summary)
    monkeypatch.setattr(chat_service, "_get_prepared_transcript", lambda video_id: prepared)
    monkeypatch.setattr(
        chat_service,
        "append_chat_message",
        lambda session_id, role, content, video_id: stored_messages.append((role, content)),
    )

    response = chat_service.answer_question(
        "J5_-l7WIO_w",
        "What is this video about?",
        "global-session",
    )

    assert response.success is True
    assert response.answer == "Full video overview"
    assert response.sources[0].start_time == 0
    assert response.sources[0].end_time == 10
    assert stored_messages == [
        ("user", "What is this video about?"),
        ("assistant", "Full video overview"),
    ]


def test_summarize_video_maps_time_sections_and_reduces_with_mocked_llm(monkeypatch):
    prepared = PreparedTranscript(
        video_id="J5_-l7WIO_w",
        source_language="en",
        segments=[
            TranscriptSegment(text=f"Transcript part {index}", start=index * 5, duration=5, language="en")
            for index in range(4)
        ],
    )
    settings = replace(
        chat_service.get_settings(),
        summary_section_seconds=10,
        max_transcript_chars_per_batch=1000,
    )
    monkeypatch.setattr(chat_service, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_service, "load_video_summary", lambda video_id: None)
    monkeypatch.setattr(chat_service, "_get_prepared_transcript", lambda video_id: prepared)
    saved: list[VideoSummaryResponse] = []
    monkeypatch.setattr(chat_service, "save_video_summary", saved.append)

    class MockLLM:
        calls: list[str] = []

        def invoke(self, prompt):
            self.calls.append(prompt)
            if prompt.startswith("Summarize only"):
                return type("Response", (), {"content": f"Section summary {len(self.calls)}"})()
            return type("Response", (), {"content": "Full video overview"})()

    mock_llm = MockLLM()
    monkeypatch.setattr(chat_service, "_build_llm", lambda: mock_llm)

    response = chat_service.summarize_video("J5_-l7WIO_w")

    assert response.success is True
    assert response.summary == "Full video overview"
    assert len(response.sections) == 2
    assert response.sections[0].start_time == 0
    assert response.sections[0].end_time == 10
    assert response.sections[1].start_time == 10
    assert response.sections[1].end_time == 20
    assert len(mock_llm.calls) == 3
    assert saved == [response]


def test_summarize_video_reuses_cached_result(monkeypatch):
    cached = VideoSummaryResponse(
        success=True,
        video_id="J5_-l7WIO_w",
        summary="Cached overview",
    )
    monkeypatch.setattr(chat_service, "load_video_summary", lambda video_id: cached)
    monkeypatch.setattr(
        chat_service,
        "_get_prepared_transcript",
        lambda video_id: (_ for _ in ()).throw(AssertionError("cache should avoid transcript work")),
    )

    assert chat_service.summarize_video("J5_-l7WIO_w") is cached


def test_answer_question_returns_transcript_failure_without_fallback(monkeypatch):
    monkeypatch.setattr(chat_service, "load_prepared_transcript", lambda video_id: None)
    monkeypatch.setattr(
        chat_service,
        "prepare_transcript",
        lambda video_id: (_ for _ in ()).throw(TranscriptNotFoundError("Transcript unavailable")),
    )

    response = chat_service.answer_question(
        "J5_-l7WIO_w",
        "A question about the video",
        "session-transcript-error",
    )

    assert response.success is False
    assert response.message.startswith("Unable to generate an answer right now")
    assert "Transcript unavailable" in response.message


def test_answer_question_returns_groq_failure(monkeypatch):
    prepared = PreparedTranscript(
        video_id="J5_-l7WIO_w",
        source_language="en",
        segments=[TranscriptSegment(text="Transcript text", start=0, duration=1, language="en")],
    )
    monkeypatch.setattr(chat_service, "load_prepared_transcript", lambda video_id: prepared)
    monkeypatch.setattr(
        chat_service,
        "get_or_build_knowledge_base",
        lambda video_id, prepared: SimpleNamespace(vectorstore=object(), documents=[]),
    )
    monkeypatch.setattr(chat_service, "get_chat_history", lambda session_id, video_id: [])
    monkeypatch.setattr(
        chat_service,
        "generate_answer",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Groq is unavailable")),
    )

    response = chat_service.answer_question(
        "J5_-l7WIO_w",
        "A specific question",
        "session-groq-error",
    )

    assert response.success is False
    assert response.message == "Unable to generate an answer right now: Groq is unavailable"
