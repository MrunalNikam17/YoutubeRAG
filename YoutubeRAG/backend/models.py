from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class VideoLoadRequest(BaseModel):
    video_id: str = Field(..., min_length=1, max_length=256)


class ChatRequest(BaseModel):
    video_id: str = Field(..., min_length=1, max_length=256)
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(..., min_length=1, max_length=128)


class VideoSummaryRequest(BaseModel):
    video_id: str = Field(..., min_length=1, max_length=256)


class SummarySection(BaseModel):
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)
    summary: str


class VideoSummaryResponse(BaseModel):
    success: bool
    video_id: str
    summary: str = ""
    sections: list[SummarySection] = Field(default_factory=list)
    message: str = ""


class SourceReference(BaseModel):
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)
    excerpt: str | None = None
    language: str | None = None


class VideoLoadResponse(BaseModel):
    success: bool
    video_id: str
    language: str = "unknown"
    normalized_language: str = "en"
    translated: bool = False
    message: str
    title: str | None = None


class ChatResponse(BaseModel):
    success: bool
    video_id: str
    session_id: str
    answer: str = ""
    sources: list[SourceReference] = Field(default_factory=list)
    language: str = "unknown"
    normalized_language: str = "en"
    translated: bool = False
    message: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    retrieval_mode: str = "vector"
    groq_configured: bool = False


class TranscriptSegment(BaseModel):
    text: str
    start: float = Field(..., ge=0)
    duration: float = Field(..., ge=0)
    language: str
    original_language: str | None = None
    segment_index: int | None = None
    video_id: str | None = None

    @property
    def end_time(self) -> float:
        return self.start + self.duration


class PreparedTranscript(BaseModel):
    video_id: str
    source_language: str
    normalized_language: str = "en"
    translated: bool = False
    title: str | None = None
    transcript_language_name: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    notes: str | None = None

    @property
    def segment_count(self) -> int:
        return len(self.segments)


class ChatMessage(BaseModel):
    role: str
    content: str


@dataclass(frozen=True)
class VideoKnowledgeBase:
    video_id: str
    vectorstore_path: str
    prepared_transcript: PreparedTranscript
    source_count: int
    vectorstore_ready: bool = True
