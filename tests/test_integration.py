from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableLambda

from backend import cache_service, chat_service, main, rag_service
from backend.models import PreparedTranscript, TranscriptSegment


class FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), float(text.lower().count("rag"))] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), float(text.lower().count("rag"))]

    def __call__(self, text: str) -> list[float]:
        return self.embed_query(text)


def test_load_then_chat_full_flow_with_external_services_mocked(monkeypatch, tmp_path):
    prepared = PreparedTranscript(
        video_id="J5_-l7WIO_w",
        source_language="en",
        segments=[
            TranscriptSegment(
                text="RAG means Retrieval Augmented Generation.",
                start=12,
                duration=4,
                language="en",
                video_id="J5_-l7WIO_w",
            ),
            TranscriptSegment(
                text="It retrieves relevant transcript chunks for an answer.",
                start=16,
                duration=4,
                language="en",
                video_id="J5_-l7WIO_w",
            ),
        ],
    )
    settings = replace(
        cache_service.get_settings(),
        data_dir=tmp_path / "data",
        transcript_cache_dir=tmp_path / "transcripts",
        vectorstore_dir=tmp_path / "vectorstores",
        chat_history_db_path=tmp_path / "history.sqlite3",
    )
    monkeypatch.setattr(cache_service, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_service, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service, "get_settings", lambda: settings)
    monkeypatch.setattr(chat_service, "prepare_transcript", lambda video_id: prepared)
    monkeypatch.setattr(rag_service, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(
        rag_service,
        "_build_llm",
        lambda model_name=None: RunnableLambda(
            lambda messages: "RAG means Retrieval Augmented Generation."
        ),
    )

    client = TestClient(main.app)
    load_response = client.post("/api/video/load", json={"video_id": "J5_-l7WIO_w"})
    chat_response = client.post(
        "/api/chat",
        json={
            "video_id": "J5_-l7WIO_w",
            "question": "What does RAG mean?",
            "session_id": "integration-session",
        },
    )

    assert load_response.status_code == 200
    assert load_response.json()["success"] is True
    assert chat_response.status_code == 200
    assert chat_response.json()["success"] is True, chat_response.json()["message"]
    assert chat_response.json()["answer"] == "RAG means Retrieval Augmented Generation."
    assert chat_response.json()["sources"][0]["start_time"] == 12
    assert [message.content for message in cache_service.get_chat_history(
        "integration-session",
        "J5_-l7WIO_w",
    )] == [
        "What does RAG mean?",
        "RAG means Retrieval Augmented Generation.",
    ]
