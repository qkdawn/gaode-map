from __future__ import annotations

from typing import Any, Dict

from modules.scope_datasets import ScopeDatasetQueryError, ScopeDatasetService
from modules.scope_datasets.spatial import SpatialQueryError

from ..schemas import AnalysisSnapshot, ToolResult


def _history_id(arguments: Dict[str, Any], snapshot: AnalysisSnapshot) -> str:
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    return str(
        arguments.get("history_id")
        or arguments.get("historyId")
        or context.get("history_id")
        or context.get("historyId")
        or ""
    ).strip()


def _service() -> ScopeDatasetService:
    return ScopeDatasetService()


async def list_scope_datasets(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del artifacts, question
    history_id = _history_id(arguments, snapshot)
    payload = _service().list_scope_datasets(history_id)
    return ToolResult(
        tool_name="list_scope_datasets",
        status="success" if history_id else "failed",
        result=payload,
        evidence=[{"field": "scope_dataset.count", "value": len(payload.get("datasets") or [])}],
        warnings=list(payload.get("warnings") or []),
        error=None if history_id else "history_id_required",
    )


async def query_scope_dataset(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del artifacts, question
    history_id = _history_id(arguments, snapshot)
    if not history_id:
        return ToolResult(tool_name="query_scope_dataset", status="failed", error="history_id_required", warnings=["history_id_required"])
    try:
        payload = _service().query_scope_dataset(
            history_id=history_id,
            source_id=str(arguments.get("source_id") or ""),
            filters=arguments.get("filters") if isinstance(arguments.get("filters"), dict) else {},
            sort=arguments.get("sort") if isinstance(arguments.get("sort"), dict) else {},
            limit=int(arguments.get("limit") or 20),
            offset=int(arguments.get("offset") or 0),
            year=arguments.get("year"),
            spatial=arguments.get("spatial") if isinstance(arguments.get("spatial"), dict) else None,
        )
    except (ScopeDatasetQueryError, SpatialQueryError) as exc:
        return ToolResult(
            tool_name="query_scope_dataset",
            status="failed",
            error=exc.code,
            warnings=[str(exc)],
        )
    return ToolResult(
        tool_name="query_scope_dataset",
        status="success",
        result=payload,
        evidence=[{"field": "scope_dataset.result_count", "value": len(payload.get("records") or [])}],
        warnings=list(payload.get("warnings") or []),
        artifacts={"scope_dataset_evidence_nodes": list(payload.get("evidence_nodes") or [])},
    )


async def aggregate_scope_dataset(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del artifacts, question
    history_id = _history_id(arguments, snapshot)
    if not history_id:
        return ToolResult(tool_name="aggregate_scope_dataset", status="failed", error="history_id_required", warnings=["history_id_required"])
    try:
        payload = _service().aggregate_scope_dataset(
            history_id=history_id,
            source_id=str(arguments.get("source_id") or ""),
            group_by=str(arguments.get("group_by") or ""),
            metrics=arguments.get("metrics") if isinstance(arguments.get("metrics"), list) else [],
            filters=arguments.get("filters") if isinstance(arguments.get("filters"), dict) else {},
            top_k=int(arguments.get("top_k") or 10),
            year=arguments.get("year"),
            spatial=arguments.get("spatial") if isinstance(arguments.get("spatial"), dict) else None,
        )
    except (ScopeDatasetQueryError, SpatialQueryError) as exc:
        return ToolResult(
            tool_name="aggregate_scope_dataset",
            status="failed",
            error=exc.code,
            warnings=[str(exc)],
        )
    return ToolResult(
        tool_name="aggregate_scope_dataset",
        status="success",
        result=payload,
        evidence=[{"field": "scope_dataset.group_count", "value": len(payload.get("rows") or [])}],
        warnings=list(payload.get("warnings") or []),
        artifacts={"scope_dataset_evidence_nodes": [payload.get("evidence_node")]},
    )


async def read_scope_record(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del artifacts, question
    history_id = _history_id(arguments, snapshot)
    if not history_id:
        return ToolResult(tool_name="read_scope_record", status="failed", error="history_id_required", warnings=["history_id_required"])
    payload = _service().read_scope_record(
        history_id=history_id,
        source_id=str(arguments.get("source_id") or ""),
        record_id=str(arguments.get("record_id") or ""),
        year=arguments.get("year"),
    )
    found = bool(payload.get("evidence_node"))
    return ToolResult(
        tool_name="read_scope_record",
        status="success" if found else "failed",
        result=payload,
        evidence=[{"field": "scope_dataset.record_id", "value": payload.get("record_id")}],
        warnings=list(payload.get("warnings") or []),
        artifacts={"scope_dataset_evidence_nodes": [payload.get("evidence_node")]} if found else {},
        error=None if found else "record_not_found",
    )
