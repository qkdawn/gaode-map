from __future__ import annotations

from typing import Any, Dict, List, Tuple

from modules.evidence_retrieval import SourceRecord

from .context_ask_compaction import as_text
from .schemas import AgentContextAskRequest, ToolResult
from .selected_sources import (
    selected_dataset_source_ids_from_items,
    source_items_from_target,
    source_records_from_items,
)
from .tool_definitions import RegisteredTool, register_scope_dataset_tools, register_source_evidence_tools


SOURCE_QA_TOOL_NAMES = {
    "list_selected_sources",
    "search_selected_source_evidence",
    "read_selected_source_evidence_node",
    "list_scope_datasets",
    "query_scope_dataset",
    "aggregate_scope_dataset",
    "read_scope_record",
}

SELECTED_SOURCE_EVIDENCE_TOOL_NAMES = {
    "list_selected_sources",
    "search_selected_source_evidence",
    "read_selected_source_evidence_node",
}


def selected_dataset_source_ids(payload: AgentContextAskRequest) -> List[str]:
    return selected_dataset_source_ids_from_items(source_items_from_target(payload.target))


def selected_source_records(payload: AgentContextAskRequest) -> List[SourceRecord]:
    return source_records_from_items(source_items_from_target(payload.target))


def selected_source_ids(payload: AgentContextAskRequest) -> List[str]:
    result: List[str] = []
    for source in selected_source_records(payload):
        if source.source_id and source.source_id not in result:
            result.append(source.source_id)
    return result


def source_qa_registry(payload: AgentContextAskRequest | None = None) -> Dict[str, RegisteredTool]:
    registry: Dict[str, RegisteredTool] = {}
    if payload is not None:
        register_source_evidence_tools(registry)
    register_scope_dataset_tools(registry)
    return {name: tool for name, tool in registry.items() if name in SOURCE_QA_TOOL_NAMES}


def validate_source_qa_arguments(
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    history_id: str,
    allowed_source_ids: List[str],
) -> Tuple[Dict[str, Any], str]:
    clean = dict(arguments or {})
    if tool_name in SELECTED_SOURCE_EVIDENCE_TOOL_NAMES:
        return clean, ""
    if not history_id:
        return {}, "history_id_required"
    clean["history_id"] = history_id
    if tool_name == "list_scope_datasets":
        return {"history_id": history_id}, ""
    source_id = as_text(clean.get("source_id"))
    if not source_id:
        return clean, "source_id_required"
    if source_id not in allowed_source_ids:
        return clean, f"source_id_not_selected:{source_id}"
    return clean, ""


def failed_source_qa_tool_result(tool_name: str, error: str) -> ToolResult:
    return ToolResult(tool_name=tool_name or "unknown_tool", status="failed", error=error, warnings=[error])
