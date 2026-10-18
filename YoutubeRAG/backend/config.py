from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent.parent


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI YouTube Video Chatbot")
    environment: str = os.getenv("ENVIRONMENT", "development")

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    huggingfacehub_api_token: str = os.getenv("HUGGINGFACEHUB_API_TOKEN", "")
    embedding_model_name: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    backend_url: str = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    retrieval_k: int = int(os.getenv("RETRIEVAL_K", "4"))
    retrieval_mode: str = os.getenv("RETRIEVAL_MODE", "vector").lower()
    retrieval_candidate_k: int = int(os.getenv("RETRIEVAL_CANDIDATE_K", "20"))
    rerank_enabled: bool = os.getenv("RERANK_ENABLED", "false").lower() in {"1", "true", "yes"}
    rerank_candidate_k: int = int(os.getenv("RERANK_CANDIDATE_K", "20"))
    max_question_chars: int = int(os.getenv("MAX_QUESTION_CHARS", "2000"))
    max_history_messages: int = int(os.getenv("MAX_HISTORY_MESSAGES", "8"))
    max_transcript_chars_per_batch: int = int(os.getenv("MAX_TRANSCRIPT_CHARS_PER_BATCH", "3500"))
    summary_section_seconds: int = int(os.getenv("SUMMARY_SECTION_SECONDS", "600"))
    whisper_fallback_enabled: bool = os.getenv("WHISPER_FALLBACK_ENABLED", "false").lower() in {"1", "true", "yes"}
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    max_video_minutes: int = int(os.getenv("MAX_VIDEO_MINUTES", "30"))
    api_key: str = os.getenv("API_KEY", "")

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", BASE_DIR / "data")))
    transcript_cache_dir: Path = field(default_factory=lambda: Path(os.getenv("TRANSCRIPT_CACHE_DIR", BASE_DIR / "data" / "transcripts")))
    vectorstore_dir: Path = field(default_factory=lambda: Path(os.getenv("VECTORSTORE_DIR", BASE_DIR / "data" / "vectorstores")))
    chat_history_db_path: Path = field(default_factory=lambda: Path(
        os.getenv("CHAT_HISTORY_DB_PATH", BASE_DIR / "data" / "chat_history.sqlite3")
    ))

    allowed_origins: list[str] = field(default_factory=lambda: _csv_env(
        "ALLOWED_ORIGINS",
        "http://localhost,http://127.0.0.1",
    ))
    allow_origin_regex: str = os.getenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"^chrome-extension://[a-p]{32}$",
    ) or r"^chrome-extension://[a-p]{32}$"
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    transcript_language_preferences: list[str] = field(default_factory=lambda: _csv_env(
        "TRANSCRIPT_LANGUAGE_PREFERENCES",
        "en,hi",
    ))

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_cache_dir.mkdir(parents=True, exist_ok=True)
        self.vectorstore_dir.mkdir(parents=True, exist_ok=True)

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
