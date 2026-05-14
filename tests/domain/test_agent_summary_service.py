import asyncio
from types import SimpleNamespace

from modules.agent.schemas import AgentSummaryRequest, AnalysisSnapshot
from modules.agent.schemas import AgentIterationPoiBuildResponse
from modules.agent.iteration_change_service import (
    build_poi_iteration_evidence_pack_v1,
    build_poi_iteration_llm_evidence,
    generate_nightlight_iteration_analysis,
    generate_poi_iteration_analysis,
)
from modules.agent.prompt_registry import get_prompt_config
from modules.agent.poi_iteration_build_service import build_agent_poi_iteration_payload, summarize_iteration_pois
from modules.agent.summary_service import (
    _build_tourism_cross_analysis_payload,
    _build_summary_llm_payload,
    _normalize_area_judgment_reasoning,
    _validate_summary_pack_payload,
    _validate_tourism_cross_analysis_payload,
    evaluate_summary_readiness,
    generate_summary_pack,
    stream_generate_summary_pack,
)
from modules.spatial_factor_engine import build_subcategory_spatial_trends


def _ready_payload():
    return {
        "data_readiness": {
            "checked": True,
            "ready": True,
            "missing_tasks": [],
            "reused": ["poi", "h3", "population", "nightlight", "road"],
            "fetched": [],
        },
        "artifacts": {},
        "warnings": [],
        "error": "",
    }


def _structured_artifacts():
    return {
        "current_poi_structure_analysis": {
            "summary_text": "餐饮与购物供给占主导。",
            "dominant_categories": ["餐饮", "购物"],
            "structure_tags": ["餐饮主导", "生活消费主导"],
        },
        "current_h3_structure_analysis": {
            "distribution_pattern": "multi_core",
            "summary_text": "空间热点呈多核分布。",
        },
        "current_population_profile_analysis": {
            "summary_text": "常住人口基础稳定。",
            "total_population": 3200,
            "top_age_band": "25-44岁",
        },
        "current_nightlight_pattern_analysis": {
            "summary_text": "夜间活跃度中等偏弱。",
            "total_radiance": 120.0,
            "economic_activity_intensity_level": "medium_high",
            "economic_activity_summary_text": "基于夜间灯光亮度，等时圈内经济活动强度呈现中等偏上水平，亮度高值主要集中在东北与东扇区。",
            "sector_direction_analysis": {
                "dominant_direction": "东北",
                "secondary_direction": "东",
            },
            "core_hotspot_count": 0,
        },
        "current_road_pattern_analysis": {
            "summary_text": "路网较密但聚集效应一般。",
            "node_count": 90,
            "edge_count": 124,
            "regression_r2": 0.12,
            "road_orientation_analysis": {
                "dominant_orientation": "东西向",
                "secondary_orientation": "东北-西南向",
            },
        },
        "current_business_profile": {
            "business_profile": "生活消费主导",
            "portrait": "更像社区型生活消费商业区。",
            "summary_text": "以餐饮和日常消费为主。",
            "business_types": ["餐饮主导", "购物配套较强"],
        },
        "current_area_character_labels": {
            "character_tags": ["社区消费", "餐饮配套"],
        },
        "current_commercial_hotspots": {
            "hotspot_mode": "multi_core",
            "summary_text": "核心较分散，跨区吸引力有限。",
            "core_zone_count": 2,
            "opportunity_zone_count": 3,
        },
    }


def test_tourism_cross_analysis_payload_includes_shared_grid_evidence():
    snapshot = AnalysisSnapshot(
        poi_summary={"total": 3},
        h3={
            "poi_h3_evidence": {
                "evidence_version": "poi_h3_evidence_v1",
                "grid_type": "h3",
                "params": {"h3_resolution": 9, "neighbor_ring": 2},
                "counts": {"grid_count": 5, "poi_count": 3},
                "metrics": {"avg_local_entropy": 0.4},
            }
        },
        population={
            "summary": {"total_population": 100},
            "grid_evidence": {
                "evidence_level": "cell_id_population_and_sex",
                "counts": {"population_cells": 2, "sex_cells": 2},
                "top_abs_sex_diff_cells": [
                    {
                        "cell_id": "r0_c0",
                        "male_value": 55,
                        "female_value": 45,
                        "sex_diff_value": 10,
                    }
                ],
            },
        },
        nightlight={"summary": {"mean_radiance": 8}},
        shared_grid={
            "evidence_version": "shared_grid_evidence_v1",
            "grid_type": "population_nightlight_shared_cell_id",
            "join_key": "cell_id",
            "uses": ["population", "poi_raster", "nightlight"],
            "evidence_level": "cell_id_overlap",
            "counts": {
                "population_cells": 2,
                "poi_cells": 2,
                "nightlight_cells": 2,
                "complete_overlap_cells": 2,
            },
            "top_coupled_cells": [
                {
                    "cell_id": "r0_c0",
                    "population_value": 80,
                    "male_value": 55,
                    "female_value": 45,
                    "sex_diff_value": 10,
                    "poi_count": 5,
                    "nightlight_radiance": 12,
                    "composite_score": 0.9,
                    "coupling_type": "high_pop_high_poi_high_light",
                    "planning_meaning": "人口、业态供给与夜间活力重合，适合作为优先策划节点。",
                }
            ],
        },
    )
    source_payload = _build_summary_llm_payload(snapshot, _structured_artifacts())
    payload = _build_tourism_cross_analysis_payload(source_payload, _valid_summary_pack())

    shared_grid = payload["spatial_evidence"]["shared_grid"]
    assert shared_grid["evidence_version"] == "shared_grid_evidence_v1"
    assert shared_grid["evidence_level"] == "cell_id_overlap"
    assert shared_grid["counts"]["complete_overlap_cells"] == 2
    assert shared_grid["top_coupled_cells"][0]["cell_id"] == "r0_c0"
    assert shared_grid["top_coupled_cells"][0]["sex_diff_value"] == 10
    assert "top_overlap_cells" not in shared_grid
    assert "grid" not in payload["population_evidence"]
    assert "grid" not in payload["poi_evidence"]
    assert payload["poi_evidence"]["h3_evidence"]["evidence_version"] == "poi_h3_evidence_v1"
    assert payload["poi_evidence"]["h3_evidence"]["params"]["h3_resolution"] == 9
    assert payload["spatial_evidence"]["poi_h3_evidence"]["counts"]["grid_count"] == 5
    assert "param_bundle" not in payload["poi_evidence"]
    assert "param_bundle" not in payload["nightlight_evidence"]
    assert "param_bundles" not in payload["spatial_evidence"]


