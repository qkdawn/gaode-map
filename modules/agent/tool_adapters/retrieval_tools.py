from __future__ import annotations

from typing import Any, Dict, List

from modules.retrieval import KnowledgeChunk, RetrievalService

from ..schemas import AnalysisSnapshot, ToolResult


def _service(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> RetrievalService:
    return RetrievalService(snapshot=snapshot, artifacts=artifacts or {})


def _chunk_payload(chunk: KnowledgeChunk) -> Dict[str, Any]:
    return {
        "title": chunk.title,
        "content": chunk.content,
        "metrics": dict(chunk.metrics or {}),
        "source_artifacts": list(chunk.source_artifacts or []),
        "warnings": list(chunk.warnings or []),
    }


def _hit_payloads(hits: List[Any]) -> List[Dict[str, Any]]:
    return [hit.model_dump(mode="python") for hit in hits]


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
        warnings=[] if hits else ["未检索到匹配的分析上下文 chunk"],
    )


async def read_analysis_chunk(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    chunk_id = str(arguments.get("chunk_id") or "").strip()
    chunk = _service(snapshot, artifacts).read_analysis_chunk(chunk_id)
    if chunk is None:
        return ToolResult(
            tool_name="read_analysis_chunk",
            status="failed",
            error="chunk_not_found",
            warnings=[f"未找到分析上下文 chunk: {chunk_id}"],
        )
    return ToolResult(
        tool_name="read_analysis_chunk",
        status="success",
        result=_chunk_payload(chunk),
        evidence=[{"field": "analysis_context.chunk_id", "value": chunk.chunk_id}],
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
        result={"hits": _hit_payloads(hits)},
        evidence=[{"field": "report_context.hit_count", "value": len(hits)}],
        warnings=[] if hits else ["未检索到匹配的报告上下文 chunk"],
    )


async def read_report_chunk(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    chunk_id = str(arguments.get("chunk_id") or "").strip()
    chunk = _service(snapshot, artifacts).read_report_chunk(chunk_id)
    if chunk is None:
        return ToolResult(
            tool_name="read_report_chunk",
            status="failed",
            error="chunk_not_found",
            warnings=[f"未找到报告上下文 chunk: {chunk_id}"],
        )
    return ToolResult(
        tool_name="read_report_chunk",
        status="success",
        result=_chunk_payload(chunk),
        evidence=[{"field": "report_context.chunk_id", "value": chunk.chunk_id}],
        warnings=list(chunk.warnings or []),
    )
