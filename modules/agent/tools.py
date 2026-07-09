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


MAIN_AGENT_FOUNDATION_TOOLS = {
    "read_current_scope",
    "read_current_results",
}


def get_tool_registry() -> Dict[str, RegisteredTool]:
    registry: Dict[str, RegisteredTool] = {}
    foundation_registry: Dict[str, RegisteredTool] = {}
    register_foundation_tools(foundation_registry)
    registry.update({name: tool for name, tool in foundation_registry.items() if name in MAIN_AGENT_FOUNDATION_TOOLS})
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