def _valid_summary_pack():
    return {
        "headline_judgment": {
            "summary": "社区型生活消费商业区，以餐饮和日常消费为核心。",
            "supporting_clause": "缺少中心型商业吸引力。",
        },
        "icsc_tags": ["餐饮主导", "购物配套较强"],
        "secondary_conclusions": [
            {
                "section_key": "spatial_structure",
                "title": "空间结构",
                "reasoning": "整体呈多核分布，但核心之间联系较弱。",
                "dimensions": [
                    {"key": "aggregation", "label": "聚集性", "conclusion": "热点形成，但集中度有限。"},
                    {"key": "mixing", "label": "混合性", "conclusion": "功能混合度中等。"},
                    {"key": "morphology", "label": "形态性", "conclusion": "整体偏分散。"},
                ],
            },
            {
                "section_key": "poi_structure",
                "title": "POI结构",
                "reasoning": "业态以生活消费和餐饮为主。",
            },
            {
                "section_key": "consumption_vitality",
                "title": "经济活动强度",
                "reasoning": "夜间经济活动强度偏弱，暂不能据此判断全天候经济活动表现。",
            },
            {
                "section_key": "business_support",
                "title": "业态承接",
                "reasoning": "路网可以承接社区级消费，但难支撑更高能级集聚。",
            },
        ],
        "user_profile": {
            "headline": "本地居民为主的稳定消费人群",
            "traits": ["以周边社区居民为主", "高频低客单消费", "以便利和就近为核心决策"],
        },
        "behavior_inference": {
            "headline": "消费行为以日常补给型为主",
            "traits": ["高频餐饮和小额消费", "跨区域吸引力有限", "夜间活跃度偏弱"],
        },
        "evidence_refs": ["analysis_snapshot.poi_summary", "analysis_snapshot.h3.summary"],
        "confidence": "moderate",
    }


def test_generate_nightlight_iteration_analysis_returns_llm_unavailable(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: False)

    result = asyncio.run(generate_nightlight_iteration_analysis({"years": [2023, 2024, 2025]}))

    assert result["status"] == "failed"
    assert result["error"] == "llm_unavailable"
    config = get_prompt_config("nightlight_iteration")
    assert result["prompt_snapshot"]["system_prompt"] == config.system_prompt
    assert result["prompt_snapshots"]["nightlight_iteration"]["system_prompt"] == config.system_prompt


def test_tourism_cross_analysis_prompt_uses_full_planning_constraints():
    config = get_prompt_config("tourism_cross_analysis")

    assert "人口数据回答" in config.system_prompt
    assert "人口密度 × POI供给" in config.system_prompt
    assert "POI业态 × 夜间灯光" in config.system_prompt
    assert "不得凭空编造政策、道路、商圈、地铁" in config.system_prompt
    assert "当前证据只能支持趋势判断，不能直接证明真实消费规模" in config.system_prompt
    assert "该地块适合以____为核心客群" in config.system_prompt


def test_validate_tourism_cross_analysis_requires_report_sections():
    valid = _validate_tourism_cross_analysis_payload({
        "title": "文旅交叉策划分析",
        "content": "一、综合判断\n成立。\n五、人口 × POI × 夜光交叉诊断\n匹配。\n九、策划结论\n该地块适合以本地客群为核心客群。",
    })
    variant = _validate_tourism_cross_analysis_payload({
        "title": "文旅交叉策划分析",
        "content": "一、综合判断\n成立。\n五、人口xPOIx夜光交叉诊断\n匹配。\n九、策划结论\n该地块适合以本地客群为核心客群。",
    })
    natural_variant = _validate_tourism_cross_analysis_payload({
        "title": "文旅交叉策划分析",
        "content": "一、综合判断\n成立。\n五、人口、POI与夜光交叉诊断\n三类信号基本匹配。\n九、策划结论\n该地块适合以本地客群为核心客群。",
    })
    invalid = _validate_tourism_cross_analysis_payload({
        "title": "文旅交叉策划分析",
        "content": "一、综合判断\n成立。",
    })

    assert valid["title"] == "文旅交叉策划分析"
    assert variant["content"]
    assert natural_variant["content"]
    assert invalid == {}


