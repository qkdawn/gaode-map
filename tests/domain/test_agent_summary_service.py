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
    _generate_summary_pack_with_llm,
    _tourism_payload_size_summary,
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
    assert "poi_h3_evidence" not in payload["spatial_evidence"]
    assert "param_bundle" not in payload["poi_evidence"]
    assert "param_bundle" not in payload["nightlight_evidence"]
    assert "param_bundles" not in payload["spatial_evidence"]


def test_tourism_cross_analysis_payload_compacts_large_h3_and_shared_grid():
    cells = [
        {
            "h3_id": f"h3-{idx}",
            "poi_count": idx,
            "density_poi_per_km2": idx * 1.5,
            "local_entropy": idx / 100,
            "category_counts": {f"cat-{cat}": cat for cat in range(20)},
            "gi_star_z_score": -8 if idx == 5 else (9 if idx == 499 else idx / 100),
            "lisa_i": idx / 50,
            "geometry": {"type": "Polygon", "coordinates": [[[idx, idx]]]},
        }
        for idx in range(500)
    ]
    source_payload = {
        "population_profile": {"summary_text": "人口基础稳定", "total_population": 10000, "top_age_band": "25-34"},
        "nightlight_pattern": {"summary_text": "夜间活力中等", "core_hotspot_count": 3},
        "poi_structure": {"summary_text": "餐饮主导", "dominant_categories": ["餐饮"]},
        "business_profile": {"summary_text": "生活消费型"},
        "spatial_structure": {"summary_text": "多核"},
        "road_pattern": {"summary_text": "路网可达"},
        "raw_evidence": {
            "poi_h3_evidence": {
                "evidence_version": "poi_h3_evidence_v1",
                "counts": {"grid_count": 500, "cell_count": 500},
                "charts": {"large": "x" * 1000},
                "ui": {"large": "x" * 1000},
                "category_meta": [{"name": f"cat-{idx}"} for idx in range(100)],
                "cells": cells,
                "derived_stats": {
                    "lq_rows": [{"h3_id": "h3-7", "lq_target": 4.2, "lq_map": {f"cat-{idx}": idx for idx in range(20)}}],
                    "gap_rows": [{"h3_id": "h3-9", "gap_score": 0.9}],
                },
            },
            "shared_grid": {
                "evidence_version": "shared_grid_evidence_v1",
                "counts": {"complete_overlap_cells": 50},
                "top_coupled_cells": [{"cell_id": f"c-{idx}", "composite_score": idx} for idx in range(50)],
            },
        },
    }

    payload = _build_tourism_cross_analysis_payload(source_payload, _valid_summary_pack())
    h3 = payload["poi_evidence"]["h3_evidence"]
    selected_ids = {cell["h3_id"] for cell in h3["cells"]}

    assert "poi_h3_evidence" not in payload["spatial_evidence"]
    assert len(h3["cells"]) <= 40
    assert {"h3-7", "h3-9", "h3-499", "h3-5"}.issubset(selected_ids)
    assert "charts" not in h3
    assert "ui" not in h3
    assert "category_meta" not in h3
    assert "geometry" not in h3["cells"][0]
    assert "category_counts" not in h3["cells"][0]
    assert len(h3["cells"][0].get("top_category_counts", {})) <= 5
    assert len(payload["spatial_evidence"]["shared_grid"]["top_coupled_cells"]) == 20


def test_tourism_cross_analysis_payload_size_summary():
    payload = _build_tourism_cross_analysis_payload(
        {
            "raw_evidence": {
                "poi_h3_evidence": {
                    "cells": [{"h3_id": "h3-1", "poi_count": 10, "density_poi_per_km2": 20}],
                },
                "shared_grid": {"top_coupled_cells": [{"cell_id": "c-1"}]},
            }
        },
        _valid_summary_pack(),
    )
    summary = _tourism_payload_size_summary("system prompt", payload)

    assert summary["prompt_bytes"] > 0
    assert summary["largest_fields"]
    assert summary["h3_cell_count"] == 1
    assert summary["shared_grid_cell_count"] == 1


