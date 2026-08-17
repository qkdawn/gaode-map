from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from modules.evidence_retrieval import (
    evidence_node_from_attachment_chunk,
    evidence_node_from_document_block,
    evidence_node_from_knowledge_chunk,
    evidence_node_from_node_payload,
    evidence_node_payload_from_node,
)
from modules.evidence_retrieval.schemas import EvidenceNode, EvidenceSearchRequest, SourceRecord
from modules.evidence_retrieval.service import EmptySearchQuestion, search_evidence
from modules.retrieval.schemas import AttachmentChunk, KnowledgeChunk


def _web_node() -> dict:
    return EvidenceNode(
        id="web:area-1:node:1",
        kind="web_excerpt",
        source_ids=["web:area-1"],
        title="Policy page",
        content="Urban renewal public service policy.",
        summary="Public service policy.",
        data={"url": "https://example.com/policy"},
        method="web_parse",
        locator="https://example.com/policy",
        citation="https://example.com/policy",
    ).model_dump(mode="json")


def test_evidence_node_contract_contains_only_unified_fields():
    assert set(EvidenceNode.model_fields) == {
        "id", "kind", "run_id", "source_ids", "metric_ids", "title", "summary", "content", "data",
        "time_scope", "spatial_scope", "method", "quality_flags", "locator", "citation",
    }


def test_evidence_node_requires_content_or_data():
    with pytest.raises(ValueError, match="requires content or data"):
        EvidenceNode(id="evidence:empty", kind="dataset_record", source_ids=["current:test"])


def test_search_evidence_returns_hits_with_score_outside_node():
    source = SourceRecord.model_validate({
        "id": "web:area-1",
        "source_kind": "web",
        "status": "ready",
        "meta": {"aiPayload": {"evidence_nodes": [_web_node()]}},
    })
    response = asyncio.run(search_evidence(EvidenceSearchRequest(
        question="public service",
        source_ids=["web:area-1"],
        sources=[source],
    )))
    assert response.hits[0].score > 0
    assert response.hits[0].node.kind == "web_excerpt"
    assert "score" not in response.hits[0].node.model_dump(mode="json")


def test_search_evidence_uses_document_blocks(monkeypatch):
    monkeypatch.setattr(
        "modules.evidence_index.adapters.document_block.DocumentBlockAdapter._rows",
        lambda _self: [SimpleNamespace(
            id=1,
            page_index=4,
            block_index=0,
            block_type="paragraph",
            section_title="Public service",
            text="Add public service facilities.",
        )],
    )
    response = asyncio.run(search_evidence(EvidenceSearchRequest(
        question="public service", source_ids=["document:doc-1"]
    )))
    node = response.hits[0].node
    assert node.kind == "document_excerpt"
    assert node.source_ids == ["document:doc-1"]
    assert node.data["document_id"] == "doc-1"


def test_parser_rejects_legacy_node_and_accepts_unified_node():
    source = SourceRecord.model_validate({"id": "web:area-1", "source_kind": "web", "status": "ready"})
    legacy = evidence_node_from_node_payload("policy", source, {
        "id": "legacy", "source_id": "web:area-1", "source_type": "web", "content": "policy"
    })
    current = evidence_node_from_node_payload("policy", source, _web_node())
    assert legacy is None
    assert current is not None
    assert current.id == "web:area-1:node:1"


def test_unified_node_round_trips_without_aliases():
    payload = evidence_node_payload_from_node(EvidenceNode.model_validate(_web_node()))
    assert payload["source_ids"] == ["web:area-1"]
    assert payload["kind"] == "web_excerpt"
    for forbidden in ("source_id", "source_type", "metadata", "score", "evidence_level", "warnings"):
        assert forbidden not in payload


def test_chunk_adapters_emit_unified_nodes():
    knowledge = evidence_node_from_knowledge_chunk(KnowledgeChunk(
        chunk_id="poi-1", kind="analysis", domain="poi", title="POI", content="Dense services."
    ))
    image = evidence_node_from_attachment_chunk(AttachmentChunk(
        chunk_id="ocr-1", attachment_id="att-1", filename="site.png", title="OCR", content="Main plaza."
    ))
    assert knowledge.kind == "analysis_summary"
    assert knowledge.source_ids == ["current:analysis:poi"]
    assert image.kind == "image_observation"
    assert image.source_ids == ["image:att-1"]


def test_document_block_adapter_emits_unified_node():
    node = evidence_node_from_document_block("document:doc-1", "Policy", {
        "block_id": "b1", "section": "Requirement", "summary": "Add public services.", "content": "Add public services.", "page_start": 3, "page_end": 3,
    })
    assert node is not None
    assert node.kind == "document_excerpt"
    assert node.locator == {"page_start": 3, "page_end": 3}


def test_search_evidence_returns_empty_without_sources():
    response = asyncio.run(search_evidence(EvidenceSearchRequest(question="public service")))
    assert response.hits == []


def test_search_evidence_rejects_empty_question():
    with pytest.raises(EmptySearchQuestion):
        asyncio.run(search_evidence(EvidenceSearchRequest(question=" ", source_ids=["document:doc-1"])))
