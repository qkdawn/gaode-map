from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from .retrieval import EVIDENCE_NODE_SCHEMA
from ..tool_adapters.scope_dataset_tools import (
    aggregate_scope_dataset,
    list_scope_datasets,
    query_scope_dataset,
    read_scope_record,
)


SOURCE_ID_ENUM = [
    "current:dataset:poi",
    "current:dataset:h3",
    "current:dataset:poi_grid",
    "current:dataset:population",
    "current:dataset:nightlight",
    "current:dataset:road_edges",
    "current:dataset:road_grid",
]

FILTER_SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {
                "type": "object",
                "properties": {
                    "eq": {},
                    "contains": {"type": "string"},
                    "gte": {"type": "number"},
                    "lte": {"type": "number"},
                },
                "additionalProperties": False,
            },
        ]
    },
}

SCOPE_DATASET_RECORD_SCHEMA = {
    "type": "object",
    "properties": {
        "record_id": {"type": "string"},
        "source_id": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "properties": {"type": "object"},
        "time_scope": {"type": "object"},
        "locator": {"type": "string"},
        "citation": {"type": "string"},
        "warnings": {"type": "array"},
    },
    "required": ["record_id", "source_id", "title", "content", "properties", "time_scope", "locator", "citation", "warnings"],
    "additionalProperties": False,
}


def register_scope_dataset_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["list_scope_datasets"] = _register(
        _tool_spec(
            name="list_scope_datasets",
            description="列出当前 history_id 下可查询的当前范围数据源，包括 POI、H3、人口、夜光和路网。优先用它确认数据年份、记录数和可查询字段。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["scope_datasets.datasets"],
            applicable_scenarios=["需要查询当前范围内全量 POI、cell、H3 或路网明细前先发现可用数据源"],
            cautions=["只表示当前范围数据源，不代表全库；年份缺失时回答必须说明限制"],
            produces=["scope_datasets"],
            input_schema={
                "type": "object",
                "properties": {"history_id": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"datasets": {"type": "array"}, "warnings": {"type": "array"}},
                "required": ["datasets", "warnings"],
                "additionalProperties": False,
            },
            readonly=True,
            cacheable=True,
        ),
        list_scope_datasets,
    )
    registry["query_scope_dataset"] = _register(
        _tool_spec(
            name="query_scope_dataset",
            description="分页读取当前范围数据源的明细记录，并把返回记录转换为 EvidenceNode。只能查询当前 history_id 的数据。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["scope_dataset.records", "scope_dataset.evidence_nodes"],
            applicable_scenarios=["查询当前范围内有哪些 POI、人口或夜光最高 cell、路网指标最高路段、H3 网格明细"],
            cautions=["默认分页，不能把返回页当作全量；只使用 list_scope_datasets 暴露的白名单字段过滤排序"],
            produces=["scope_dataset_evidence_nodes"],
            input_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "enum": SOURCE_ID_ENUM},
                    "filters": FILTER_SCHEMA,
                    "sort": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
                        },
                        "additionalProperties": False,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "offset": {"type": "integer", "minimum": 0},
                    "year": {"type": "integer"},
                    "history_id": {"type": "string"},
                },
                "required": ["source_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "total_count": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                    "records": {"type": "array", "items": SCOPE_DATASET_RECORD_SCHEMA},
                    "evidence_nodes": {"type": "array", "items": EVIDENCE_NODE_SCHEMA},
                    "warnings": {"type": "array"},
                },
                "required": ["source_id", "total_count", "limit", "offset", "has_more", "records", "evidence_nodes", "warnings"],
                "additionalProperties": False,
            },
            readonly=True,
            cacheable=True,
        ),
        query_scope_dataset,
    )
    registry["aggregate_scope_dataset"] = _register(
        _tool_spec(
            name="aggregate_scope_dataset",
            description="对当前范围数据源做受控聚合，例如 POI 按类型计数、人口或夜光 cell 求最大值、路网指标分组统计。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="analyze",
            llm_exposure="primary",
            evidence_contract=["scope_dataset.aggregates"],
            applicable_scenarios=["回答当前范围内有多少、按类别统计、Top 类别、指标均值或最大值"],
            cautions=["聚合结果仍限定当前 history_id；年份缺失或混合时必须说明"],
            produces=["scope_dataset_aggregate"],
            input_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "enum": SOURCE_ID_ENUM},
                    "group_by": {"type": "string"},
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]},
                                "field": {"type": "string"},
                                "as": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "filters": FILTER_SCHEMA,
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                    "year": {"type": "integer"},
                    "history_id": {"type": "string"},
                },
                "required": ["source_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "group_by": {"type": "string"},
                    "total_groups": {"type": "integer"},
                    "rows": {"type": "array"},
                    "warnings": {"type": "array"},
                },
                "required": ["source_id", "group_by", "total_groups", "rows", "warnings"],
                "additionalProperties": False,
            },
            readonly=True,
            cacheable=True,
        ),
        aggregate_scope_dataset,
    )
    registry["read_scope_record"] = _register(
        _tool_spec(
            name="read_scope_record",
            description="按 record_id 读取当前范围 POI、cell、H3 或路网 feature 单条详情，返回完整 EvidenceNode。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["scope_dataset.evidence_node"],
            applicable_scenarios=["回答中需要引用某个具体 POI、cell、H3 或路段时读取完整证据"],
            cautions=["record_id 必须来自 query_scope_dataset 的结果，不能猜测"],
            produces=["scope_dataset_evidence_nodes"],
            input_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "enum": SOURCE_ID_ENUM},
                    "record_id": {"type": "string"},
                    "year": {"type": "integer"},
                    "history_id": {"type": "string"},
                },
                "required": ["source_id", "record_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "record_id": {"type": "string"},
                    "record": {"anyOf": [SCOPE_DATASET_RECORD_SCHEMA, {"type": "object"}]},
                    "evidence_node": {"anyOf": [EVIDENCE_NODE_SCHEMA, {"type": "null"}]},
                    "warnings": {"type": "array"},
                },
                "required": ["source_id", "record_id", "record", "evidence_node", "warnings"],
                "additionalProperties": False,
            },
            readonly=True,
            cacheable=True,
        ),
        read_scope_record,
    )
