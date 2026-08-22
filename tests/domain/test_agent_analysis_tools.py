import asyncio

from modules.agent.analysis_extractors import (
    analyze_poi_mix,
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    detect_commercial_hotspots,
    project_nightlight_agent_facts,
)
from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tool_adapters.analysis_tools import (
    analyze_target_supply_gap_from_scope,
)


def _snapshot() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        poi_summary={"total": 120},
        h3={"summary": {"grid_count": 12, "avg_density_poi_per_km2": 18.6}},
        road={"summary": {"node_count": 3682, "edge_count": 4089}},
        population={"summary": {"total_population": 54326.544, "male_ratio": 0.49, "female_ratio": 0.51}},
        nightlight={"summary": {"total_radiance": 1316.555, "mean_radiance": 3.15, "max_radiance": 9.8, "lit_pixel_ratio": 1.0}},
        frontend_analysis={
            "poi": {
                "category_stats": {
                    "labels": ["餐饮", "购物", "科教文化", "住宿", "公司", "商务住宅"],
                    "values": [1000, 565, 333, 274, 159, 113],
                }
            },
            "h3": {
                "derived_stats": {
                    "structureSummary": {
                        "rows": [
                            {"h3_id": "a", "structure_signal": 2.1, "is_structure_signal": True, "density": 18.2, "poi_count": 60},
                            {"h3_id": "b", "structure_signal": 1.8, "is_structure_signal": True, "density": 16.5, "poi_count": 42},
                        ],
                        "giZStats": {"mean": 1.2},
                        "lisaIStats": {"mean": 0.6},
                    },
                    "typingSummary": {
                        "rows": [
                            {"h3_id": "a", "type_key": "high_mix", "is_opportunity": True, "density": 18.2},
                            {"h3_id": "b", "type_key": "high_mix", "is_opportunity": True, "density": 16.5},
                        ],
                        "opportunityCount": 2,
                        "recommendation": "优先排查高密-高混合且邻域为正的网格",
                    },
                    "gapSummary": {
                        "rows": [
                            {"h3_id": "a", "gap_zone_label": "高需求低供给", "gap_score": 0.42, "demand_pct": 0.85, "supply_pct": 0.43},
                            {"h3_id": "b", "gap_zone_label": "中需求偏低供给", "gap_score": 0.28, "demand_pct": 0.73, "supply_pct": 0.45},
                        ],
                        "opportunityCount": 2,
                        "recommendation": "咖啡优先关注高需求低供给",
                    },
                },
                "target_category": "coffee",
                "target_category_label": "咖啡",
            },
            "road": {
                "metric": "choice",
                "main_tab": "analysis",
                "regression": {"r2": 0.62},
            },
            "population": {
                "analysis_view": "age",
                "age_distribution": [
                    {"age_band": "20", "age_band_label": "20-24岁", "total": 8000},
                    {"age_band_label": "25-34岁", "total": 12000},
                    {"age_band_label": "35-44岁", "total": 9800},
                ],
                "layer_summary": {"top_dominant_age_band_label": "25-34岁", "dominant_cell_ratio": 0.37},
            },
            "nightlight": {
                "analysis_view": "hotspot",
                "analysis": {
                    "core_hotspot_count": 4,
                    "hotspot_cell_ratio": 0.33,
                    "peak_radiance": 9.8,
                    "max_distance_km": 1.8,
                    "peak_to_edge_ratio": 2.6,
                    "brightness_context_level": "medium_high",
                    "brightness_context_summary_text": "等时圈内夜光亮度背景呈现中等偏上水平，亮度高值主要集中在东北与东扇区。",
                    "sector_direction_analysis": {"dominant_direction": "东北", "secondary_direction": "东"},
                },
                "legend_note": "地图轮廓仅表示热点边界",
            },
        },
    )


def test_read_tools_extract_structured_analysis_from_snapshot():
    snapshot = _snapshot()

    poi = build_poi_structure_analysis(snapshot, {})
    h3 = build_h3_structure_analysis(snapshot, {})
    road = build_road_pattern_analysis(snapshot, {})
    population = build_population_profile_analysis(snapshot, {})
    nightlight = build_nightlight_pattern_analysis(snapshot, {})

    assert poi["dominant_categories"][0] == "餐饮"
    assert poi["evidence_ready"] is True
    assert h3["distribution_pattern"] in {"single_core", "multi_core", "corridor"}
    assert h3["evidence_ready"] is True
    assert road["regression_r2"] == 0.62
    assert road["evidence_ready"] is True
    assert population["top_age_band"] == "25-34岁"
    assert population["top_age_band_population"] == 12000
    assert population["top_age_band_ratio"] == round(12000 / 54326.544, 6)
    assert len(population["age_distribution_ratios"]) == 3
    assert population["age_distribution_ratios"][0]["age_band_label"] == "25-34岁"
    assert population["age_distribution_ratios"][0]["ratio"] == round(12000 / 54326.544, 6)
    assert population["evidence_ready"] is True
    assert nightlight["mean_radiance"] == 3.15
    assert nightlight["peak_radiance"] == 9.8
    assert nightlight["peak_to_edge_ratio"] == 2.6
    assert "core_hotspot_count" not in nightlight
    assert "brightness_context_level" not in nightlight
    assert "brightness_context_summary_text" not in nightlight
    assert "pattern_tags" not in nightlight
    assert nightlight["evidence_ready"] is True


