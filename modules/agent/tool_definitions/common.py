from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

from ..schemas import ToolResult, ToolSpec

ToolRunner = Callable[..., Awaitable[ToolResult]]


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    runner: ToolRunner


def _register(spec: ToolSpec, runner: ToolRunner) -> RegisteredTool:
    return RegisteredTool(spec=spec, runner=runner)


def _tool_spec(
    *,
    name: str,
    description: str,
    category: str,
    layer: str,
    ui_tier: str,
    data_domain: str,
    capability_type: str,
    scene_type: str = "general",
    llm_exposure: str = "secondary",
    toolkit_id: str = "",
    default_policy_key: str = "",
    evidence_contract: List[str] | None = None,
    applicable_scenarios: List[str] | None = None,
    cautions: List[str] | None = None,
    requires: List[str] | None = None,
    produces: List[str] | None = None,
    input_schema: Dict | None = None,
    output_schema: Dict | None = None,
    readonly: bool = False,
    cost_level: str = "safe",
    risk_level: str = "safe",
    timeout_sec: int = 30,
    cacheable: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        category=category,
        layer=layer,
        ui_tier=ui_tier,
        data_domain=data_domain,
        capability_type=capability_type,
        scene_type=scene_type,
        llm_exposure=llm_exposure,
        toolkit_id=toolkit_id,
        default_policy_key=default_policy_key,
        evidence_contract=list(evidence_contract or []),
        applicable_scenarios=list(applicable_scenarios or []),
        cautions=list(cautions or []),
        requires=list(requires or []),
        produces=list(produces or []),
        input_schema=input_schema or {"type": "object", "properties": {}, "additionalProperties": False},
        output_schema=output_schema or {"type": "object", "properties": {}, "additionalProperties": True},
        readonly=readonly,
        cost_level=cost_level,
        risk_level=risk_level,
        timeout_sec=timeout_sec,
        cacheable=cacheable,
    )
