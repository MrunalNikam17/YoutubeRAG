from __future__ import annotations

from functools import lru_cache
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import get_settings
from .models import TranscriptSegment


TRANSLATION_SYSTEM_PROMPT = """You are a precise transcript translation engine.
Translate transcript segments into English.
Rules:
- Preserve meaning exactly.
- Do not summarize or omit content.
- Preserve technical terms and acronyms such as RAG, FAISS, LangChain, LLM, embedding, retriever.
- Keep proper nouns and code terms unchanged unless a direct English form is needed.
- Keep the same order as the input.
- Return valid JSON only.
- The JSON response must be an array of objects with the exact same length and order as the input.
- Each object must have only one field: text.
"""

_FALLBACK_MODELS = (
    None,
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "allam-2-7b",
)


def _build_llm(model_name: str | None = None) -> ChatOpenAI:
    settings = get_settings()
    if not settings.groq_enabled:
        raise RuntimeError("GROQ_API_KEY is not configured")
    model = model_name or settings.groq_model
    try:
        return ChatOpenAI(
            model=model,
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            temperature=0.1,
        )
    except TypeError:  # pragma: no cover - compatibility fallback
        return ChatOpenAI(
            model_name=model,
            openai_api_key=settings.groq_api_key,
            openai_api_base=settings.groq_base_url,
            temperature=0.1,
        )


@lru_cache(maxsize=1)
def _get_llm() -> ChatOpenAI:
    return _build_llm()


def _chunk_segments(segments: list[TranscriptSegment], max_chars: int) -> list[list[TranscriptSegment]]:
    batches: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    current_chars = 0
    for segment in segments:
        text_len = len(segment.text)
        if current and current_chars + text_len > max_chars:
            batches.append(current)
            current = [segment]
            current_chars = text_len
            continue
        current.append(segment)
        current_chars += text_len
    if current:
        batches.append(current)
    return batches


def _parse_translation_payload(raw_text: str, expected_length: int) -> list[str] | None:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    items: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict) and "text" in item:
                items.append(str(item["text"]))
    if len(items) != expected_length:
        return None
    return items


def _translate_batch_with_llm(batch: list[TranscriptSegment], source_language: str) -> list[str]:
    payload = [
        {"index": index, "text": segment.text, "start": segment.start, "duration": segment.duration}
        for index, segment in enumerate(batch)
    ]
    message = HumanMessage(
        content=(
            f"Translate the following {source_language} transcript segments into English.\n"
            f"Return JSON only, with exactly {len(batch)} objects in the same order.\n"
            f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        )
    )
    last_error: Exception | None = None
    for model_name in _FALLBACK_MODELS:
        try:
            llm = _build_llm(model_name)
            response = llm.invoke([SystemMessage(content=TRANSLATION_SYSTEM_PROMPT), message])
            content = getattr(response, "content", str(response))
            translations = _parse_translation_payload(content, len(batch))
            if translations is None:
                raise ValueError("The translation model did not return valid JSON")
            return translations
        except Exception as exc:
            last_error = exc
            message_text = str(exc).lower()
            if model_name is None and "model" not in message_text:
                break
            if "model_not_found" not in message_text and "does not exist or you do not have access" not in message_text:
                break
    if last_error is not None:
        raise last_error
    raise ValueError("The translation model did not return valid JSON")


def _translate_with_transcript_source(transcript_source: Any) -> list[TranscriptSegment] | None:
    if transcript_source is None or not hasattr(transcript_source, "translate"):
        return None
    try:
        translated_transcript = transcript_source.translate("en")
        fetched = translated_transcript.fetch() if hasattr(translated_transcript, "fetch") else translated_transcript
        raw_segments = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
        translated_segments: list[TranscriptSegment] = []
        for index, item in enumerate(raw_segments):
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            translated_segments.append(
                TranscriptSegment(
                    text=text,
                    start=float(item.get("start", 0.0)),
                    duration=float(item.get("duration", 0.0)),
                    language="en",
                    original_language=str(getattr(transcript_source, "language_code", "unknown")),
                    segment_index=index,
                )
            )
        return translated_segments or None
    except Exception:
        return None


def translate_transcript_to_english(
    segments: list[TranscriptSegment],
    source_language: str,
    transcript_source: Any | None = None,
) -> tuple[list[TranscriptSegment], bool]:
    if source_language.lower().startswith("en"):
        normalized = [segment.model_copy(update={"language": "en", "original_language": segment.original_language or source_language}) for segment in segments]
        return normalized, False

    settings = get_settings()
    batches = _chunk_segments(segments, max_chars=settings.max_transcript_chars_per_batch)
    translated_segments: list[TranscriptSegment] = []

    try:
        for batch in batches:
            translated_texts = _translate_batch_with_llm(batch, source_language)
            for segment, text in zip(batch, translated_texts):
                translated_segments.append(
                    segment.model_copy(
                        update={
                            "text": text.strip(),
                            "language": "en",
                            "original_language": segment.original_language or source_language,
                        }
                    )
                )
        return translated_segments, True
    except Exception:
        fallback_segments = _translate_with_transcript_source(transcript_source)
        if fallback_segments:
            return fallback_segments, True
        normalized = [
            segment.model_copy(update={"language": "en", "original_language": segment.original_language or source_language})
            for segment in segments
        ]
        return normalized, False
