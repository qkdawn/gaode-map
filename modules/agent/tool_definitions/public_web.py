from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.public_web_tools import search_public_web


def register_public_web_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["search_public_web"] = _register(
        _tool_spec(
            name="search_public_web",
            description="搜索公开网页并返回候选结果。",
            category="information", layer="L1", ui_tier="foundation", data_domain="general",
            capability_type="fetch", llm_exposure="primary", produces=["public_web_search"],
            input_schema={
                "type": "object",
                "properties": {"history_id": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
                "required": ["query"], "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "provider": {"type": "string"}, "results": {"type": "array", "items": {"type": "string"}}},
                "required": ["query", "provider", "results"], "additionalProperties": False,
            },
            readonly=True, cacheable=False, timeout_sec=60,
        ),
        search_public_web,
    )
