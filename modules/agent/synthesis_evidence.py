from __future__ import annotations

from typing import Any, Dict, List

from .schemas import AgentEvidenceItem, AnalysisSnapshot
from .synthesis_metrics import build_summary_metrics


def evidence_confidence(value: Any, *, source_available: bool = True) -> str:
    if value in (None, "", [], {}):
        return "weak"
    return "moderate" if source_available else "weak"


def build_analysis_evidence(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> List[AgentEvidenceItem]:
    metrics = build_summary_metrics(snapshot, artifacts)
    evidence: List[AgentEvidenceItem] = []

    if metrics["business_profile_label"]:
        evidence.append(
            AgentEvidenceItem(
                metric="business_profile",
                value={
                    "business_profile": metrics["business_profile_label"],
                    "portrait": metrics["business_profile_portrait"],
                    "functional_mix_score": metrics["functional_mix_score"],
                },
                interpretation="raw_signal: POI category mix and functional_mix_score are available.",
                source="current_business_profile / current_poi_structure_analysis",
                confidence="moderate",
                limitation="商业画像不能直接等同于客流、消费能力或经营收益，仍需结合实地与交易数据验证。",
            )
        )
    if metrics["commercial_hotspot_mode"]:
        evidence.append(
            AgentEvidenceItem(
                metric="commercial_hotspots",
                value={
                    "hotspot_mode": metrics["commercial_hotspot_mode"],
                    "core_zone_count": metrics["core_zone_count"],
                    "opportunity_zone_count": metrics["opportunity_zone_count"],
                },
                interpretation="raw_signal: hotspot_mode, core_zone_count and opportunity_zone_count are available.",
                source="current_commercial_hotspots / current_h3_structure_analysis",
                confidence="moderate",
                limitation="热点只说明空间集聚信号，不代表租金、品牌质量或真实到访强度。",
            )
        )
    if metrics["target_supply_gap_level"]:
        evidence.append(
            AgentEvidenceItem(
                metric="target_supply_gap",
                value={
                    "place_type": metrics["target_supply_gap_place_type"],
                    "supply_gap_level": metrics["target_supply_gap_level"],
                    "gap_mode": metrics["target_supply_gap_mode"],
                },
                interpretation="raw_signal: target supply gap level and gap_mode are available.",
                source="current_target_supply_gap / current_h3_structure_analysis",
                confidence="moderate",
                limitation="缺口指标不能直接推出开店可行性，仍需验证店面条件、竞品质量、租金与动线。",
            )
        )
    if metrics["business_place_type"]:
        evidence.append(
            AgentEvidenceItem(
                metric="business_site_advice",
                value={
                    "place_type": metrics["business_place_type"],
                    "types": metrics["business_types"],
                    "keywords": metrics["business_keywords"],
                },
                interpretation="目标业态参数说明本轮判断围绕哪些 POI 类型与关键词展开。",
                source="business_site_advice",
                confidence="moderate",
                limitation="业态参数只是分析口径，不代表真实经营品类已经完整覆盖。",
            )
        )
    if metrics["poi_count"] is not None:
        evidence.append(
            AgentEvidenceItem(
                metric="poi_count",
                value=metrics["poi_count"],
                interpretation="raw_signal: POI sample count is available.",
                source="analysis_snapshot.poi_summary / current_pois",
                confidence=evidence_confidence(metrics["poi_count"]),
                limitation="POI 数量不能直接等同于客流、消费力或经营收益。",
            )
        )
    if metrics["h3_grid_count"] or metrics["avg_density_poi_per_km2"] is not None:
        evidence.append(
            AgentEvidenceItem(
                metric="h3_density",
                value={
                    "grid_count": metrics["h3_grid_count"],
                    "avg_density_poi_per_km2": metrics["avg_density_poi_per_km2"],
                },
                interpretation="raw_signal: POI H3 grid count and density are available.",
                source="analysis_snapshot.h3.summary / current_poi_h3_summary",
                confidence=evidence_confidence(metrics["h3_grid_count"]),
                limitation="网格密度受边界、采样范围和 POI 完整度影响，不能单独作为选址结论。",
            )
        )
    if metrics["road_node_count"] or metrics["road_edge_count"]:
        evidence.append(
            AgentEvidenceItem(
                metric="road_structure",
                value={
                    "node_count": metrics["road_node_count"],
                    "edge_count": metrics["road_edge_count"],
                },
                interpretation="raw_signal: road node and edge counts are available.",
                source="analysis_snapshot.road.summary / current_road_summary",
                confidence=evidence_confidence(metrics["road_node_count"] or metrics["road_edge_count"]),
                limitation="路网结构不能替代实际步行环境、停车和公共交通条件。",
            )
        )
    if metrics["population_total"] is not None:
        evidence.append(
            AgentEvidenceItem(
                metric="population_profile",
                value={
                    "total_population": metrics["population_total"],
                    "male_ratio": metrics["population_male_ratio"],
                    "female_ratio": metrics["population_female_ratio"],
                },
                interpretation="raw_signal: population total and sex ratio fields are available.",
                source="analysis_snapshot.population.summary / current_population_summary",
                confidence=evidence_confidence(metrics["population_total"]),
                limitation="人口栅格是居住或活动 proxy，不能直接代表购买力、客群偏好或实时客流。",
            )
        )
    if metrics["nightlight_peak_radiance"] is not None or metrics["nightlight_mean_radiance"] is not None:
        evidence.append(
            AgentEvidenceItem(
                metric="nightlight_activity",
                value={
                    "total_radiance": metrics["nightlight_total_radiance"],
                    "mean_radiance": metrics["nightlight_mean_radiance"],
                    "peak_radiance": metrics["nightlight_peak_radiance"],
                    "lit_pixel_ratio": metrics["nightlight_lit_pixel_ratio"],
                },
                interpretation="raw_signal: nightlight total, mean, peak and lit-pixel fields are available.",
                source="analysis_snapshot.nightlight.summary / current_nightlight_summary",
                confidence=evidence_confidence(metrics["nightlight_peak_radiance"] or metrics["nightlight_mean_radiance"]),
                limitation="夜光是 proxy 指标，受道路照明、建筑亮灯和遥感噪声影响，不能直接代表消费热度。",
            )
        )
    return evidence
