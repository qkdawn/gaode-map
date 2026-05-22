from __future__ import annotations

from typing import Any, Dict, List

from ..analysis_extractors import (
    analyze_poi_mix,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    infer_area_character_labels,
    score_site_candidates,
)
from ..policy_table import resolve_policy
from ..schemas import AnalysisSnapshot, ToolResult
from .analysis_tools import analyze_target_supply_gap_from_scope
from .business_tools import run_business_site_advice
from .capability_tools import (
    analyze_poi_structure,
    analyze_spatial_structure,
    get_area_data_bundle,
    infer_area_labels,
)
from .scope_tools import extract_scope_polygon


def _pack_evidence_chain(*items: tuple[str, Any, str, str]) -> List[Dict[str, Any]]:
    chain: List[Dict[str, Any]] = []
    for tool_name, metric_value, rule_or_reason, confidence in items:
        if metric_value in (None, "", [], {}):
            continue
        chain.append(
            {
                "tool_name": tool_name,
                "metric": tool_name,
                "value": metric_value,
                "rule_or_reason": rule_or_reason,
                "confidence": confidence,
            }
        )
    return chain


async def run_area_character_pack(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    policy = resolve_policy(arguments.get("policy_key"), fallback="district_summary")
    local_artifacts = dict(artifacts or {})

    existing_bundle = local_artifacts.get("current_area_data_bundle")
    existing_readiness = local_artifacts.get("current_data_readiness")
    if not isinstance(existing_bundle, dict) or not isinstance(existing_readiness, dict) or not existing_readiness.get("ready"):
        data_bundle = await get_area_data_bundle(
            arguments={
                "policy_key": policy["policy_key"],
                "source": arguments.get("source"),
                "mode": arguments.get("mode") or policy.get("mode"),
                "resolution": arguments.get("resolution") or policy.get("h3_resolution"),
            },
            snapshot=snapshot,
            artifacts=local_artifacts,
            question=question,
        )
        local_artifacts.update(data_bundle.artifacts or {})
    else:
        data_bundle = ToolResult(
            tool_name="get_area_data_bundle",
            status="success",
            result=dict(existing_bundle),
            artifacts=dict(local_artifacts),
        )
    if data_bundle.status == "failed":
        return ToolResult(
            tool_name="run_area_character_pack",
            status="failed",
            result={
                "policy_key": policy["policy_key"],
                "policy_params": policy,
                "data_readiness": dict(local_artifacts.get("current_data_readiness") or {}),
            },
            warnings=list(data_bundle.warnings or []),
            error=data_bundle.error or "area_data_bundle_failed",
            artifacts=dict(local_artifacts),
        )

    poi_result = await analyze_poi_structure(arguments={}, snapshot=snapshot, artifacts=local_artifacts, question=question)
    local_artifacts.update(poi_result.artifacts or {})
    spatial_result = await analyze_spatial_structure(arguments={}, snapshot=snapshot, artifacts=local_artifacts, question=question)
    local_artifacts.update(spatial_result.artifacts or {})
    labels_result = await infer_area_labels(arguments={}, snapshot=snapshot, artifacts=local_artifacts, question=question)
    local_artifacts.update(labels_result.artifacts or {})

    poi_structure = build_poi_structure_analysis(snapshot, local_artifacts)
    business_profile = analyze_poi_mix(snapshot, local_artifacts, poi_structure=poi_structure)
    population_profile = build_population_profile_analysis(snapshot, local_artifacts)
    nightlight_pattern = build_nightlight_pattern_analysis(snapshot, local_artifacts)
    road_pattern = build_road_pattern_analysis(snapshot, local_artifacts)
    labels = infer_area_character_labels(
        snapshot,
        local_artifacts,
        poi_structure=poi_structure,
        business_profile=business_profile,
        population_profile=population_profile,
        nightlight_pattern=nightlight_pattern,
        road_pattern=road_pattern,
    )

    evidence_chain = _pack_evidence_chain(
        ("analyze_poi_structure", poi_structure.get("dominant_categories"), "POI 主导业态结构", "strong" if poi_structure.get("evidence_ready") else "weak"),
        ("analyze_spatial_structure", spatial_result.result.get("distribution_pattern"), "空间结构与多核/单核判断", "moderate"),
        ("infer_area_labels", labels.get("rule_hits"), "规则标签命中", labels.get("confidence") or "weak"),
        ("population_profile", population_profile.get("top_age_band"), "人口主年龄段", "moderate"),
        ("nightlight_pattern", nightlight_pattern.get("core_hotspot_count"), "夜间活力核心数量", "moderate"),
        ("road_pattern", road_pattern.get("node_count"), "路网节点规模", "moderate"),
    )
    payload = {
        "character_tags": labels.get("character_tags") or [],
        "dominant_functions": labels.get("dominant_functions") or business_profile.get("dominant_functions") or [],
        "activity_period": labels.get("activity_period") or "全天均衡",
        "crowd_traits": labels.get("crowd_traits") or [],
        "spatial_temperament": labels.get("spatial_temperament") or "",
        "evidence_chain": evidence_chain,
        "confidence": labels.get("confidence") or "weak",
        "policy_key": policy["policy_key"],
        "policy_params": policy,
        "analysis_mode": str(arguments.get("analysis_mode") or "district_summary"),
        "summary_text": labels.get("summary_text") or "",
        "data_readiness": dict(local_artifacts.get("current_data_readiness") or {}),
    }
    return ToolResult(
        tool_name="run_area_character_pack",
        status="success",
        result=payload,
        evidence=(data_bundle.evidence or []) + (poi_result.evidence or []) + (spatial_result.evidence or []) + (labels_result.evidence or []),
        warnings=(data_bundle.warnings or []) + (poi_result.warnings or []) + (spatial_result.warnings or []) + (labels_result.warnings or []),
        artifacts={
            **local_artifacts,
            "area_character_pack": payload,
            "current_area_character_labels": labels,
        },
    )


async def run_site_selection_pack(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    policy = resolve_policy(arguments.get("policy_key"), fallback="business_catchment_1km")
    local_artifacts = dict(artifacts or {})
    polygon = extract_scope_polygon(snapshot)
    if polygon and not local_artifacts.get("scope_polygon"):
        local_artifacts["scope_polygon"] = polygon
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    if scope and not local_artifacts.get("scope_data"):
        local_artifacts["scope_data"] = scope

    business_result = await run_business_site_advice(
        arguments={
            "place_type": arguments.get("place_type"),
            "source": arguments.get("source"),
            "year": arguments.get("year"),
            "resolution": arguments.get("resolution") or policy.get("h3_resolution"),
            "include_mode": arguments.get("include_mode") or policy.get("include_mode"),
            "min_overlap_ratio": arguments.get("min_overlap_ratio") or policy.get("min_overlap_ratio"),
            "neighbor_ring": arguments.get("neighbor_ring") or policy.get("neighbor_ring"),
            "mode": arguments.get("mode") or policy.get("mode"),
        },
        snapshot=snapshot,
        artifacts=local_artifacts,
        question=question,
    )
    local_artifacts.update(business_result.artifacts or {})
    if business_result.status == "failed":
        return ToolResult(
            tool_name="run_site_selection_pack",
            status="failed",
            result={"policy_key": policy["policy_key"], "policy_params": policy},
            evidence=list(business_result.evidence or []),
            warnings=list(business_result.warnings or []),
            error=business_result.error or "site_selection_base_failed",
            artifacts=dict(local_artifacts),
        )

    resolved_place_type = str(business_result.result.get("place_type") or arguments.get("place_type") or "").strip()
    gap_result = await analyze_target_supply_gap_from_scope(
        arguments={"place_type": resolved_place_type},
        snapshot=snapshot,
        artifacts=local_artifacts,
        question=question,
    )
    local_artifacts.update(gap_result.artifacts or {})
    population_profile = build_population_profile_analysis(snapshot, local_artifacts)
    nightlight_pattern = build_nightlight_pattern_analysis(snapshot, local_artifacts)
    road_pattern = build_road_pattern_analysis(snapshot, local_artifacts)
    scoring = score_site_candidates(
        snapshot,
        local_artifacts,
        target_supply_gap=gap_result.result,
        population_profile=population_profile,
        nightlight_pattern=nightlight_pattern,
        road_pattern=road_pattern,
    )
    evidence_chain = _pack_evidence_chain(
        ("run_business_site_advice", business_result.result.get("poi_count"), "目标业态基础供给样本", "moderate"),
        ("analyze_target_supply_gap", gap_result.result.get("candidate_zones"), "H3 缺口与候选格提取", "moderate" if gap_result.result.get("candidate_zones") else "weak"),
        ("score_site_candidates", scoring.get("ranking"), "程序化评分排序", scoring.get("confidence") or "weak"),
        ("population_profile", population_profile.get("total_population"), "人口支撑", "moderate"),
        ("nightlight_pattern", nightlight_pattern.get("core_hotspot_count"), "夜间活力", "moderate"),
        ("road_pattern", road_pattern.get("node_count"), "可达性", "moderate"),
    )
    payload = {
        "candidate_sites": scoring.get("candidate_sites") or [],
        "ranking": scoring.get("ranking") or [],
        "strengths": scoring.get("strengths") or [],
        "risks": scoring.get("risks") or [],
        "not_recommended_reason": scoring.get("not_recommended_reason") or "",
        "evidence_chain": evidence_chain,
        "confidence": scoring.get("confidence") or "weak",
        "policy_key": policy["policy_key"],
        "policy_params": policy,
        "place_type": resolved_place_type or gap_result.result.get("place_type") or str(arguments.get("place_type") or "").strip(),
        "summary_text": scoring.get("summary_text") or gap_result.result.get("summary_text") or "",
    }
    return ToolResult(
        tool_name="run_site_selection_pack",
        status="success",
        result=payload,
        evidence=(business_result.evidence or []) + (gap_result.evidence or []),
        warnings=(business_result.warnings or []) + (gap_result.warnings or []),
        artifacts={
            **local_artifacts,
            "site_selection_pack": payload,
            "current_target_supply_gap": gap_result.result,
            "current_site_candidate_scores": scoring,
        },
    )


async def run_placeholder_scene_pack(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, snapshot, artifacts, question
    return ToolResult(
        tool_name="placeholder_scene_pack",
        status="failed",
        warnings=["该场景工具包已预留分类，但当前版本尚未实现。"],
        error="scene_pack_not_implemented",
    )
