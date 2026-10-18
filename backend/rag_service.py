from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:  # pragma: no cover - compatibility fallback
    from langchain_community.embeddings import HuggingFaceEmbeddings

from langchain_openai import ChatOpenAI

from .cache_service import get_cache_paths, load_prepared_transcript, save_prepared_transcript
from .config import get_settings
from .models import ChatMessage, PreparedTranscript, TranscriptSegment, VideoKnowledgeBase

SYSTEM_PROMPT = """You are an AI assistant that answers questions about a YouTube video.
Answer ONLY using the provided transcript context and the conversation history.
Do not use outside knowledge.
Do not hallucinate.
If the transcript does not contain enough information to answer the question, say exactly:
I couldn't find that information in this video.
When possible, answer clearly and concisely.
If timestamps are available, mention the relevant source timestamp(s).
"""


@dataclass(frozen=True)
class RetrievalAnswer:
    answer: str
    sources: list[Document]


@dataclass(frozen=True)
class VectorStoreBundle:
    video_id: str
    vectorstore: FAISS
    documents: list[Document]
    prepared_transcript: PreparedTranscript
    cache_vectorstore_path: str


_FALLBACK_MODELS = (
    None,
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "allam-2-7b",
)


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    settings = get_settings()
    try:
        return HuggingFaceEmbeddings(model_name=settings.embedding_model_name)
    except TypeError:  # pragma: no cover - compatibility fallback
        return HuggingFaceEmbeddings(model_name=settings.embedding_model_name, model_kwargs={"device": "cpu"})


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
            temperature=0.15,
        )
    except TypeError:  # pragma: no cover - compatibility fallback
        return ChatOpenAI(
            model_name=model,
            openai_api_key=settings.groq_api_key,
            openai_api_base=settings.groq_base_url,
            temperature=0.15,
        )


@lru_cache(maxsize=1)
def _get_llm() -> ChatOpenAI:
    return _build_llm()