def test_generate_nightlight_iteration_analysis_validates_llm_payload(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        config = get_prompt_config("nightlight_iteration")
        assert kwargs["system_prompt"] == config.system_prompt
        assert kwargs["user_payload"]["task"] == "nightlight_iteration_change"
        assert kwargs["user_payload"]["evidence"]["period"] == "2023-2025"
        return {
            "headline": "热点增强",
            "trend_summary": "总辐亮连续上升",
            "hotspot_migration": "新增热点多于衰退热点",
            "risk_or_opportunity": "夜间消费机会增强",
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_nightlight_iteration_analysis({"period": "2023-2025"}))

    assert result["status"] == "ready"
    config = get_prompt_config("nightlight_iteration")
    assert result["prompt_snapshot"]["system_prompt"] == config.system_prompt
    assert result["prompt_snapshots"]["nightlight_iteration"]["system_prompt"] == config.system_prompt
    assert result["ai_analysis"]["headline"] == "热点增强"


def test_generate_poi_iteration_analysis_validates_llm_payload(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        config = get_prompt_config("poi_iteration")
        assert kwargs["system_prompt"] == config.system_prompt
        assert kwargs["user_payload"]["task"] == "poi_iteration_change"
        assert kwargs["user_payload"]["evidence"]["years"] == [2023, 2024, 2025]
        assert kwargs["user_payload"]["evidence"]["evidence_version"] == "poi_iteration_v1"
        assert kwargs["user_payload"]["evidence"]["spatial_factors"]["geometry_mode"] == "point"
        assert kwargs["user_payload"]["evidence"]["subcategory_spatial_trends"][0]["name"]
        assert kwargs["user_payload"]["evidence"]["growth_area_signal"]["growth_rows"][0]["name"] == "咖啡厅"
        return {
            "summary_points": ["POI规模中等", "餐饮为主导业态", "岳麓区为核心区域"],
            "fastest_growth": "咖啡 +120%",
            "declining_category": "传统零售 -35%",
            "emerging_area": "咖啡厅新增偏东北、中圈层补点",
            "structure_judgement": "业态结构偏消费型",
            "driver_analysis": [
                {"driver": "餐饮补充型增长", "evidence": "咖啡厅增加", "confidence": "中", "explanation": "小类增量支撑日常消费。"}
            ],
            "planning_implications": [
                {"implication": "强化日常消费底盘", "evidence": "餐饮主导", "suggested_direction": "轻餐饮与社交消费。"}
            ],
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({
        "years": [2023, 2024, 2025],
        "summaries": [
            {
                "year": 2023,
                "subcategory_counts": {"咖啡厅": 1},
                "top_subcategories": [{"name": "咖啡厅", "parent": "餐饮"}],
                "points": [{"lng": 112.0, "lat": 28.0, "subcategory": "咖啡厅", "category": "餐饮", "area": "一区"}],
            },
            {
                "year": 2025,
                "subcategory_counts": {"咖啡厅": 2},
                "top_subcategories": [{"name": "咖啡厅", "parent": "餐饮"}],
                "points": [
                    {"lng": 112.02, "lat": 28.02, "subcategory": "咖啡厅", "category": "餐饮", "area": "二区"},
                    {"lng": 112.021, "lat": 28.021, "subcategory": "咖啡厅", "category": "餐饮", "area": "二区"},
                ],
            },
        ],
    }))

    assert result["status"] == "ready"
    assert result["spatial_factors"]["geometry_mode"] == "point"
    assert result["subcategory_spatial_trend_rows"]
    assert result["ai_summary"][0] == "POI规模中等"
    assert result["ai_insights"]["emerging_area"]["interpretation"]
    assert "poi_iteration_v1" in result["ai_prompt"]
    assert "growth_area_signal" in result["ai_prompt"]
    assert "User payload" in result["ai_prompt_payload_note"]
    config = get_prompt_config("poi_iteration")
    assert result["prompt_snapshot"]["system_prompt"] == config.system_prompt
    assert result["prompt_snapshots"]["poi_iteration"]["system_prompt"] == config.system_prompt
    assert result["validation_results"]["poi_iteration"]["source"] == "backend"
    assert result["validation_results"]["poi_iteration"]["validated_output"]["summary_points"][0] == "POI规模中等"


def test_generate_poi_iteration_analysis_sends_compact_llm_evidence(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs["user_payload"]["evidence"])
        return {
            "summary_points": ["POI规模下降", "餐饮仍为主导"],
            "fastest_growth": "餐饮增长较快",
            "declining_category": "购物减少",
            "emerging_area": "咖啡厅新增偏东北、中圈层补点",
            "structure_judgement": "生活消费主导",
            "driver_analysis": [
                {"driver": "餐饮配套增强", "evidence": "餐饮增长较快", "confidence": "中", "explanation": "餐饮增长解释生活消费底盘增强。"}
            ],
            "planning_implications": [
                {"implication": "强化餐饮承接", "evidence": "餐饮仍为主导", "suggested_direction": "餐饮与日常服务。"}
            ],
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)
    points = [
        {"lng": 112.0 + idx * 0.001, "lat": 28.0 + idx * 0.001, "subcategory": "咖啡厅", "category": "餐饮", "area": "一区"}
        for idx in range(40)
    ]

    result = asyncio.run(generate_poi_iteration_analysis({
        "years": [2020, 2022, 2024],
        "summaries": [
            {"year": 2020, "count": 20, "subcategory_counts": {"咖啡厅": 20}, "top_subcategories": [{"name": "咖啡厅", "parent": "餐饮"}], "points": points[:20]},
            {"year": 2024, "count": 40, "subcategory_counts": {"咖啡厅": 40}, "top_subcategories": [{"name": "咖啡厅", "parent": "餐饮"}], "points": points},
        ],
        "area_heatmaps": [{"year": 2024, "point_count": 40, "points": points, "cells": [{"intensity": idx} for idx in range(30)]}],
        "area_heatmap_snapshots": [{"year": 2024, "image_url": "data:image/png;base64,large"}],
    }))

    assert result["status"] == "ready"
    assert captured["evidence_version"] == "poi_iteration_v1"
    assert captured["year_summaries"][0]["poi_count"] == 20
    assert "points" not in captured["year_summaries"][0]
    assert captured["area_distribution"][0]["hotspot_cell_count"] == 30
    assert len(captured["area_distribution"][0]["top_cells"]) == 12
    assert captured["growth_area_signal"]["growth_rows"][0]["name"] == "咖啡厅"
    assert captured["constraints"]["no_coordinate_reasoning"] is True
    assert "area_heatmap_snapshots" not in captured
    assert "data:image/png" not in str(captured)


def test_build_poi_iteration_evidence_pack_v1_omits_images_and_full_points():
    points = [{"lng": 112 + idx, "lat": 28, "category": "餐饮", "subcategory": "咖啡厅"} for idx in range(20)]
    evidence = build_poi_iteration_evidence_pack_v1({
        "years": [2020, 2024],
        "summaries": [{"year": 2024, "count": 20, "points": points, "top_subcategories": [], "top_areas": [{"name": "岳麓区"}]}],
        "area_heatmaps": [{"year": 2024, "point_count": 20, "points": points, "cells": [{"intensity": idx} for idx in range(20)]}],
        "area_heatmap_snapshots": [{"image_url": "data:image/png;base64,large"}],
        "area_heatmap_boundary": [{"x": 1, "y": 2}],
        "area_heatmap_polygon": [[112, 28]],
    })

    assert evidence["task"] == "poi_iteration_change"
    assert evidence["evidence_version"] == "poi_iteration_v1"
    assert evidence["scope"]["area_name"] == "岳麓区"
    assert evidence["scope"]["polygon_point_count"] == 1
    assert evidence["year_summaries"][0]["poi_count"] == 20
    assert "points" not in evidence["year_summaries"][0]
    assert evidence["area_distribution"][0]["hotspot_cell_count"] == 20
    assert len(evidence["area_distribution"][0]["top_cells"]) == 12
    assert "area_heatmap_snapshots" not in evidence
    assert "data:image/png" not in str(evidence)


def test_build_poi_iteration_evidence_pack_v1_includes_h3_metrics_and_derived_rows():
    evidence = build_poi_iteration_evidence_pack_v1({
        "years": [2020, 2024],
        "summaries": [
            {"year": 2020, "count": 1, "category_counts": {"food": 1}, "subcategory_counts": {"cafe": 1}},
            {"year": 2024, "count": 2, "category_counts": {"food": 2}, "subcategory_counts": {"cafe": 2}},
        ],
        "h3_evidence": {
            "evidence_version": "poi_h3_evidence_v1",
            "grid_type": "h3",
            "params": {"h3_resolution": 9, "neighbor_ring": 2},
            "counts": {"grid_count": 1, "poi_count": 2},
            "metrics": {"avg_density_poi_per_km2": 18.2, "avg_local_entropy": 0.62},
            "summary": {"global_moran_i_density": 0.2, "gi_z_stats": {"count": 1}, "lisa_i_stats": {"count": 1}},
            "cells": [
                {
                    "h3_id": "h3-1",
                    "poi_count": 2,
                    "density_poi_per_km2": 18.2,
                    "local_entropy": 0.62,
                    "neighbor_mean_density": 10.0,
                    "neighbor_mean_entropy": 0.4,
                    "neighbor_count": 6,
                    "category_counts": {"food": 2},
                    "gi_star_z_score": 2.4,
                    "gi_star_value": 1.1,
                    "lisa_i": 0.32,
                    "lisa_z_score": 1.8,
                }
            ],
            "derived_stats": {
                "structure_rows": [{"h3_id": "h3-1", "structure_signal": 2.4}],
                "typing_rows": [{"h3_id": "h3-1", "type_key": "high_density_high_mix"}],
                "lq_rows": [{"h3_id": "h3-1", "lq_target": 1.5, "lq_map": {"food": 1.5}}],
                "gap_rows": [{"h3_id": "h3-1", "gap_score": 0.3}],
            },
        },
    })

    h3 = evidence["h3_evidence"]
    assert h3["evidence_version"] == "poi_h3_evidence_v1"
    assert h3["params"]["h3_resolution"] == 9
    assert h3["cells"][0]["density_poi_per_km2"] == 18.2
    assert h3["cells"][0]["gi_star_z_score"] == 2.4
    assert h3["cells"][0]["lisa_i"] == 0.32
    assert h3["derived_stats"]["lq_rows"][0]["lq_target"] == 1.5
    assert h3["derived_stats"]["gap_rows"][0]["gap_score"] == 0.3
    assert h3["constraints"]["poi_only"] is True


def test_build_poi_iteration_evidence_pack_v1_includes_yearly_grid_evidence():
    evidence = build_poi_iteration_evidence_pack_v1({
        "years": [2023, 2025],
        "summaries": [{"year": 2023, "count": 1}, {"year": 2025, "count": 2}],
        "yearly_grid_evidence": {
            "evidence_version": "poi_iteration_yearly_grid_evidence_v1",
            "years": [2023, 2025],
            "grid_scope": "poi_iteration_h3_per_year",
            "latest_year": 2025,
            "latest_h3_evidence": {
                "cells": [{
                    "h3_id": "h3-2025",
                    "poi_count": 2,
                    "density_poi_per_km2": 12,
                    "gi_star_z_score": 2.1,
                }],
            },
            "items": [{
                "year": 2025,
                "status": "ready",
                "h3_evidence": {
                    "cells": [{
                        "h3_id": "h3-2025",
                        "poi_count": 2,
                        "density_poi_per_km2": 12,
                        "lisa_i": 0.2,
                    }],
                },
            }],
        },
    })

    yearly = evidence["yearly_grid_evidence"]
    assert yearly["evidence_version"] == "poi_iteration_yearly_grid_evidence_v1"
    assert yearly["grid_scope"] == "poi_iteration_h3_per_year"
    assert yearly["items"][0]["year"] == 2025
    assert yearly["items"][0]["h3_evidence"]["cells"][0]["h3_id"] == "h3-2025"
    assert "raster_grid_evidence" not in yearly["items"][0]


def test_build_poi_iteration_evidence_pack_v1_ranks_subcategory_changes():
    evidence = build_poi_iteration_evidence_pack_v1({
        "years": [2020, 2024],
        "summaries": [
            {
                "year": 2020,
                "count": 100,
                "category_counts": {"餐饮": 60, "购物": 40},
                "subcategory_counts": {"中餐厅": 50, "咖啡厅": 1, "商场": 40},
                "top_subcategories": [{"name": "中餐厅", "parent": "餐饮"}, {"name": "咖啡厅", "parent": "餐饮"}],
            },
            {
                "year": 2024,
                "count": 100,
                "category_counts": {"餐饮": 50, "购物": 50},
                "subcategory_counts": {"中餐厅": 30, "咖啡厅": 2, "商场": 50},
                "top_subcategories": [{"name": "中餐厅", "parent": "餐饮"}, {"name": "咖啡厅", "parent": "餐饮"}],
            },
        ],
        "subcategory_spatial_trend_rows": [{"name": "咖啡厅", "dominant_direction": "东北", "delta": 1}],
    })

    assert {row["name"] for row in evidence["category_changes"][:2]} == {"餐饮", "购物"}
    assert evidence["subcategory_changes"][0]["name"] == "咖啡厅"
    assert evidence["subcategory_changes"][0]["has_spatial_signal"] is True
    assert evidence["subcategory_changes"][1]["name"] == "中餐厅"
    assert evidence["subcategory_spatial_trends"][0]["name"] == "咖啡厅"
    assert evidence["growth_area_signal"]["growth_rows"][0]["name"] == "咖啡厅"
    assert build_poi_iteration_llm_evidence(evidence)["evidence_version"] == "poi_iteration_v1"


def test_build_poi_iteration_evidence_pack_v1_separates_low_base_rate_growth():
    evidence = build_poi_iteration_evidence_pack_v1({
        "years": [2020, 2024],
        "summaries": [
            {
                "year": 2020,
                "count": 5000,
                "category_counts": {"自然": 2, "公司": 180, "餐饮": 1200},
                "subcategory_counts": {"博物馆": 1, "快餐厅": 220, "中餐厅": 800},
            },
            {
                "year": 2024,
                "count": 5000,
                "category_counts": {"自然": 5, "公司": 225, "餐饮": 1360},
                "subcategory_counts": {"博物馆": 4, "快餐厅": 375, "中餐厅": 624},
            },
        ],
    })

    highlights = evidence["material_change_highlights"]
    assert highlights["category_growth"][0]["name"] == "餐饮"
    assert highlights["category_growth"][1]["name"] == "公司"
    assert highlights["subcategory_growth"][0]["name"] == "快餐厅"
    assert highlights["low_base_growth_watchlist"][0]["name"] in {"自然", "博物馆"}
    assert evidence["constraints"]["no_low_base_rate_as_primary"] is True


def test_generate_poi_iteration_analysis_formats_object_insights(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "summary_points": ["一级业态以餐饮为主", "小类以快餐厅增长较快"],
            "fastest_growth": {"category": "公司", "delta": "+29", "subcategory": "快餐厅", "change": "+106"},
            "declining_category": {"category": "购物", "delta": "-330", "subcategory": "购物相关场所", "change": "-153"},
            "emerging_area": "未发现明显新兴区域",
            "structure_judgement": "餐饮内部快餐厅占比上升",
            "driver_analysis": [
                {"driver": "快餐厅小类拉动", "evidence": "快餐厅变化 +106", "confidence": "中", "explanation": "小类增长推动餐饮内部结构变化。"}
            ],
            "planning_implications": [
                {"implication": "关注快餐与便捷消费", "evidence": "快餐厅增长较快", "suggested_direction": "便捷餐饮配套。"}
            ],
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({"years": [2023, 2024, 2025]}))

    assert result["status"] == "ready"
    assert result["ai_insights"]["fastest_growth"]["category"]
    assert result["ai_insights"]["fastest_growth"]["subcategory"]
    assert "interpretation" in result["ai_insights"]["emerging_area"]
    assert result["ai_insights"]["emerging_area"]["interpretation"]
    assert "????" not in result["ai_insights"]["emerging_area"]["interpretation"]


def test_generate_poi_iteration_analysis_accepts_seven_field_payload(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "summary_points": ["POI 总量温和增长。", "餐饮保持主导。"],
            "fastest_growth": "餐饮增长最快。",
            "declining_category": "未发现明显衰退。",
            "emerging_area": "北向中圈层加密。",
            "structure_judgement": "生活消费型复合结构。",
            "driver_analysis": [
                {"driver": "生活消费需求支撑", "evidence": "餐饮保持主导", "confidence": "中", "explanation": "主导业态稳定说明消费底盘仍在。"}
            ],
            "planning_implications": [
                {"implication": "延续生活消费基础", "evidence": "餐饮保持主导", "suggested_direction": "餐饮与配套服务。"}
            ],
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({"years": [2022, 2024]}))

    assert result["status"] == "ready"
    assert result["driver_analysis"][0]["driver"] == "生活消费需求支撑"
    assert "report_title" not in result
    assert "report_content" not in result


def test_generate_poi_iteration_analysis_rejects_missing_driver_or_planning(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "summary_points": ["POI 总量温和增长。", "餐饮保持主导。"],
            "fastest_growth": "餐饮增长最快。",
            "declining_category": "未发现明显衰退。",
            "emerging_area": "北向中圈层加密。",
            "structure_judgement": "生活消费型复合结构。",
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({
        "years": [2022, 2024],
        "summaries": [{"year": 2022, "count": 10}, {"year": 2024, "count": 12}],
    }))

    assert result["status"] == "failed"
    assert result["error"] == "invalid_ai_analysis"


def test_generate_poi_iteration_analysis_returns_llm_unavailable(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: False)

    result = asyncio.run(generate_poi_iteration_analysis({"years": [2023, 2024, 2025]}))

    assert result["status"] == "failed"
    assert result["error"] == "llm_unavailable"
    assert "poi_iteration_v1" in result["ai_prompt"]
    assert "不包含全量 POI 点" in result["ai_prompt_payload_note"]


def test_summarize_iteration_pois_resolves_type_map_category_and_subcategory():
    result = summarize_iteration_pois(
        [
            {"id": "a", "type": "type-050500", "adname": "一区", "location": [112.9, 28.1]},
            {"id": "b", "typecode": "050100", "adname": "二区", "location": [112.91, 28.11]},
            {"id": "c", "type_code": "060100", "adname": "一区", "location": [112.92, 28.12]},
        ],
        2025,
    )

    assert result["year"] == 2025
    assert result["category_counts"]["餐饮"] == 2
    assert result["subcategory_counts"]["咖啡厅"] == 1
    assert result["top_subcategories"][0]["parent"]
    assert result["points"][0]["subcategory"] == "咖啡厅"


def test_summarize_iteration_pois_keeps_all_subcategories_and_group_mix():
    pois = [
        {"id": f"poi-{index}", "type": f"Food/Sub{index:02d}", "adname": "Area", "location": [112.0 + index * 0.001, 28.0]}
        for index in range(10)
    ]

    result = summarize_iteration_pois(pois, 2025)

    assert result["subcategory_count"] == 10
    assert len(result["top_subcategories"]) == 10
    assert len(result["category_to_subcategory_mix"]["Food"]) == 10


def test_subcategory_spatial_trends_keep_all_changed_subcategories():
    first_points = []
    last_points = []
    first_counts = {}
    last_counts = {}
    top_subcategories = []
    for index in range(8):
        name = f"Sub{index:02d}"
        first_counts[name] = 1
        last_counts[name] = 2
        top_subcategories.append({"name": name, "parent": "Food"})
        first_points.append({"lng": 112.0 + index * 0.001, "lat": 28.0, "subcategory": name, "category": "Food", "area": "A"})
        last_points.extend([
            {"lng": 112.02 + index * 0.001, "lat": 28.02, "subcategory": name, "category": "Food", "area": "B"},
            {"lng": 112.021 + index * 0.001, "lat": 28.021, "subcategory": name, "category": "Food", "area": "B"},
        ])

    result = build_subcategory_spatial_trends(
        [
            {"year": 2023, "subcategory_counts": first_counts, "top_subcategories": top_subcategories, "points": first_points},
            {"year": 2025, "subcategory_counts": last_counts, "top_subcategories": top_subcategories, "points": last_points},
        ],
        center=[112.0, 28.0],
    )

    assert len(result["subcategory_spatial_trend_rows"]) == 8


def test_build_agent_poi_iteration_payload_aggregates_history_and_spatial_fields(monkeypatch):
    monkeypatch.setattr("modules.agent.poi_iteration_build_service.settings.amap_web_service_key", "test-amap-key")

    class FakeRepo:
        def get_pois(self, history_id, year=None):
            pois_by_year = {
                2023: [
                    {"id": "a", "type": "type-050500", "adname": "一区", "location": [112.9, 28.1]},
                    {"id": "b", "typecode": "060100", "adname": "一区", "location": [112.91, 28.11]},
                ],
                2025: [
                    {"id": "c", "type": "type-050500", "adname": "二区", "location": [112.94, 28.14]},
                    {"id": "d", "type": "type-050500", "adname": "二区", "location": [112.95, 28.15]},
                    {"id": "e", "typecode": "050100", "adname": "二区", "location": [112.96, 28.16]},
                ],
            }
            return {
                "history_id": history_id,
                "polygon": [[112.89, 28.09], [112.97, 28.09], [112.97, 28.17], [112.89, 28.17], [112.89, 28.09]],
                "pois": pois_by_year.get(int(year), []),
                "poi_summary": {"total": len(pois_by_year.get(int(year), []))},
                "count": len(pois_by_year.get(int(year), [])),
                "available_years": [2023, 2025],
                "selected_year": year,
            }

    async def fake_generate(evidence):
        return {
            "status": "failed",
            "ai_summary": [],
            "ai_insights": {},
            "spatial_factors": {"geometry_mode": "point"},
            "subcategory_spatial_trend_rows": [{"name": "咖啡厅", "dominant_direction": "东北"}],
            "subcategory_spatial_summary": ["咖啡厅向东北增强"],
            "error": "llm_unavailable",
        }

    monkeypatch.setattr("modules.agent.poi_iteration_build_service._generate_poi_iteration_analysis", fake_generate)

    result = asyncio.run(build_agent_poi_iteration_payload(
        {"history_id": "history-1", "years": [2023, 2025], "center": [112.93, 28.13]},
        FakeRepo(),
    ))

    assert result["status"] == "ready"
    assert result["years"] == [2023, 2025]
    assert result["summaries"][1]["subcategory_counts"]["咖啡厅"] == 2
    assert result["subcategory_trend_rows"]
    assert result["spatial_factors"] == {}
    assert result["subcategory_spatial_trend_rows"] == []
    assert result["ai_status"] == "pending"
    assert result["ai_error"] == ""
    assert result["area_heatmap_basemap"]["source"] == "amap_static_url"
    assert "restapi.amap.com/v3/staticmap" in result["area_heatmap_basemap"]["url"]
    assert result["area_heatmap_basemap"]["bounds"]["min_lng"] < result["area_heatmap_basemap"]["bounds"]["max_lng"]
    assert result["area_heatmap_basemap"]["center"]
    assert result["area_heatmap_basemap"]["zoom"]
    assert result["area_heatmap_basemap"]["size"]["width"] == 640
    assert result["area_heatmap_boundary"]
    assert result["area_heatmap_polygon"]
    assert all(0 <= point["x"] <= 100 and 0 <= point["y"] <= 100 for point in result["area_heatmap_boundary"])
    response_payload = AgentIterationPoiBuildResponse.model_validate(result).model_dump()
    assert response_payload["ai_status"] == "pending"
    assert response_payload["area_heatmap_basemap"]["source"] == "amap_static_url"
    assert response_payload["area_heatmap_boundary"]
    assert response_payload["area_heatmap_polygon"]


def test_build_agent_poi_iteration_payload_roundtrips_yearly_grid_evidence(monkeypatch):
    class FakeRepo:
        def get_pois(self, history_id, year=None):
            year = int(year)
            return {
                "history_id": history_id,
                "polygon": [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.1], [112.0, 28.0]],
                "pois": [{"id": f"poi-{year}", "type": "type-050500", "adname": "A", "location": [112.0, 28.0]}],
                "available_years": [2023, 2025],
                "selected_year": year,
            }

    yearly = {
        "evidence_version": "poi_iteration_yearly_grid_evidence_v1",
        "years": [2023, 2025],
        "grid_scope": "poi_iteration_h3_per_year",
        "grid_type": "h3",
        "latest_year": 2025,
        "items": [{"year": 2025, "status": "ready", "h3_evidence": {"evidence_version": "poi_h3_evidence_v1"}}],
        "latest_h3_evidence": {"evidence_version": "poi_h3_evidence_v1"},
    }

    result = asyncio.run(build_agent_poi_iteration_payload(
        {"history_id": "history-1", "years": [2023, 2025], "center": [112.0, 28.0], "yearly_grid_evidence": yearly},
        FakeRepo(),
    ))

    response_payload = AgentIterationPoiBuildResponse.model_validate(result).model_dump()
    assert response_payload["yearly_grid_evidence"]["evidence_version"] == "poi_iteration_yearly_grid_evidence_v1"
    assert response_payload["yearly_grid_evidence"]["latest_year"] == 2025


def test_build_agent_poi_iteration_payload_area_heatmap_basemap_is_pure_svg_metadata(monkeypatch):
    monkeypatch.setattr("modules.agent.poi_iteration_build_service.settings.amap_web_service_key", "")

    class FakeRepo:
        def get_pois(self, history_id, year=None):
            year = int(year)
            return {
                "history_id": history_id,
                "polygon": [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.1], [112.0, 28.0]],
                "pois": [{"id": f"poi-{year}", "type": "type-050500", "adname": "A", "location": [112.0 + year * 0.00001, 28.0]}],
                "poi_summary": {"total": 1},
                "count": 1,
                "available_years": [2023, 2025],
                "selected_year": year,
            }

    async def fake_generate(evidence):
        return {"status": "failed", "ai_summary": [], "ai_insights": {}, "error": "llm_unavailable"}

    monkeypatch.setattr("modules.agent.poi_iteration_build_service._generate_poi_iteration_analysis", fake_generate)

    result = asyncio.run(build_agent_poi_iteration_payload(
        {"history_id": "history-1", "years": [2023, 2025], "center": [112.0, 28.0]},
        FakeRepo(),
    ))

    assert result["area_heatmaps"]
    assert result["area_heatmap_basemap"]["source"] == "none"
    assert result["area_heatmap_basemap"]["url"] == ""
    assert result["area_heatmap_basemap"]["zoom"] is None
    assert result["area_heatmap_basemap"]["size"] == result["area_heatmap_basemap"]["view"]
    assert result["area_heatmap_polygon"]


