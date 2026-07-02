from __future__ import annotations

import asyncio

import pytest

from modules.evidence_retrieval import (
    evidence_node_from_attachment_chunk,
    evidence_node_from_document_index_node,
    evidence_node_from_knowledge_chunk,
    evidence_node_payload_from_node,
)
from modules.evidence_retrieval.schemas import EvidenceNode, EvidenceSearchRequest, SourceRecord
from modules.evidence_retrieval.service import EmptySearchQuestion, search_evidence
from modules.retrieval.schemas import AttachmentChunk, KnowledgeChunk


def test_search_evidence_uses_pageindex_document_tools(monkeypatch):
    monkeypatch.setattr(
        "modules.evidence_retrieval.service.get_pageindex_document_structure",
        lambda _document_id: '[{"title":"公共服务补位具体化问题：","node_id":"0002","line_num":5,"summary":"项目应补齐公共服务设施。"}]',
    )
    monkeypatch.setattr(
        "modules.evidence_retrieval.service.get_pageindex_page_content",
        lambda _document_id, _pages: '[{"page":5,"content":"项目应补齐公共服务设施，支撑居民与游客复合需求。"}]',
    )

    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="公共服务", top_k=8, source_ids=["document:doc-1"])))

    assert response.nodes[0].metadata["document_id"] == "doc-1"
    assert response.nodes[0].evidence_level == "pageindex_node"
    assert response.nodes[0].citation == "PageIndex line 5"
    assert "公共服务设施" in response.nodes[0].content


def test_search_evidence_returns_empty_without_source_ids():
    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="公共服务", top_k=8, source_ids=[])))

    assert response.nodes == []


def test_search_evidence_accepts_source_ids_for_document_pageindex(monkeypatch):
    monkeypatch.setattr(
        "modules.evidence_retrieval.service.get_pageindex_document_structure",
        lambda _document_id: '[{"title":"城市更新政策","node_id":"policy-1","line_num":8,"summary":"鼓励补齐公共服务设施。"}]',
    )
    monkeypatch.setattr(
        "modules.evidence_retrieval.service.get_pageindex_page_content",
        lambda _document_id, _pages: '[{"page":8,"content":"城市更新政策鼓励补齐公共服务设施和慢行空间。"}]',
    )

    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="公共服务", top_k=8, source_ids=["document:doc-1"])))

    assert response.nodes[0].source_id == "document:doc-1"
    assert response.nodes[0].evidence_level == "pageindex_node"


def test_search_evidence_converts_source_payload_evidence_to_nodes():
    response = asyncio.run(
        search_evidence(
            EvidenceSearchRequest(
                question="夜间活力",
                top_k=8,
                source_ids=["database:area-1:test"],
                sources=[
                    {
                        "id": "database:area-1:test",
                        "title": "数据库资料包",
                        "status": "ready",
                        "meta": {
                            "sourceKind": "database",
                            "aiPayload": {
                                "evidence_nodes": [
                                    {
                                        "id": "database:area-1:test:node:1",
                                        "source_id": "database:area-1:test",
                                        "source_type": "database",
                                        "title": "夜光活力摘要",
                                        "content": "该区域夜间活力较强，夜光均值高于周边。",
                                        "citation": "数据库记录 history-1",
                                        "metadata": {"record_id": "history-1"},
                                    }
                                ]
                            },
                        },
                    }
                ],
            )
        )
    )

    assert response.nodes[0].source_type == "database"
    assert response.nodes[0].citation == "数据库记录 history-1"


def test_search_evidence_reads_only_canonical_evidence_nodes():
    source_payload = {
        "id": "web:area-1:test",
        "title": "网页来源",
        "status": "ready",
        "meta": {
            "sourceKind": "web",
            "aiPayload": {
                "evidence_nodes": [
                    {
                        "id": "web:area-1:test:node:1",
                        "source_id": "web:area-1:test",
                        "source_type": "web",
                        "title": "政策网页",
                        "content": "城市更新政策鼓励公共服务补位。",
                        "evidence_level": "web_chunk",
                        "citation": "https://example.com/policy",
                    }
                ],
            },
        },
    }
    source = SourceRecord.model_validate(source_payload)
    response = asyncio.run(
        search_evidence(
            EvidenceSearchRequest(
                question="公共服务",
                top_k=8,
                source_ids=["web:area-1:test"],
                sources=[source_payload],
            )
        )
    )

    assert source.evidence_count == 1
    assert response.nodes[0].id == "web:area-1:test:node:1"
    assert response.nodes[0].evidence_level == "web_chunk"
    assert "旧 evidence view" not in response.nodes[0].content


def test_source_record_counts_canonical_web_source_nodes():
    source = SourceRecord.model_validate(
        {
            "id": "web:area-1:abc",
            "title": "地区资料",
            "status": "ready",
            "meta": {
                "sourceKind": "web",
                "aiPayload": {
                    "evidence_nodes": [{
                        "id": "web:area-1:abc:node:1",
                        "source_id": "web:area-1:abc",
                        "source_type": "web",
                        "title": "网页",
                        "content": "政策资料",
                    }]
                },
            },
        }
    )

    assert source.source_kind == "web"
    assert source.evidence_count == 1


