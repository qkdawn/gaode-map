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
    score_site_candidates,
)
from ..policy_table import resolve_policy
from ..schemas import AnalysisSnapshot, ToolResult
from .analysis_tools import analyze_target_supply_gap_from_scope
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


def _next_option(rank: int, title: str, why: str, prompt: str, *, application: str, evidence: List[str]) -> Dict[str, Any]:
    return {
        "rank": rank,
        "title": title,
        "application": application,
        "why": why,
        "prompt": prompt,
        "evidence_basis": evidence,
    }


def build_next_analysis_options(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    local_artifacts = dict(artifacts or {})
    readiness = {
        "poi": bool(local_artifacts.get("current_pois") or snapshot.pois or (snapshot.poi_summary or {}).get("total")),
        "h3": bool(_current_poi_h3_summary(snapshot, local_artifacts)) or _has_frontend_panel(snapshot, "h3"),
        "population": bool(_current_summary(snapshot, local_artifacts, "population")) or _has_frontend_panel(snapshot, "population"),
        "nightlight": bool(_current_summary(snapshot, local_artifacts, "nightlight")) or _has_frontend_panel(snapshot, "nightlight"),
        "road": bool(_current_summary(snapshot, local_artifacts, "road")) or _has_frontend_panel(snapshot, "road"),
        "frontend_analysis": bool(snapshot.frontend_analysis),
    }
    ready_dimensions = [key for key, ready in readiness.items() if ready and key != "frontend_analysis"]
    missing_dimensions = [key for key, ready in readiness.items() if not ready and key != "frontend_analysis"]
    options: List[Dict[str, Any]] = []
    has_business_chain = all(readiness.get(key) for key in ("poi", "h3", "population", "nightlight", "road"))
    has_market_chain = readiness["poi"] and readiness["h3"]
    if has_business_chain:
        options.append(
            _next_option(
                len(options) + 1,
                "业态缺口与选址预筛",
                "商业链路证据已齐，下一步应从成熟热区里筛出高需求、低同质、好到达的补位缝隙，而不是继续证明哪里最热。",
                "选择一个目标业态，识别供给缺口、机会格和候选点位，并剔除只在热力图上好看的伪机会。",
                application="商业选址 / 招商补位",
                evidence=["poi", "h3", "population", "nightlight", "road"],
            )
        )
    if has_market_chain:
        options.append(
            _next_option(
                len(options) + 1,
                "细分业态与竞品结构",
                "POI 与 H3 已能支撑微商圈拆分，下一步应区分学生高频、社区刚需、文创停留和夜间社交等不同消费场景。",
                "选择目标业态，生成细分 POI、H3 密度和空间缺口，并判断竞品饱和度与消费场景是否匹配。",
                application="竞品调查 / 业态定位",
                evidence=["poi", "h3"],
            )
        )
    if readiness["road"] and (readiness["h3"] or readiness["poi"]):
        options.append(
            _next_option(
                len(options) + 1,
                "可达性真实性校验",
                "热点和道路证据已能对照，下一步要识别人很多、店很多但不好到达、难识别、难转化的位置风险。",
                "叠加热点、候选格、路网集成度/选择度与主路支路关系，剔除实际导流能力弱的位置。",
                application="交通可达 / 点位风险",
                evidence=["road", "h3" if readiness["h3"] else "poi"],
            )
        )
    if readiness["nightlight"] and readiness["poi"]:
        options.append(
            _next_option(
                len(options) + 1,
                "夜间活力与业态匹配",
                "夜光与 POI 已能对照，但夜光强不等于消费强，下一步要判断亮度来源和业态承接是否重叠。",
                "对比夜光热点与 POI 分布，区分餐饮、社区照明、道路照明、校园活动和文化休闲带动。",
                application="夜经济 / 运营时段",
                evidence=["nightlight", "poi"],
            )
        )
    if readiness["population"] and readiness["poi"]:
        options.append(
            _next_option(
                len(options) + 1,
                "客群与服务供给匹配",
                "人口与 POI 已能对照，下一步要判断供给是否服务真实日常人群，而不是只服务地图上的热度。",
                "对照人口结构、居住基底和 POI 供给，拆分社区复购、学生高频和外来到访需求。",
                application="客群画像 / 社区服务",
                evidence=["population", "poi"],
            )
        )
    if not options:
        options.append(
            _next_option(
                1,
                "先补齐基础证据链",
                f"missing_dimensions={','.join(missing_dimensions) or '-'}",
                "补齐缺失的基础结果后再生成下一步分析 raw metrics",
                application="数据就绪 / 分析准备",
                evidence=ready_dimensions,
            )
        )
    return {
        "readiness": readiness,
        "ready_dimensions": ready_dimensions,
        "missing_dimensions": missing_dimensions,
        "recommended_options": options[:5],
        "summary_text": f"已基于当前证据就绪状态生成 {min(len(options), 5)} 个下一步分析方向。",
    }


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


async def rank_next_analysis_options(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    payload = build_next_analysis_options(snapshot, artifacts)
    return ToolResult(
        tool_name="rank_next_analysis_options",
        status="success",
        result=payload,
        evidence=[
            {"field": "next_analysis.ready_dimensions", "value": payload.get("ready_dimensions")},
            {"field": "next_analysis.recommended_options", "value": payload.get("recommended_options")},
        ],
        artifacts={"current_next_analysis_options": payload},
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


async def score_site_candidates_tool(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    target_supply_gap = await analyze_target_supply_gap_from_scope(
        arguments={"place_type": str(arguments.get("place_type") or "")},
        snapshot=snapshot,
        artifacts=artifacts,
        question=question,
    )
    population_profile = build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = build_road_pattern_analysis(snapshot, artifacts)
    payload = score_site_candidates(
        snapshot,
        artifacts,
        target_supply_gap=target_supply_gap.result,
        population_profile=population_profile,
        nightlight_pattern=nightlight_pattern,
        road_pattern=road_pattern,
    )
    return ToolResult(
        tool_name="score_site_candidates",
        status="success",
        result=payload,
        evidence=[
            {"field": "site.ranking", "value": payload.get("ranking")},
            {"field": "site.confidence", "value": payload.get("confidence")},
        ],
        warnings=list(target_supply_gap.warnings or []),
        artifacts={
            "current_target_supply_gap": target_supply_gap.result,
            "current_site_candidate_scores": payload,
        },
    )
