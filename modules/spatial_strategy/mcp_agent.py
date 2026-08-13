from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from core.config import settings


_ALLOWED_TOOLS = {"project_context", "query_data", "read_project_document"}
_AGENT_CONTEXT_LIST_SAMPLE_SIZE = 8
_AGENT_CONTEXT_MAPPING_LIMIT = 32
_AGENT_CONTEXT_TEXT_LIMIT = 1_200
_AGENT_CONTEXT_MAX_DEPTH = 6


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _coordinate_pairs(value: Any) -> Iterable[tuple[float, float]]:
    if isinstance(value, Mapping):
        yield from _coordinate_pairs(value.get("coordinates") or value.get("scope"))
        return
    if not isinstance(value, (list, tuple)):
        return
    if len(value) >= 2 and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:2]):
        yield float(value[0]), float(value[1])
        return
    for item in value:
        yield from _coordinate_pairs(item)


def _compact_scope(scope: Any) -> dict[str, Any]:
    pairs = list(_coordinate_pairs(scope))
    if not pairs:
        return {"defined": bool(scope)}
    longitudes, latitudes = zip(*pairs)
    return {
        "defined": True,
        "coordinate_pair_count": len(pairs),
        "bounds": {
            "min_lng": min(longitudes),
            "min_lat": min(latitudes),
            "max_lng": max(longitudes),
            "max_lat": max(latitudes),
        },
    }


def _compact_agent_value(value: Any, *, depth: int = 0) -> Any:
    """Retain decision evidence while excluding repeated grid and asset detail from model context."""
    if isinstance(value, str):
        if len(value) <= _AGENT_CONTEXT_TEXT_LIMIT:
            return value
        return {
            "text_preview": value[:_AGENT_CONTEXT_TEXT_LIMIT],
            "text_length": len(value),
            "truncated": True,
        }
    if not isinstance(value, (Mapping, list, tuple)):
        return value
    if depth >= _AGENT_CONTEXT_MAX_DEPTH:
        return {"omitted": True, "value_type": type(value).__name__}
    if isinstance(value, Mapping):
        items = list(value.items())
        compacted = {
            str(key): _compact_agent_value(item, depth=depth + 1)
            for key, item in items[:_AGENT_CONTEXT_MAPPING_LIMIT]
        }
        if len(items) > _AGENT_CONTEXT_MAPPING_LIMIT:
            compacted["omitted_key_count"] = len(items) - _AGENT_CONTEXT_MAPPING_LIMIT
        return compacted
    values = list(value)
    sampled = values[:_AGENT_CONTEXT_LIST_SAMPLE_SIZE]
    compacted_values = [_compact_agent_value(item, depth=depth + 1) for item in sampled]
    if len(values) <= _AGENT_CONTEXT_LIST_SAMPLE_SIZE:
        return compacted_values
    return {
        "item_count": len(values),
        "sample": compacted_values,
        "detail_omitted": True,
    }


def _compact_project_context_for_agent(context: Mapping[str, Any]) -> dict[str, Any]:
    project = context.get("project")
    compact_project = _compact_agent_value(project) if isinstance(project, Mapping) else {}
    documents = context.get("documents") or []
    compact_documents = [
        _compact_agent_value(document)
        for document in documents
        if isinstance(document, Mapping)
    ] if isinstance(documents, (list, tuple)) else []
    if isinstance(project, Mapping):
        compact_project["scope"] = _compact_scope(project.get("scope"))
    return {
        "schema_version": context.get("schema_version"),
        "agent_context_mode": "decision_summary",
        "project": compact_project,
        "documents": compact_documents,
        "datasets": _compact_agent_value(context.get("datasets") or []),
        "computed_results": _compact_agent_value(context.get("computed_results") or []),
        "warnings": _compact_agent_value(context.get("warnings") or []),
    }


async def call_spatial_mcp_tool(*, history_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in _ALLOWED_TOOLS:
        raise ValueError("spatial_mcp_tool_not_allowed")
    payload = dict(arguments or {})
    payload["history_id"] = history_id
    async with streamablehttp_client(
        str(settings.spatial_mcp_url).rstrip("/"),
        timeout=float(settings.spatial_mcp_timeout_s),
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, payload)
            structured_content = _jsonable(getattr(result, "structuredContent", None))
            if tool_name == "project_context" and isinstance(structured_content, Mapping):
                structured_content = _compact_project_context_for_agent(structured_content)
            return {
                "tool_name": tool_name,
                "is_error": bool(getattr(result, "isError", False)),
                # The decision workflow consumes the canonical structured result. Keeping the
                # MCP text mirror would transmit the same data a second time on every tool turn.
                "content": [] if structured_content is not None else _jsonable(getattr(result, "content", [])),
                "structured_content": structured_content,
            }


def read_previous_chapter(
    *,
    decision_state: Mapping[str, Any],
    current_step_order: int,
    step_key: str = "",
    step_order: int | None = None,
) -> dict[str, Any]:
    """Read one completed earlier chapter without placing all chapters in the prompt."""
    steps = decision_state.get("steps") if isinstance(decision_state, Mapping) else None
    if not isinstance(steps, Mapping):
        raise ValueError("previous_chapter_state_unavailable")

    target_key = str(step_key or "").strip()
    if target_key:
        entry = steps.get(target_key)
    else:
        target_order = int(step_order or 0)
        entry = next(
            (
                value for value in steps.values()
                if isinstance(value, Mapping) and int(value.get("step_order") or 0) == target_order
            ),
            None,
        )
    if not isinstance(entry, Mapping):
        raise ValueError("previous_chapter_not_found")

    resolved_order = int(entry.get("step_order") or 0)
    if resolved_order >= int(current_step_order):
        raise ValueError("previous_chapter_must_be_completed_before_current_step")
    chapter = str(entry.get("reader_chapter") or "").strip()
    if not chapter:
        raise ValueError("previous_chapter_content_unavailable")
    return {
        "step_key": target_key or str(entry.get("step_key") or ""),
        "step_order": resolved_order,
        "title": str(entry.get("title") or ""),
        "reader_chapter": chapter,
    }
