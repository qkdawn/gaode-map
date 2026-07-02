from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.evidence_retrieval import EmptySearchQuestion
from modules.evidence_retrieval.schemas import EvidenceNode, EvidenceSearchResponse
from router.domains import evidence_retrieval
from router.domains.evidence_retrieval import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_search_api_returns_evidence_nodes(monkeypatch):
    async def fake_search(payload):
        assert payload.question == "公共服务"
        assert payload.top_k == 8
        assert payload.source_ids == ["document:doc-1"]
        return EvidenceSearchResponse(
            nodes=[
                EvidenceNode(
                    id="document:doc-1:pageindex:5",
                    source_id="document:doc-1",
                    source_type="document",
                    title="PageIndex 节点",
                    content="原文",
                    summary="摘要",
                    metadata={"document_id": "doc-1", "page_start": 5, "page_end": 5},
                    locator="pageindex:5",
                    evidence_level="pageindex_node",
                    citation="PageIndex line 5",
                    score=1.0,
                )
            ]
        )

    monkeypatch.setattr(evidence_retrieval, "search_evidence", fake_search)

    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "公共服务", "top_k": 8, "source_ids": ["document:doc-1"]})

    assert response.status_code == 200
    payload = response.json()
    assert "results" not in payload
    assert payload["nodes"][0]["evidence_level"] == "pageindex_node"
    assert payload["nodes"][0]["citation"] == "PageIndex line 5"


def test_search_api_accepts_source_payload(monkeypatch):
    async def fake_search(payload):
        assert payload.question == "夜间活力"
        assert payload.top_k == 5
        assert payload.source_ids == ["database:area-1:test"]
        assert payload.sources[0].source_id == "database:area-1:test"
        assert payload.sources[0].source_kind == "database"
        node = EvidenceNode(
            id="database:area-1:test:evidence:1",
            source_id="database:area-1:test",
            source_type="database",
            title="夜光活力摘要",
            content="该区域夜间活力较强。",
            summary="夜间活力较强",
            citation="数据库记录 history-1",
            score=2.0,
        )
        return EvidenceSearchResponse(nodes=[node])

    monkeypatch.setattr(evidence_retrieval, "search_evidence", fake_search)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/search",
            json={
                "question": "夜间活力",
                "top_k": 5,
                "source_ids": ["database:area-1:test"],
                "sources": [
                    {
                        "id": "database:area-1:test",
                        "title": "数据库资料包",
                        "status": "ready",
                        "meta": {"sourceKind": "database"},
                    }
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"][0]["source_id"] == "database:area-1:test"
    assert "results" not in payload
    assert payload["nodes"][0]["citation"] == "数据库记录 history-1"


def test_search_api_maps_errors(monkeypatch):
    async def empty(_payload):
        raise EmptySearchQuestion("empty_search_question")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", empty)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": " ", "top_k": 8, "source_ids": []})
    assert response.status_code == 400
    assert response.json()["detail"] == "empty_search_question"

    async def unavailable(_payload):
        raise RuntimeError("pageindex down")

    monkeypatch.setattr(evidence_retrieval, "search_evidence", unavailable)
    with TestClient(_build_test_app()) as client:
        response = client.post("/search", json={"question": "问题", "top_k": 8, "source_ids": ["document:doc-1"]})
    assert response.status_code == 503
    assert response.json()["detail"] == "pageindex_search_unavailable"