def test_build_agent_poi_iteration_payload_returns_base_payload_before_ai(monkeypatch):
    monkeypatch.setattr("modules.agent.poi_iteration_build_service.settings.amap_web_service_key", "")
    monkeypatch.setattr("modules.agent.poi_iteration_build_service._POI_ITERATION_AI_TIMEOUT_S", 0.01)

    class FakeRepo:
        def get_pois(self, history_id, year=None):
            year = int(year)
            return {
                "history_id": history_id,
                "polygon": [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.1], [112.0, 28.0]],
                "pois": [{"id": f"poi-{year}", "type": "type-050500", "adname": "A", "location": [112.02, 28.02]}],
                "poi_summary": {"total": 1},
                "count": 1,
                "available_years": [2023, 2025],
                "selected_year": year,
            }

    called = False

    async def slow_generate(evidence):
        nonlocal called
        called = True
        await asyncio.sleep(1)
        return {"status": "ready", "ai_summary": ["late"], "ai_insights": {}, "error": ""}

    monkeypatch.setattr("modules.agent.poi_iteration_build_service._generate_poi_iteration_analysis", slow_generate)

    result = asyncio.run(build_agent_poi_iteration_payload(
        {"history_id": "history-1", "years": [2023, 2025], "center": [112.0, 28.0]},
        FakeRepo(),
    ))

    assert result["status"] == "ready"
    assert result["area_heatmaps"]
    assert result["area_heatmap_boundary"]
    assert result["ai_status"] == "pending"
    assert result["ai_summary"] == []
    assert result["ai_error"] == ""
    assert called is False


