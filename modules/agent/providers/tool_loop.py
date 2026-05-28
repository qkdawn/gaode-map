from __future__ import annotations

import json
from typing import Any, Dict, List

from ..analysis_extractors import (
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    is_h3_structure_ready,
    is_nightlight_pattern_ready,
    is_poi_structure_ready,
    is_population_profile_ready,
    is_road_pattern_ready,
)
from ..gate import classify_question_type
from ..schemas import AnalysisSnapshot, ContextBundle, PlanStep, ToolResult, WorkingMemory
from ..tools import RegisteredTool


def trim_messages(messages) -> List[Dict[str, str]]:
    from core.config import settings

    max_turns = max(1, int(settings.ai_max_context_turns or 12))
    kept = messages[-max_turns:]
    normalized: List[Dict[str, str]] = []
    for item in kept:
        role = str(item.role or "").strip() or "user"
        content = str(item.content or "").strip()
        if content:
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
        "poi": {"count": len(snapshot.pois or []), "summary": snapshot.poi_summary or {}},
        "h3": {"summary": h3_payload.get("summary") or {}, "grid_count": h3_payload.get("grid_count") or 0},
        "road": {"summary": road_payload.get("summary") or {}},
        "population": {"summary": population_payload.get("summary") or {}},
        "nightlight": {"summary": nightlight_payload.get("summary") or {}},
        "frontend_analysis_keys": list(frontend_analysis.keys())[:20],
        "active_panel": snapshot.active_panel,
        "current_filters": current_filters,
    }


def context_digest(context: ContextBundle) -> Dict[str, Any]:
    return {
        "facts": dict(context.facts or {}),
        "analysis": dict(context.analysis or {}),
        "limits": list(context.limits or []),
        "available_artifacts": list(context.available_artifacts or []),
        "context_summary": context.context_summary.model_dump(),
    }


def tool_catalog(registry: Dict[str, RegisteredTool]) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for name, registered in registry.items():
        spec = registered.spec
        catalog.append(
            {
                "name": name,
                "description": spec.description,
                "category": spec.category,
                "layer": spec.layer,
                "ui_tier": spec.ui_tier,
                "data_domain": spec.data_domain,
                "capability_type": spec.capability_type,
                "scene_type": spec.scene_type,
                "llm_exposure": spec.llm_exposure,
                "toolkit_id": spec.toolkit_id,
                "default_policy_key": spec.default_policy_key,
                "applicable_scenarios": list(spec.applicable_scenarios or []),
                "cautions": list(spec.cautions or []),
                "evidence_contract": list(spec.evidence_contract or []),
                "requires": list(spec.requires or []),
                "produces": list(spec.produces or []),
                "readonly": bool(spec.readonly),
                "cost_level": spec.cost_level,
                "risk_level": spec.risk_level,
                "input_schema": spec.input_schema,
            }
        )
    return catalog


def llm_visible_registry(registry: Dict[str, RegisteredTool], *, include_secondary: bool = False) -> Dict[str, RegisteredTool]:
    visible: Dict[str, RegisteredTool] = {}
    for name, registered in registry.items():
        exposure = str(registered.spec.llm_exposure or "secondary")
        if exposure == "primary" or (include_secondary and exposure == "secondary"):
            visible[name] = registered
    return visible


def planner_question_archetype(question: str) -> str:
    question_text = str(question or "").strip()
    classified = classify_question_type(question_text) or "general"
    if classified == "general" and any(token in question_text for token in ("核心", "热点", "集中", "分布", "偏空", "空白", "多核", "单核")):
        return "metric"
    return classified


