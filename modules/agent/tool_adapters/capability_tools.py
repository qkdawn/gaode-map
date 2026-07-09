from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

from ..analysis_extractors import (
    analyze_poi_mix,
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    infer_area_character_labels,
)
from ..policy_table import resolve_policy
from ..schemas import AnalysisSnapshot, ToolResult
from .h3_tools import compute_h3_metrics_from_scope_and_pois
from .nightlight_tools import compute_nightlight_overview_from_scope
from .poi_tools import fetch_pois_in_scope
from .population_tools import compute_population_overview_from_scope
from .result_tools import read_current_results
from .road_tools import compute_road_syntax_from_scope
from .scope_tools import read_current_scope

ToolAdapter = Callable[..., Awaitable[ToolResult]]
_DIMENSION_KEYS = ("poi", "h3", "population", "nightlight", "road")


async def _run_child_tool(
    *,
    runner: ToolAdapter,
    tool_name: str,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    try:
        return await runner(arguments=arguments, snapshot=snapshot, artifacts=artifacts, question=question)
    except Exception as exc:
        return ToolResult(
            tool_name=tool_name,
            status="failed",
            warnings=[str(exc)],
            error=exc.__class__.__name__,
        )


def _current_summary(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    artifact = artifacts.get(f"current_{key}_summary")
    if isinstance(artifact, dict):
        return dict(artifact)
    source = getattr(snapshot, key, {})
    if isinstance(source, dict) and isinstance(source.get("summary"), dict):
        return dict(source.get("summary") or {})
    return {}


def _current_poi_h3_summary(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    artifact = artifacts.get("current_poi_h3_summary")
    if isinstance(artifact, dict):
        return dict(artifact)
    source = snapshot.h3 if isinstance(snapshot.h3, dict) else {}
    if isinstance(source.get("summary"), dict):
        return dict(source.get("summary") or {})
    return {}


def _has_scope(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> bool:
    if artifacts.get("scope_polygon"):
        return True
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    return bool(scope.get("polygon") or scope.get("drawn_polygon") or scope.get("isochrone_feature"))


def _available_dimensions(snapshot: AnalysisSnapshot, local_artifacts: Dict[str, Any]) -> List[str]:
    available: List[str] = []
    for key in _DIMENSION_KEYS:
        if key == "poi":
            if bool(local_artifacts.get("current_pois") or snapshot.pois or (snapshot.poi_summary or {}).get("total")):
                available.append(key)
            continue
        if bool(_current_poi_h3_summary(snapshot, local_artifacts) if key == "h3" else _current_summary(snapshot, local_artifacts, key)):
            available.append(key)
    return available


def _missing_dimensions_from_results(read_results_payload: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    poi_count = read_results_payload.get("poi_count")
    if not isinstance(poi_count, int) or poi_count <= 0:
        missing.append("poi")
    if not bool(read_results_payload.get("has_h3_summary")):
        missing.append("h3")
    if not bool(read_results_payload.get("has_population_summary")):
        missing.append("population")
    if not bool(read_results_payload.get("has_nightlight_summary")):
        missing.append("nightlight")
    if not bool(read_results_payload.get("has_road_summary")):
        missing.append("road")
    return missing


def _has_frontend_panel(snapshot: AnalysisSnapshot, key: str) -> bool:
    frontend_analysis = snapshot.frontend_analysis if isinstance(snapshot.frontend_analysis, dict) else {}
    panel = frontend_analysis.get(key)
    return isinstance(panel, dict) and bool(panel)


async def ensure_area_data_readiness(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> Dict[str, Any]:
    auto_fetch = bool(arguments.get("auto_fetch", True))
    policy = resolve_policy(arguments.get("policy_key"), fallback="district_summary")
    local_artifacts = dict(artifacts or {})
    evidence: List[Dict[str, Any]] = []
    warnings: List[str] = []
    tool_statuses: List[Dict[str, Any]] = []

    if not _has_scope(snapshot, local_artifacts):
        return {
            "status": "failed",
            "error": "missing_scope_polygon",
            "warnings": ["缺少分析范围，无法执行数据就绪检查"],
            "evidence": [],
            "tool_statuses": [],
            "data_readiness": {"checked": False, "reused": [], "fetched": [], "ready": False},
            "bundle_result": {},
            "artifacts": dict(local_artifacts),
        }

    scope_result = await _run_child_tool(
        runner=read_current_scope,
        tool_name="read_current_scope",
        arguments={},
        snapshot=snapshot,
        artifacts=local_artifacts,
        question=question,
    )
    tool_statuses.append({"tool_name": "read_current_scope", "status": scope_result.status, "error": scope_result.error or ""})
    evidence.extend(scope_result.evidence or [])
    warnings.extend(scope_result.warnings or [])
    if scope_result.status == "success":
        local_artifacts.update(scope_result.artifacts or {})
    else:
        return {
            "status": "failed",
            "error": scope_result.error or "missing_scope_polygon",
            "warnings": warnings,
            "evidence": evidence,
            "tool_statuses": tool_statuses,
            "data_readiness": {"checked": False, "reused": [], "fetched": [], "ready": False},
            "bundle_result": {},
            "artifacts": dict(local_artifacts),
        }

    read_results_result = await _run_child_tool(
        runner=read_current_results,
        tool_name="read_current_results",
        arguments={},
        snapshot=snapshot,
        artifacts=local_artifacts,
        question=question,
    )
    tool_statuses.append({"tool_name": "read_current_results", "status": read_results_result.status, "error": read_results_result.error or ""})
    evidence.extend(read_results_result.evidence or [])
    warnings.extend(read_results_result.warnings or [])
    if read_results_result.status == "success":
        local_artifacts.update(read_results_result.artifacts or {})
    else:
        return {
            "status": "failed",
            "error": read_results_result.error or "read_results_failed",
            "warnings": warnings,
            "evidence": evidence,
            "tool_statuses": tool_statuses,
            "data_readiness": {"checked": False, "reused": [], "fetched": [], "ready": False},
            "bundle_result": {},
            "artifacts": dict(local_artifacts),
        }

    read_results_payload = dict(read_results_result.result or {})
    missing_dimensions = _missing_dimensions_from_results(read_results_payload)
    reused_dimensions = [key for key in _DIMENSION_KEYS if key not in missing_dimensions]
    fetched_dimensions: List[str] = []
    failed_dimensions: List[str] = []
    dimension_tool_names = {
        "poi": "fetch_pois_in_scope",
        "h3": "compute_h3_metrics_from_scope_and_pois",
        "population": "compute_population_overview_from_scope",
        "nightlight": "compute_nightlight_overview_from_scope",
        "road": "compute_road_syntax_from_scope",
    }
    if not auto_fetch:
        for dimension_key in _DIMENSION_KEYS:
            tool_statuses.append(
                {
                    "tool_name": dimension_tool_names[dimension_key],
                    "status": "skipped" if dimension_key in missing_dimensions else "reused",
                }
            )
        bundle_result = {
            "policy_key": policy["policy_key"],
            "policy_params": policy,
            "available_dimensions": _available_dimensions(snapshot, local_artifacts),
            "tool_statuses": tool_statuses,
        }
        data_readiness = {
            "checked": True,
            "reused": reused_dimensions,
            "fetched": [],
            "ready": not bool(missing_dimensions),
        }
        status = "success"
        error = ""
        artifacts_payload = {
            **local_artifacts,
            "current_area_data_bundle": {**bundle_result, "data_readiness": data_readiness},
            "current_data_readiness": data_readiness,
        }
        return {
            "status": status,
            "error": error,
            "warnings": warnings,
            "evidence": evidence,
            "tool_statuses": tool_statuses,
            "data_readiness": data_readiness,
            "bundle_result": {**bundle_result, "data_readiness": data_readiness},
            "artifacts": artifacts_payload,
        }

    dimension_tool_map: List[tuple[str, str, ToolAdapter, Dict[str, Any]]] = [
        ("poi", "fetch_pois_in_scope", fetch_pois_in_scope, {"source": str(arguments.get("source") or "local")}),
        (
            "h3",
            "compute_h3_metrics_from_scope_and_pois",
            compute_h3_metrics_from_scope_and_pois,
            {
                "resolution": int(arguments.get("resolution") or policy.get("h3_resolution") or 10),
                "include_mode": str(arguments.get("include_mode") or policy.get("include_mode") or "intersects"),
                "min_overlap_ratio": float(arguments.get("min_overlap_ratio") or policy.get("min_overlap_ratio") or 0.0),
                "neighbor_ring": int(arguments.get("neighbor_ring") or policy.get("neighbor_ring") or 1),
            },
        ),
        (
            "population",
            "compute_population_overview_from_scope",
            compute_population_overview_from_scope,
            {"coord_type": "gcj02"},
        ),
        (
            "nightlight",
            "compute_nightlight_overview_from_scope",
            compute_nightlight_overview_from_scope,
            {"coord_type": "gcj02", "year": arguments.get("year")},
        ),
        (
            "road",
            "compute_road_syntax_from_scope",
            compute_road_syntax_from_scope,
            {"mode": str(arguments.get("mode") or policy.get("mode") or "walking")},
        ),
    ]

    for dimension_key, tool_name, runner, child_arguments in dimension_tool_map:
        if dimension_key not in missing_dimensions:
            tool_statuses.append({"tool_name": tool_name, "status": "reused"})
            continue
        result = await _run_child_tool(
            runner=runner,
            tool_name=tool_name,
            arguments=child_arguments,
            snapshot=snapshot,
            artifacts=local_artifacts,
            question=question,
        )
        tool_statuses.append({"tool_name": tool_name, "status": result.status, "error": result.error or ""})
        evidence.extend(result.evidence or [])
        warnings.extend(result.warnings or [])
        if result.status == "success":
            local_artifacts.update(result.artifacts or {})
            fetched_dimensions.append(dimension_key)
        else:
            failed_dimensions.append(dimension_key)

    bundle_result = {
        "policy_key": policy["policy_key"],
        "policy_params": policy,
        "available_dimensions": _available_dimensions(snapshot, local_artifacts),
        "tool_statuses": tool_statuses,
    }
    data_readiness = {
        "checked": True,
        "reused": reused_dimensions,
        "fetched": fetched_dimensions,
        "ready": not bool(failed_dimensions),
    }
    status = "success" if data_readiness["ready"] else "failed"
    error = "" if status == "success" else "missing_required_dimensions"
    artifacts_payload = {
        **local_artifacts,
        "current_area_data_bundle": {**bundle_result, "data_readiness": data_readiness},
        "current_data_readiness": data_readiness,
    }
    return {
        "status": status,
        "error": error,
        "warnings": warnings,
        "evidence": evidence,
        "tool_statuses": tool_statuses,
        "data_readiness": data_readiness,
        "bundle_result": {**bundle_result, "data_readiness": data_readiness},
        "artifacts": artifacts_payload,
    }


async def get_area_data_bundle(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    readiness_payload = await ensure_area_data_readiness(
        arguments=arguments,
        snapshot=snapshot,
        artifacts=artifacts,
        question=question,
    )
    if readiness_payload["status"] == "failed":
        return ToolResult(
            tool_name="get_area_data_bundle",
            status="failed",
            result={"data_readiness": dict(readiness_payload.get("data_readiness") or {})},
            warnings=list(readiness_payload["warnings"] or []),
            error=str(readiness_payload["error"] or "area_data_bundle_failed"),
            artifacts=dict(readiness_payload["artifacts"] or {}),
        )
    return ToolResult(
        tool_name="get_area_data_bundle",
        status="success",
        result=dict(readiness_payload["bundle_result"] or {}),
        evidence=list(readiness_payload["evidence"] or []),
        warnings=list(readiness_payload["warnings"] or []),
        artifacts=dict(readiness_payload["artifacts"] or {}),
    )


async def analyze_poi_structure(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    poi_structure = build_poi_structure_analysis(snapshot, artifacts)
    business_profile = analyze_poi_mix(snapshot, artifacts, poi_structure=poi_structure)
    return ToolResult(
        tool_name="analyze_poi_structure",
        status="success",
        result={
            "structure_tags": list(poi_structure.get("structure_tags") or []),
            "dominant_categories": list(poi_structure.get("dominant_categories") or []),
            "business_profile": business_profile.get("business_profile"),
            "functional_mix_score": business_profile.get("functional_mix_score"),
            "summary_text": business_profile.get("summary_text") or poi_structure.get("summary_text") or "",
        },
        evidence=[
            {"field": "poi.structure.dominant_categories", "value": poi_structure.get("dominant_categories")},
            {"field": "poi.structure.business_profile", "value": business_profile.get("business_profile")},
        ],
        warnings=[] if poi_structure.get("evidence_ready") else [str(poi_structure.get("summary_text") or "POI 结构证据不足")],
        artifacts={
            "current_poi_structure_analysis": poi_structure,
            "current_business_profile": business_profile,
        },
    )


async def analyze_spatial_structure(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    h3_structure = build_h3_structure_analysis(snapshot, artifacts)
    population_profile = build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = build_road_pattern_analysis(snapshot, artifacts)
    return ToolResult(
        tool_name="analyze_spatial_structure",
        status="success",
        result={
            "distribution_pattern": h3_structure.get("distribution_pattern"),
            "population_view": population_profile.get("summary_text"),
            "nightlight_view": nightlight_pattern.get("summary_text"),
            "road_view": road_pattern.get("summary_text"),
            "summary_text": (
                f"H3: {h3_structure.get('distribution_pattern') or 'unknown'}; "
                "人口/夜光/路网证据已整理。"
            ),
        },
        evidence=[
            {"field": "h3.structure.distribution_pattern", "value": h3_structure.get("distribution_pattern")},
            {"field": "population.profile.top_age_band", "value": population_profile.get("top_age_band")},
            {"field": "nightlight.pattern.core_hotspot_count", "value": nightlight_pattern.get("core_hotspot_count")},
            {"field": "road.pattern.node_count", "value": road_pattern.get("node_count")},
        ],
        artifacts={
            "current_h3_structure_analysis": h3_structure,
            "current_population_profile_analysis": population_profile,
            "current_nightlight_pattern_analysis": nightlight_pattern,
            "current_road_pattern_analysis": road_pattern,
        },
    )


async def infer_area_labels(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    poi_structure = build_poi_structure_analysis(snapshot, artifacts)
    business_profile = analyze_poi_mix(snapshot, artifacts, poi_structure=poi_structure)
    population_profile = build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = build_road_pattern_analysis(snapshot, artifacts)
    payload = infer_area_character_labels(
        snapshot,
        artifacts,
        poi_structure=poi_structure,
        business_profile=business_profile,
        population_profile=population_profile,
        nightlight_pattern=nightlight_pattern,
        road_pattern=road_pattern,
    )
    return ToolResult(
        tool_name="infer_area_labels",
        status="success",
        result=payload,
        evidence=[
            {"field": "area.character_tags", "value": payload.get("character_tags")},
            {"field": "area.rule_hits", "value": payload.get("rule_hits")},
        ],
        artifacts={
            "current_poi_structure_analysis": poi_structure,
            "current_business_profile": business_profile,
            "current_population_profile_analysis": population_profile,
            "current_nightlight_pattern_analysis": nightlight_pattern,
            "current_road_pattern_analysis": road_pattern,
            "current_area_character_labels": payload,
        },
    )
