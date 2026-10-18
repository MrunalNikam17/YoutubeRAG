from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
import secrets
from threading import Lock
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from .cache_service import safe_video_id
from .chat_service import answer_question, load_video_for_video_id, summarize_video
from .config import get_settings
from .models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    VideoLoadRequest,
    VideoLoadResponse,
    VideoSummaryRequest,
    VideoSummaryResponse,
)
from .transcript_service import extract_video_id

settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0.0")
_request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", _request_id_context.get()),
        }
        for name in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("youtube_rag")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allow_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)

_rate_limit_requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()


@app.middleware("http")
async def add_request_id_and_log(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_id) else str(uuid.uuid4())
    token = _request_id_context.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response
    except Exception:
        logger.exception(
            "request failed",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        raise
    finally:
        _request_id_context.reset(token)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured_key = settings.api_key
    if configured_key and (
        x_api_key is None or not secrets.compare_digest(x_api_key, configured_key)
    ):
        raise HTTPException(status_code=401, detail="A valid X-API-Key header is required.")


def enforce_rate_limit(request: Request) -> None:
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return

    key = (request.url.path, request.client.host if request.client else "unknown")
    now = time.monotonic()
    with _rate_limit_lock:
        requests = _rate_limit_requests[key]
        while requests and now - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
        requests.append(now)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        retrieval_mode=settings.retrieval_mode,
        groq_configured=settings.groq_enabled,
    )


@app.post("/api/video/load", response_model=VideoLoadResponse)
def api_video_load(
    payload: VideoLoadRequest,
    _: None = Depends(enforce_rate_limit),
    __: None = Depends(require_api_key),
) -> VideoLoadResponse:
    try:
        raw_id = extract_video_id(payload.video_id) or payload.video_id
        video_id = safe_video_id(raw_id)
        return load_video_for_video_id(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        return VideoLoadResponse(
            success=False,
            video_id=payload.video_id,
            language="unknown",
            normalized_language="en",
            translated=False,
            message=f"Unable to load the video: {exc}",
        )


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(
    payload: ChatRequest,
    _: None = Depends(enforce_rate_limit),
    __: None = Depends(require_api_key),
) -> ChatResponse:
    try:
        raw_id = extract_video_id(payload.video_id) or payload.video_id
        video_id = safe_video_id(raw_id)
        return answer_question(video_id=video_id, question=payload.question, session_id=payload.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        return ChatResponse(
            success=False,
            video_id=payload.video_id,
            session_id=payload.session_id,
            answer="",
            sources=[],
            message=f"Unable to answer the question: {exc}",
        )


@app.post("/api/video/summary", response_model=VideoSummaryResponse)
def api_video_summary(
    payload: VideoSummaryRequest,
    _: None = Depends(require_api_key),
) -> VideoSummaryResponse:
    try:
        raw_id = extract_video_id(payload.video_id) or payload.video_id
        return summarize_video(safe_video_id(raw_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to summarize the video: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
