from __future__ import annotations

from dataclasses import dataclass
import re
import textwrap

from .cache_service import (
    append_chat_message,
    get_chat_history,
    load_prepared_transcript,
    load_video_summary,
    safe_video_id,
    save_prepared_transcript,
    save_video_summary,
)
from .config import get_settings
from .models import (
    ChatResponse,
    PreparedTranscript,
    SourceReference,
    SummarySection,
    VideoLoadResponse,
    VideoSummaryResponse,
)
from .rag_service import VectorStoreBundle, _build_llm, generate_answer, get_or_build_knowledge_base
from .transcript_service import prepare_transcript


@dataclass(frozen=True)
class VideoState:
    video_id: str
    prepared_transcript: PreparedTranscript
    knowledge_base: VectorStoreBundle | None


_GLOBAL_QUESTION_PATTERNS = (
    re.compile(r"\b(?:summar(?:y|ies|i[sz](?:e|ation))|overview|main points?|key takeaways|highlights)\b", re.IGNORECASE),
    re.compile(r"\bwhat (?:is|was) (?:this|the) video about\b", re.IGNORECASE),
    re.compile(r"\b(?:whole|entire) video\b", re.IGNORECASE),
)


def classify_question(question: str) -> str:
    if any(pattern.search(question) for pattern in _GLOBAL_QUESTION_PATTERNS):
        return "global"
    return "specific"


def _get_prepared_transcript(video_id: str) -> PreparedTranscript:
    prepared = load_prepared_transcript(video_id)
    if prepared is None:
        prepared = prepare_transcript(video_id)
        save_prepared_transcript(prepared)
    return prepared


