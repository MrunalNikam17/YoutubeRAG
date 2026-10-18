from __future__ import annotations

from dataclasses import replace
import json

from backend import cache_service, rag_service
from backend.models import PreparedTranscript, TranscriptSegment
from langchain_core.documents import Document


class FakeEmbeddings:
    def embed_documents(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([
                float(lowered.count("rag")),
                float(lowered.count("retriever")),
                float(len(text)),
            ])
        return vectors

    def embed_query(self, text):
        lowered = text.lower()
        return [float(lowered.count("rag")), float(lowered.count("retriever")), float(len(text))]

    def __call__(self, text):
        return self.embed_query(text)


def test_chunk_transcript_segments_preserves_metadata():
    segments = [
        TranscriptSegment(text="First segment.", start=0.0, duration=2.0, language="en", original_language="hi", video_id="J5_-l7WIO_w"),
        TranscriptSegment(text="Second segment.", start=2.0, duration=3.0, language="en", original_language="hi", video_id="J5_-l7WIO_w"),
    ]

    documents = rag_service.chunk_transcript_segments(segments, chunk_size=50, chunk_overlap=10)

    assert documents
    assert documents[0].metadata["video_id"] == "J5_-l7WIO_w"
    assert documents[0].metadata["start_time"] == 0.0
    assert documents[0].metadata["end_time"] == 5.0


def test_vectorstore_creation_and_retrieval(monkeypatch):
    monkeypatch.setattr(rag_service, "get_embeddings", lambda: FakeEmbeddings())

    prepared = PreparedTranscript(
        video_id="J5_-l7WIO_w",
        source_language="en",
        translated=False,
        segments=[
            TranscriptSegment(text="RAG stands for Retrieval Augmented Generation.", start=0.0, duration=4.0, language="en", video_id="J5_-l7WIO_w"),
            TranscriptSegment(text="A retriever finds relevant chunks.", start=4.0, duration=4.0, language="en", video_id="J5_-l7WIO_w"),
        ],
    )

    documents = rag_service.create_documents(prepared)
    vectorstore = rag_service.build_vectorstore(documents)
    results = rag_service.retrieve_documents(vectorstore, "What does RAG stand for?", k=1)

    assert results
    assert "RAG" in results[0].page_content


def test_vectorstore_manifest_tracks_saved_files(tmp_path):
    (tmp_path / "index.faiss").write_bytes(b"index data")
    (tmp_path / "index.pkl").write_bytes(b"pickle data")

    rag_service._write_index_manifest(str(tmp_path))

    manifest = json.loads((tmp_path / "index.manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"index.faiss", "index.pkl"}
    assert rag_service._verify_index_manifest(str(tmp_path))

    (tmp_path / "index.faiss").write_bytes(b"tampered index")
    assert not rag_service._verify_index_manifest(str(tmp_path))


def test_load_vectorstore_does_not_deserialize_invalid_cache(monkeypatch, tmp_path):
    called = False

    def load_local(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("unverified cache must not be deserialized")

    monkeypatch.setattr(rag_service, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(rag_service.FAISS, "load_local", load_local)

    assert rag_service.load_vectorstore(str(tmp_path)) is None
    assert called is False


def test_hybrid_retrieval_finds_keyword_heavy_chunk_missed_by_vector(monkeypatch):
    docs = [
        Document(page_content="General discussion about quarterly planning."),
        Document(page_content="The speaker introduces the next topic."),
        Document(page_content="In 2024, Nia Park reported 17.3 million units in the QX-91 study."),
    ]

    class KeywordBlindVectorStore:
        def similarity_search(self, question, k):
            return docs[:k if k == 1 else 2]

    vectorstore = KeywordBlindVectorStore()
    settings = replace(
        rag_service.get_settings(),
        retrieval_k=1,
        retrieval_mode="vector",
        retrieval_candidate_k=3,
    )
    monkeypatch.setattr(rag_service, "get_settings", lambda: settings)

    vector_results = rag_service.retrieve_documents(
        vectorstore,
        "Nia Park QX-91 17.3 million units",
        documents=docs,
    )
    assert vector_results[0] is docs[0]

    settings = replace(settings, retrieval_mode="hybrid")
    hybrid_results = rag_service.retrieve_documents(
        vectorstore,
        "Nia Park QX-91 17.3 million units",
        documents=docs,
    )

    assert hybrid_results[0] is docs[2]


def test_retrieval_deduplicates_near_identical_chunks():
    documents = [
        Document(page_content="The speaker explains retrieval augmented generation in detail."),
        Document(page_content="The speaker explains retrieval augmented generation in detail!"),
        Document(page_content="A separate discussion covers transcript translation."),
    ]

    results = rag_service._deduplicate_documents(documents, 3)

    assert results == [documents[0], documents[2]]


def test_optional_cross_encoder_reranks_candidates(monkeypatch):
    docs = [
        Document(page_content="Initial vector result"),
        Document(page_content="Cross encoder winner"),
        Document(page_content="Another candidate"),
    ]

    class VectorStore:
        def similarity_search(self, question, k):
            return docs[:k]

    class CrossEncoder:
        def predict(self, pairs):
            assert len(pairs) == 3
            return [0.1, 0.9, 0.2]

    settings = replace(
        rag_service.get_settings(),
        retrieval_mode="vector",
        retrieval_k=1,
        retrieval_candidate_k=3,
        rerank_enabled=True,
        rerank_candidate_k=3,
    )
    monkeypatch.setattr(rag_service, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service, "_get_cross_encoder", lambda: CrossEncoder())

    results = rag_service.retrieve_documents(VectorStore(), "query")

    assert results == [docs[1]]


def test_invalid_index_cache_is_discarded_and_rebuilt(monkeypatch, tmp_path):
    settings = replace(
        cache_service.get_settings(),
        data_dir=tmp_path / "data",
        transcript_cache_dir=tmp_path / "transcripts",
        vectorstore_dir=tmp_path / "vectorstores",
    )
    monkeypatch.setattr(cache_service, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service, "get_embeddings", lambda: FakeEmbeddings())
    prepared = PreparedTranscript(
        video_id="J5_-l7WIO_w",
        source_language="en",
        segments=[TranscriptSegment(text="RAG transcript text", start=0, duration=2, language="en")],
    )
    cache_paths = cache_service.get_cache_paths(prepared.video_id)
    cache_paths.vectorstore_dir.mkdir(parents=True)
    (cache_paths.vectorstore_dir / "tampered.pkl").write_bytes(b"untrusted")

    bundle = rag_service.load_or_create_knowledge_base(prepared)

    assert bundle.vectorstore is not None
    assert rag_service._verify_index_manifest(str(cache_paths.vectorstore_dir))
    assert "tampered.pkl" not in {path.name for path in cache_paths.vectorstore_dir.iterdir()}
