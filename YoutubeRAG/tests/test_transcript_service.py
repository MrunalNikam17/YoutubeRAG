from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend import transcript_service
from backend.models import TranscriptSegment


class _FakeFetched:
    def __init__(self, data):
        self._data = data

    def to_raw_data(self):
        return self._data


@dataclass
class _FakeTranscript:
    language_code: str
    language: str
    is_generated: bool = False
    is_translatable: bool = True

    def fetch(self):
        return _FakeFetched(
            [
                {"text": "RAG का मतलब Retrieval Augmented Generation है।", "start": 12.0, "duration": 4.0},
                {"text": "यह जानकारी transcript में है।", "start": 16.0, "duration": 3.0},
            ]
        )


class _FakeTranscriptList:
    def __iter__(self):
        yield _FakeTranscript(language_code="hi", language="Hindi")


class _FakeAPI:
    def list(self, video_id):
        assert video_id == "J5_-l7WIO_w"
        return _FakeTranscriptList()


def test_extract_video_id_from_youtube_url():
    assert transcript_service.extract_video_id("https://www.youtube.com/watch?v=J5_-l7WIO_w") == "J5_-l7WIO_w"


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/J5_-l7WIO_w",
        "https://www.youtube.com/shorts/J5_-l7WIO_w",
        "https://www.youtube.com/embed/J5_-l7WIO_w",
        "J5_-l7WIO_w",
    ],
)
def test_extract_video_id_variants(url):
    assert transcript_service.extract_video_id(url) == "J5_-l7WIO_w"


def test_detect_transcript_language_prefers_hindi_when_english_missing():
    transcripts = [_FakeTranscript(language_code="hi", language="Hindi")]
    assert transcript_service.detect_transcript_language(transcripts) == "hi"


def test_fetch_transcript_segments_returns_segments(monkeypatch):
    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", lambda: _FakeAPI())

    segments, source = transcript_service.fetch_transcript_segments("J5_-l7WIO_w")

    assert source.language_code == "hi"
    assert len(segments) == 2
    assert segments[0].text.startswith("RAG")
    assert segments[0].start == 12.0


def test_prepare_transcript_uses_translation(monkeypatch):
    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", lambda: _FakeAPI())
    monkeypatch.setattr(transcript_service, "fetch_video_title", lambda video_id: "Video title")

    def fake_translate(segments, source_language, transcript_source=None):
        translated = [
            segment.model_copy(update={"text": "RAG stands for Retrieval Augmented Generation.", "language": "en", "original_language": source_language})
            for segment in segments
        ]
        return translated, True

    monkeypatch.setattr(transcript_service, "translate_transcript_to_english", fake_translate)

    prepared = transcript_service.prepare_transcript("J5_-l7WIO_w")

    assert prepared.source_language == "hi"
    assert prepared.translated is True
    assert prepared.segments[0].language == "en"
    assert prepared.segments[0].text.startswith("RAG stands for")


def test_prepare_transcript_uses_optional_whisper_fallback(monkeypatch):
    settings = replace(transcript_service.get_settings(), whisper_fallback_enabled=True)
    monkeypatch.setattr(transcript_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        transcript_service,
        "fetch_transcript_segments",
        lambda video_id: (_ for _ in ()).throw(transcript_service.TranscriptDisabledError("no captions")),
    )
    expected_segments = [
        TranscriptSegment(
            text="Spoken words from the video.",
            start=3.0,
            duration=2.5,
            language="en",
            video_id="J5_-l7WIO_w",
        )
    ]
    monkeypatch.setattr(
        transcript_service,
        "_transcribe_audio_with_whisper",
        lambda video_id: (expected_segments, "en"),
    )
    monkeypatch.setattr(transcript_service, "fetch_video_title", lambda video_id: "Video title")

    prepared = transcript_service.prepare_transcript("J5_-l7WIO_w")

    assert prepared.segments == expected_segments
    assert prepared.transcript_language_name == "en"
    assert prepared.title == "Video title"


def test_whisper_fallback_is_disabled_by_default(monkeypatch):
    settings = replace(transcript_service.get_settings(), whisper_fallback_enabled=False)
    monkeypatch.setattr(transcript_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        transcript_service,
        "fetch_transcript_segments",
        lambda video_id: (_ for _ in ()).throw(transcript_service.TranscriptDisabledError("no captions")),
    )
    monkeypatch.setattr(
        transcript_service,
        "_transcribe_audio_with_whisper",
        lambda video_id: (_ for _ in ()).throw(AssertionError("fallback should be disabled")),
    )

    with pytest.raises(transcript_service.TranscriptDisabledError):
        transcript_service.prepare_transcript("J5_-l7WIO_w")


