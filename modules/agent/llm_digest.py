from __future__ import annotations

import json
from typing import Any, Dict, List

from .schemas import AgentContextSummary, AnalysisSnapshot, ContextBundle, ToolResult


def shape_summary(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "key_count": len(value), "keys": list(value.keys())[:20]}
    if isinstance(value, list):
        return {"type": "array", "count": len(value)}
    return {"type": type(value).__name__}


def compact_for_llm(value: Any, *, depth: int = 0, max_depth: int = 5) -> Any:
    if value in (None, "", [], {}):
        return value
    if isinstance(value, str):
        return value if len(value) <= 800 else f"{value[:800]}..."
    if isinstance(value, (int, float, bool)):
        return value
    if depth >= max_depth:
        return shape_summary(value)
    if isinstance(value, list):
        if len(value) <= 12:
            return [compact_for_llm(item, depth=depth + 1, max_depth=max_depth) for item in value]
        return {
            "type": "array",
            "count": len(value),
            "sample": [compact_for_llm(item, depth=depth + 1, max_depth=max_depth) for item in value[:8]],
        }
    if isinstance(value, dict):
        items = list(value.items())
        compacted = {
            str(key): compact_for_llm(item, depth=depth + 1, max_depth=max_depth)
            for key, item in items[:30]
        }
        if len(items) > 30:
            compacted["_truncated"] = {
                "total_keys": len(items),
                "omitted_keys": [str(key) for key, _ in items[30:50]],
            }
        return compacted
    return str(value)


def compact_context_summary_dump(summary: AgentContextSummary) -> Dict[str, Any]:
    payload = summary.model_dump()
    payload["filters_digest"] = compact_for_llm(payload.get("filters_digest") or {}, max_depth=3)
    return payload


def _frontend_analysis_digest(frontend_analysis: Dict[str, Any]) -> Dict[str, Any]:
    sections = [str(key) for key, value in frontend_analysis.items() if isinstance(value, dict) and value]
    return {
        "available_sections": sections[:20],
        "section_count": len(sections),
    }


def trim_messages(messages) -> List[Dict[str, str]]:
    from core.config import settings

    max_turns = max(1, int(settings.ai_max_context_turns or 12))
    max_content_chars = 4000
    kept = messages[-max_turns:]
    normalized: List[Dict[str, str]] = []
    for item in kept:
        role = str(item.role or "").strip() or "user"
        content = str(item.content or "").strip()
        if content:
            if len(content) > max_content_chars:
                content = f"{content[:max_content_chars]}..."
            normalized.append({"role": role, "content": content})
    return normalized


def snapshot_digest(snapshot: AnalysisSnapshot) -> Dict[str, Any]:
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    current_filters = snapshot.current_filters if isinstance(snapshot.current_filters, dict) else {}
    h3_payload = snapshot.h3 if isinstance(snapshot.h3, dict) else {}
    road_payload = snapshot.road if isinstance(snapshot.road, dict) else {}
    population_payload = snapshot.population if isinstance(snapshot.population, dict) else {}
    nightlight_payload = snapshot.nightlight if isinstance(snapshot.nightlight, dict) else {}
    frontend_analysis = snapshot.frontend_analysis if isinstance(snapshot.frontend_analysis, dict) else {}
    return {
        "context": {
            "mode": context.get("mode"),
            "time_min": context.get("time_min"),
            "source": context.get("source"),
            "scope_source": context.get("scope_source"),
            "year": context.get("year"),
        },
        "scope": {
            "has_polygon": bool(scope.get("polygon") or scope.get("drawn_polygon")),
            "has_isochrone_feature": bool(scope.get("isochrone_feature")),
        },
        "poi": {"count": len(snapshot.pois or []), "summary": compact_for_llm(snapshot.poi_summary or {}, max_depth=4)},
        "h3": {"summary": compact_for_llm(h3_payload.get("summary") or {}, max_depth=4), "grid_count": h3_payload.get("grid_count") or 0},
        "road": {"summary": compact_for_llm(road_payload.get("summary") or {}, max_depth=4)},
        "population": {"summary": compact_for_llm(population_payload.get("summary") or {}, max_depth=4)},
        "nightlight": {"summary": compact_for_llm(nightlight_payload.get("summary") or {}, max_depth=4)},
        "frontend_analysis_keys": list(frontend_analysis.keys())[:20],
        "active_panel": snapshot.active_panel,
        "current_filters": compact_for_llm(current_filters, max_depth=3),
    }