def test_build_agent_poi_iteration_payload_area_heatmap_uses_polygon_bounds_and_filters_outside_points(monkeypatch):
    class FakeRepo:
        def get_pois(self, history_id, year=None):
            year = int(year)
            pois_by_year = {
                2023: [
                    {"id": "inside-2023", "type": "type-050500", "adname": "A", "location": [112.91, 28.11]},
                ],
                2025: [
                    {"id": "inside-2025", "type": "type-050500", "adname": "A", "location": [112.92, 28.12]},
                    {"id": "outside-2025", "type": "type-050500", "adname": "B", "location": [113.5, 29.0]},
                ],
            }
            return {
                "history_id": history_id,
                "polygon": [[112.89, 28.09], [112.97, 28.09], [112.97, 28.17], [112.89, 28.17], [112.89, 28.09]],
                "pois": pois_by_year.get(year, []),
                "poi_summary": {"total": len(pois_by_year.get(year, []))},
                "count": len(pois_by_year.get(year, [])),
                "available_years": [2023, 2025],
                "selected_year": year,
            }

    async def fake_generate(evidence):
        return {"status": "failed", "ai_summary": [], "ai_insights": {}, "error": "llm_unavailable"}

    monkeypatch.setattr("modules.agent.poi_iteration_build_service._generate_poi_iteration_analysis", fake_generate)

    result = asyncio.run(build_agent_poi_iteration_payload(
        {"history_id": "history-1", "years": [2023, 2025], "center": [112.93, 28.13]},
        FakeRepo(),
    ))

    bounds = result["area_heatmap_basemap"]["bounds"]
    assert bounds["min_lng"] < 112.89
    assert bounds["max_lng"] > 112.97
    assert bounds["max_lng"] < 113.5
    assert result["area_heatmaps"][1]["point_count"] == 1
    assert result["area_heatmap_boundary"]
    assert all(0 <= point["x"] <= 100 and 0 <= point["y"] <= 100 for point in result["area_heatmap_boundary"])
    xs = [point["x"] for point in result["area_heatmap_boundary"]]
    ys = [point["y"] for point in result["area_heatmap_boundary"]]
    view = result["area_heatmap_basemap"]["view"]
    assert min(xs) <= 15
    assert max(xs) >= view["width"] - 15
    assert min(ys) <= 16
    assert max(ys) >= view["height"] - 16
    assert "svg_viewport" not in result["area_heatmap_basemap"]["bounds"]


