from __future__ import annotations

from typing import Any, Dict, List

from modules.evidence_retrieval import (
    evidence_node_from_knowledge_chunk,
)
from modules.retrieval import KnowledgeChunk, RetrievalService

from ..schemas import AnalysisSnapshot, ToolResult


def _service(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> RetrievalService:
    return RetrievalService(snapshot=snapshot, artifacts=artifacts or {})


def _node_payload(node: Any) -> Dict[str, Any]:
    return node.model_dump(mode="python") if hasattr(node, "model_dump") else dict(node or {})


def _chunk_payload(chunk: KnowledgeChunk) -> Dict[str, Any]:
    node = evidence_node_from_knowledge_chunk(chunk)
    evidence_node = _node_payload(node)
    return {
        "node_id": evidence_node["id"],
        "source_id": evidence_node["source_id"],
        "source_type": evidence_node["source_type"],
        "evidence_node": evidence_node,
    }


def _internal_key_from_node_id(node_id: str) -> str:
    text = str(node_id or "").strip()
    marker = ":node:"
    if marker not in text:
        return "__invalid_evidence_node_id__"
    return text.split(marker, 1)[1].strip()


def _source_id_for_domain(domain: str, *, prefix: str = "current:analysis") -> str:
    text = str(domain or "").strip()
    return f"{prefix}:{text}" if text else prefix


def _hit_payloads(hits: List[Any], *, source_type: str = "system", source_prefix: str = "current:analysis") -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for hit in hits:
        payload = hit.model_dump(mode="python")
        source_id = _source_id_for_domain(payload.get("domain"), prefix=source_prefix)
        node_id = f"{source_id}:node:{payload.get('chunk_id')}"
        evidence_node = {
            "id": node_id,
            "source_id": source_id,
            "source_type": source_type,
            "title": str(payload.get("title") or payload.get("domain") or "检索命中"),
            "content": str(payload.get("snippet") or ""),
            "summary": str(payload.get("snippet") or "")[:260],
            "metadata": {
                "domain": str(payload.get("domain") or ""),
                "search_hit": True,
            },
            "locator": f"node:{node_id}",
            "score": float(payload.get("score") or 0.0),
            "evidence_level": str(payload.get("evidence_level") or "source_evidence"),
            "warnings": ["search_hit_summary_only: read evidence_node by node_id for full content"],
            "citation": str(payload.get("title") or node_id),
        }
        payloads.append(
            {
                "node_id": node_id,
                "source_id": source_id,
                "source_type": source_type,
                "evidence_node": evidence_node,
            }
        )
    return payloads


async def search_analysis_context(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    domains = arguments.get("domains") if isinstance(arguments.get("domains"), list) else []
    hits = _service(snapshot, artifacts).search_analysis_context(
        query=str(arguments.get("query") or ""),
        domains=[str(item) for item in domains],
        top_k=int(arguments.get("top_k") or 8),
    )
    return ToolResult(
        tool_name="search_analysis_context",
        status="success",
        result={"hits": _hit_payloads(hits)},
        evidence=[{"field": "analysis_context.hit_count", "value": len(hits)}],
        warnings=[] if hits else ["未检索到匹配的分析上下文 EvidenceNode"],
    )


async def read_analysis_evidence_node(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    node_id = str(arguments.get("node_id") or "").strip()
    internal_key = _internal_key_from_node_id(node_id)
    chunk = _service(snapshot, artifacts).read_analysis_chunk(internal_key)
    if chunk is None:
        return ToolResult(
            tool_name="read_analysis_evidence_node",
            status="failed",
            error="evidence_node_not_found",
            warnings=[f"未找到分析上下文 EvidenceNode: {node_id}"],
        )
    return ToolResult(
        tool_name="read_analysis_evidence_node",
        status="success",
        result=_chunk_payload(chunk),
        evidence=[{"field": "analysis_context.node_id", "value": _chunk_payload(chunk)["node_id"]}],
        warnings=list(chunk.warnings or []),
    )


async def search_report_context(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    hits = _service(snapshot, artifacts).search_report_context(
        query=str(arguments.get("query") or ""),
        top_k=int(arguments.get("top_k") or 8),
    )
    return ToolResult(
        tool_name="search_report_context",
        status="success",
        result={"hits": _hit_payloads(hits, source_prefix="current:report")},
        evidence=[{"field": "report_context.hit_count", "value": len(hits)}],
        warnings=[] if hits else ["未检索到匹配的报告上下文 EvidenceNode"],
    )


async def read_report_evidence_node(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    node_id = str(arguments.get("node_id") or "").strip()
    internal_key = _internal_key_from_node_id(node_id)
    chunk = _service(snapshot, artifacts).read_report_chunk(internal_key)
    if chunk is None:
        return ToolResult(
            tool_name="read_report_evidence_node",
            status="failed",
            error="evidence_node_not_found",
            warnings=[f"未找到报告上下文 EvidenceNode: {node_id}"],
        )
    return ToolResult(
        tool_name="read_report_evidence_node",
        status="success",
        result=_chunk_payload(chunk),
        evidence=[{"field": "report_context.node_id", "value": _chunk_payload(chunk)["node_id"]}],
        warnings=list(chunk.warnings or []),
    )