def test_nightlight_agent_projection_removes_map_only_classes():
    projected = project_nightlight_agent_facts({
        "mean_radiance": 3.2,
        "p90_radiance": 8.1,
        "core_hotspot_count": 4,
        "hotspot_cell_ratio": 0.33,
        "brightness_context_level": "medium_high",
        "brightness_context_summary_text": "人工等级说明",
        "pattern_tags": ["nightlife_core"],
        "sector_direction_analysis": {
            "dominant_direction": "东北",
            "hotspot_count": 3,
            "sectors": [{
                "key": "ne",
                "label": "东北",
                "cell_count": 5,
                "mean_radiance": 4.1,
                "hotspot_count": 2,
            }],
        },
    })

    assert projected == {
        "mean_radiance": 3.2,
        "p90_radiance": 8.1,
        "sector_direction_analysis": {
            "dominant_direction": "东北",
            "sectors": [{
                "key": "ne",
                "label": "东北",
                "cell_count": 5,
                "mean_radiance": 4.1,
            }],
        },
    }


def test_explanation_tools_build_business_hotspot_and_gap_artifacts():
    snapshot = _snapshot()
    artifacts = {
        "current_poi_structure_analysis": build_poi_structure_analysis(snapshot, {}),
        "current_h3_structure_analysis": build_h3_structure_analysis(snapshot, {}),
        "current_poi_h3_grid": {
            "type": "FeatureCollection",
            "count": 2,
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[112.9800, 28.1900], [112.9810, 28.1900], [112.9810, 28.1910], [112.9800, 28.1910], [112.9800, 28.1900]]],
                    },
                    "properties": {"h3_id": "a"},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[112.9820, 28.1920], [112.9830, 28.1920], [112.9830, 28.1930], [112.9820, 28.1930], [112.9820, 28.1920]]],
                    },
                    "properties": {"h3_id": "b"},
                },
            ],
        },
        "current_pois": [
            {"lng": 112.9804, "lat": 28.1905, "name": "星巴克", "type": "poi", "lines": ["人民路"]},
            {"lng": 112.9824, "lat": 28.1925, "name": "万达广场", "type": "poi", "lines": ["黄兴路"]},
        ],
    }

    mix = analyze_poi_mix(
        snapshot,
        artifacts,
        poi_structure=artifacts["current_poi_structure_analysis"],
    )
    hotspots = detect_commercial_hotspots(
        snapshot,
        artifacts,
        h3_structure=artifacts["current_h3_structure_analysis"],
        poi_structure=artifacts["current_poi_structure_analysis"],
    )
    gap = asyncio.run(
        analyze_target_supply_gap_from_scope(
            arguments={"place_type": "咖啡厅"},
            snapshot=snapshot,
            artifacts=artifacts,
            question="这里适合开咖啡吗",
        )
    )

    assert mix["business_profile"] == "poi_mix_raw_signal"
    assert mix["functional_mix_score"] is not None
    assert hotspots["core_zone_count"] >= 1
    assert gap.result["place_type"] == "咖啡厅"
    assert gap.result["max_gap_value"] > 0
    assert "supply_gap_level" not in gap.result
    assert "gap_mode" not in gap.result
    assert len(gap.result["candidate_zones"]) >= 1
    assert gap.result["candidate_zones"][0]["approx_address"]


def test_read_tools_degrade_gracefully_when_frontend_analysis_missing():
    snapshot = AnalysisSnapshot()

    poi = build_poi_structure_analysis(snapshot, {})
    h3 = build_h3_structure_analysis(snapshot, {})
    population = build_population_profile_analysis(snapshot, {})

    assert poi["summary_text"]
    assert poi["data_status"] == "empty"
    assert poi["evidence_ready"] is False
    assert h3["distribution_pattern"] == "weak_signal"
    assert h3["data_status"] == "empty"
    assert h3["evidence_ready"] is False
    assert population["summary_text"]
    assert population["data_status"] == "empty"
    assert population["evidence_ready"] is False
