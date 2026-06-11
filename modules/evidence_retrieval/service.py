from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable, List

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from core.config import settings
from modules.jobs import JobCreateResponse, create_job, schedule_job
from store.ai_database import SessionLocal
from store.ai_models import EvidenceChunk, EvidenceEmbedding

from .schemas import EvidenceSearchRequest, EvidenceSearchResponse, EvidenceSearchResult


class AiDatabaseUnavailable(RuntimeError):
    pass


class EmbeddingServiceUnavailable(RuntimeError):
    pass


class EmptySearchQuestion(ValueError):
    pass


def schedule_evidence_index(document_id: str | None = None) -> JobCreateResponse:
    normalized_document_id = _normalize_optional_document_id(document_id)
    target_type = "document" if normalized_document_id else "evidence_embeddings"
    target_id = normalized_document_id or "all"
    job = create_job(job_type="build_embedding", target_type=target_type, target_id=target_id)
    schedule_job(job.id, build_missing_evidence_embeddings)
    return JobCreateResponse(job_id=job.id, status=job.status)


async def build_missing_evidence_embeddings(target_id: str) -> int:
    document_id = None if str(target_id or "").strip() in {"", "all"} else str(target_id).strip()
    chunks = _load_unembedded_chunks(document_id)
    if not chunks:
        return 0

    texts = [_embedding_text_for(chunk) for chunk in chunks]
    vectors = await embed_texts(texts)
    if len(vectors) != len(chunks):
        raise EmbeddingServiceUnavailable("embedding_count_mismatch")

    session = SessionLocal()
    try:
        now = datetime.utcnow()
        for chunk, vector in zip(chunks, vectors):
            session.add(
                EvidenceEmbedding(
                    evidence_id=int(chunk.id),
                    document_id=str(chunk.document_id),
                    embedding=_normalize_vector(vector),
                    embedding_model=_embedding_model(),
                    created_at=now,
                )
            )
        session.commit()
        return len(chunks)
    except SQLAlchemyError as exc:
        session.rollback()
        raise AiDatabaseUnavailable("ai_database_unavailable") from exc
    finally:
        session.close()


async def search_evidence(request: EvidenceSearchRequest) -> EvidenceSearchResponse:
    question = str(request.question or "").strip()
    if not question:
        raise EmptySearchQuestion("empty_search_question")
    vector = (await embed_texts([question]))[0]
    document_ids = [item for item in (str(value).strip() for value in request.document_ids or []) if item]
    results = _search_by_vector(_normalize_vector(vector), top_k=int(request.top_k or 8), document_ids=document_ids)
    return EvidenceSearchResponse(results=results)


async def embed_texts(texts: List[str]) -> List[List[float]]:
    cleaned = [str(text or "").strip() for text in texts]
    if not cleaned:
        return []
    base_url = str(settings.ai_base_url or "").rstrip("/")
    api_key = str(settings.ai_api_key or "").strip()
    model = _embedding_model()
    if not base_url or not api_key or not model:
        raise EmbeddingServiceUnavailable("embedding_service_unavailable")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": cleaned,
    }
    try:
        async with httpx.AsyncClient(timeout=float(settings.ai_timeout_s or 60)) as client:
            response = await client.post(f"{base_url}/embeddings", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise EmbeddingServiceUnavailable("embedding_service_unavailable") from exc

    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise EmbeddingServiceUnavailable("embedding_service_unavailable")

    vectors: List[List[float]] = []
    for item in sorted(rows, key=lambda row: int(row.get("index", len(vectors))) if isinstance(row, dict) else len(vectors)):
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(embedding, list):
            raise EmbeddingServiceUnavailable("embedding_service_unavailable")
        vectors.append(_normalize_vector(embedding))
    return vectors


def _load_unembedded_chunks(document_id: str | None) -> List[EvidenceChunk]:
    session = SessionLocal()
    try:
        query = (
            session.query(EvidenceChunk)
            .outerjoin(EvidenceEmbedding, EvidenceEmbedding.evidence_id == EvidenceChunk.id)
            .filter(EvidenceEmbedding.id.is_(None))
            .order_by(EvidenceChunk.document_id.asc(), EvidenceChunk.id.asc())
        )
        if document_id:
            query = query.filter(EvidenceChunk.document_id == document_id)
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows
    except SQLAlchemyError as exc:
        raise AiDatabaseUnavailable("ai_database_unavailable") from exc
    finally:
        session.close()


def _search_by_vector(vector: List[float], *, top_k: int, document_ids: List[str]) -> List[EvidenceSearchResult]:
    session = SessionLocal()
    try:
        distance_expr = EvidenceEmbedding.embedding.cosine_distance(vector)
        statement = (
            select(EvidenceChunk, (1 - distance_expr).label("score"))
            .join(EvidenceEmbedding, EvidenceEmbedding.evidence_id == EvidenceChunk.id)
            .order_by(distance_expr.asc())
            .limit(max(1, min(int(top_k or 8), 50)))
        )
        if document_ids:
            statement = statement.where(EvidenceChunk.document_id.in_(document_ids))
        rows = session.execute(statement).all()
        return [_search_result(chunk, score) for chunk, score in rows]
    except (AttributeError, SQLAlchemyError) as exc:
        raise AiDatabaseUnavailable("ai_database_unavailable") from exc
    finally:
        session.close()


def _search_result(chunk: EvidenceChunk, score: float) -> EvidenceSearchResult:
    return EvidenceSearchResult(
        evidence_id=int(chunk.id),
        document_id=str(chunk.document_id),
        text=str(chunk.text or ""),
        summary=str(chunk.summary or ""),
        semantic_type=str(chunk.semantic_type or ""),
        tags=list(chunk.tags or []),
        page_start=int(chunk.page_start or 1),
        page_end=int(chunk.page_end or chunk.page_start or 1),
        citation=str(chunk.citation or ""),
        score=float(score or 0),
    )


def _embedding_text_for(chunk: EvidenceChunk) -> str:
    parts = [
        str(chunk.summary or "").strip(),
        str(chunk.text or "").strip(),
        " ".join(str(tag) for tag in (chunk.tags or [])),
        str(chunk.semantic_type or "").strip(),
    ]
    return "\n".join(part for part in parts if part)


def _normalize_optional_document_id(document_id: str | None) -> str | None:
    normalized = str(document_id or "").strip()
    return normalized or None


def _embedding_model() -> str:
    return str(settings.evidence_embedding_model or "BAAI/bge-m3").strip()


def _normalize_vector(raw: Iterable[object]) -> List[float]:
    try:
        vector = [float(value) for value in raw]
    except Exception as exc:
        raise EmbeddingServiceUnavailable("embedding_service_unavailable") from exc
    if not vector:
        raise EmbeddingServiceUnavailable("embedding_service_unavailable")
    return vector
