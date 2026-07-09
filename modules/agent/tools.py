from __future__ import annotations

from typing import Dict

from .tool_definitions import (
    RegisteredTool,
    ToolRunner,
    register_business_analyst_tools,
    register_foundation_tools,
    register_retrieval_tools,
    register_scope_dataset_tools,
    register_source_evidence_tools,
)


def get_tool_registry() -> Dict[str, RegisteredTool]:
    registry: Dict[str, RegisteredTool] = {}
    register_foundation_tools(registry)
    register_business_analyst_tools(registry)
    register_source_evidence_tools(registry)
    register_retrieval_tools(registry)
    register_scope_dataset_tools(registry)
    return registry


__all__ = [
    "RegisteredTool",
    "ToolRunner",
    "get_tool_registry",
]
