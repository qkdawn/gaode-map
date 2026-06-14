from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.evidence_retrieval import EmptySearchQuestion
from modules.evidence_retrieval.schemas import EvidenceSearchResponse, EvidenceSearchResult
from router.domains import evidence_retrieval
from router.domains.evidence_retrieval import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_search_api_returns_pageindex_results(monkeypatch):
    async def fake_search(payload):
        assert payload.question == "公共服务"
        assert payload.top_k == 8
        assert payload.document_ids == ["doc-1"]
        return EvidenceSearchResponse(
            results=[
                EvidenceSearchResult(
                    evidence_id=1,
                    document_id="doc-1",
                    text="原文",
                    summary="摘要",
                    semantic_type="pageindex_node",
                    tags=["pageindex", "document"],
                    page_start=5,
                    page_end=5,
                    citation="PageIndex line 5",
                    score=1.0,
                )
            ]
        )

    monkeypatch.setattr(evidence_retrieval, "search_evidence", fake_search)

    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "公共服务", "top_k": 8, "document_ids": ["doc-1"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["semantic_type"] == "pageindex_node"
    assert payload["results"][0]["citation"] == "PageIndex line 5"


def test_search_api_maps_errors(monkeypatch):
    async def empty(_payload):
        raise EmptySearchQuestion("empty_search_question")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", empty)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": " ", "top_k": 8, "document_ids": []})
    assert response.status_code == 400
    assert response.json()["detail"] == "empty_search_question"

    async def unavailable(_payload):
        raise RuntimeError("pageindex down")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", unavailable)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "问题", "top_k": 8, "document_ids": ["doc-1"]})
    assert response.status_code == 503
    assert response.json()["detail"] == "pageindex_search_unavailable"