def _format_timestamp(seconds: float) -> str:
    total_seconds = int(max(0.0, seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _segment_to_document(segment: TranscriptSegment) -> Document:
    return Document(
        page_content=segment.text.strip(),
        metadata={
            "video_id": segment.video_id,
            "start_time": float(segment.start),
            "end_time": float(segment.end_time),
            "original_language": segment.original_language or segment.language,
            "language": segment.language,
            "segment_index": segment.segment_index,
        },
    )


def _finalize_chunk(
    batch: list[TranscriptSegment],
    chunk_size: int,
    chunk_overlap: int,
) -> list[Document]:
    if not batch:
        return []

    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    combined_text = " ".join(segment.text.strip() for segment in batch if segment.text.strip())
    start_time = float(batch[0].start)
    end_time = float(batch[-1].end_time)
    metadata = {
        "video_id": batch[0].video_id,
        "start_time": start_time,
        "end_time": end_time,
        "original_language": batch[0].original_language or batch[0].language,
        "language": batch[0].language,
        "segment_count": len(batch),
    }

    if len(combined_text) <= chunk_size:
        return [Document(page_content=combined_text, metadata=metadata)]

    chunks = splitter.split_text(combined_text)
    return [Document(page_content=chunk, metadata=dict(metadata, chunk_index=index)) for index, chunk in enumerate(chunks)]


def chunk_transcript_segments(
    segments: list[TranscriptSegment],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    settings = get_settings()
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap

    batches: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    current_length = 0

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if current and current_length + len(text) > chunk_size:
            batches.append(current)
            current = []
            current_length = 0
        current.append(segment)
        current_length += len(text) + 1

    if current:
        batches.append(current)

    documents: list[Document] = []
    for batch in batches:
        documents.extend(_finalize_chunk(batch, chunk_size=chunk_size, chunk_overlap=chunk_overlap))
    return documents


def create_documents(prepared_transcript: PreparedTranscript) -> list[Document]:
    # Keep the transcript source metadata intact and create retrievable chunks.
    chunked_documents = chunk_transcript_segments(prepared_transcript.segments)
    if chunked_documents:
        return chunked_documents
    return [_segment_to_document(segment) for segment in prepared_transcript.segments]


def build_vectorstore(documents: list[Document]) -> FAISS:
    if not documents:
        raise ValueError("Cannot build a vector store without documents")
    embeddings = get_embeddings()
    return FAISS.from_documents(documents, embeddings)


def _manifest_path(path: str) -> Path:
    return Path(path) / "index.manifest.json"


def _index_file_hashes(path: str) -> dict[str, str]:
    directory = Path(path)
    return {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(directory.iterdir())
        if file.is_file() and file.name != "index.manifest.json"
    }


def _write_index_manifest(path: str) -> None:
    manifest = _manifest_path(path)
    manifest.write_text(
        json.dumps(_index_file_hashes(path), sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _verify_index_manifest(path: str) -> bool:
    manifest = _manifest_path(path)
    if not manifest.is_file():
        return False
    try:
        expected = json.loads(manifest.read_text(encoding="utf-8"))
        return bool(expected) and expected == _index_file_hashes(path)
    except (OSError, ValueError, TypeError):
        return False


def save_vectorstore(vectorstore: FAISS, path: str) -> None:
    vectorstore.save_local(path)
    _write_index_manifest(path)


def load_vectorstore(path: str) -> FAISS | None:
    if not _verify_index_manifest(path):
        return None
    embeddings = get_embeddings()
    try:
        return FAISS.load_local(path, embeddings, allow_dangerous_deserialization=True)
    except TypeError:  # pragma: no cover - compatibility fallback
        try:
            return FAISS.load_local(path, embeddings)
        except Exception:
            return None
    except Exception:
        return None


def load_or_create_knowledge_base(prepared_transcript: PreparedTranscript) -> VectorStoreBundle:
    cache_paths = get_cache_paths(prepared_transcript.video_id)
    cached_vectorstore = load_vectorstore(str(cache_paths.vectorstore_dir))
    if cached_vectorstore is not None:
        documents = create_documents(prepared_transcript)
        return VectorStoreBundle(
            video_id=prepared_transcript.video_id,
            vectorstore=cached_vectorstore,
            documents=documents,
            prepared_transcript=prepared_transcript,
            cache_vectorstore_path=str(cache_paths.vectorstore_dir),
        )

    if cache_paths.vectorstore_dir.exists():
        shutil.rmtree(cache_paths.vectorstore_dir)
    documents = create_documents(prepared_transcript)
    vectorstore = build_vectorstore(documents)
    cache_paths.root.mkdir(parents=True, exist_ok=True)
    cache_paths.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    save_vectorstore(vectorstore, str(cache_paths.vectorstore_dir))
    save_prepared_transcript(prepared_transcript)
    return VectorStoreBundle(
        video_id=prepared_transcript.video_id,
        vectorstore=vectorstore,
        documents=documents,
        prepared_transcript=prepared_transcript,
        cache_vectorstore_path=str(cache_paths.vectorstore_dir),
    )


def get_or_build_knowledge_base(video_id: str, prepared_transcript: PreparedTranscript | None = None) -> VectorStoreBundle:
    transcript = prepared_transcript or load_prepared_transcript(video_id)
    if transcript is None:
        raise ValueError("Transcript is not prepared for this video")
    return load_or_create_knowledge_base(transcript)


def _format_history(history: list[ChatMessage]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for message in history:
        role = message.role.strip().lower()
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {message.content.strip()}")
    return "\n".join(lines)


def _format_context(documents: list[Document]) -> str:
    formatted_chunks: list[str] = []
    for index, document in enumerate(documents, start=1):
        metadata = document.metadata or {}
        start = _format_timestamp(float(metadata.get("start_time", 0.0)))
        end = _format_timestamp(float(metadata.get("end_time", metadata.get("start_time", 0.0))))
        formatted_chunks.append(
            f"[Source {index} | {start} - {end}]\n{document.page_content.strip()}"
        )
    return "\n\n".join(formatted_chunks)


def _collect_sources(documents: list[Document]) -> list[Document]:
    deduped: list[Document] = []
    seen: set[tuple[Any, Any]] = set()
    for document in documents:
        metadata = document.metadata or {}
        key = (metadata.get("start_time"), metadata.get("end_time"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(document)
    return deduped


def retrieve_documents(
    vectorstore: FAISS,
    question: str,
    k: int | None = None,
    documents: list[Document] | None = None,
) -> list[Document]:
    settings = get_settings()
    result_count = k or settings.retrieval_k
    use_hybrid = settings.retrieval_mode == "hybrid"
    candidate_count = max(
        result_count,
        settings.rerank_candidate_k if settings.rerank_enabled else settings.retrieval_candidate_k,
    )
    vector_results = vectorstore.similarity_search(
        question,
        k=candidate_count if use_hybrid or settings.rerank_enabled else result_count,
    )

    if use_hybrid:
        corpus = documents if documents is not None else _all_vectorstore_documents(vectorstore)
        ranked_documents = _reciprocal_rank_fusion(
            vector_results,
            _bm25_rank(corpus, question, candidate_count),
            limit=candidate_count,
        )
    else:
        ranked_documents = vector_results

    if settings.rerank_enabled and ranked_documents:
        ranked_documents = _rerank_documents(question, ranked_documents, candidate_count)

    return _deduplicate_documents(ranked_documents, result_count)


def _deduplicate_documents(documents: list[Document], limit: int) -> list[Document]:
    unique: list[Document] = []
    normalized_texts: list[str] = []
    token_sets: list[set[str]] = []
    for document in documents:
        normalized = " ".join(document.page_content.lower().split())
        tokens = set(_tokens(normalized))
        duplicate = False
        for existing_text, existing_tokens in zip(normalized_texts, token_sets):
            union = tokens | existing_tokens
            token_similarity = len(tokens & existing_tokens) / len(union) if union else 1.0
            if (
                normalized == existing_text
                or SequenceMatcher(None, normalized, existing_text).ratio() >= 0.92
                or token_similarity >= 0.9
            ):
                duplicate = True
                break
        if duplicate:
            continue
        unique.append(document)
        normalized_texts.append(normalized)
        token_sets.append(tokens)
        if len(unique) >= limit:
            break
    return unique


def _all_vectorstore_documents(vectorstore: FAISS) -> list[Document]:
    docstore = getattr(vectorstore, "docstore", None)
    documents = getattr(docstore, "_dict", {}).values()
    return [document for document in documents if isinstance(document, Document)]


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _bm25_rank(documents: list[Document], query: str, limit: int) -> list[Document]:
    query_terms = set(_tokens(query))
    tokenized = [_tokens(document.page_content) for document in documents]
    if not query_terms or not documents:
        return []

    document_frequency = {
        term: sum(term in set(tokens) for tokens in tokenized)
        for term in query_terms
    }
    average_length = sum(len(tokens) for tokens in tokenized) / len(tokenized)
    scores: list[tuple[float, int, Document]] = []
    for index, (document, tokens) in enumerate(zip(documents, tokenized)):
        frequencies = {term: tokens.count(term) for term in query_terms}
        score = 0.0
        for term, frequency in frequencies.items():
            if frequency == 0:
                continue
            inverse_frequency = math.log(1 + (len(documents) - document_frequency[term] + 0.5) /
                                         (document_frequency[term] + 0.5))
            length_norm = frequency + 1.2 * (0.25 + 0.75 * len(tokens) / max(average_length, 1))
            score += inverse_frequency * frequency * 2.2 / length_norm
        if score > 0:
            scores.append((score, index, document))
    scores.sort(key=lambda item: (-item[0], item[1]))
    return [document for _, _, document in scores[:limit]]


def _reciprocal_rank_fusion(
    first: list[Document],
    second: list[Document],
    limit: int,
    rank_constant: int = 60,
    rank_weights: tuple[float, float] = (2.0, 1.0),
) -> list[Document]:
    scores: dict[tuple[str, Any, Any], tuple[float, Document]] = {}
    for weight, ranked_list in zip(rank_weights, (second, first)):
        for rank, document in enumerate(ranked_list, start=1):
            metadata = document.metadata or {}
            key = (document.page_content, metadata.get("start_time"), metadata.get("end_time"))
            score, _ = scores.get(key, (0.0, document))
            scores[key] = (score + weight / (rank_constant + rank), document)
    return [
        document
        for _, document in sorted(scores.values(), key=lambda item: item[0], reverse=True)[:limit]
    ]


@lru_cache(maxsize=1)
def _get_cross_encoder() -> Any:
    from sentence_transformers import CrossEncoder

    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


def _rerank_documents(question: str, documents: list[Document], limit: int) -> list[Document]:
    reranker = _get_cross_encoder()
    scores = reranker.predict([(question, document.page_content) for document in documents])
    return [
        document
        for _, document in sorted(
            zip(scores, documents),
            key=lambda item: float(item[0]),
            reverse=True,
        )[:limit]
    ]


def generate_answer(
    question: str,
    vectorstore: FAISS,
    history: list[ChatMessage] | None = None,
    k: int | None = None,
    documents: list[Document] | None = None,
) -> RetrievalAnswer:
    history = history or []
    retrieved_documents = retrieve_documents(vectorstore, question, k=k, documents=documents)
    context = _format_context(retrieved_documents)
    chat_history = _format_history(history)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                "Conversation history:\n{chat_history}\n\nContext:\n{context}\n\nQuestion:\n{question}",
            ),
        ]
    )

    last_error: Exception | None = None
    for model_name in _FALLBACK_MODELS:
        try:
            llm = _build_llm(model_name)
            chain = prompt | llm | StrOutputParser()
            answer = chain.invoke({"chat_history": chat_history, "context": context, "question": question}).strip()
            return RetrievalAnswer(answer=answer, sources=_collect_sources(retrieved_documents))
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            if model_name is None and "model" not in message:
                break
            if "model_not_found" not in message and "does not exist or you do not have access" not in message:
                break
    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to generate an answer")
