from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlparse
import re

from youtube_transcript_api import YouTubeTranscriptApi

from .config import get_settings
from .models import PreparedTranscript, TranscriptSegment
from .translation_service import translate_transcript_to_english

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class TranscriptSource:
    language_code: str
    language_name: str | None
    is_generated: bool | None
    is_translatable: bool | None
    transcript: Any


class TranscriptError(RuntimeError):
    pass


class TranscriptNotFoundError(TranscriptError):
    pass


class TranscriptDisabledError(TranscriptError):
    pass


class InvalidVideoIdError(TranscriptError):
    pass


class VideoTooLongError(TranscriptError):
    pass


def extract_video_id(url_or_id: str) -> str | None:
    value = (url_or_id or "").strip()
    if not value:
        return None

    if _VIDEO_ID_RE.fullmatch(value):
        return value

    if "youtube.com/shorts/" in value:
        match = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", value)
        if match:
            return match.group(1)

    if "/embed/" in value:
        match = re.search(r"/embed/([A-Za-z0-9_-]{11})", value)
        if match:
            return match.group(1)

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)

    if host in {"www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"}:
        video_id = query.get("v", [None])[0]
        if video_id and _VIDEO_ID_RE.fullmatch(video_id):
            return video_id
        if parsed.path.startswith("/shorts/"):
            match = re.search(r"/shorts/([A-Za-z0-9_-]{11})", parsed.path)
            if match:
                return match.group(1)
        if parsed.path.startswith("/live/"):
            match = re.search(r"/live/([A-Za-z0-9_-]{11})", parsed.path)
            if match:
                return match.group(1)

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.lstrip("/").split("/")[0]
        if _VIDEO_ID_RE.fullmatch(candidate):
            return candidate

    return None


def fetch_video_title(video_id: str) -> str | None:
    cleaned = extract_video_id(video_id) or video_id
    if not cleaned:
        return None
    try:
        import urllib.request
        import json
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={cleaned}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("title")
    except Exception:
        return None



def _iter_transcripts(transcript_list: Any) -> list[Any]:
    if transcript_list is None:
        return []
    try:
        return list(transcript_list)
    except TypeError:
        pass
    if hasattr(transcript_list, "transcripts"):
        try:
            return list(transcript_list.transcripts)
        except TypeError:
            return []
    return []


def _select_transcript_source(transcripts: list[Any], preferred_languages: list[str]) -> Any | None:
    normalized_preference = [language.lower() for language in preferred_languages]
    candidates = transcripts[:]

    def score(item: Any) -> tuple[int, int, str]:
        code = str(getattr(item, "language_code", "")).lower()
        base_code = code.split("-")[0]
        generated_penalty = 1 if bool(getattr(item, "is_generated", False)) else 0
        if code in normalized_preference or base_code in normalized_preference:
            preferred_rank = normalized_preference.index(code) if code in normalized_preference else normalized_preference.index(base_code)
            return (preferred_rank, generated_penalty, code)
        return (len(normalized_preference) + 1, generated_penalty, code)

    candidates.sort(key=score)
    return candidates[0] if candidates else None


def detect_transcript_language(transcripts: list[Any], preferred_languages: list[str] | None = None) -> str | None:
    preferred_languages = preferred_languages or get_settings().transcript_language_preferences
    source = _select_transcript_source(transcripts, preferred_languages)
    return getattr(source, "language_code", None) if source else None


def _get_transcript_api() -> YouTubeTranscriptApi:
    return YouTubeTranscriptApi()


def _get_transcript_list(api: YouTubeTranscriptApi, video_id: str) -> list[Any]:
    if hasattr(api, "list"):
        try:
            return _iter_transcripts(api.list(video_id))
        except Exception:
            pass
    if hasattr(YouTubeTranscriptApi, "list_transcripts"):
        try:
            return _iter_transcripts(YouTubeTranscriptApi.list_transcripts(video_id))
        except Exception:
            pass
    return []


def _fetch_raw_segments(selected_transcript: Any, api: YouTubeTranscriptApi, video_id: str) -> list[dict[str, Any]]:
    if hasattr(selected_transcript, "fetch"):
        try:
            fetched = selected_transcript.fetch()
            if hasattr(fetched, "to_raw_data"):
                return list(fetched.to_raw_data())
            return list(fetched)
        except Exception:
            pass

    if hasattr(api, "fetch"):
        try:
            fetched = api.fetch(video_id, languages=[getattr(selected_transcript, "language_code", "en")])
            if hasattr(fetched, "to_raw_data"):
                return list(fetched.to_raw_data())
            return list(fetched)
        except Exception:
            pass

    raise TranscriptNotFoundError("Transcript could not be fetched for this video.")


