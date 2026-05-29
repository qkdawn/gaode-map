from __future__ import annotations

from typing import Any, Dict, List

from modules.retrieval import KnowledgeChunk, RetrievalService
from modules.retrieval.attachments import read_attachment_context, search_attachment_context

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


def _attachment_scope(artifacts: Dict[str, Any]) -> tuple[str, List[str]]:
    conversation_id = str((artifacts or {}).get("uploaded_attachment_conversation_id") or "").strip()
    attachment_ids = [
        str(item).strip()
        for item in ((artifacts or {}).get("uploaded_attachment_ids") or [])
        if str(item).strip()
    ]
    return conversation_id, attachment_ids


async def search_uploaded_attachment_context(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del snapshot, question
    conversation_id, default_attachment_ids = _attachment_scope(artifacts)
    requested_ids = arguments.get("attachment_ids") if isinstance(arguments.get("attachment_ids"), list) else []
    attachment_ids = [str(item).strip() for item in requested_ids if str(item).strip()] or default_attachment_ids
    if not conversation_id or not attachment_ids:
        return ToolResult(
            tool_name="search_uploaded_attachment_context",
            status="failed",
            error="attachment_context_missing",
            warnings=["当前对话没有可检索的上传附件。"],
        )
    hits = search_attachment_context(
        conversation_id=conversation_id,
        attachment_ids=attachment_ids,
        query=str(arguments.get("query") or ""),
        top_k=int(arguments.get("top_k") or 8),
    )
    return ToolResult(
        tool_name="search_uploaded_attachment_context",
        status="success",
        result={"hits": [hit.model_dump(mode="python") for hit in hits]},
        evidence=[{"field": "uploaded_attachment.hit_count", "value": len(hits)}],
        warnings=[] if hits else ["未检索到匹配的上传附件证据。"],
    )


async def read_uploaded_attachment_context(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del snapshot, question
    conversation_id, default_attachment_ids = _attachment_scope(artifacts)
    requested_ids = arguments.get("attachment_ids") if isinstance(arguments.get("attachment_ids"), list) else []
    attachment_ids = [str(item).strip() for item in requested_ids if str(item).strip()] or default_attachment_ids
    chunk_id = str(arguments.get("chunk_id") or "").strip()
    if not conversation_id or not attachment_ids:
        return ToolResult(
            tool_name="read_uploaded_attachment_context",
            status="failed",
            error="attachment_context_missing",
            warnings=["当前对话没有可读取的上传附件。"],
        )
    chunk = read_attachment_context(
        conversation_id=conversation_id,
        attachment_ids=attachment_ids,
        chunk_id=chunk_id,
    )
    if chunk is None:
        return ToolResult(
            tool_name="read_uploaded_attachment_context",
            status="failed",
            error="attachment_chunk_not_found",
            warnings=[f"未找到上传附件证据块: {chunk_id}"],
        )
    return ToolResult(
        tool_name="read_uploaded_attachment_context",
        status="success",
        result=chunk.model_dump(mode="python"),
        evidence=[
            {"field": "uploaded_attachment.chunk_id", "value": chunk.chunk_id},
            {"field": "uploaded_attachment.filename", "value": chunk.filename},
        ],
        warnings=list(chunk.warnings or []),
    )
