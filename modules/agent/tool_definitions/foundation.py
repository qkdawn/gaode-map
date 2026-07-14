from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.current_poi_tools import query_current_pois
from ..tool_adapters.project_tools import read_project_context
from ..tool_adapters.result_tools import read_current_results
from ..tool_adapters.scope_tools import read_current_scope


def register_foundation_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["read_project_context"] = _register(
        _tool_spec(
            name="read_project_context",
            description="读取当前项目文档、项目证据、空间范围和对应历史记录的分析摘要",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["project_evidence_dossier", "scope_polygon", "analysis_history"],
            applicable_scenarios=["开始理解项目", "读取项目任务书和现状约束", "结合项目文档与 GIS 分析"],
            cautions=["没有项目文档时不得将 GIS 数据当作项目事实", "没有 history_id 时不能确认分析数据版本"],
            produces=["project_context"],
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {
                    "history_id": {"type": "string"},
                    "documents": {"type": "array"},
                    "project_evidence": {"type": "array"},
                    "evidence_conflicts": {"type": "array"},
                    "scope": {"type": "object"},
                    "analysis_results": {"type": "object"},
                    "warnings": {"type": "array"},
                },
                "required": ["history_id", "documents", "project_evidence", "scope", "analysis_results", "warnings"],
                "additionalProperties": True,
            },
            readonly=True,
        ),
        read_project_context,
    )
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
    registry["query_current_pois"] = _register(
        _tool_spec(
            name="query_current_pois",
            description="按 history_id 查询保存的当前范围 POI 数据集，支持关键词、类别和分页",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="poi",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["current_pois"],
            applicable_scenarios=["列出当前范围内某类 POI", "查询当前范围保存的 POI 明细", "回答范围内有哪些学校、医院、餐饮等"],
            cautions=["只查询当前 history_id 保存的 POI 数据集，不读取 snapshot.pois，也不代表完整城市 POI 数据库"],
            produces=["current_poi_query"],
            input_schema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "匹配 POI 名称、类型、类别、地址的关键词，例如 学校、医院、咖啡"},
                    "category": {"type": "string", "description": "可选类别或类型过滤词，例如 科教文化、餐饮"},
                    "history_id": {"type": "string", "description": "可选；不传则使用当前 analysis_snapshot.context.history_id"},
                    "year": {"type": "integer", "description": "可选年份过滤"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "total": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                    "data_source": {"type": "string", "enum": ["scope_dataset"]},
                    "rows": {"type": "array"},
                },
                "required": ["total", "limit", "offset", "has_more", "data_source", "rows"],
                "additionalProperties": True,
            },
            readonly=True,
            cacheable=True,
        ),
        query_current_pois,
    )


