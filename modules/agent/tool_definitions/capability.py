from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.capability_tools import (
    analyze_poi_structure,
    analyze_spatial_structure,
    get_area_data_bundle,
    infer_area_labels,
    rank_next_analysis_options,
    score_site_candidates_tool,
)
from ..tool_adapters.spatial_cell_tools import build_unified_spatial_cells_tool


def register_capability_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["get_area_data_bundle"] = _register(
        _tool_spec(
            name="get_area_data_bundle",
            description="按参数策略表补齐区域画像所需的 POI/H3/人口/夜光/路网基础数据包",
            category="action",
            layer="L2",
            ui_tier="capability",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            toolkit_id="area_character_pack",
            default_policy_key="district_summary",
            evidence_contract=["current_area_data_bundle", "policy_key"],
            applicable_scenarios=["区域画像", "调性判断", "前期研究"],
            cautions=["优先作为场景工具内部步骤；单独调用时仍需后续解释层工具"],
            requires=["scope_polygon"],
            produces=["current_area_data_bundle", "current_poi_summary", "current_poi_h3_summary", "current_population_summary", "current_nightlight_summary", "current_road_summary"],
            input_schema={
                "type": "object",
                "properties": {
                    "policy_key": {"type": "string"},
                    "source": {"type": "string", "enum": ["local", "gaode"]},
                    "mode": {"type": "string"},
                    "resolution": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
        ),
        get_area_data_bundle,
    )
    registry["analyze_poi_structure"] = _register(
        _tool_spec(
            name="analyze_poi_structure",
            description="基于 POI 结构生成业态主导、复合度和商业画像",
            category="processing",
            layer="L2",
            ui_tier="capability",
            data_domain="poi",
            capability_type="analyze",
            llm_exposure="primary",
            scene_type="area_character",
            toolkit_id="area_character_pack",
            evidence_contract=["current_poi_structure_analysis", "current_business_profile"],
            applicable_scenarios=["区域画像", "商圈分析", "功能定位"],
            cautions=["不能替代选址打分"],
            produces=["current_poi_structure_analysis", "current_business_profile"],
            readonly=True,
            cost_level="normal",
        ),
        analyze_poi_structure,
    )
    registry["rank_next_analysis_options"] = _register(
        _tool_spec(
            name="rank_next_analysis_options",
            description="基于当前证据就绪状态推荐下一步最值得开展的分析方向",
            category="processing",
            layer="L2",
            ui_tier="capability",
            data_domain="general",
            capability_type="decide",
            llm_exposure="primary",
            scene_type="general",
            toolkit_id="next_analysis_pack",
            evidence_contract=["current_next_analysis_options"],
            applicable_scenarios=["下一步分析建议", "研究路线选择", "应用分析入口"],
            cautions=["只推荐分析方向，不直接替代具体选址、招商或经营判断"],
            produces=["current_next_analysis_options"],
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            readonly=True,
            cost_level="safe",
        ),
        rank_next_analysis_options,
    )
    registry["analyze_spatial_structure"] = _register(
        _tool_spec(
            name="analyze_spatial_structure",
            description="整理 H3、人口、夜光、路网结构，形成空间结构概览",
            category="processing",
            layer="L2",
            ui_tier="capability",
            data_domain="grid",
            capability_type="analyze",
            llm_exposure="primary",
            scene_type="area_character",
            toolkit_id="area_character_pack",
            evidence_contract=[
                "current_h3_structure_analysis",
                "current_population_profile_analysis",
                "current_nightlight_pattern_analysis",
                "current_road_pattern_analysis",
            ],
            applicable_scenarios=["区域调性", "活力判断", "空间结构分析"],
            cautions=["输出是结构概览，不直接给经营建议"],
            produces=[
                "current_h3_structure_analysis",
                "current_population_profile_analysis",
                "current_nightlight_pattern_analysis",
                "current_road_pattern_analysis",
            ],
            readonly=True,
            cost_level="normal",
        ),
        analyze_spatial_structure,
    )
    registry["build_unified_spatial_cells"] = _register(
        _tool_spec(
            name="build_unified_spatial_cells",
            description="把 POI、人口、夜光和路网指标统一聚合到人口/夜光共享栅格 cell_id 上",
            category="processing",
            layer="L2",
            ui_tier="capability",
            data_domain="grid",
            capability_type="analyze",
            llm_exposure="primary",
            scene_type="area_character",
            toolkit_id="area_character_pack",
            evidence_contract=["current_unified_spatial_cells", "current_unified_spatial_cells_summary"],
            applicable_scenarios=["区域画像", "商业特征总结", "空间对齐校验"],
            cautions=["同格证据不能直接推断客流、消费力、营业额或收益"],
            requires=["scope_polygon"],
            produces=["current_unified_spatial_cells", "current_unified_spatial_cells_summary"],
            input_schema={
                "type": "object",
                "properties": {
                    "coord_type": {"type": "string", "enum": ["gcj02", "wgs84"]},
                    "population_year": {"type": "string"},
                    "nightlight_year": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "road_mode": {"type": "string", "enum": ["walking", "bicycling", "driving"]},
                    "poi_coord_type": {"type": "string", "enum": ["gcj02", "wgs84"]},
                },
                "additionalProperties": False,
            },
            readonly=True,
            cost_level="normal",
            timeout_sec=90,
        ),
        build_unified_spatial_cells_tool,
    )
    registry["infer_area_labels"] = _register(
        _tool_spec(
            name="infer_area_labels",
            description="基于规则标签引擎输出区域标签、主导功能和证据命中",
            category="processing",
            layer="L2",
            ui_tier="capability",
            data_domain="commerce",
            capability_type="interpret",
            llm_exposure="primary",
            scene_type="area_character",
            toolkit_id="area_character_pack",
            evidence_contract=["current_area_character_labels", "rule_hits"],
            applicable_scenarios=["区域调性判断", "片区定位", "概念研究"],
            cautions=["标签来自规则命中，不能替代详细控规和财务测算"],
            produces=["current_area_character_labels"],
            readonly=True,
            cost_level="normal",
        ),
        infer_area_labels,
    )
    registry["score_site_candidates"] = _register(
        _tool_spec(
            name="score_site_candidates",
            description="程序化计算候选格得分与排序，输出优势、风险和推荐顺序",
            category="processing",
            layer="L2",
            ui_tier="capability",
            data_domain="commerce",
            capability_type="decide",
            llm_exposure="primary",
            scene_type="site_selection",
            toolkit_id="site_selection_pack",
            default_policy_key="business_catchment_1km",
            evidence_contract=["current_site_candidate_scores", "current_target_supply_gap"],
            applicable_scenarios=["建店选址", "品牌补位", "候选点排序"],
            cautions=["排序结果依赖当前候选格证据，不能替代租金和财务测算"],
            produces=["current_site_candidate_scores", "current_target_supply_gap"],
            input_schema={
                "type": "object",
                "properties": {
                    "place_type": {"type": "string"},
                },
                "additionalProperties": False,
            },
            readonly=True,
            cost_level="normal",
        ),
        score_site_candidates_tool,
    )


