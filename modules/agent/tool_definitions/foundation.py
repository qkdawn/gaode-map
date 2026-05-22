from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.h3_tools import build_h3_grid_from_scope, compute_h3_metrics_from_scope_and_pois
from ..tool_adapters.nightlight_tools import compute_nightlight_overview_from_scope
from ..tool_adapters.poi_tools import fetch_pois_in_scope
from ..tool_adapters.population_tools import compute_population_overview_from_scope
from ..tool_adapters.result_tools import read_current_results
from ..tool_adapters.road_tools import compute_road_syntax_from_scope
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
                "current_h3_summary",
                "current_population_summary",
                "current_nightlight_summary",
                "current_road_summary",
            ],
            applicable_scenarios=["所有地图分析任务复用已有结果"],
            produces=[
                "current_pois",
                "current_poi_summary",
                "current_h3_summary",
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
    registry["fetch_pois_in_scope"] = _register(
        _tool_spec(
            name="fetch_pois_in_scope",
            description="在当前 scope 内抓取 POI 数据",
            category="action",
            layer="L1",
            ui_tier="foundation",
            data_domain="poi",
            capability_type="fetch",
            llm_exposure="secondary",
            requires=["scope_polygon"],
            produces=["current_pois", "current_poi_summary"],
            evidence_contract=["poi.count", "poi.source"],
            applicable_scenarios=["基础数据补齐", "业态样本抓取", "选址前置"],
            cautions=["不能单独用于判断建店可行性，需结合人口、活力和竞品视角"],
            input_schema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "enum": ["local", "gaode"]},
                    "types": {"type": "string"},
                    "keywords": {"type": "string"},
                    "max_count": {"type": "integer", "minimum": 1, "maximum": 5000},
                    "year": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "poi_count": {"type": "integer"},
                    "source": {"type": "string"},
                    "types": {"type": "string"},
                    "keywords": {"type": "string"},
                },
                "required": ["poi_count", "source", "types", "keywords"],
                "additionalProperties": True,
            },
            cost_level="normal",
            timeout_sec=120,
        ),
        fetch_pois_in_scope,
    )
    registry["build_h3_grid_from_scope"] = _register(
        _tool_spec(
            name="build_h3_grid_from_scope",
            description="根据当前 scope 生成 H3 网格",
            category="action",
            layer="L1",
            ui_tier="foundation",
            data_domain="grid",
            capability_type="transform",
            llm_exposure="hidden",
            requires=["scope_polygon"],
            produces=["current_h3_grid"],
            applicable_scenarios=["网格化预处理"],
            cautions=["仅生成网格，不直接形成业务判断"],
            input_schema={
                "type": "object",
                "properties": {
                    "resolution": {"type": "integer", "minimum": 0},
                    "include_mode": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "grid_count": {"type": "integer"},
                    "resolution": {"type": "integer"},
                },
                "required": ["grid_count", "resolution"],
                "additionalProperties": True,
            },
            cost_level="normal",
            timeout_sec=60,
        ),
        build_h3_grid_from_scope,
    )
    registry["compute_h3_metrics_from_scope_and_pois"] = _register(
        _tool_spec(
            name="compute_h3_metrics_from_scope_and_pois",
            description="结合 scope 和 POI 计算 H3 指标",
            category="action",
            layer="L1",
            ui_tier="foundation",
            data_domain="grid",
            capability_type="analyze",
            llm_exposure="secondary",
            requires=["scope_polygon"],
            produces=["current_h3", "current_h3_grid", "current_h3_summary", "current_h3_charts"],
            evidence_contract=["h3.summary.grid_count", "h3.summary.avg_density_poi_per_km2"],
            applicable_scenarios=["空间分布分析", "机会网格识别", "选址前置"],
            cautions=["只提供空间统计，不直接替代调性或选址结论"],
            input_schema={
                "type": "object",
                "properties": {
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
                    "grid_count": {"type": "integer"},
                    "poi_count": {"type": "integer"},
                },
                "required": ["grid_count", "poi_count"],
                "additionalProperties": True,
            },
            cost_level="normal",
            timeout_sec=180,
        ),
        compute_h3_metrics_from_scope_and_pois,
    )
    registry["compute_population_overview_from_scope"] = _register(
        _tool_spec(
            name="compute_population_overview_from_scope",
            description="根据当前 scope 计算人口概览摘要",
            category="action",
            layer="L1",
            ui_tier="foundation",
            data_domain="population",
            capability_type="analyze",
            llm_exposure="primary",
            requires=["scope_polygon"],
            produces=["current_population", "current_population_summary"],
            evidence_contract=["population.summary.total_population", "population.summary.male_ratio"],
            applicable_scenarios=["人口底盘查看", "居住适宜性", "区域画像"],
            cautions=["不能直接推断消费能力或客流"],
            default_policy_key="community_life_circle",
            input_schema={
                "type": "object",
                "properties": {
                    "coord_type": {"type": "string", "enum": ["gcj02", "wgs84"]},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "total_population": {"type": "number"},
                    "male_ratio": {"type": "number"},
                    "female_ratio": {"type": "number"},
                },
                "required": ["total_population", "male_ratio", "female_ratio"],
                "additionalProperties": True,
            },
            cost_level="normal",
            timeout_sec=180,
        ),
        compute_population_overview_from_scope,
    )
    registry["compute_nightlight_overview_from_scope"] = _register(
        _tool_spec(
            name="compute_nightlight_overview_from_scope",
            description="根据当前 scope 计算夜光概览摘要",
            category="action",
            layer="L1",
            ui_tier="foundation",
            data_domain="nightlight",
            capability_type="analyze",
            llm_exposure="primary",
            requires=["scope_polygon"],
            produces=["current_nightlight", "current_nightlight_summary"],
            evidence_contract=["nightlight.summary.total_radiance", "nightlight.summary.max_radiance"],
            applicable_scenarios=["活力评估", "夜间消费判断", "区域画像"],
            cautions=["夜光只可视作活力 proxy，不能直接等同客流"],
            default_policy_key="district_summary",
            input_schema={
                "type": "object",
                "properties": {
                    "coord_type": {"type": "string", "enum": ["gcj02", "wgs84"]},
                    "year": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "total_radiance": {"type": "number"},
                    "mean_radiance": {"type": "number"},
                    "peak_radiance": {"type": "number"},
                    "lit_pixel_ratio": {"type": "number"},
                },
                "additionalProperties": True,
            },
            cost_level="normal",
            timeout_sec=180,
        ),
        compute_nightlight_overview_from_scope,
    )
    registry["compute_road_syntax_from_scope"] = _register(
        _tool_spec(
            name="compute_road_syntax_from_scope",
            description="根据当前 scope 计算路网句法摘要",
            category="action",
            layer="L1",
            ui_tier="foundation",
            data_domain="road",
            capability_type="analyze",
            llm_exposure="primary",
            requires=["scope_polygon"],
            produces=["current_road", "current_road_summary"],
            evidence_contract=["road.summary.node_count", "road.summary.edge_count"],
            applicable_scenarios=["路网可达性", "站城分析", "区域画像"],
            cautions=["不应把路网指标直接替代交通流量结论"],
            default_policy_key="community_life_circle",
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "graph_model": {"type": "string"},
                    "highway_filter": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "node_count": {"type": "integer"},
                    "edge_count": {"type": "integer"},
                },
                "required": ["node_count", "edge_count"],
                "additionalProperties": True,
            },
            cost_level="expensive",
            risk_level="safe",
            timeout_sec=900,
        ),
        compute_road_syntax_from_scope,
    )


