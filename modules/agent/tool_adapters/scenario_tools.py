from __future__ import annotations

from typing import Any, Dict

from ..analysis_extractors import (
    analyze_poi_mix,
    build_area_character_facts,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    build_site_candidate_facts,
)
from ..policy_table import resolve_policy
from ..schemas import AnalysisSnapshot, ToolResult
from .analysis_tools import analyze_target_supply_gap_from_scope
from .business_tools import run_business_site_advice
from .capability_tools import (
    analyze_poi_structure,
    analyze_spatial_structure,
    get_area_data_bundle,
    build_area_facts,
)
from .result_tools import read_current_results
from .scope_tools import extract_scope_polygon


async def run_area_fact_pack(
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
            tool_name="run_area_fact_pack",
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
    facts_result = await build_area_facts(arguments={}, snapshot=snapshot, artifacts=local_artifacts, question=question)
    local_artifacts.update(facts_result.artifacts or {})

    poi_structure = build_poi_structure_analysis(snapshot, local_artifacts)
    business_profile = analyze_poi_mix(snapshot, local_artifacts, poi_structure=poi_structure)
    population_profile = build_population_profile_analysis(snapshot, local_artifacts)
    nightlight_pattern = build_nightlight_pattern_analysis(snapshot, local_artifacts)
    road_pattern = build_road_pattern_analysis(snapshot, local_artifacts)
    facts = build_area_character_facts(
        snapshot,
        local_artifacts,
        poi_structure=poi_structure,
        business_profile=business_profile,
        population_profile=population_profile,
        road_pattern=road_pattern,
    )

    payload = {
        "facts": facts,
        "policy_key": policy["policy_key"],
        "policy_params": policy,
        "analysis_mode": str(arguments.get("analysis_mode") or "district_summary"),
        "data_readiness": dict(local_artifacts.get("current_data_readiness") or {}),
    }
    return ToolResult(
        tool_name="run_area_fact_pack",
        status="success",
        result=payload,
        evidence=(data_bundle.evidence or []) + (poi_result.evidence or []) + (spatial_result.evidence or []) + (facts_result.evidence or []),
        warnings=(data_bundle.warnings or []) + (poi_result.warnings or []) + (spatial_result.warnings or []) + (facts_result.warnings or []),
        artifacts={
            **local_artifacts,
            "area_fact_pack": payload,
            "current_area_character_facts": facts,
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
    current_results = await read_current_results(
        arguments={},
        snapshot=snapshot,
        artifacts=local_artifacts,
        question=question,
    )
    local_artifacts.update(
        {
            key: value
            for key, value in (current_results.artifacts or {}).items()
            if value not in ({}, [], None) and not local_artifacts.get(key)
        }
    )

    business_result = await run_business_site_advice(
        arguments={
            "place_type": arguments.get("place_type"),
            "source": arguments.get("source"),
            "year": arguments.get("year"),
            "resolution": arguments.get("resolution") or policy.get("h3_resolution"),
            "include_mode": arguments.get("include_mode") or policy.get("include_mode"),
            "min_overlap_ratio": arguments.get("min_overlap_ratio") or policy.get("min_overlap_ratio"),
            "mode": arguments.get("mode") or policy.get("mode"),
        },
        snapshot=snapshot,
        artifacts=local_artifacts,
        question=question,
    )
    local_artifacts.update(business_result.artifacts or {})
    if business_result.status == "failed":
        base_error = business_result.error or "site_selection_base_failed"
        if base_error not in {"missing_scope_polygon", "unresolved_place_type"}:
            base_error = "site_selection_base_failed"
        return ToolResult(
            tool_name="run_site_selection_pack",
            status="failed",
            result={"policy_key": policy["policy_key"], "policy_params": policy},
            evidence=list(business_result.evidence or []),
            warnings=list(business_result.warnings or []),
            error=base_error,
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
    road_pattern = build_road_pattern_analysis(snapshot, local_artifacts)
    candidate_facts = build_site_candidate_facts(
        snapshot,
        local_artifacts,
        target_supply_gap=gap_result.result,
        population_profile=population_profile,
        road_pattern=road_pattern,
    )
    payload = {
        "candidate_sites": candidate_facts.get("candidate_sites") or [],
        "candidate_count": candidate_facts.get("candidate_count") or 0,
        "policy_key": policy["policy_key"],
        "policy_params": policy,
        "place_type": resolved_place_type or gap_result.result.get("place_type") or str(arguments.get("place_type") or "").strip(),
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
            "current_site_candidate_facts": candidate_facts,
        },
    )
