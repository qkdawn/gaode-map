from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.evidence_retrieval import AiDatabaseUnavailable, EmbeddingServiceUnavailable, EmptySearchQuestion
from modules.evidence_retrieval.schemas import EvidenceSearchResponse, EvidenceSearchResult
from modules.jobs import JobCreateResponse
from router.domains import evidence_retrieval
from router.domains.evidence_retrieval import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_evidence_index_api_returns_job(monkeypatch):
    def fake_schedule(document_id=None):
        assert document_id is None
        return JobCreateResponse(job_id="job-1", status="pending")

    monkeypatch.setattr(evidence_retrieval, "schedule_evidence_index", fake_schedule)

    with TestClient(_build_test_app()) as client:
        response = client.post("/evidence/index", json={})

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-1", "status": "pending"}


def test_evidence_index_api_accepts_document_id(monkeypatch):
    def fake_schedule(document_id=None):
        assert document_id == "doc-1"
        return JobCreateResponse(job_id="job-2", status="pending")

    monkeypatch.setattr(evidence_retrieval, "schedule_evidence_index", fake_schedule)

    with TestClient(_build_test_app()) as client:
        response = client.post("/evidence/index", json={"document_id": "doc-1"})

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-2"


def test_search_api_returns_results(monkeypatch):
    async def fake_search(payload):
        assert payload.question == "公共服务"
        assert payload.top_k == 8
        assert payload.document_ids == []
        return EvidenceSearchResponse(
            results=[
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
                    score=0.9,
                )
            ]
        )

    monkeypatch.setattr(evidence_retrieval, "search_evidence", fake_search)

    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "公共服务", "top_k": 8, "document_ids": []})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["evidence_id"] == 1
    assert payload["results"][0]["score"] == 0.9


def test_search_api_maps_errors(monkeypatch):
    async def empty(_payload):
        raise EmptySearchQuestion("empty_search_question")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", empty)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": " ", "top_k": 8, "document_ids": []})
    assert response.status_code == 400
    assert response.json()["detail"] == "empty_search_question"

    async def embedding_down(_payload):
        raise EmbeddingServiceUnavailable("embedding_service_unavailable")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", embedding_down)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "问题", "top_k": 8, "document_ids": []})
    assert response.status_code == 503
    assert response.json()["detail"] == "embedding_service_unavailable"

    async def db_down(_payload):
        raise AiDatabaseUnavailable("ai_database_unavailable")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", db_down)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "问题", "top_k": 8, "document_ids": []})
    assert response.status_code == 503
    assert response.json()["detail"] == "ai_database_unavailable"
