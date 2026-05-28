from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.retrieval_tools import (
    read_analysis_chunk,
    read_report_chunk,
    search_analysis_context,
    search_report_context,
)


SEARCH_HITS_SCHEMA = {
    "type": "object",
    "properties": {
        "hits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "title": {"type": "string"},
                    "domain": {"type": "string"},
                    "snippet": {"type": "string"},
                    "evidence_level": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["chunk_id", "title", "domain", "snippet", "evidence_level", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hits"],
    "additionalProperties": False,
}

READ_CHUNK_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "content": {"type": "string"},
        "metrics": {"type": "object"},
        "source_artifacts": {"type": "array"},
        "warnings": {"type": "array"},
    },
    "required": ["title", "content", "metrics", "source_artifacts", "warnings"],
    "additionalProperties": False,
}


def register_retrieval_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["search_analysis_context"] = _register(
        _tool_spec(
            name="search_analysis_context",
            description="搜索当前会话的结构化分析上下文。涉及分析结论时先 search，再用 read_analysis_chunk 读取证据块。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["analysis_context.hits"],
            applicable_scenarios=["按问题检索 H3、POI、人口、夜光、路网、选址候选点证据"],
            cautions=["search 只返回摘要，回答前应读取相关 chunk"],
            produces=["analysis_context_hits"],
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
    registry["read_analysis_chunk"] = _register(
        _tool_spec(
            name="read_analysis_chunk",
            description="按 chunk_id 读取当前会话的分析证据块，返回正文、指标、来源 artifact 和限制说明。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["analysis_context.chunk"],
            applicable_scenarios=["读取 search_analysis_context 命中的证据块"],
            produces=["analysis_context_chunk"],
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
            output_schema=READ_CHUNK_SCHEMA,
            readonly=True,
            cacheable=True,
        ),
        read_analysis_chunk,
    )
    registry["search_report_context"] = _register(
        _tool_spec(
            name="search_report_context",
            description="搜索当前会话已生成的报告上下文。追问报告结论依据时先 search_report_context，再 read_report_chunk。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["report_context.hits"],
            applicable_scenarios=["检索区域画像、选址报告、审计说明、证据链"],
            cautions=["报告结论不足时应再检索 analysis context 查原始指标"],
            produces=["report_context_hits"],
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
    registry["read_report_chunk"] = _register(
        _tool_spec(
            name="read_report_chunk",
            description="按 chunk_id 读取当前会话报告证据块，返回报告段落、来源 artifact 和限制说明。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["report_context.chunk"],
            applicable_scenarios=["读取 search_report_context 命中的报告证据块"],
            produces=["report_context_chunk"],
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
            output_schema=READ_CHUNK_SCHEMA,
            readonly=True,
            cacheable=True,
        ),
        read_report_chunk,
    )
