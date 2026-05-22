from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _named_placeholder, _register, _tool_spec
from ..tool_adapters.scenario_tools import run_area_character_pack, run_site_selection_pack


def register_scenario_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["run_area_character_pack"] = _register(
        _tool_spec(
            name="run_area_character_pack",
            description="固定流程完成区域总体调性判断，输出标签、主导功能和证据链",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="general",
            capability_type="decide",
            scene_type="area_character",
            llm_exposure="primary",
            toolkit_id="area_character_pack",
            default_policy_key="district_summary",
            evidence_contract=["area_character_pack", "current_area_character_labels"],
            applicable_scenarios=["区域总体调性", "片区功能定位", "前期策划"],
            cautions=["不能替代控规、财务测算或详细专项研究"],
            requires=["scope_polygon"],
            produces=["area_character_pack", "current_area_character_labels"],
            input_schema={
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "analysis_mode": {"type": "string"},
                    "policy_key": {"type": "string"},
                    "source": {"type": "string", "enum": ["local", "gaode"]},
                    "mode": {"type": "string"},
                    "resolution": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "character_tags": {"type": "array"},
                    "dominant_functions": {"type": "array"},
                    "activity_period": {"type": "string"},
                    "crowd_traits": {"type": "array"},
                    "spatial_temperament": {"type": "string"},
                    "evidence_chain": {"type": "array"},
                    "confidence": {"type": "string"},
                },
                "additionalProperties": True,
            },
            cost_level="normal",
            timeout_sec=600,
        ),
        run_area_character_pack,
    )
    registry["run_site_selection_pack"] = _register(
        _tool_spec(
            name="run_site_selection_pack",
            description="固定流程完成建店选址/补位分析，输出候选点排序、优劣势和证据链",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="commerce",
            capability_type="decide",
            scene_type="site_selection",
            llm_exposure="primary",
            toolkit_id="site_selection_pack",
            default_policy_key="business_catchment_1km",
            evidence_contract=["site_selection_pack", "current_site_candidate_scores", "current_target_supply_gap"],
            applicable_scenarios=["商业建店选址", "品牌补位", "候选点排序"],
            cautions=["不含租金、财务和真实竞品经营数据，结果用于预筛"],
            requires=["scope_polygon"],
            produces=["site_selection_pack", "current_site_candidate_scores", "current_target_supply_gap"],
            input_schema={
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "place_type": {"type": "string"},
                    "brand_profile": {"type": "string"},
                    "policy_key": {"type": "string"},
                    "source": {"type": "string", "enum": ["local", "gaode"]},
                    "year": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "mode": {"type": "string"},
                    "resolution": {"type": "integer", "minimum": 0},
                    "include_mode": {"type": "string"},
                    "min_overlap_ratio": {"type": "number", "minimum": 0},
                    "neighbor_ring": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "candidate_sites": {"type": "array"},
                    "ranking": {"type": "array"},
                    "strengths": {"type": "array"},
                    "risks": {"type": "array"},
                    "not_recommended_reason": {"type": "string"},
                    "evidence_chain": {"type": "array"},
                    "confidence": {"type": "string"},
                },
                "additionalProperties": True,
            },
            cost_level="expensive",
            timeout_sec=900,
        ),
        run_site_selection_pack,
    )

    registry["run_vitality_assessment_pack"] = _register(
        _tool_spec(
            name="run_vitality_assessment_pack",
            description="预留的活力评估场景工具包",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="nightlight",
            capability_type="decide",
            scene_type="vitality",
            llm_exposure="hidden",
            toolkit_id="vitality_pack",
            applicable_scenarios=["活力评估"],
            cautions=["当前版本尚未实现"],
            requires=["scope_polygon"],
        ),
        _named_placeholder("run_vitality_assessment_pack"),
    )
    registry["run_tod_pack"] = _register(
        _tool_spec(
            name="run_tod_pack",
            description="预留的 TOD / 站城分析工具包",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="road",
            capability_type="decide",
            scene_type="tod",
            llm_exposure="hidden",
            toolkit_id="tod_pack",
            default_policy_key="tod_station_area",
            applicable_scenarios=["TOD / 站城分析"],
            cautions=["当前版本尚未实现"],
            requires=["scope_polygon"],
        ),
        _named_placeholder("run_tod_pack"),
    )
    registry["run_livability_pack"] = _register(
        _tool_spec(
            name="run_livability_pack",
            description="预留的居住适宜性分析工具包",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="population",
            capability_type="decide",
            scene_type="livability",
            llm_exposure="hidden",
            toolkit_id="livability_pack",
            applicable_scenarios=["居住适宜性"],
            cautions=["当前版本尚未实现"],
            requires=["scope_polygon"],
        ),
        _named_placeholder("run_livability_pack"),
    )
    registry["run_facility_gap_pack"] = _register(
        _tool_spec(
            name="run_facility_gap_pack",
            description="预留的公服配置缺口识别工具包",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="commerce",
            capability_type="decide",
            scene_type="facility_gap",
            llm_exposure="hidden",
            toolkit_id="facility_gap_pack",
            applicable_scenarios=["公服配置缺口识别"],
            cautions=["当前版本尚未实现"],
            requires=["scope_polygon"],
        ),
        _named_placeholder("run_facility_gap_pack"),
    )
    registry["run_renewal_priority_pack"] = _register(
        _tool_spec(
            name="run_renewal_priority_pack",
            description="预留的更新优先级排序工具包",
            category="action",
            layer="L2",
            ui_tier="scenario",
            data_domain="general",
            capability_type="decide",
            scene_type="renewal_priority",
            llm_exposure="hidden",
            toolkit_id="renewal_priority_pack",
            applicable_scenarios=["更新优先级排序"],
            cautions=["当前版本尚未实现"],
            requires=["scope_polygon"],
        ),
        _named_placeholder("run_renewal_priority_pack"),
    )