def artifact_digest(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> Dict[str, Any]:
    artifacts = memory.artifacts if isinstance(memory.artifacts, dict) else {}
    poi_structure = artifacts.get("current_poi_structure_analysis") if isinstance(artifacts.get("current_poi_structure_analysis"), dict) else {}
    h3_structure = artifacts.get("current_h3_structure_analysis") if isinstance(artifacts.get("current_h3_structure_analysis"), dict) else build_h3_structure_analysis(snapshot, artifacts)
    population_profile = artifacts.get("current_population_profile_analysis") if isinstance(artifacts.get("current_population_profile_analysis"), dict) else build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = artifacts.get("current_nightlight_pattern_analysis") if isinstance(artifacts.get("current_nightlight_pattern_analysis"), dict) else build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = artifacts.get("current_road_pattern_analysis") if isinstance(artifacts.get("current_road_pattern_analysis"), dict) else build_road_pattern_analysis(snapshot, artifacts)
    analysis_readiness = {
        "poi": is_poi_structure_ready(poi_structure),
        "h3": is_h3_structure_ready(h3_structure),
        "population": is_population_profile_ready(population_profile),
        "nightlight": is_nightlight_pattern_ready(nightlight_pattern),
        "road": is_road_pattern_ready(road_pattern),
    }
    summary_keys = [
        key
        for key in ("current_poi_summary", "current_h3_summary", "current_population_summary", "current_nightlight_summary", "current_road_summary")
        if isinstance(artifacts.get(key), dict) and artifacts.get(key)
    ]
    if not summary_keys:
        if isinstance(snapshot.poi_summary, dict) and snapshot.poi_summary:
            summary_keys.append("snapshot.poi_summary")
        for key in ("h3", "population", "nightlight", "road"):
            payload = getattr(snapshot, key, {})
            if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) and payload.get("summary"):
                summary_keys.append(f"snapshot.{key}.summary")
    analysis_keys = [
        key
        for key, ready in (
            ("current_poi_structure_analysis", analysis_readiness["poi"]),
            ("current_h3_structure_analysis", analysis_readiness["h3"]),
            ("current_population_profile_analysis", analysis_readiness["population"]),
            ("current_nightlight_pattern_analysis", analysis_readiness["nightlight"]),
            ("current_road_pattern_analysis", analysis_readiness["road"]),
        )
        if ready and isinstance(artifacts.get(key), dict) and artifacts.get(key)
    ]
    frontend_analysis = snapshot.frontend_analysis if isinstance(snapshot.frontend_analysis, dict) else {}
    frontend_keys = [key for key, value in frontend_analysis.items() if isinstance(value, dict) and value][:10]
    derived_keys = [
        key
        for key in ("current_business_profile", "current_commercial_hotspots", "current_target_supply_gap", "business_site_advice")
        if isinstance(artifacts.get(key), dict) and artifacts.get(key)
    ]
    return {
        "summary_artifacts": summary_keys,
        "analysis_artifacts": analysis_keys,
        "analysis_readiness": analysis_readiness,
        "empty_analysis_dimensions": [key for key, ready in analysis_readiness.items() if not ready and key != "poi"],
        "derived_artifacts": derived_keys,
        "frontend_analysis_keys": frontend_keys,
        "available_artifacts": list(artifacts.keys()),
    }


def planner_tool_routing_hints() -> Dict[str, Any]:
    return {
        "layers": {
            "foundation": [
                "read_current_scope",
                "read_current_results",
                "search_analysis_context",
                "read_analysis_chunk",
                "search_report_context",
                "read_report_chunk",
                "fetch_pois_in_scope",
                "compute_h3_metrics_from_scope_and_pois",
                "compute_population_overview_from_scope",
                "compute_nightlight_overview_from_scope",
                "compute_road_syntax_from_scope",
            ],
            "capability": [
                "get_area_data_bundle",
                "analyze_poi_structure",
                "analyze_spatial_structure",
                "infer_area_labels",
                "score_site_candidates",
            ],
            "scenario": ["run_area_character_pack", "run_site_selection_pack"],
        },
        "priority_rules": [
            "先读 scope 和 current_results，再决定是否需要重算基础数据。",
            "涉及已有分析结论或报告追问时，优先 search 对应上下文，再 read 命中的 chunk。",
            "区域画像类问题优先使用 run_area_character_pack。",
            "选址评估类问题优先使用 run_site_selection_pack。",
            "如果上游分析产物不完整，先补依赖，再给结论。",
            "frontend_analysis 只能作为参考线索，不能替代正式分析结果。",
            "如果 audit_feedback 指出证据不足，应回退到更保守的工具链路。",
        ],
        "dependencies": {
            "run_area_character_pack": ["scope_polygon"],
            "run_site_selection_pack": ["scope_polygon", "place_type"],
            "infer_area_labels": [
                "current_poi_structure_analysis",
                "current_population_profile_analysis",
                "current_nightlight_pattern_analysis",
                "current_road_pattern_analysis",
            ],
            "score_site_candidates": ["current_target_supply_gap"],
        },
        "question_routes": {
            "area_character": ["read_current_results", "run_area_character_pack"],
            "site_selection": ["read_current_results", "run_site_selection_pack"],
            "population": ["read_current_results", "compute_population_overview_from_scope"],
            "nightlight": ["read_current_results", "compute_nightlight_overview_from_scope"],
            "road": ["read_current_results", "compute_road_syntax_from_scope"],
        },
    }


def chat_completion_tools(registry: Dict[str, RegisteredTool], *, include_secondary: bool = False) -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": registered.spec.description,
                "parameters": registered.spec.input_schema or {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
        for name, registered in llm_visible_registry(registry, include_secondary=include_secondary).items()
    ]


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


def tool_output_payload(result: ToolResult) -> str:
    return json.dumps(
        {
            "tool_name": result.tool_name,
            "status": result.status,
            "result": result.result,
            "evidence": result.evidence,
            "warnings": result.warnings,
            "error": result.error,
        },
        ensure_ascii=False,
    )


def is_reusable_tool_call(registered: RegisteredTool, step: PlanStep) -> bool:
    return bool(registered.spec.readonly and registered.spec.name in {"read_current_scope", "read_current_results"} and not (step.arguments or {}))


def tool_cache_key(step: PlanStep) -> str:
    return f"{step.tool_name}:{json.dumps(step.arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"
