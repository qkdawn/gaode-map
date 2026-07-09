from __future__ import annotations

from typing import Any, Dict, List

from modules.providers.amap.utils.get_type_info import infer_type_info_from_text

from .analysis_extractors import (
    is_business_profile_ready,
    is_commercial_hotspots_ready,
    is_h3_structure_ready,
    is_nightlight_pattern_ready,
    is_poi_structure_ready,
    is_population_profile_ready,
    is_road_pattern_ready,
    is_target_supply_gap_ready,
)
from .intent_signals import mentions_nightlight, mentions_population, mentions_road, mentions_summary, mentions_supply
from .schemas import AnalysisSnapshot, AuditResult, ContextBundle, WorkingMemory


def _current_summary(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    artifact_key = f"current_{key}_summary"
    if isinstance(artifacts.get(artifact_key), dict):
        return dict(artifacts.get(artifact_key) or {})
    source = getattr(snapshot, key, {})
    if isinstance(source, dict) and isinstance(source.get("summary"), dict):
        return dict(source.get("summary") or {})
    return {}


def _current_poi_h3_summary(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(artifacts.get("current_poi_h3_summary"), dict):
        return dict(artifacts.get("current_poi_h3_summary") or {})
    source = snapshot.h3 if isinstance(snapshot.h3, dict) else {}
    if isinstance(source.get("summary"), dict):
        return dict(source.get("summary") or {})
    return {}


def _has_pois(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> bool:
    return bool(artifacts.get("current_pois") or snapshot.pois or (snapshot.poi_summary or {}).get("total"))


def _current_analysis(artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = artifacts.get(key)
    return dict(value or {}) if isinstance(value, dict) else {}


def _has_target_poi_evidence(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], question: str) -> bool:
    target = infer_type_info_from_text(question)
    if not target:
        return _has_pois(snapshot, artifacts)
    summary = artifacts.get("current_poi_summary") if isinstance(artifacts.get("current_poi_summary"), dict) else snapshot.poi_summary
    if not _has_pois(snapshot, artifacts):
        return False
    if not isinstance(summary, dict):
        return False
    summary_types = set(part for part in str(summary.get("types") or "").split("|") if part)
    target_types = set(part for part in str(target.get("types") or "").split("|") if part)
    if summary_types and target_types and summary_types.intersection(target_types):
        return True
    summary_keywords = str(summary.get("keywords") or "")
    target_keywords = str(target.get("keywords") or "")
    target_label = str(target.get("label") or "")
    return bool(summary_keywords and (summary_keywords == target_keywords or target_label in summary_keywords))


def _has_h3_density(summary: Dict[str, Any]) -> bool:
    return bool(summary) and (summary.get("grid_count") is not None or summary.get("avg_density_poi_per_km2") is not None)


def _has_road_evidence(summary: Dict[str, Any]) -> bool:
    return bool(summary) and (summary.get("node_count") is not None or summary.get("edge_count") is not None)


def _has_population_evidence(summary: Dict[str, Any]) -> bool:
    return bool(summary) and summary.get("total_population") is not None


def _has_nightlight_evidence(summary: Dict[str, Any]) -> bool:
    return bool(summary) and (summary.get("max_radiance") is not None or summary.get("mean_radiance") is not None)


def _has_poi_structure_evidence(analysis: Dict[str, Any]) -> bool:
    return is_poi_structure_ready(analysis)


def _has_h3_structure_evidence(analysis: Dict[str, Any]) -> bool:
    return is_h3_structure_ready(analysis)


def _has_target_candidate_evidence(analysis: Dict[str, Any]) -> bool:
    return bool((analysis or {}).get("candidate_zones"))


def _has_population_profile_evidence(analysis: Dict[str, Any]) -> bool:
    return is_population_profile_ready(analysis)


def _has_nightlight_pattern_evidence(analysis: Dict[str, Any]) -> bool:
    return is_nightlight_pattern_ready(analysis)


def _has_road_pattern_evidence(analysis: Dict[str, Any]) -> bool:
    return is_road_pattern_ready(analysis)


def _is_hotspot_question(question: str) -> bool:
    return any(token in question for token in ("核心", "热点", "集中", "分布", "偏空", "空白", "多核", "单核"))


def _append_unique(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def audit_execution(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    memory: WorkingMemory,
) -> AuditResult:
    artifacts = memory.artifacts
    h3_summary = _current_poi_h3_summary(snapshot, artifacts)
    road_summary = _current_summary(snapshot, artifacts, "road")
    population_summary = _current_summary(snapshot, artifacts, "population")
    nightlight_summary = _current_summary(snapshot, artifacts, "nightlight")
    poi_structure = _current_analysis(artifacts, "current_poi_structure_analysis")
    h3_structure = _current_analysis(artifacts, "current_h3_structure_analysis")
    road_pattern = _current_analysis(artifacts, "current_road_pattern_analysis")
    population_profile = _current_analysis(artifacts, "current_population_profile_analysis")
    nightlight_pattern = _current_analysis(artifacts, "current_nightlight_pattern_analysis")
    business_profile = _current_analysis(artifacts, "current_business_profile")
    commercial_hotspots = _current_analysis(artifacts, "current_commercial_hotspots")
    target_supply_gap = _current_analysis(artifacts, "current_target_supply_gap")
    business_site_advice = _current_analysis(artifacts, "business_site_advice")
    issues: List[str] = []
    missing_evidence: List[str] = []
    required_evidence: List[str] = []
    needs_comprehensive_business_evidence = mentions_summary(question) or mentions_supply(question)
    needs_business_site_advice = mentions_supply(question) and bool(infer_type_info_from_text(question))
    needs_hotspot_analysis = _is_hotspot_question(question) and not mentions_road(question) and not mentions_population(question)
    needs_next_analysis = any(token in question for token in ("下一步", "继续", "还可以", "做什么分析", "还能分析"))

    has_h3_view = _has_h3_density(h3_summary) or _has_h3_structure_evidence(h3_structure)
    has_population_view = _has_population_evidence(population_summary) or _has_population_profile_evidence(population_profile)
    has_nightlight_view = _has_nightlight_evidence(nightlight_summary) or _has_nightlight_pattern_evidence(nightlight_pattern)
    has_road_view = _has_road_evidence(road_summary) or _has_road_pattern_evidence(road_pattern)
    has_poi_view = _has_pois(snapshot, artifacts) or _has_poi_structure_evidence(poi_structure)

    if needs_comprehensive_business_evidence:
        _append_unique(required_evidence, "POI 供给证据")
        has_poi_evidence = _has_target_poi_evidence(snapshot, artifacts, question) if needs_business_site_advice else has_poi_view
        if not has_poi_evidence:
            _append_unique(missing_evidence, "POI 供给证据")
        _append_unique(required_evidence, "POI H3 密度证据")
        if not has_h3_view:
            _append_unique(missing_evidence, "POI H3 密度证据")
        if mentions_summary(question):
            _append_unique(required_evidence, "商业画像分析")
            if not is_business_profile_ready(business_profile):
                _append_unique(missing_evidence, "商业画像分析")

    if needs_comprehensive_business_evidence or mentions_population(question):
        _append_unique(required_evidence, "人口概览")
    if (needs_comprehensive_business_evidence or mentions_population(question)) and not has_population_view:
        _append_unique(missing_evidence, "人口概览")
    if needs_comprehensive_business_evidence or mentions_nightlight(question):
        _append_unique(required_evidence, "夜光概览")
    if (needs_comprehensive_business_evidence or mentions_nightlight(question)) and not has_nightlight_view:
        _append_unique(missing_evidence, "夜光概览")
    if needs_comprehensive_business_evidence or mentions_road(question):
        _append_unique(required_evidence, "路网概览")
    if (needs_comprehensive_business_evidence or mentions_road(question)) and not has_road_view:
        _append_unique(missing_evidence, "路网概览")
    if needs_hotspot_analysis:
        _append_unique(required_evidence, "空间热点分析")
        if not is_commercial_hotspots_ready(commercial_hotspots):
            _append_unique(missing_evidence, "空间热点分析")
    if mentions_supply(question) and bool(infer_type_info_from_text(question)):
        _append_unique(required_evidence, "目标业态补位分析")
        if not is_target_supply_gap_ready(target_supply_gap) and not business_site_advice:
            _append_unique(missing_evidence, "目标业态补位分析")
        _append_unique(required_evidence, "候选格子列表")
        if not _has_target_candidate_evidence(target_supply_gap):
            _append_unique(missing_evidence, "候选格子列表")
    if needs_next_analysis:
        if not any([has_poi_view, has_h3_view, has_population_view, has_nightlight_view, has_road_view]):
            _append_unique(missing_evidence, "可用于判断下一步的分析证据")

    if mentions_population(question) and not has_population_view:
        issues.append("人口相关结论缺少 total_population 证据。")
    if mentions_nightlight(question) and not has_nightlight_view:
        issues.append("夜间活力相关结论缺少夜光峰值证据。")
    if mentions_supply(question) and (
        "POI 供给证据" in missing_evidence
        or "POI H3 密度证据" in missing_evidence
        or "目标业态补位分析" in missing_evidence
        or "候选格子列表" in missing_evidence
    ):
        issues.append("当前缺少供给或空间密度证据，暂不能形成具体补位/选址判断。")
    if mentions_summary(question) and missing_evidence:
        issues.append(f"区域总结仍有证据缺口：{'、'.join(missing_evidence)}。")
    if needs_next_analysis and "可用于判断下一步的分析证据" in missing_evidence:
        issues.append("当前缺少可用于排序下一步动作的范围分析证据。")
    if any(token in question for token in ("客流", "消费", "收益", "营业额")):
        issues.append("当前 Agent 不应直接从 GIS 指标推断客流、消费能力或经营收益。")
    for limit in context.limits:
        if "不能直接从 GIS 指标推断客流" in limit and any(token in question for token in ("客流", "消费", "收益", "营业额")):
            issues.append(limit)
            break

    return AuditResult(
        passed=not missing_evidence,
        issues=issues,
        missing_evidence=missing_evidence,
        required_evidence=required_evidence,
    )
