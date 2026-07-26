from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.public_web_tools import search_public_web


def register_public_web_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["search_public_web"] = _register(
        _tool_spec(
            name="search_public_web",
            description="按项目区域和分类检索公开网页，并返回带标题、链接和网页证据摘要的来源。文旅调研按自然、历史、非遗、产业和生活等类别使用，搜索摘要不足时必须保留缺口。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["public_web.sources"],
            produces=["cultural_tourism_web_sources"],
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
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}, "items": {"type": "array"}, "evidence_refs": {"type": "array"}}, "additionalProperties": False},
            readonly=True,
            cacheable=False,
            timeout_sec=30,
        ),
        search_public_web,
    )
