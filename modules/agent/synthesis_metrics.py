from __future__ import annotations

from typing import Dict

from .analysis_extractors import (
    is_business_profile_ready,
    is_commercial_hotspots_ready,
    is_h3_structure_ready,
    is_nightlight_pattern_ready,
    is_poi_structure_ready,
    is_population_profile_ready,
    is_road_pattern_ready,
    is_target_supply_gap_ready,
    project_nightlight_agent_facts,
)
from .schemas import AnalysisSnapshot


def build_summary_metrics(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> Dict[str, object]:
    business_site_advice = artifacts.get("business_site_advice") if isinstance(artifacts.get("business_site_advice"), dict) else {}
    poi_structure = artifacts.get("current_poi_structure_analysis") if isinstance(artifacts.get("current_poi_structure_analysis"), dict) else {}
    h3_structure = artifacts.get("current_h3_structure_analysis") if isinstance(artifacts.get("current_h3_structure_analysis"), dict) else {}
    road_pattern = artifacts.get("current_road_pattern_analysis") if isinstance(artifacts.get("current_road_pattern_analysis"), dict) else {}
    population_profile = artifacts.get("current_population_profile_analysis") if isinstance(artifacts.get("current_population_profile_analysis"), dict) else {}
    nightlight_pattern = (
        project_nightlight_agent_facts(artifacts.get("current_nightlight_pattern_analysis"))
        if isinstance(artifacts.get("current_nightlight_pattern_analysis"), dict)
        else {}
    )
    business_profile = artifacts.get("current_business_profile") if isinstance(artifacts.get("current_business_profile"), dict) else {}
    commercial_hotspots = artifacts.get("current_commercial_hotspots") if isinstance(artifacts.get("current_commercial_hotspots"), dict) else {}
    target_supply_gap = artifacts.get("current_target_supply_gap") if isinstance(artifacts.get("current_target_supply_gap"), dict) else {}
    h3_summary = artifacts.get("current_poi_h3_summary") or ((snapshot.h3 or {}).get("summary") if isinstance(snapshot.h3, dict) else {}) or {}
    road_summary = artifacts.get("current_road_summary") or ((snapshot.road or {}).get("summary") if isinstance(snapshot.road, dict) else {}) or {}
    population_summary = artifacts.get("current_population_summary") or ((snapshot.population or {}).get("summary") if isinstance(snapshot.population, dict) else {}) or {}
    nightlight_summary = artifacts.get("current_nightlight_summary") or ((snapshot.nightlight or {}).get("summary") if isinstance(snapshot.nightlight, dict) else {}) or {}
    poi_summary = artifacts.get("current_poi_summary") or snapshot.poi_summary or {}
    raw_poi_total = (poi_summary or {}).get("total")
    poi_count = int(raw_poi_total) if raw_poi_total is not None else None
    frontend_analysis = snapshot.frontend_analysis if isinstance(snapshot.frontend_analysis, dict) else {}
    poi_panel = frontend_analysis.get("poi") if isinstance(frontend_analysis.get("poi"), dict) else {}
    category_stats = poi_panel.get("category_stats") if isinstance(poi_panel.get("category_stats"), dict) else {}
    labels = [str(item) for item in (category_stats.get("labels") or []) if str(item).strip()]
    values = []
    for item in category_stats.get("values") or []:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            values.append(0.0)
    pairs = []
    total_category_value = sum(value for value in values if value > 0)
    for index, label in enumerate(labels):
        value = values[index] if index < len(values) else 0.0
        if value <= 0:
            continue
        ratio = (value / total_category_value) if total_category_value > 0 else 0.0
        pairs.append({"label": label, "count": int(value), "ratio": round(ratio, 4)})
    pairs.sort(key=lambda item: item["count"], reverse=True)
    return {
        "poi_count": poi_count,
        "h3_grid_count": int(h3_summary.get("grid_count") or 0),
        "avg_density_poi_per_km2": h3_summary.get("avg_density_poi_per_km2"),
        "road_node_count": int(road_summary.get("node_count") or 0),
        "road_edge_count": int(road_summary.get("edge_count") or 0),
        "population_total": population_summary.get("total_population"),
        "population_male_ratio": population_summary.get("male_ratio"),
        "population_female_ratio": population_summary.get("female_ratio"),
        "nightlight_total_radiance": nightlight_summary.get("total_radiance"),
        "nightlight_mean_radiance": nightlight_summary.get("mean_radiance"),
        "nightlight_peak_radiance": nightlight_summary.get("max_radiance"),
        "nightlight_lit_pixel_ratio": nightlight_summary.get("lit_pixel_ratio"),
        "business_place_type": business_site_advice.get("place_type"),
        "business_types": business_site_advice.get("types"),
        "business_keywords": business_site_advice.get("keywords"),
        "business_tool_statuses": business_site_advice.get("tool_statuses") or [],
        "poi_category_mix": pairs[:8],
        "poi_structure_summary": poi_structure.get("summary_text") if is_poi_structure_ready(poi_structure) else None,
        "poi_structure_tags": poi_structure.get("structure_tags") or [],
        "h3_distribution_pattern": h3_structure.get("distribution_pattern"),
        "h3_structure_summary": h3_structure.get("summary_text") if is_h3_structure_ready(h3_structure) else None,
        "road_pattern_summary": road_pattern.get("summary_text") if is_road_pattern_ready(road_pattern) else None,
        "population_profile_summary": population_profile.get("summary_text") if is_population_profile_ready(population_profile) else None,
        "nightlight_pattern_summary": (
            {
                key: nightlight_pattern.get(key)
                for key in (
                    "total_radiance", "mean_radiance", "p90_radiance", "peak_radiance",
                    "lit_pixel_ratio", "peak_to_edge_ratio", "sector_direction_analysis",
                )
                if nightlight_pattern.get(key) not in (None, {}, [])
            }
            if is_nightlight_pattern_ready(nightlight_pattern)
            else None
        ),
        "business_profile_label": (
            business_profile.get("poi_mix_signal") or business_profile.get("business_profile")
            if is_business_profile_ready(business_profile)
            else None
        ),
        "business_profile_portrait": None,
        "business_profile_summary": business_profile.get("summary_text") if is_business_profile_ready(business_profile) else None,
        "functional_mix_score": business_profile.get("functional_mix_score"),
        "commercial_hotspot_mode": commercial_hotspots.get("hotspot_mode") if is_commercial_hotspots_ready(commercial_hotspots) else None,
        "commercial_hotspot_summary": commercial_hotspots.get("summary_text") if is_commercial_hotspots_ready(commercial_hotspots) else None,
        "core_zone_count": commercial_hotspots.get("core_zone_count") if is_commercial_hotspots_ready(commercial_hotspots) else None,
        "opportunity_zone_count": commercial_hotspots.get("opportunity_zone_count") if is_commercial_hotspots_ready(commercial_hotspots) else None,
        "target_supply_gap_max_gap_value": target_supply_gap.get("max_gap_value") if is_target_supply_gap_ready(target_supply_gap) else None,
        "target_supply_gap_candidate_count": target_supply_gap.get("candidate_count") if is_target_supply_gap_ready(target_supply_gap) else 0,
        "target_supply_gap_place_type": target_supply_gap.get("place_type") if is_target_supply_gap_ready(target_supply_gap) else None,
        "target_supply_gap_candidates": target_supply_gap.get("candidate_zones") if is_target_supply_gap_ready(target_supply_gap) else [],
    }