def _format_timestamp(seconds: float) -> str:
    total_seconds = int(max(0.0, seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _build_summary_inputs(prepared: PreparedTranscript) -> list[tuple[float, float, str]]:
    settings = get_settings()
    max_chars = max(1, settings.max_transcript_chars_per_batch)
    section_seconds = max(1, settings.summary_section_seconds)
    inputs: list[tuple[float, float, str]] = []
    current: list[tuple[float, float, str]] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if current:
            inputs.append((
                current[0][0],
                current[-1][1],
                " ".join(text for _, _, text in current),
            ))
        current = []
        current_chars = 0

    for segment in prepared.segments:
        text = segment.text.strip()
        if not text:
            continue
        pieces = textwrap.wrap(text, width=max_chars, break_long_words=True, break_on_hyphens=False) or [text]
        text_cursor = 0
        for piece in pieces:
            piece_offset = text.find(piece, text_cursor)
            if piece_offset < 0:
                piece_offset = text_cursor
            relative_start = piece_offset / max(len(text), 1)
            piece_start = segment.start + segment.duration * relative_start
            piece_end = min(segment.end_time, piece_start + segment.duration * len(piece) / max(len(text), 1))
            text_cursor = piece_offset + len(piece)
            if current and (
                piece_start - current[0][0] >= section_seconds
                or current_chars + len(piece) > max_chars
            ):
                flush()
            current.append((piece_start, piece_end, piece))
            current_chars += len(piece) + 1
    flush()
    return inputs


def _response_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        ).strip()
    return str(content).strip()


def _run_summary_prompt(prompt: str) -> str:
    return _response_text(_build_llm().invoke(prompt))


def _summary_batches(summaries: list[str], max_chars: int) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for summary in summaries:
        if current and current_chars + len(summary) > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(summary)
        current_chars += len(summary) + 1
    if current:
        batches.append(current)
    return batches


def summarize_video(video_id: str) -> VideoSummaryResponse:
    cleaned_video_id = safe_video_id(video_id)
    cached_summary = load_video_summary(cleaned_video_id)
    if cached_summary is not None:
        return cached_summary

    prepared = _get_prepared_transcript(cleaned_video_id)
    summary_inputs = _build_summary_inputs(prepared)
    if not summary_inputs:
        raise ValueError("The transcript did not contain any usable segments.")

    section_summaries: list[str] = []
    sections: list[SummarySection] = []
    for start_time, end_time, transcript_text in summary_inputs:
        prompt = (
            "Summarize only the transcript text below. Preserve important names, numbers, and events. "
            "Do not add outside information.\n"
            f"Transcript timestamps: {_format_timestamp(start_time)} - {_format_timestamp(end_time)}\n"
            f"Transcript:\n{transcript_text}"
        )
        section_summary = _run_summary_prompt(prompt)
        section_summaries.append(section_summary)
        sections.append(SummarySection(start_time=start_time, end_time=end_time, summary=section_summary))

    max_chars = max(1, get_settings().max_transcript_chars_per_batch)
    reduced_summaries = section_summaries
    while len("\n".join(reduced_summaries)) > max_chars and len(reduced_summaries) > 1:
        batches = _summary_batches(reduced_summaries, max_chars)
        if len(batches) >= len(reduced_summaries):
            break
        reduced_summaries = [
            _run_summary_prompt(
                "Condense these transcript section summaries without adding information:\n"
                + "\n\n".join(batch)
            )
            for batch in batches
        ]

    final_summary = _run_summary_prompt(
        "Combine the following transcript section summaries into a clear overview of the full video. "
        "Use only the provided information and retain key names, numbers, and conclusions:\n"
        + "\n\n".join(reduced_summaries)
    )
    result = VideoSummaryResponse(
        success=True,
        video_id=cleaned_video_id,
        summary=final_summary,
        sections=sections,
        message="Video summary generated successfully",
    )
    save_video_summary(result)
    return result


def _prepared_to_load_response(prepared: PreparedTranscript, message: str) -> VideoLoadResponse:
    return VideoLoadResponse(
        success=True,
        video_id=prepared.video_id,
        language=prepared.source_language,
        normalized_language=prepared.normalized_language,
        translated=prepared.translated,
        message=message,
        title=prepared.title,
    )


def load_video_for_video_id(video_id: str) -> VideoLoadResponse:
    cleaned_video_id = safe_video_id(video_id)
    prepared = _get_prepared_transcript(cleaned_video_id)

    # Build or load the vectorstore cache now so the first user question is fast.
    knowledge_base = get_or_build_knowledge_base(cleaned_video_id, prepared)
    _ = knowledge_base  # explicit: the warm-up is intentional.

    message = "Video loaded successfully"
    if prepared.translated:
        message = "Video loaded successfully and transcript was translated to English"
    return _prepared_to_load_response(prepared, message)


def _build_sources(retrieved_documents: list) -> list[SourceReference]:
    sources: list[SourceReference] = []
    for document in retrieved_documents:
        metadata = document.metadata or {}
        start_time = float(metadata.get("start_time", 0.0))
        end_time = float(metadata.get("end_time", start_time))
        sources.append(
            SourceReference(
                start_time=start_time,
                end_time=end_time,
                excerpt=document.page_content[:240],
                language=metadata.get("original_language") or metadata.get("language"),
            )
        )
    return sources


def answer_question(video_id: str, question: str, session_id: str) -> ChatResponse:
    cleaned_video_id = safe_video_id(video_id)
    settings = get_settings()

    if len(question.strip()) > settings.max_question_chars:
        return ChatResponse(
            success=False,
            video_id=cleaned_video_id,
            session_id=session_id,
            answer="",
            sources=[],
            message="The question is too long. Please shorten it and try again.",
        )

    history = get_chat_history(session_id, cleaned_video_id)
    prepared: PreparedTranscript | None = None

    try:
        if classify_question(question) == "global":
            summary = summarize_video(cleaned_video_id)
            answer = summary.summary
            sources = [
                SourceReference(
                    start_time=section.start_time,
                    end_time=section.end_time,
                    excerpt=section.summary[:240],
                    language="en",
                )
                for section in summary.sections
            ]
            prepared = _get_prepared_transcript(cleaned_video_id)
            append_chat_message(session_id, "user", question, cleaned_video_id)
            append_chat_message(session_id, "assistant", answer, cleaned_video_id)
            return ChatResponse(
                success=True,
                video_id=cleaned_video_id,
                session_id=session_id,
                answer=answer,
                sources=sources,
                language=prepared.source_language if prepared else "unknown",
                normalized_language=prepared.normalized_language if prepared else "en",
                translated=prepared.translated if prepared else False,
                message="Answer generated successfully",
            )

        prepared = _get_prepared_transcript(cleaned_video_id)
        knowledge_base = get_or_build_knowledge_base(cleaned_video_id, prepared)
        result = generate_answer(
            question=question,
            vectorstore=knowledge_base.vectorstore,
            history=history,
            documents=knowledge_base.documents,
        )
    except Exception as exc:
        return ChatResponse(
            success=False,
            video_id=cleaned_video_id,
            session_id=session_id,
            answer="",
            sources=[],
            language=prepared.source_language if prepared else "unknown",
            normalized_language=prepared.normalized_language if prepared else "en",
            translated=prepared.translated if prepared else False,
            message=f"Unable to generate an answer right now: {exc}",
        )

    append_chat_message(session_id, "user", question, cleaned_video_id)
    append_chat_message(session_id, "assistant", result.answer, cleaned_video_id)

    return ChatResponse(
        success=True,
        video_id=cleaned_video_id,
        session_id=session_id,
        answer=result.answer,
        sources=_build_sources(result.sources),
        language=prepared.source_language,
        normalized_language=prepared.normalized_language,
        translated=prepared.translated,
        message="Answer generated successfully",
    )
