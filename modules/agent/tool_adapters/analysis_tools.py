from __future__ import annotations

from typing import Any, Dict

from modules.providers.amap.utils.get_type_info import infer_type_info_from_text, resolve_type_info

from ..analysis_extractors import (
    analyze_poi_mix,
    analyze_target_supply_gap,
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    detect_commercial_hotspots,
)
from ..schemas import AnalysisSnapshot, ToolResult


def _success_result(*, tool_name: str, result: Dict[str, Any], evidence: Dict[str, Any], artifacts: Dict[str, Any]) -> ToolResult:
    ready = bool(result.get("evidence_ready")) if isinstance(result, dict) else False
    return ToolResult(
        tool_name=tool_name,
        status="success",
        result=result,
        evidence=[evidence],
        warnings=[] if ready else [str(result.get("summary_text") or "当前缺少可直接利用的结构化分析结果。")],
        artifacts=artifacts,
    )


async def read_poi_structure_analysis(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    payload = build_poi_structure_analysis(snapshot, artifacts)
    return _success_result(
        tool_name="read_poi_structure_analysis",
        result=payload,
        evidence={"field": "poi.structure.summary_text", "value": payload.get("summary_text")},
        artifacts={"current_poi_structure_analysis": payload},
    )


async def read_h3_structure_analysis(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    payload = build_h3_structure_analysis(snapshot, artifacts)
    return _success_result(
        tool_name="read_h3_structure_analysis",
        result=payload,
        evidence={"field": "h3.structure.distribution_pattern", "value": payload.get("distribution_pattern")},
        artifacts={"current_h3_structure_analysis": payload},
    )


async def read_road_pattern_analysis(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    payload = build_road_pattern_analysis(snapshot, artifacts)
    return _success_result(
        tool_name="read_road_pattern_analysis",
        result=payload,
        evidence={"field": "road.pattern.summary_text", "value": payload.get("summary_text")},
        artifacts={"current_road_pattern_analysis": payload},
    )


async def read_population_profile_analysis(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    payload = build_population_profile_analysis(snapshot, artifacts)
    ready = bool(payload.get("evidence_ready"))
    return ToolResult(
        tool_name="read_population_profile_analysis",
        status="success",
        result=payload,
        evidence=[
            {"field": "population.profile.summary_text", "value": payload.get("summary_text")},
            {"field": "population.profile.top_age_band", "value": payload.get("top_age_band")},
            {"field": "population.profile.top_age_band_ratio", "value": payload.get("top_age_band_ratio")},
            {"field": "population.profile.age_distribution_ratios", "value": payload.get("age_distribution_ratios")},
        ],
        warnings=[] if ready else [str(payload.get("summary_text") or "当前缺少可直接利用的结构化分析结果。")],
        artifacts={"current_population_profile_analysis": payload},
    )


async def read_nightlight_pattern_analysis(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    payload = build_nightlight_pattern_analysis(snapshot, artifacts)
    return _success_result(
        tool_name="read_nightlight_pattern_analysis",
        result=payload,
        evidence={"field": "nightlight.pattern.summary_text", "value": payload.get("summary_text")},
        artifacts={"current_nightlight_pattern_analysis": payload},
    )


async def analyze_poi_mix_from_scope(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    poi_structure = (
        dict(artifacts.get("current_poi_structure_analysis"))
        if isinstance(artifacts.get("current_poi_structure_analysis"), dict)
        else build_poi_structure_analysis(snapshot, artifacts)
    )
    payload = analyze_poi_mix(snapshot, artifacts, poi_structure=poi_structure)
    return ToolResult(
        tool_name="analyze_poi_mix_from_scope",
        status="success",
        result=payload,
        evidence=[
            {"field": "business_profile.business_profile", "value": payload.get("business_profile")},
            {"field": "business_profile.functional_mix_score", "value": payload.get("functional_mix_score")},
        ],
        artifacts={
            "current_poi_structure_analysis": poi_structure,
            "current_business_profile": payload,
        },
    )


async def detect_commercial_hotspots_from_scope(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    target_category = str(arguments.get("target_category") or "").strip()
    h3_structure = (
        dict(artifacts.get("current_h3_structure_analysis"))
        if isinstance(artifacts.get("current_h3_structure_analysis"), dict)
        else build_h3_structure_analysis(snapshot, artifacts)
    )
    poi_structure = (
        dict(artifacts.get("current_poi_structure_analysis"))
        if isinstance(artifacts.get("current_poi_structure_analysis"), dict)
        else build_poi_structure_analysis(snapshot, artifacts)
    )
    payload = detect_commercial_hotspots(
        snapshot,
        artifacts,
        target_category=target_category,
        h3_structure=h3_structure,
        poi_structure=poi_structure,
    )
    return ToolResult(
        tool_name="detect_commercial_hotspots",
        status="success",
        result=payload,
        evidence=[
            {"field": "commercial_hotspots.hotspot_mode", "value": payload.get("hotspot_mode")},
            {"field": "commercial_hotspots.core_zone_count", "value": payload.get("core_zone_count")},
        ],
        artifacts={
            "current_h3_structure_analysis": h3_structure,
            "current_poi_structure_analysis": poi_structure,
            "current_commercial_hotspots": payload,
        },
    )


async def analyze_target_supply_gap_from_scope(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    place_type = str(arguments.get("place_type") or "").strip()
    target = resolve_type_info(place_type) if place_type else infer_type_info_from_text(question)
    resolved_place_type = str((target or {}).get("label") or place_type).strip()
    h3_structure = (
        dict(artifacts.get("current_h3_structure_analysis"))
        if isinstance(artifacts.get("current_h3_structure_analysis"), dict)
        else build_h3_structure_analysis(snapshot, artifacts)
    )
    payload = analyze_target_supply_gap(
        snapshot,
        artifacts,
        place_type=resolved_place_type,
        h3_structure=h3_structure,
    )
    return ToolResult(
        tool_name="analyze_target_supply_gap",
        status="success",
        result=payload,
        evidence=[
            {"field": "target_supply_gap.place_type", "value": payload.get("place_type")},
            {"field": "target_supply_gap.supply_gap_level", "value": payload.get("supply_gap_level")},
            {"field": "target_supply_gap.gap_mode", "value": payload.get("gap_mode")},
        ],
        artifacts={
            "current_h3_structure_analysis": h3_structure,
            "current_target_supply_gap": payload,
        },
    )
