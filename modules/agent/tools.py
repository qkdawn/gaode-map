from __future__ import annotations

from typing import Dict

from .tool_definitions import (
    RegisteredTool,
    ToolRunner,
    register_analysis_business_tools,
    register_capability_tools,
    register_foundation_tools,
    register_retrieval_tools,
    register_scenario_tools,
)


def get_tool_registry() -> Dict[str, RegisteredTool]:
    registry: Dict[str, RegisteredTool] = {}
    register_foundation_tools(registry)
    register_retrieval_tools(registry)
    register_capability_tools(registry)
    register_scenario_tools(registry)
    register_analysis_business_tools(registry)
    return registry


__all__ = [
    "RegisteredTool",
    "ToolRunner",
    "get_tool_registry",
]
