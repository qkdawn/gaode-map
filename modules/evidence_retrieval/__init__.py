from .adapters import (
    canonical_source_kind,
    attachment_source_id,
    attachment_source_kind,
    database_source_id,
    evidence_node_from_attachment_chunk,
    evidence_node_from_database_record,
    evidence_node_from_document_block,
    evidence_node_from_knowledge_chunk,
    evidence_node_from_node_payload,
    evidence_node_payload_from_node,
    evidence_node_payloads_from_nodes,
    evidence_nodes_from_source,
    evidence_nodes_from_package,
)
from .schemas import EvidenceNode, EvidenceSearchRequest, EvidenceSearchResponse, SourceRecord


def __getattr__(name: str):
    if name in {"EmptySearchQuestion", "search_evidence"}:
        from .service import EmptySearchQuestion, search_evidence

        return {"EmptySearchQuestion": EmptySearchQuestion, "search_evidence": search_evidence}[name]
    raise AttributeError(name)

__all__ = [
    "EmptySearchQuestion",
    "EvidenceSearchRequest",
    "EvidenceSearchResponse",
    "EvidenceNode",
    "SourceRecord",
    "canonical_source_kind",
    "attachment_source_id",
    "attachment_source_kind",
    "database_source_id",
    "evidence_node_from_attachment_chunk",
    "evidence_node_from_database_record",
    "evidence_node_from_document_block",
    "evidence_node_from_knowledge_chunk",
    "evidence_node_from_node_payload",
    "evidence_node_payload_from_node",
    "evidence_node_payloads_from_nodes",
    "evidence_nodes_from_source",
    "evidence_nodes_from_package",
    "search_evidence",
]