def test_build_agent_poi_iteration_payload_area_heatmap_falls_back_to_poi_bounds_without_polygon(monkeypatch):
    class FakeRepo:
        def get_pois(self, history_id, year=None):
            year = int(year)
            return {
                "history_id": history_id,
                "polygon": [],
                "pois": [{"id": f"poi-{year}", "type": "type-050500", "adname": "A", "location": [112.0 + (year - 2023) * 0.01, 28.0]}],
                "poi_summary": {"total": 1},
                "count": 1,
                "available_years": [2023, 2025],
                "selected_year": year,
            }

    async def fake_generate(evidence):
        return {"status": "failed", "ai_summary": [], "ai_insights": {}, "error": "llm_unavailable"}

    monkeypatch.setattr("modules.agent.poi_iteration_build_service._generate_poi_iteration_analysis", fake_generate)

    result = asyncio.run(build_agent_poi_iteration_payload(
        {"history_id": "history-1", "years": [2023, 2025], "center": [112.0, 28.0]},
        FakeRepo(),
    ))

    assert result["area_heatmaps"]
    assert result["area_heatmap_basemap"]["bounds"]["min_lng"] < result["area_heatmap_basemap"]["bounds"]["max_lng"]
    assert result["area_heatmap_basemap"]["bounds"]["min_lat"] < result["area_heatmap_basemap"]["bounds"]["max_lat"]
    assert result["area_heatmap_boundary"] == []
    assert result["area_heatmap_polygon"] == []