def test_search_evidence_maps_web_source_to_web_nodes():
    response = asyncio.run(
        search_evidence(
            EvidenceSearchRequest(
                question="政策资料",
                top_k=8,
                source_ids=["web:area-1:abc"],
                sources=[
                    {
                        "id": "web:area-1:abc",
                        "title": "地区资料",
                        "status": "ready",
                        "meta": {
                            "sourceKind": "web",
                            "aiPayload": {
                                "evidence_nodes": [
                                    {
                                        "id": "web:area-1:abc:node:1",
                                        "source_id": "web:area-1:abc",
                                        "source_type": "web",
                                        "title": "政策网页",
                                        "content": "该区域有城市更新政策资料。",
                                        "citation": "https://example.com/policy",
                                    }
                                ]
                            },
                        },
                    }
                ],
            )
        )
    )

    assert response.nodes[0].source_id == "web:area-1:abc"
    assert response.nodes[0].source_type == "web"


def test_source_adapters_convert_chunks_to_evidence_nodes():
    knowledge_node = evidence_node_from_knowledge_chunk(
        KnowledgeChunk(
            chunk_id="poi-1",
            kind="analysis",
            domain="poi",
            title="POI 摘要",
            content="餐饮和生活服务较密集。",
            evidence_level="derived_metric",
        ),
        question="餐饮",
    )
    attachment_node = evidence_node_from_attachment_chunk(
        AttachmentChunk(
            chunk_id="ocr-1",
            attachment_id="att-1",
            filename="现场照片.png",
            title="OCR 片段",
            content="入口标识和商业街导视。",
            metadata={"mime_type": "image/png"},
        ),
        question="导视",
    )

    assert knowledge_node.source_id == "current:analysis:poi"
    assert knowledge_node.source_type == "system"
    assert knowledge_node.id == "current:analysis:poi:node:poi-1"
    assert "chunk_id" not in knowledge_node.metadata
    assert attachment_node.source_id == "image:att-1"
    assert attachment_node.source_type == "image"
    assert attachment_node.id == "image:att-1:node:ocr-1"
    assert "chunk_id" not in attachment_node.metadata


def test_evidence_node_payload_preserves_source_identity():
    payload = evidence_node_payload_from_node(
        EvidenceNode(
            id="web:area-1:node-1",
            source_id="web:area-1",
            source_type="web",
            title="政策网页",
            content="城市更新政策摘要",
            summary="政策摘要",
            metadata={"url": "https://example.com"},
            locator="https://example.com",
            evidence_level="web_chunk",
            citation="https://example.com",
        )
    )

    assert payload["id"] == "web:area-1:node-1"
    assert payload["source_id"] == "web:area-1"
    assert payload["source_type"] == "web"
    assert payload["metadata"]["url"] == "https://example.com"


def test_ai_payload_evidence_nodes_round_trip_canonical_node_id():
    node_payload = evidence_node_payload_from_node(
        EvidenceNode(
            id="database:history-1:analysis_history:history-1:record",
            source_id="database:history-1:analysis_history:history-1",
            source_type="database",
            title="历史分析记录",
            content="夜间活力较强，适合作为夜生活资料来源。",
            summary="夜间活力较强",
            metadata={"record_id": "history-1"},
            locator="analysis_history:history-1",
            evidence_level="database_record",
            citation="数据库记录 analysis_history/history-1",
        )
    )

    response = asyncio.run(
        search_evidence(
            EvidenceSearchRequest(
                question="夜间活力",
                top_k=8,
                source_ids=["database:history-1:analysis_history:history-1"],
                sources=[
                    {
                        "id": "database:history-1:analysis_history:history-1",
                        "title": "数据库来源",
                        "status": "ready",
                        "meta": {
                            "sourceKind": "database",
                            "aiPayload": {"evidence_nodes": [node_payload]},
                        },
                    }
                ],
            )
        )
    )

    assert response.nodes[0].id == "database:history-1:analysis_history:history-1:record"
    assert response.nodes[0].source_type == "database"
    assert response.nodes[0].locator == "analysis_history:history-1"


def test_document_index_node_converts_to_evidence_node_payload():
    node = evidence_node_from_document_index_node(
        "document:doc-1",
        "政策文件",
        {
            "node_id": "n1",
            "parent_node_id": "root",
            "title": "政策要求",
            "summary": "政策要求完善公共服务设施。",
            "page_start": 3,
            "page_end": 3,
            "level": 1,
        },
    )

    assert node is not None
    payload = evidence_node_payload_from_node(node)
    assert payload["evidence_level"] == "pageindex_node"
    assert payload["id"] == "document:doc-1:pageindex:n1"
    assert payload["source_type"] == "document"
    assert payload["citation"] == "PageIndex p.3"


def test_search_evidence_rejects_empty_question():
    with pytest.raises(EmptySearchQuestion):
        asyncio.run(search_evidence(EvidenceSearchRequest(question=" ", top_k=8, source_ids=["document:doc-1"])))
