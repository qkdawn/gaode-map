from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.public_web_tools import search_public_web


def register_public_web_tools(registry: Dict[str, RegisteredTool]) -> None:
    source_item_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "url": {"type": "string"},
            "publisher": {"type": "string"},
            "publication_date": {"type": "string"},
            "access_date": {"type": "string"},
            "query": {"type": "string"},
            "research_category": {"type": "string"},
            "original_excerpt": {"type": "string"},
            "applicable_scope": {"type": "string"},
            "inference_boundary": {"type": "string"},
            "search_attempt": {"type": "object"},
        },
        "required": [
            "title", "url", "publisher", "publication_date", "access_date", "query",
            "research_category", "original_excerpt", "applicable_scope", "inference_boundary",
            "search_attempt",
        ],
    }
    registry["search_public_web"] = _register(
        _tool_spec(
            name="search_public_web",
            description="按项目区域和资料类别检索公开网页。每个类别最多依次执行原始查询、行政区+主题重组、机构/来源替代三轮；网页无结果也是成功的研究状态，返回覆盖结论与检索记录。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["public_web.sources", "public_web.coverage"],
            produces=["public_web_sources"],
            input_schema={
                "type": "object",
                "properties": {
                    "area_id": {"type": "string"},
                    "history_id": {"type": "string"},
                    "region_name": {"type": "string"},
                    "administrative_area": {"type": "string"},
                    "topic": {"type": "string"},
                    "intent": {"type": "string"},
                    "categories": {"type": "array", "items": {"type": "string"}},
                    "source_modes": {"type": "array", "items": {"type": "string"}},
                    "urls": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "items": {"type": "array", "items": source_item_schema},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "coverage_status": {"type": "string", "enum": ["usable_sources_found", "searched_no_usable_source", "failed"]},
                    "attempts": {"type": "array", "items": {"type": "object"}},
                    "category_coverage": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["summary", "items", "evidence_refs", "coverage_status", "attempts", "category_coverage"],
                "additionalProperties": False,
            },
            readonly=True,
            cacheable=False,
            timeout_sec=180,
        ),
        search_public_web,
    )