def _normalize_segments(raw_segments: list[dict[str, Any]], language: str, video_id: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for index, item in enumerate(raw_segments):
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = float(item.get("start", 0.0))
        duration = float(item.get("duration", 0.0))
        segments.append(
            TranscriptSegment(
                text=text,
                start=start,
                duration=duration,
                language=language,
                original_language=language,
                segment_index=index,
                video_id=video_id,
            )
        )
    return segments


def _validate_video_duration(duration_seconds: float, max_video_minutes: int) -> None:
    if duration_seconds > max_video_minutes * 60:
        raise VideoTooLongError(
            f"Video is longer than the configured maximum of {max_video_minutes} minutes for speech-to-text transcription."
        )


def _transcribe_audio_with_whisper(video_id: str) -> tuple[list[TranscriptSegment], str]:
    try:
        from yt_dlp import YoutubeDL
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptError(
            "Speech-to-text fallback requires the optional yt-dlp and faster-whisper packages."
        ) from exc

    settings = get_settings()
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="youtube-rag-audio-") as temporary_directory:
        output_template = str(Path(temporary_directory) / "audio.%(ext)s")
        options = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        with YoutubeDL(options) as downloader:
            metadata = downloader.extract_info(url, download=False)
            duration = float(metadata.get("duration") or 0)
            if duration <= 0:
                raise TranscriptError("Unable to determine video duration for speech-to-text transcription.")
            _validate_video_duration(duration, settings.max_video_minutes)
            downloaded = downloader.extract_info(url, download=True)
            requested_downloads = downloaded.get("requested_downloads") or []
            audio_path = (
                requested_downloads[0].get("filepath")
                if requested_downloads
                else downloaded.get("_filename") or downloader.prepare_filename(downloaded)
            )

        if not Path(audio_path).is_file():
            raise TranscriptError("yt-dlp did not produce a usable audio file.")
        model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
        transcription, metadata = model.transcribe(str(audio_path), beam_size=5)
        language = str(getattr(metadata, "language", "en") or "en")
        segments = [
            TranscriptSegment(
                text=segment.text.strip(),
                start=float(segment.start),
                duration=max(0.0, float(segment.end) - float(segment.start)),
                language=language,
                original_language=language,
                segment_index=index,
                video_id=video_id,
            )
            for index, segment in enumerate(transcription)
            if segment.text.strip()
        ]

    if not segments:
        raise TranscriptNotFoundError("Speech-to-text did not produce any usable transcript segments.")
    return segments, language


def fetch_transcript_segments(video_id: str, preferred_languages: list[str] | None = None) -> tuple[list[TranscriptSegment], TranscriptSource]:
    cleaned_video_id = extract_video_id(video_id) or video_id
    if not cleaned_video_id or not _VIDEO_ID_RE.fullmatch(cleaned_video_id):
        raise InvalidVideoIdError("Invalid YouTube video ID.")

    preferred_languages = preferred_languages or get_settings().transcript_language_preferences
    api = _get_transcript_api()

    transcript_list = _get_transcript_list(api, cleaned_video_id)
    if not transcript_list:
        raise TranscriptDisabledError("Transcript is unavailable or disabled for this video.")

    selected = _select_transcript_source(transcript_list, preferred_languages)
    if selected is None:
        raise TranscriptNotFoundError("No transcript could be selected for this video.")

    language_code = str(getattr(selected, "language_code", "unknown")).lower() or "unknown"
    language_name = getattr(selected, "language", None)
    raw_segments = _fetch_raw_segments(selected, api, cleaned_video_id)
    segments = _normalize_segments(raw_segments, language_code, cleaned_video_id)
    if not segments:
        raise TranscriptNotFoundError("The transcript did not contain any usable segments.")

    return segments, TranscriptSource(
        language_code=language_code,
        language_name=language_name,
        is_generated=getattr(selected, "is_generated", None),
        is_translatable=getattr(selected, "is_translatable", None),
        transcript=selected,
    )


def prepare_transcript(video_id: str) -> PreparedTranscript:
    cleaned_video_id = extract_video_id(video_id) or video_id
    try:
        segments, source = fetch_transcript_segments(cleaned_video_id)
        source_language = source.language_code
        transcript_source = source.transcript
        transcript_language_name = source.language_name
    except (TranscriptDisabledError, TranscriptNotFoundError):
        settings = get_settings()
        if not settings.whisper_fallback_enabled:
            raise
        segments, source_language = _transcribe_audio_with_whisper(cleaned_video_id)
        transcript_source = None
        transcript_language_name = source_language

    if source_language.startswith("en"):
        normalized_segments = segments
        translated = False
    else:
        normalized_segments, translated = translate_transcript_to_english(
            segments,
            source_language=source_language,
            transcript_source=transcript_source,
        )

    return PreparedTranscript(
        video_id=cleaned_video_id,
        source_language=source_language,
        normalized_language="en",
        translated=translated,
        title=fetch_video_title(cleaned_video_id),
        transcript_language_name=transcript_language_name,
        segments=normalized_segments,
        notes="Transcript normalized for English-only retrieval.",
    )