def _valid_summary_pack_new_schema():
    payload = dict(_valid_summary_pack())
    sections = payload.pop("secondary_conclusions")
    for section in sections:
        payload[section["section_key"]] = dict(section)
    payload["tourism_cross_analysis"] = {
        "title": "文旅交叉策划分析",
        "content": "一、综合判断\n成立。\n五、人口 × POI × 夜光交叉诊断\n匹配。\n九、策划结论\n该地块适合以本地客群为核心客群。",
    }
    return payload


def _request():
    return AgentSummaryRequest(
        conversation_id="summary-test",
        history_id="history-1",
        analysis_snapshot=AnalysisSnapshot(
            poi_summary={"total": 24},
            frontend_analysis={
                "poi": {
                    "category_stats": {
                        "labels": ["餐饮", "购物", "生活服务"],
                        "values": [18, 9, 5],
                    }
                }
            },
        ),
    )


def test_generate_summary_pack_marks_llm_unavailable(monkeypatch):
    async def fake_ensure(**_):
        return _ready_payload()

    async def fake_pack(**_):
        return SimpleNamespace(status="success", warnings=[], artifacts={}, error="")

    monkeypatch.setattr("modules.agent.summary_service.ensure_area_data_readiness", fake_ensure)
    monkeypatch.setattr("modules.agent.summary_service.run_area_character_pack", fake_pack)
    monkeypatch.setattr(
        "modules.agent.summary_service._derive_structured_status",
        lambda snapshot, artifacts: {"missing_tasks": [], "artifacts": _structured_artifacts()},
    )
    monkeypatch.setattr("modules.agent.summary_service.is_llm_enabled", lambda: False)

    result = asyncio.run(generate_summary_pack(_request()))

    assert result.data_readiness.ready is True
    assert result.summary_pack == {}
    assert result.panel_payloads["summary_status"]["status"] == "llm_unavailable"
    assert result.panel_payloads["summary_status"]["generated"] is False
    assert result.panel_payloads["summary_status"]["error_code"] == "llm_unavailable"
    assert result.panel_payloads["summary_status"]["retryable"] is False


def test_evaluate_summary_readiness_uses_readonly_precheck(monkeypatch):
    seen = {}

    async def fake_ensure(**kwargs):
        seen["arguments"] = kwargs.get("arguments")
        return {
            "data_readiness": {
                "checked": True,
                "ready": False,
                "reused": ["poi", "nightlight"],
                "fetched": [],
            },
            "artifacts": {},
            "warnings": [],
            "error": "",
        }

    monkeypatch.setattr("modules.agent.summary_service.ensure_area_data_readiness", fake_ensure)
    monkeypatch.setattr(
        "modules.agent.summary_service._derive_structured_status",
        lambda snapshot, artifacts: {"missing_tasks": [], "artifacts": {}},
    )

    result = asyncio.run(evaluate_summary_readiness(_request()))

    assert seen["arguments"] == {"auto_fetch": False}
    assert result.data_readiness.ready is False
    assert result.data_readiness.fetched == []
    assert result.error == ""


def test_generate_summary_pack_rejects_invalid_llm_payload(monkeypatch):
    async def fake_ensure(**_):
        return _ready_payload()

    async def fake_pack(**_):
        return SimpleNamespace(status="success", warnings=[], artifacts={}, error="")

    async def fake_generate(*_args, **_kwargs):
        return {}

    monkeypatch.setattr("modules.agent.summary_service.ensure_area_data_readiness", fake_ensure)
    monkeypatch.setattr("modules.agent.summary_service.run_area_character_pack", fake_pack)
    monkeypatch.setattr(
        "modules.agent.summary_service._derive_structured_status",
        lambda snapshot, artifacts: {"missing_tasks": [], "artifacts": _structured_artifacts()},
    )
    monkeypatch.setattr("modules.agent.summary_service.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.agent.summary_service._generate_summary_pack_with_llm", fake_generate)

    result = asyncio.run(generate_summary_pack(_request()))

    assert result.summary_pack == {}
    assert result.error == "summary_pack_invalid"
    assert result.panel_payloads["summary_status"]["status"] == "generation_failed"
    assert result.panel_payloads["summary_status"]["generated"] is False
    assert result.panel_payloads["summary_status"]["error_code"] == "schema_invalid"
    assert result.panel_payloads["summary_status"]["retryable"] is False


