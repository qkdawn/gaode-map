from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.retrieval_tools import (
    read_analysis_evidence_node,
    read_report_evidence_node,
    search_analysis_context,
    search_report_context,
)


EVIDENCE_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "source_id": {"type": "string"},
        "source_type": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "summary": {"type": "string"},
        "metadata": {"type": "object"},
        "locator": {"type": "string"},
        "score": {"type": "number"},
        "evidence_level": {"type": "string"},
        "warnings": {"type": "array"},
        "citation": {"type": "string"},
    },
    "required": ["id", "source_id", "source_type", "title", "content", "summary", "metadata", "locator", "score", "evidence_level", "warnings", "citation"],
    "additionalProperties": False,
}


SEARCH_HITS_SCHEMA = {
    "type": "object",
    "properties": {
        "hits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "source_type": {"type": "string"},
                    "evidence_node": EVIDENCE_NODE_SCHEMA,
                },
                "required": ["node_id", "source_id", "source_type", "evidence_node"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hits"],
    "additionalProperties": False,
}

READ_EVIDENCE_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "node_id": {"type": "string"},
        "source_id": {"type": "string"},
        "source_type": {"type": "string"},
        "evidence_node": EVIDENCE_NODE_SCHEMA,
    },
    "required": ["node_id", "source_id", "source_type", "evidence_node"],
    "additionalProperties": False,
}


def register_retrieval_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["search_analysis_context"] = _register(
        _tool_spec(
            name="search_analysis_context",
            description="搜索当前会话的结构化分析上下文。涉及分析结论时先 search，再用 read_analysis_evidence_node 读取完整 EvidenceNode。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["analysis_context.hits"],
            applicable_scenarios=["按问题检索 H3、POI、人口、夜光、路网、选址候选点证据"],
            cautions=["search 只返回摘要级 EvidenceNode，回答前应按 node_id 读取相关完整 EvidenceNode"],
            produces=["analysis_context_evidence_nodes"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "domains": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["poi", "h3", "population", "nightlight", "road", "site_selection"],
                        },
                    },
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema=SEARCH_HITS_SCHEMA,
            readonly=True,
            cacheable=True,
        ),
        search_analysis_context,
    )
    registry["read_analysis_evidence_node"] = _register(
        _tool_spec(
            name="read_analysis_evidence_node",
            description="按 node_id 读取当前会话的分析 EvidenceNode，返回完整节点、来源和限制说明。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["analysis_context.evidence_node"],
            applicable_scenarios=["读取 search_analysis_context 命中的完整证据节点"],
            produces=["analysis_context_evidence_node"],
            input_schema={
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
                "additionalProperties": False,
            },
            output_schema=READ_EVIDENCE_NODE_SCHEMA,
            readonly=True,
            cacheable=True,
        ),
        read_analysis_evidence_node,
    )
    registry["search_report_context"] = _register(
        _tool_spec(
            name="search_report_context",
            description="搜索当前会话已生成的报告上下文。追问报告结论依据时先 search_report_context，再 read_report_evidence_node 读取完整 EvidenceNode。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["report_context.hits"],
            applicable_scenarios=["检索区域画像、选址报告、审计说明、证据链"],
            cautions=["报告结论不足时应再检索 analysis context 查原始指标"],
            produces=["report_context_evidence_nodes"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema=SEARCH_HITS_SCHEMA,
            readonly=True,
            cacheable=True,
        ),
        search_report_context,
    )
    registry["read_report_evidence_node"] = _register(
        _tool_spec(
            name="read_report_evidence_node",
            description="按 node_id 读取当前会话报告 EvidenceNode，返回完整节点、来源和限制说明。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["report_context.evidence_node"],
            applicable_scenarios=["读取 search_report_context 命中的完整报告证据节点"],
            produces=["report_context_evidence_node"],
            input_schema={
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
                "additionalProperties": False,
            },
            output_schema=READ_EVIDENCE_NODE_SCHEMA,
            readonly=True,
            cacheable=True,
        ),
        read_report_evidence_node,
    )
