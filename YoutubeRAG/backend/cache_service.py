from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import json
import re
import sqlite3

from .config import get_settings
from .models import ChatMessage, PreparedTranscript, VideoSummaryResponse

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class CachePaths:
    root: Path
    transcript_json: Path
    vectorstore_dir: Path
    metadata_json: Path
    summary_json: Path


def safe_video_id(video_id: str) -> str:
    cleaned = video_id.strip()
    if not cleaned:
        raise ValueError("video_id cannot be empty")
    if not _VIDEO_ID_RE.fullmatch(cleaned):
        raise ValueError("video_id contains invalid characters")
    return cleaned


def get_cache_paths(video_id: str) -> CachePaths:
    settings = get_settings()
    cleaned = safe_video_id(video_id)
    root = settings.vectorstore_dir / cleaned
    return CachePaths(
        root=root,
        transcript_json=settings.transcript_cache_dir / f"{cleaned}.json",
        vectorstore_dir=root / "faiss",
        metadata_json=root / "metadata.json",
        summary_json=root / "summary.json",
    )


def ensure_cache_dirs(video_id: str) -> CachePaths:
    paths = get_cache_paths(video_id)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    paths.transcript_json.parent.mkdir(parents=True, exist_ok=True)
    paths.metadata_json.parent.mkdir(parents=True, exist_ok=True)
    return paths


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_prepared_transcript(prepared: PreparedTranscript) -> CachePaths:
    paths = ensure_cache_dirs(prepared.video_id)
    payload = prepared.model_dump(mode="json") if hasattr(prepared, "model_dump") else prepared.dict()
    save_json(paths.transcript_json, payload)
    save_json(paths.metadata_json, {
        "video_id": prepared.video_id,
        "source_language": prepared.source_language,
        "normalized_language": prepared.normalized_language,
        "translated": prepared.translated,
        "segment_count": prepared.segment_count,
        "title": prepared.title,
    })
    return paths


def load_prepared_transcript(video_id: str) -> PreparedTranscript | None:
    payload = load_json(get_cache_paths(video_id).transcript_json)
    if not payload:
        return None
    if hasattr(PreparedTranscript, "model_validate"):
        return PreparedTranscript.model_validate(payload)
    return PreparedTranscript.parse_obj(payload)


def save_video_summary(summary: VideoSummaryResponse) -> None:
    paths = get_cache_paths(summary.video_id)
    payload = summary.model_dump(mode="json") if hasattr(summary, "model_dump") else summary.dict()
    save_json(paths.summary_json, payload)


def load_video_summary(video_id: str) -> VideoSummaryResponse | None:
    payload = load_json(get_cache_paths(video_id).summary_json)
    if not payload:
        return None
    if hasattr(VideoSummaryResponse, "model_validate"):
        return VideoSummaryResponse.model_validate(payload)
    return VideoSummaryResponse.parse_obj(payload)


def _connect_chat_history() -> sqlite3.Connection:
    settings = get_settings()
    settings.chat_history_db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.chat_history_db_path, timeout=10)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS chat_history_session_video ON chat_history (session_id, video_id, id)"
    )
    connection.commit()
    return connection


def append_chat_message(session_id: str, role: str, content: str, video_id: str | None = None) -> None:
    cleaned_video_id = safe_video_id(video_id) if video_id is not None else ""
    settings = get_settings()
    with closing(_connect_chat_history()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO chat_history (session_id, video_id, role, content) VALUES (?, ?, ?, ?)",
                (session_id, cleaned_video_id, role, content),
            )
            connection.execute(
                """
                DELETE FROM chat_history
                WHERE id IN (
                    SELECT id FROM chat_history
                    WHERE session_id = ? AND video_id = ?
                    ORDER BY id DESC LIMIT -1 OFFSET ?
                )
                """,
                (session_id, cleaned_video_id, max(0, settings.max_history_messages)),
            )


def get_chat_history(session_id: str, video_id: str | None = None) -> list[ChatMessage]:
    cleaned_video_id = safe_video_id(video_id) if video_id is not None else ""
    limit = max(0, get_settings().max_history_messages)
    if limit == 0:
        return []
    with closing(_connect_chat_history()) as connection:
        rows = connection.execute(
            """
            SELECT role, content FROM chat_history
            WHERE session_id = ? AND video_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, cleaned_video_id, limit),
        ).fetchall()
    return [ChatMessage(role=role, content=content) for role, content in reversed(rows)]


def clear_chat_history(session_id: str, video_id: str | None = None) -> None:
    with closing(_connect_chat_history()) as connection:
        with connection:
            if video_id is None:
                connection.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
            else:
                connection.execute(
                    "DELETE FROM chat_history WHERE session_id = ? AND video_id = ?",
                    (session_id, safe_video_id(video_id)),
                )
