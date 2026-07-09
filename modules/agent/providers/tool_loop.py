from __future__ import annotations

from typing import Dict, List

from ..tools import RegisteredTool


def llm_visible_registry(registry: Dict[str, RegisteredTool], *, include_secondary: bool = False) -> Dict[str, RegisteredTool]:
    visible: Dict[str, RegisteredTool] = {}
    for name, registered in registry.items():
        exposure = str(registered.spec.llm_exposure or "secondary")
        if exposure == "primary" or (include_secondary and exposure == "secondary"):
            visible[name] = registered
    return visible


def chat_completion_tools(registry: Dict[str, RegisteredTool], *, include_secondary: bool = False) -> List[Dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": registered.spec.description,
                "parameters": registered.spec.input_schema or {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
        for name, registered in llm_visible_registry(registry, include_secondary=include_secondary).items()
    ]