def context_digest(context: ContextBundle) -> Dict[str, Any]:
    analysis: Dict[str, Any] = {}
    for key, value in dict(context.analysis or {}).items():
        if key == "frontend_analysis" and isinstance(value, dict):
            analysis[key] = _frontend_analysis_digest(value)
        else:
            analysis[str(key)] = compact_for_llm(value, max_depth=4)
    return {
        "facts": compact_for_llm(dict(context.facts or {}), max_depth=3),
        "analysis": analysis,
        "limits": list(context.limits or []),
        "available_artifacts": list(context.available_artifacts or []),
        "context_summary": compact_context_summary_dump(context.context_summary),
    }


def compact_json(value: Any, *, max_length: int = 160) -> str:
    if value in (None, "", [], {}):
        return ""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return f"{text[:max_length]}..." if len(text) > max_length else text


def summarize_tool_arguments(arguments: Dict[str, Any]) -> str:
    if not isinstance(arguments, dict) or not arguments:
        return "无参数"
    preferred = ("place_type", "types", "keywords", "resolution", "include_mode", "mode", "graph_model", "highway_filter", "year", "max_count", "coord_type")
    items = [f"{key}={arguments.get(key)}" for key in preferred if key in arguments and arguments.get(key) not in (None, "", [], {})]
    if not items:
        items = [f"{key}={compact_json(value, max_length=40)}" for key, value in list(arguments.items())[:4] if value not in (None, "", [], {})]
    return ", ".join(items) or "无参数"


def summarize_tool_result(result: ToolResult) -> str:
    if result.status == "failed":
        return str(result.error or "执行失败")
    payload = result.result if isinstance(result.result, dict) else {}
    if not payload:
        return "无结果"
    preferred = ("place_type", "poi_count", "h3_grid_count", "grid_count", "resolution", "road_node_count", "road_edge_count", "population_total", "nightlight_mean_radiance", "source", "total")
    items = [f"{key}={payload.get(key)}" for key in preferred if key in payload and payload.get(key) not in (None, "", [], {})]
    if not items:
        items = [f"{key}={compact_json(value, max_length=50)}" for key, value in list(payload.items())[:4] if value not in (None, "", [], {})]
    return ", ".join(items) or "无结果"


def tool_result_llm_digest(result: ToolResult) -> Dict[str, Any]:
    artifacts = result.artifacts if isinstance(result.artifacts, dict) else {}
    return {
        "tool_name": result.tool_name,
        "status": result.status,
        "result_summary": summarize_tool_result(result),
        "result_shape": shape_summary(result.result),
        "evidence_sample": [
            compact_for_llm(item, max_depth=3)
            for item in list(result.evidence or [])[:8]
        ],
        "evidence_count": len(result.evidence or []),
        "warnings": [str(item) for item in list(result.warnings or [])[:8] if str(item).strip()],
        "error": result.error,
        "artifact_keys": list(artifacts.keys()),
        "artifact_shapes": {str(key): shape_summary(value) for key, value in artifacts.items()},
    }


def tool_results_llm_digest(results: List[ToolResult]) -> List[Dict[str, Any]]:
    return [tool_result_llm_digest(result) for result in results or []]


def audit_tool_result_digest(result: ToolResult) -> Dict[str, Any]:
    return tool_result_llm_digest(result)


def audit_tool_results_digest(results: List[ToolResult]) -> List[Dict[str, Any]]:
    return tool_results_llm_digest(results)