def test_whisper_fallback_enforces_maximum_video_duration():
    with pytest.raises(transcript_service.VideoTooLongError, match="maximum of 30 minutes"):
        transcript_service._validate_video_duration(30 * 60 + 1, 30)

    transcript_service._validate_video_duration(30 * 60, 30)


def test_transcript_list_uses_compatibility_api_after_list_fails(monkeypatch):
    transcript = _FakeTranscript(language_code="en", language="English")

    class CompatibleAPI:
        def list(self, video_id):
            raise RuntimeError("new client API")

        @staticmethod
        def list_transcripts(video_id):
            return [transcript]

    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", CompatibleAPI)

    result = transcript_service._get_transcript_list(CompatibleAPI(), "J5_-l7WIO_w")

    assert result == [transcript]


def test_fetch_transcript_segments_rejects_invalid_id_and_missing_captions(monkeypatch):
    with pytest.raises(transcript_service.InvalidVideoIdError):
        transcript_service.fetch_transcript_segments("../secret")

    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", lambda: object())
    with pytest.raises(transcript_service.TranscriptDisabledError):
        transcript_service.fetch_transcript_segments("J5_-l7WIO_w")


def test_raw_transcript_fetch_uses_api_fallback():
    class FailingTranscript:
        language_code = "en"

        def fetch(self):
            raise RuntimeError("legacy fetch failed")

    class CompatibleAPI:
        def fetch(self, video_id, languages):
            assert video_id == "J5_-l7WIO_w"
            assert languages == ["en"]
            return [{"text": "fallback captions", "start": 1, "duration": 2}]

    raw = transcript_service._fetch_raw_segments(
        FailingTranscript(),
        CompatibleAPI(),
        "J5_-l7WIO_w",
    )

    assert raw[0]["text"] == "fallback captions"


def test_whisper_audio_fallback_uses_mocked_download_and_model(monkeypatch, tmp_path):
    settings = replace(transcript_service.get_settings(), whisper_model="tiny", max_video_minutes=30)
    monkeypatch.setattr(transcript_service, "get_settings", lambda: settings)

    yt_dlp = ModuleType("yt_dlp")

    class MockYoutubeDL:
        def __init__(self, options):
            self.options = options
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def extract_info(self, url, download):
            self.calls += 1
            if not download:
                return {"duration": 25}
            audio_path = self.options["outtmpl"].replace("%(ext)s", "webm")
            Path(audio_path).write_bytes(b"mock audio")
            return {"requested_downloads": [{"filepath": audio_path}]}

    yt_dlp.YoutubeDL = MockYoutubeDL
    faster_whisper = ModuleType("faster_whisper")

    class MockWhisperModel:
        def __init__(self, model, device, compute_type):
            assert model == "tiny"
            assert device == "cpu"
            assert compute_type == "int8"

        def transcribe(self, audio_path, beam_size):
            assert Path(audio_path).exists()
            assert beam_size == 5
            return [SimpleNamespace(text="  spoken transcript ", start=2.0, end=4.5)], SimpleNamespace(language="en")

    faster_whisper.WhisperModel = MockWhisperModel
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)
    monkeypatch.setitem(sys.modules, "faster_whisper", faster_whisper)

    segments, language = transcript_service._transcribe_audio_with_whisper("J5_-l7WIO_w")

    assert language == "en"
    assert segments[0].text == "spoken transcript"
    assert segments[0].start == 2.0
    assert segments[0].duration == 2.5


def test_whisper_audio_fallback_rejects_over_limit_duration(monkeypatch):
    settings = replace(transcript_service.get_settings(), max_video_minutes=30)
    monkeypatch.setattr(transcript_service, "get_settings", lambda: settings)
    yt_dlp = ModuleType("yt_dlp")

    class LongVideoDownloader:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def extract_info(self, url, download):
            assert download is False
            return {"duration": 30 * 60 + 1}

    yt_dlp.YoutubeDL = LongVideoDownloader
    faster_whisper = ModuleType("faster_whisper")
    faster_whisper.WhisperModel = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("long video must be rejected before model loading")
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)
    monkeypatch.setitem(sys.modules, "faster_whisper", faster_whisper)

    with pytest.raises(transcript_service.VideoTooLongError):
        transcript_service._transcribe_audio_with_whisper("J5_-l7WIO_w")
