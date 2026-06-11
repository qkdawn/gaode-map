from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.evidence_retrieval.schemas import EvidenceSearchRequest
from modules.evidence_retrieval.service import (
    EmbeddingServiceUnavailable,
    build_missing_evidence_embeddings,
    schedule_evidence_index,
    search_evidence,
)
from store.ai_models import AiBase, Document, EvidenceChunk, EvidenceEmbedding


@pytest.fixture()
def ai_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    AiBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("modules.evidence_retrieval.service.SessionLocal", factory)
    return factory


def _seed_document(session, document_id: str):
    session.add(
        Document(
            id=document_id,
            title="报告",
            file_name="report.pdf",
            file_type="pdf",
            file_path="/tmp/report.pdf",
            upload_time=datetime(2026, 6, 12, 1, 0, 0),
            status="parsed",
        )
    )


def _seed_chunk(session, evidence_id: int, document_id: str, text: str):
    session.add(
        EvidenceChunk(
            id=evidence_id,
            document_id=document_id,
            document_role="evidence_document",
            text=text,
            summary=f"{text}摘要",
            page_start=1,
            page_end=1,
            section_path=["章节"],
            chunk_type="paragraph",
            semantic_type="background_statement",
            tags=["project_background"],
            citation="《报告》p.1",
            created_at=datetime(2026, 6, 12, 1, 0, 0),
        )
    )


def test_build_missing_evidence_embeddings_indexes_only_missing_chunks(ai_session, monkeypatch):
    session = ai_session()
    try:
        _seed_document(session, "doc-1")
        _seed_chunk(session, 1, "doc-1", "第一条")
        _seed_chunk(session, 2, "doc-1", "第二条")
        session.add(
            EvidenceEmbedding(
                evidence_id=1,
                document_id="doc-1",
                embedding=[0.1, 0.2],
                embedding_model="BAAI/bge-m3",
                created_at=datetime(2026, 6, 12, 1, 0, 0),
            )
        )
        session.commit()
    finally:
        session.close()

    async def fake_embed_texts(texts):
        assert len(texts) == 1
        assert "第二条" in texts[0]
        return [[0.3, 0.4]]

    monkeypatch.setattr("modules.evidence_retrieval.service.embed_texts", fake_embed_texts)

    count = asyncio.run(build_missing_evidence_embeddings("all"))

    session = ai_session()
    try:
        rows = session.query(EvidenceEmbedding).order_by(EvidenceEmbedding.evidence_id.asc()).all()
        assert count == 1
        assert [row.evidence_id for row in rows] == [1, 2]
    finally:
        session.close()


def test_build_missing_evidence_embeddings_filters_document_id(ai_session, monkeypatch):
    session = ai_session()
    try:
        _seed_document(session, "doc-1")
        _seed_document(session, "doc-2")
        _seed_chunk(session, 1, "doc-1", "第一条")
        _seed_chunk(session, 2, "doc-2", "第二条")
        session.commit()
    finally:
        session.close()

    async def fake_embed_texts(texts):
        assert len(texts) == 1
        assert "第二条" in texts[0]
        return [[0.3, 0.4]]

    monkeypatch.setattr("modules.evidence_retrieval.service.embed_texts", fake_embed_texts)

    count = asyncio.run(build_missing_evidence_embeddings("doc-2"))

    session = ai_session()
    try:
        rows = session.query(EvidenceEmbedding).all()
        assert count == 1
        assert rows[0].document_id == "doc-2"
    finally:
        session.close()


def test_build_missing_evidence_embeddings_does_not_write_partial_on_embedding_failure(ai_session, monkeypatch):
    session = ai_session()
    try:
        _seed_document(session, "doc-1")
        _seed_chunk(session, 1, "doc-1", "第一条")
        session.commit()
    finally:
        session.close()

    async def fail_embed_texts(_texts):
        raise EmbeddingServiceUnavailable("embedding_service_unavailable")

    monkeypatch.setattr("modules.evidence_retrieval.service.embed_texts", fail_embed_texts)

    with pytest.raises(EmbeddingServiceUnavailable):
        asyncio.run(build_missing_evidence_embeddings("all"))

    session = ai_session()
    try:
        assert session.query(EvidenceEmbedding).count() == 0
    finally:
        session.close()


def test_search_evidence_returns_service_results(monkeypatch):
    captured = {}

    async def fake_embed_texts(texts):
        assert texts == ["公共服务"]
        return [[0.1, 0.2]]

    def fake_search(vector, *, top_k, document_ids):
        captured["vector"] = vector
        captured["top_k"] = top_k
        captured["document_ids"] = document_ids
        from modules.evidence_retrieval.schemas import EvidenceSearchResult

        return [
            EvidenceSearchResult(
                evidence_id=1,
                document_id="doc-1",
                text="原文",
                summary="摘要",
                semantic_type="public_service_requirement",
                tags=["public_service"],
                page_start=1,
                page_end=2,
                citation="《报告》p.1",
                score=0.91,
            )
        ]

    monkeypatch.setattr("modules.evidence_retrieval.service.embed_texts", fake_embed_texts)
    monkeypatch.setattr("modules.evidence_retrieval.service._search_by_vector", fake_search)

    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="公共服务", top_k=8, document_ids=["doc-1"])))

    assert captured == {"vector": [0.1, 0.2], "top_k": 8, "document_ids": ["doc-1"]}
    assert response.results[0].evidence_id == 1
    assert response.results[0].score == 0.91


def test_schedule_evidence_index_creates_build_embedding_job(monkeypatch):
    created = {}
    scheduled = {}

    def fake_create_job(**kwargs):
        created.update(kwargs)

        class Job:
            id = "job-1"
            status = "pending"

        return Job()

    def fake_schedule_job(job_id, handler):
        scheduled["job_id"] = job_id
        scheduled["handler"] = handler

    monkeypatch.setattr("modules.evidence_retrieval.service.create_job", fake_create_job)
    monkeypatch.setattr("modules.evidence_retrieval.service.schedule_job", fake_schedule_job)

    response = schedule_evidence_index("doc-1")

    assert response.job_id == "job-1"
    assert created == {"job_type": "build_embedding", "target_type": "document", "target_id": "doc-1"}
    assert scheduled == {"job_id": "job-1", "handler": build_missing_evidence_embeddings}