def test_validate_summary_pack_accepts_legacy_area_judgment_array():
    result = _validate_summary_pack_payload(
        _valid_summary_pack(),
        icsc_tags=["餐饮主导"],
        evidence_refs=["analysis_snapshot.poi_summary"],
    )

    assert result["spatial_structure"]["title"]
    assert result["business_support"]["reasoning"]
    assert "secondary_conclusions" not in result


def test_validate_summary_pack_requires_all_area_judgments():
    payload = _valid_summary_pack_new_schema()
    payload.pop("business_support")

    result = _validate_summary_pack_payload(
        payload,
        icsc_tags=["餐饮主导"],
        evidence_refs=["analysis_snapshot.poi_summary"],
    )

    assert result == {}


def test_generate_summary_pack_returns_new_schema(monkeypatch):
    async def fake_ensure(**_):
        return _ready_payload()

    async def fake_pack(**_):
        return SimpleNamespace(status="success", warnings=[], artifacts={}, error="")

    async def fake_generate(*_args, **_kwargs):
        return _valid_summary_pack_new_schema()

    monkeypatch.setattr("modules.agent.summary_service.ensure_area_data_readiness", fake_ensure)
    monkeypatch.setattr("modules.agent.summary_service.run_area_character_pack", fake_pack)
    monkeypatch.setattr(
        "modules.agent.summary_service._derive_structured_status",
        lambda snapshot, artifacts: {"missing_tasks": [], "artifacts": _structured_artifacts()},
    )
    monkeypatch.setattr("modules.agent.summary_service.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.agent.summary_service._generate_summary_pack_with_llm", fake_generate)

    result = asyncio.run(generate_summary_pack(_request()))

    assert result.error == ""
    assert result.summary_pack["headline_judgment"]["summary"].startswith("社区型生活消费商业区")
    assert "secondary_conclusions" not in result.summary_pack
    assert result.summary_pack["spatial_structure"]["title"]
    assert result.summary_pack["poi_structure"]["reasoning"]
    assert result.summary_pack["consumption_vitality"]["reasoning"]
    assert result.summary_pack["business_support"]["reasoning"]
    assert result.summary_pack["user_profile"]["headline"] == "本地居民为主的稳定消费人群"
    assert result.summary_pack["behavior_inference"]["traits"][0] == "高频餐饮和小额消费"
    assert result.summary_pack["icsc_tags"] == ["餐饮主导", "购物配套较强"]
    assert result.summary_pack["validation_results"]["tourism_cross_analysis"]["source"] == "backend"
    assert result.summary_pack["validation_results"]["tourism_cross_analysis"]["validated_output"]["title"] == "文旅交叉策划分析"
    assert result.panel_payloads["summary_status"]["status"] == "ready"


def test_consumption_vitality_rewrites_to_direction_orientation_template():
    source_payload = _build_summary_llm_payload(_request().analysis_snapshot, _structured_artifacts())
    normalized = _normalize_area_judgment_reasoning(
        {
            "consumption_vitality": {
                "section_key": "consumption_vitality",
                "title": "经济活动强度",
                "reasoning": "夜间经济活动强度偏弱，暂不能据此判断全天候经济活动表现。",
            }
        },
        source_payload,
    )

    economic_reasoning = normalized["consumption_vitality"]["reasoning"]
    assert economic_reasoning.startswith("从空间分布来看，等时圈内夜间经济活动整体处于中等偏上水平")
    assert "高值区域主要集中在东北及东方向" in economic_reasoning
    assert "区域道路以东西向为主，东北-西南向为辅" in economic_reasoning
    assert "高度一致" in economic_reasoning
    assert "交通廊道对夜间经济活动的空间引导作用较明显" in economic_reasoning
    for token in ["消费能力", "客流", "营业额", "白天活跃", "日间消费", "全天候经济活动"]:
        assert token not in economic_reasoning


def test_stream_generate_summary_pack_emits_section_events(monkeypatch):
    async def fake_ensure(**_):
        return _ready_payload()

    async def fake_pack(**_):
        return SimpleNamespace(status="success", warnings=[], artifacts={}, error="")

    async def fake_headline(*_args, **_kwargs):
        return {
            "summary": "社区型生活消费商业区",
            "supporting_clause": "以餐饮和购物配套为主。",
        }

    async def fake_section(section_key, *_args, **_kwargs):
        return dict(_valid_summary_pack_new_schema()[section_key])

    async def fake_profile(section_key, *_args, **_kwargs):
        payload = _valid_summary_pack()
        return dict(payload[section_key])

    async def fake_followups(*_args, **_kwargs):
        return ["解释结论依据", "展开业态建议", "转为执行清单"]

    monkeypatch.setattr("modules.agent.summary_service.ensure_area_data_readiness", fake_ensure)
    monkeypatch.setattr("modules.agent.summary_service.run_area_character_pack", fake_pack)
    monkeypatch.setattr(
        "modules.agent.summary_service._derive_structured_status",
        lambda snapshot, artifacts: {"missing_tasks": [], "artifacts": _structured_artifacts()},
    )
    monkeypatch.setattr("modules.agent.summary_service.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.agent.summary_service._generate_headline_section_with_llm", fake_headline)
    monkeypatch.setattr("modules.agent.summary_service._generate_summary_section_with_llm", fake_section)
    monkeypatch.setattr("modules.agent.summary_service._generate_profile_section_with_llm", fake_profile)
    monkeypatch.setattr("modules.agent.summary_service._generate_followup_questions_with_llm", fake_followups)

    async def collect():
        events = []
        async for event in stream_generate_summary_pack(_request()):
            events.append(event)
        return events

    events = asyncio.run(collect())

    event_types = [event.type for event in events]
    assert "section_start" in event_types
    assert "section_delta" in event_types
    assert "section_complete" in event_types
    assert event_types[-1] == "final"
    final_payload = events[-1].payload
    assert final_payload["summary_pack"]["headline_judgment"]["summary"] == "社区型生活消费商业区"
    assert "secondary_conclusions" not in final_payload["summary_pack"]
    assert final_payload["summary_pack"]["spatial_structure"]["title"]
    assert final_payload["summary_pack"]["followup_questions"][0] == "解释结论依据"
    assert final_payload["summary_pack"]["validation_results"]["headline"]["source"] == "backend"
    assert final_payload["panel_payloads"]["validation_results"]["headline"]["validated_output"]["summary"] == "社区型生活消费商业区"
