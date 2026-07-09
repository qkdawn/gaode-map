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
from ..llm_digest import tool_result_llm_digest
from ..schemas import AnalysisSnapshot, PlanStep, ToolResult, WorkingMemory
from ..tools import RegisteredTool


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


def _tool_argument_hints(name: str) -> Dict[str, Any]:
    if name in {"search_analysis_context", "search_report_context"}:
        return {"query": "用户原问题", "top_k": 8}
    if name in {"read_analysis_evidence_node", "read_report_evidence_node"}:
        return {"node_id": "来自 search 命中的 node_id"}
    if name == "list_selected_sources":
        return {}
    if name == "search_selected_source_evidence":
        return {"query": "用户原问题", "source_ids": ["来自 list_selected_sources 的 source_id"], "top_k": 8}
    if name == "read_selected_source_evidence_node":
        return {"node_id": "来自 search_selected_source_evidence 命中的 node_id"}
    if name == "list_scope_datasets":
        return {}
    if name == "query_scope_dataset":
        return {"source_id": "current:dataset:poi", "limit": 20, "offset": 0}
    if name == "aggregate_scope_dataset":
        return {"source_id": "current:dataset:poi", "group_by": "category", "metrics": [{"op": "count", "field": "*", "as": "count"}]}
    if name == "read_scope_record":
        return {"source_id": "current:dataset:poi", "record_id": "来自 query_scope_dataset 的 record_id"}
    return {}


def compact_tool_catalog(registry: Dict[str, RegisteredTool]) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for name, registered in registry.items():
        spec = registered.spec
        intent = str(spec.description or "").strip()
        catalog.append(
            {
                "name": name,
                "intent": intent[:96],
                "layer": spec.layer,
                "data_domain": spec.data_domain,
                "requires": list(spec.requires or [])[:8],
                "produces": list(spec.produces or [])[:8],
                "readonly": bool(spec.readonly),
                "cost_level": spec.cost_level,
                "risk_level": spec.risk_level,
                "argument_hints": _tool_argument_hints(name),
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
        for key in ("current_poi_summary", "current_poi_h3_summary", "current_population_summary", "current_nightlight_summary", "current_road_summary")
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
                "list_selected_sources",
                "search_selected_source_evidence",
                "read_selected_source_evidence_node",
                "search_analysis_context",
                "read_analysis_evidence_node",
                "search_report_context",
                "read_report_evidence_node",
                "list_scope_datasets",
                "query_scope_dataset",
                "aggregate_scope_dataset",
                "read_scope_record",
            ],
            "capability": [],
            "scenario": [],
        },
        "priority_rules": [
            "主 Agent 当前只做来源分析和证据读取，不重算基础数据、不运行区域画像或选址 pack。",
            "已选分析来源问题先 list_selected_sources，再 search_selected_source_evidence / read_selected_source_evidence_node。",
            "涉及已有分析结论或报告追问时，优先 search 对应上下文，再 read 命中的 EvidenceNode。",
            "涉及当前范围内全量明细、TopN、分页、按类别统计或具体对象时，先 list_scope_datasets，再 query_scope_dataset / aggregate_scope_dataset / read_scope_record。",
            "用户提到文件、图片、报告、图纸、表格时，只使用已进入来源区并可检索的 EvidenceNode。",
            "下一步分析建议类问题只排序分析方向，不直接调用区域画像或选址场景工具。",
            "frontend_analysis 只能作为参考线索，不能替代正式分析结果。",
            "如果 audit_feedback 指出证据不足，应回退到更保守的工具链路。",
        ],
        "dependencies": {},
        "question_routes": {
            "source_analysis": ["list_selected_sources", "search_selected_source_evidence", "read_selected_source_evidence_node"],
            "current_dataset": ["list_scope_datasets", "aggregate_scope_dataset", "query_scope_dataset", "read_scope_record"],
            "analysis_evidence": ["search_analysis_context", "read_analysis_evidence_node"],
            "report_evidence": ["search_report_context", "read_report_evidence_node"],
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


def tool_output_payload(result: ToolResult) -> str:
    return json.dumps(tool_result_llm_digest(result), ensure_ascii=False)


def is_reusable_tool_call(registered: RegisteredTool, step: PlanStep) -> bool:
    return bool(registered.spec.readonly and registered.spec.name in {"read_current_scope", "read_current_results"} and not (step.arguments or {}))


def tool_cache_key(step: PlanStep) -> str:
    return f"{step.tool_name}:{json.dumps(step.arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"
