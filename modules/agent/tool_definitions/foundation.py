from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.result_tools import read_current_results
from ..tool_adapters.scope_tools import read_current_scope


def register_foundation_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["read_current_scope"] = _register(
        _tool_spec(
            name="read_current_scope",
            description="读取当前 analysis snapshot 中的 scope / isochrone / polygon",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["scope_polygon"],
            applicable_scenarios=["所有地图分析任务起步"],
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "has_scope": {"type": "boolean"},
                    "active_panel": {"type": "string"},
                },
                "required": ["has_scope", "active_panel"],
                "additionalProperties": True,
            },
            produces=["scope_polygon", "isochrone_feature"],
            readonly=True,
        ),
        read_current_scope,
    )
    registry["read_current_results"] = _register(
        _tool_spec(
            name="read_current_results",
            description="读取当前 analysis snapshot 中已存在的结果摘要",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=[
                "current_poi_summary",
                "current_poi_h3_summary",
                "current_population_summary",
                "current_nightlight_summary",
                "current_road_summary",
            ],
            applicable_scenarios=["所有地图分析任务复用已有结果"],
            produces=[
                "current_pois",
                "current_poi_summary",
                "current_poi_h3",
                "current_poi_h3_grid",
                "current_poi_h3_summary",
                "current_poi_h3_charts",
                "current_road_summary",
                "current_population_summary",
                "current_nightlight_summary",
            ],
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "poi_count": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "has_h3_summary": {"type": "boolean"},
                    "has_road_summary": {"type": "boolean"},
                    "has_population_summary": {"type": "boolean"},
                    "has_nightlight_summary": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
            readonly=True,
        ),
        read_current_results,
    )


