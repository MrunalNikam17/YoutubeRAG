from __future__ import annotations

from dataclasses import replace
import json

from backend import translation_service
from backend.models import TranscriptSegment


def test_translate_transcript_to_english_short_circuits_for_english(monkeypatch):
    segments = [TranscriptSegment(text="Hello world", start=0.0, duration=2.0, language="en")]

    translated, changed = translation_service.translate_transcript_to_english(segments, "en")

    assert changed is False
    assert translated[0].text == "Hello world"
    assert translated[0].language == "en"


def test_translate_transcript_to_english_uses_model(monkeypatch):
    segments = [
        TranscriptSegment(text="RAG का मतलब Retrieval Augmented Generation है।", start=0.0, duration=4.0, language="hi"),
        TranscriptSegment(text="यह एक retriever का उपयोग करता है।", start=4.0, duration=4.0, language="hi"),
    ]

    def fake_llm(batch, source_language):
        return [
            "RAG stands for Retrieval Augmented Generation.",
            "It uses a retriever.",
        ]

    monkeypatch.setattr(translation_service, "_translate_batch_with_llm", fake_llm)

    translated, changed = translation_service.translate_transcript_to_english(segments, "hi")

    assert changed is True
    assert translated[0].text.startswith("RAG stands for")
    assert translated[1].text == "It uses a retriever."


def test_chunk_segments_respects_character_limit():
    segments = [
        TranscriptSegment(text="1234", start=0, duration=1, language="fr"),
        TranscriptSegment(text="5678", start=1, duration=1, language="fr"),
        TranscriptSegment(text="90", start=2, duration=1, language="fr"),
    ]

    batches = translation_service._chunk_segments(segments, max_chars=6)

    assert [[segment.text for segment in batch] for batch in batches] == [
        ["1234"],
        ["5678", "90"],
    ]


def test_parse_translation_payload_accepts_json_fence_and_rejects_wrong_length():
    assert translation_service._parse_translation_payload(
        '```json\n[{"text":"Hello"}]\n```',
        expected_length=1,
    ) == ["Hello"]
    assert translation_service._parse_translation_payload('["One"]', expected_length=2) is None
    assert translation_service._parse_translation_payload("not json", expected_length=1) is None


def test_translate_batch_calls_mocked_llm_and_parses_response(monkeypatch):
    segment = TranscriptSegment(text="Bonjour", start=0, duration=1, language="fr")
    fake_llm = type(
        "MockLLM",
        (),
        {"invoke": lambda self, messages: type("Response", (), {
            "content": json.dumps([{"text": "Hello"}])
        })()},
    )()
    monkeypatch.setattr(translation_service, "_build_llm", lambda model_name=None: fake_llm)

    assert translation_service._translate_batch_with_llm([segment], "fr") == ["Hello"]


def test_translation_uses_native_transcript_fallback(monkeypatch):
    segment = TranscriptSegment(text="Bonjour", start=0, duration=1, language="fr")

    class NativeTranscript:
        language_code = "fr"

        def translate(self, language):
            assert language == "en"
            return [{"text": "Hello", "start": 0, "duration": 1}]

    monkeypatch.setattr(
        translation_service,
        "_translate_batch_with_llm",
        lambda batch, source_language: (_ for _ in ()).throw(RuntimeError("LLM unavailable")),
    )

    translated, changed = translation_service.translate_transcript_to_english(
        [segment],
        "fr",
        NativeTranscript(),
    )

    assert changed is True
    assert translated[0].text == "Hello"
    assert translated[0].language == "en"


def test_translation_falls_back_to_original_text_if_all_translation_fails(monkeypatch):
    segment = TranscriptSegment(text="Bonjour", start=0, duration=1, language="fr")
    monkeypatch.setattr(
        translation_service,
        "_translate_batch_with_llm",
        lambda batch, source_language: (_ for _ in ()).throw(RuntimeError("LLM unavailable")),
    )

    translated, changed = translation_service.translate_transcript_to_english([segment], "fr")

    assert changed is False
    assert translated[0].text == "Bonjour"
    assert translated[0].language == "en"
    assert translated[0].original_language == "fr"


def test_build_llm_requires_groq_api_key(monkeypatch):
    settings = replace(translation_service.get_settings(), groq_api_key="")
    monkeypatch.setattr(translation_service, "get_settings", lambda: settings)

    try:
        translation_service._build_llm()
    except RuntimeError as exc:
        assert "GROQ_API_KEY" in str(exc)
    else:
        raise AssertionError("missing Groq key should be reported")
