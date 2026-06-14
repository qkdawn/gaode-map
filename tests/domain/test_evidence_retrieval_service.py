from __future__ import annotations

import asyncio

import pytest

from modules.evidence_retrieval.schemas import EvidenceSearchRequest
from modules.evidence_retrieval.service import EmptySearchQuestion, search_evidence


def test_search_evidence_uses_pageindex_document_tools(monkeypatch):
    monkeypatch.setattr(
        "modules.evidence_retrieval.service.get_pageindex_document_structure",
        lambda _document_id: '[{"title":"公共服务补位具体化问题：","node_id":"0002","line_num":5,"summary":"项目应补齐公共服务设施。"}]',
    )
    monkeypatch.setattr(
        "modules.evidence_retrieval.service.get_pageindex_page_content",
        lambda _document_id, _pages: '[{"page":5,"content":"项目应补齐公共服务设施，支撑居民与游客复合需求。"}]',
    )

    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="公共服务", top_k=8, document_ids=["doc-1"])))

    assert response.results[0].document_id == "doc-1"
    assert response.results[0].semantic_type == "pageindex_node"
    assert response.results[0].citation == "PageIndex line 5"
    assert "公共服务设施" in response.results[0].text


def test_search_evidence_returns_empty_without_document_ids():
    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="公共服务", top_k=8, document_ids=[])))

    assert response.results == []


def test_search_evidence_rejects_empty_question():
    with pytest.raises(EmptySearchQuestion):
        asyncio.run(search_evidence(EvidenceSearchRequest(question=" ", top_k=8, document_ids=["doc-1"])))