def _valid_summary_pack():
    return {
        "headline_judgment": {
            "summary": "社区型生活消费商业区，以餐饮和日常消费为核心。",
            "supporting_clause": "缺少中心型商业吸引力。",
        },
        "icsc_tags": ["餐饮主导", "购物配套较强"],
        "spatial_structure": {
            "section_key": "spatial_structure",
            "title": "空间结构",
            "reasoning": "整体呈多核分布，但核心之间联系较弱。",
            "dimensions": [
                {"key": "aggregation", "label": "聚集性", "conclusion": "热点形成，但集中度有限。"},
                {"key": "mixing", "label": "混合性", "conclusion": "功能混合度中等。"},
                {"key": "morphology", "label": "形态性", "conclusion": "整体偏分散。"},
            ],
        },
        "poi_structure": {
            "section_key": "poi_structure",
            "title": "POI结构",
            "reasoning": "业态以生活消费和餐饮为主。",
        },
        "consumption_vitality": {
            "section_key": "consumption_vitality",
            "title": "经济活动强度",
            "reasoning": "夜间经济活动强度偏弱，暂不能据此判断全天候经济活动表现。",
        },
        "business_support": {
            "section_key": "business_support",
            "title": "业态承接",
            "reasoning": "路网可以承接社区级消费，但难支撑更高能级集聚。",
        },
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


def test_tourism_cross_analysis_prompt_uses_ai_translation_without_fixed_templates():
    config = get_prompt_config("tourism_cross_analysis")

    assert "AI 基于三类证据自行生成" in config.system_prompt
    assert "人口密度 × POI供给" in config.system_prompt
    assert "不得凭空编造政策、道路、商圈、地铁" in config.system_prompt
    assert "当前证据只能支持趋势判断，不能直接证明真实消费规模" in config.system_prompt
    assert "不要求固定九节标题" in config.system_prompt
    assert "该地块适合以____为核心客群" not in config.system_prompt


def test_validate_tourism_cross_analysis_accepts_flexible_content():
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
    flexible = _validate_tourism_cross_analysis_payload({
        "title": "文旅交叉策划分析",
        "content": "人口、POI 和夜光证据可以自然组织，不要求固定九节。",
    })

    assert valid["title"] == "文旅交叉策划分析"
    assert variant["content"]
    assert natural_variant["content"]
    assert flexible["content"]


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
            "report_title": "业态基础分析总结报告",
            "report_sections": [
                {
                    "heading": "餐饮与咖啡厅增量构成主要变化",
                    "paragraphs": ["从 POI 变化看，区域总量保持增长，餐饮与咖啡厅小类提供主要增量。"],
                },
                {
                    "heading": "中圈层补点明显",
                    "paragraphs": ["空间信号显示咖啡厅新增偏东北与中圈层，说明增长更偏内部加密。"],
                },
            ],
            "report_content": "业态基础分析总结报告\n\n餐饮与咖啡厅增量构成主要变化\n\n从 POI 变化看，区域总量保持增长，餐饮与咖啡厅小类提供主要增量。",
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
    assert result["report_title"] == "业态基础分析总结报告"
    assert result["report_sections"][0]["heading"] == "餐饮与咖啡厅增量构成主要变化"
    assert "区域总量保持增长" in result["report_content"]
    assert "poi_iteration_v1" in result["ai_prompt"]
    assert "growth_area_signal" in result["ai_prompt"]
    assert "User payload" in result["ai_prompt_payload_note"]
    config = get_prompt_config("poi_iteration")
    assert result["prompt_snapshot"]["system_prompt"] == config.system_prompt
    assert result["prompt_snapshots"]["poi_iteration"]["system_prompt"] == config.system_prompt
    assert result["validation_results"]["poi_iteration"]["source"] == "backend"
    assert result["validation_results"]["poi_iteration"]["validated_output"]["report_title"] == "业态基础分析总结报告"


def test_generate_poi_iteration_analysis_sends_compact_llm_evidence(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs["user_payload"]["evidence"])
        return {
            "report_title": "业态基础分析总结报告",
            "report_sections": [
                {
                    "heading": "区域业态变化可读",
                    "paragraphs": ["POI 多年证据已被压缩传入，可用于判断总量、结构和空间变化。"],
                }
            ],
            "report_content": "业态基础分析总结报告\n\n区域业态变化可读\n\nPOI 多年证据已被压缩传入，可用于判断总量、结构和空间变化。",
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
    assert yearly["items"][0]["h3_summary"]["representative_cells"][0]["h3_id"] == "h3-2025"
    assert "raster_grid_evidence" not in yearly["items"][0]
    assert "h3_evidence" not in yearly["items"][0]


def test_build_poi_iteration_evidence_pack_v1_compacts_large_h3_context():
    cells = [
        {
            "h3_id": f"h3-{idx}",
            "poi_count": idx,
            "density_poi_per_km2": idx * 1.5,
            "local_entropy": idx / 100,
            "category_counts": {f"cat-{cat}": cat for cat in range(20)},
            "gi_star_z_score": -8 if idx == 5 else (9 if idx == 499 else idx / 100),
            "lisa_i": idx / 50,
            "geometry": {"type": "Polygon", "coordinates": [[[idx, idx]]]},
        }
        for idx in range(500)
    ]
    yearly_items = [
        {
            "year": 2018 + year_idx,
            "h3_evidence": {
                "counts": {"cell_count": 500},
                "metrics": {"avg_density_poi_per_km2": year_idx},
                "cells": cells,
                "derived_stats": {
                    "lq_rows": [{"h3_id": "h3-7", "lq_target": 4.2, "lq_map": {f"cat-{idx}": idx for idx in range(20)}}],
                    "gap_rows": [{"h3_id": "h3-9", "gap_score": 0.9}],
                },
            },
        }
        for year_idx in range(8)
    ]

    evidence = build_poi_iteration_evidence_pack_v1({
        "years": list(range(2018, 2026)),
        "summaries": [{"year": 2018, "count": 10}, {"year": 2025, "count": 20}],
        "h3_evidence": {
            "counts": {"cell_count": 500},
            "charts": {"large": "x" * 1000},
            "ui": {"large": "x" * 1000},
            "category_meta": [{"name": f"cat-{idx}"} for idx in range(100)],
            "cells": cells,
            "derived_stats": {
                "lq_rows": [{"h3_id": "h3-7", "lq_target": 4.2, "lq_map": {f"cat-{idx}": idx for idx in range(20)}}],
                "gap_rows": [{"h3_id": "h3-9", "gap_score": 0.9}],
            },
        },
        "yearly_grid_evidence": {"items": yearly_items},
    })

    h3 = evidence["h3_evidence"]
    selected_ids = {cell["h3_id"] for cell in h3["cells"]}
    assert len(h3["cells"]) <= 40
    assert {"h3-7", "h3-9", "h3-499", "h3-5"}.issubset(selected_ids)
    assert "charts" not in h3
    assert "ui" not in h3
    assert "category_meta" not in h3
    assert "category_counts" not in h3["cells"][0]
    assert len(h3["cells"][0].get("top_category_counts", {})) <= 5
    assert len(evidence["yearly_grid_evidence"]["items"]) == 8
    assert len(evidence["yearly_grid_evidence"]["items"][0]["h3_summary"]["representative_cells"]) <= 12


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


def test_generate_poi_iteration_analysis_accepts_report_payload(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "report_title": "业态基础分析总结报告",
            "report_sections": [
                {
                    "heading": "餐饮内部结构增强",
                    "paragraphs": ["快餐厅等小类增长说明餐饮内部结构存在便捷消费增强信号。"],
                },
                {
                    "heading": "便捷消费值得继续核对",
                    "paragraphs": ["后续可以围绕快餐、轻餐和社交消费组织业态承接。"],
                },
            ],
            "report_content": "业态基础分析总结报告\n\n餐饮内部结构增强\n\n快餐厅等小类增长说明餐饮内部结构存在便捷消费增强信号。",
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({"years": [2023, 2024, 2025]}))

    assert result["status"] == "ready"
    assert result["report_sections"][0]["heading"] == "餐饮内部结构增强"
    assert "summary_points" not in result


def test_generate_poi_iteration_analysis_rejects_invalid_report_payload(monkeypatch):
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

    assert result["status"] == "failed"
    assert result["error"] == "invalid_ai_analysis"


def test_generate_poi_iteration_analysis_rejects_missing_report_sections(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "report_title": "业态基础分析总结报告",
            "report_content": "只有正文但没有结构化章节。",
        }

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fake_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({
        "years": [2022, 2024],
        "summaries": [{"year": 2022, "count": 10}, {"year": 2024, "count": 12}],
    }))

    assert result["status"] == "failed"
    assert result["error"] == "invalid_ai_analysis"


def test_generate_poi_iteration_analysis_returns_context_too_large_without_llm_call(monkeypatch):
    monkeypatch.setattr("modules.agent.iteration_change_service.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.agent.iteration_change_service._POI_ITERATION_PROMPT_BUDGET_BYTES", 100)

    async def fail_invoke(**kwargs):
        raise AssertionError("LLM should not be called when POI iteration context is over budget")

    monkeypatch.setattr("modules.agent.iteration_change_service._invoke_json_role", fail_invoke)

    result = asyncio.run(generate_poi_iteration_analysis({
        "years": [2022, 2024],
        "summaries": [
            {
                "year": 2022,
                "count": 10,
                "category_counts": {"餐饮": 10},
                "subcategory_counts": {"中餐厅": 10},
            },
            {
                "year": 2024,
                "count": 12,
                "category_counts": {"餐饮": 12},
                "subcategory_counts": {"中餐厅": 12},
            },
        ],
        "h3_evidence": {
            "cells": [{"h3_id": "h3-1", "poi_count": 12, "density_poi_per_km2": 20}],
        },
    }))

    assert result["status"] == "failed"
    assert result["error"] == "poi_iteration_context_too_large"
    assert result["context_size_summary"]["prompt_bytes"] > result["context_size_summary"]["budget_bytes"]
    assert result["context_size_summary"]["largest_fields"]
    assert result["context_size_summary"]["h3_cell_count"] == 1


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


def test_generate_summary_pack_records_tourism_context_too_large(monkeypatch):
    calls = []

    async def fake_invoke(**kwargs):
        calls.append(kwargs["phase"])
        if kwargs["phase"] == "summary_pack":
            return {
                "headline_judgment": {"summary": "社区型生活消费商业区", "supporting_clause": "餐饮主导。"},
                "user_profile": {"headline": "本地居民为主", "traits": ["高频餐饮", "就近消费"]},
                "behavior_inference": {"headline": "日常消费", "traits": ["晚间消费", "小额高频"]},
            }
        if kwargs["phase"].startswith("summary_section_"):
            section_key = kwargs["phase"].replace("summary_section_", "")
            return dict(_valid_summary_pack_new_schema()[section_key])
        if kwargs["phase"] == "summary_tourism_cross_analysis":
            raise AssertionError("tourism LLM call should be skipped when context is over budget")
        raise AssertionError(f"unexpected phase {kwargs['phase']}")

    monkeypatch.setattr("modules.agent.summary_service.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.agent.summary_service._invoke_json_role", fake_invoke)
    monkeypatch.setattr("modules.agent.summary_service._TOURISM_PROMPT_BUDGET_BYTES", 100)

    result = asyncio.run(_generate_summary_pack_with_llm(_request().analysis_snapshot, _structured_artifacts()))

    validation = result["validation_results"]["tourism_cross_analysis"]
    assert "summary_tourism_cross_analysis" not in calls
    assert validation["status"] == "failed"
    assert validation["error"] == "tourism_cross_analysis_context_too_large"
    assert validation["context_size_summary"]["prompt_bytes"] > validation["context_size_summary"]["budget_bytes"]


def test_generate_summary_pack_records_tourism_exception(monkeypatch):
    async def fake_invoke(**kwargs):
        if kwargs["phase"] == "summary_pack":
            return {
                "headline_judgment": {"summary": "社区型生活消费商业区", "supporting_clause": "餐饮主导。"},
                "user_profile": {"headline": "本地居民为主", "traits": ["高频餐饮", "就近消费"]},
                "behavior_inference": {"headline": "日常消费", "traits": ["晚间消费", "小额高频"]},
            }
        if kwargs["phase"].startswith("summary_section_"):
            section_key = kwargs["phase"].replace("summary_section_", "")
            return dict(_valid_summary_pack_new_schema()[section_key])
        if kwargs["phase"] == "summary_tourism_cross_analysis":
            raise RuntimeError("CSU 400 context length exceeded")
        raise AssertionError(f"unexpected phase {kwargs['phase']}")

    monkeypatch.setattr("modules.agent.summary_service.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.agent.summary_service._invoke_json_role", fake_invoke)

    result = asyncio.run(_generate_summary_pack_with_llm(_request().analysis_snapshot, _structured_artifacts()))

    assert result["headline_judgment"]["summary"].startswith("社区型")
    validation = result["validation_results"]["tourism_cross_analysis"]
    assert validation["status"] == "failed"
    assert "RuntimeError" in validation["error"]
    assert "tourism_cross_analysis" not in result


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
    assert economic_reasoning.startswith("nightlight_level=中等偏上")
    assert "nightlight_direction=东北及东" in economic_reasoning
    assert "road_orientation=东西向,东北-西南向" in economic_reasoning
    assert "direction_orientation_consistency=dominant_direction_matches_orientation" in economic_reasoning
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
    assert final_payload["summary_pack"]["spatial_structure"]["title"]
    assert final_payload["summary_pack"]["followup_questions"][0] == "解释结论依据"
    assert final_payload["summary_pack"]["validation_results"]["headline"]["source"] == "backend"
    assert final_payload["panel_payloads"]["validation_results"]["headline"]["validated_output"]["summary"] == "社区型生活消费商业区"
