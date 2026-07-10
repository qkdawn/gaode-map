from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import AgentTurnRequest
from .skills.urban_strategy_stage1 import evaluate_readiness


class CapabilityAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    target: str


class CapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    required: bool = True


class AnalysisCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str
    category: Literal["planning", "analysis", "delivery", "governance"]
    status: Literal["available", "planned", "unavailable"]
    executor_type: Literal["skill", "service"]
    executor_id: str
    input_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    output_contract: list[str] = Field(default_factory=list)
    supports_map: bool = False
    supports_resume: bool = False
    supports_versions: bool = False
    estimated_stages: int = 1
    icon: str
    workspace_kind: Literal["composer", "full"] = "composer"


class CapabilityReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    status: Literal["ready", "limited", "blocked", "unavailable"]
    satisfied: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    actions: list[CapabilityAction] = Field(default_factory=list)
    limited_mode_allowed: bool = False


_CAPABILITIES = (
    AnalysisCapability(
        id="urban-strategy-stage1",
        display_name="城市更新 Stage 1",
        description="从项目证据形成定位竞争、空间功能决策矩阵、策划报告和设计任务书。",
        category="planning",
        status="available",
        executor_type="skill",
        executor_id="urban-strategy-stage1",
        input_requirements=[
            CapabilityRequirement(id="project_scope", label="项目空间范围"),
            CapabilityRequirement(id="project_brief", label="项目摘要与决策问题"),
            CapabilityRequirement(id="evidence", label="项目资料或分析证据"),
        ],
        output_contract=[
            "证据台账",
            "定位方案与反证",
            "空间功能决策矩阵",
            "Stage 1 报告",
            "质量审计",
        ],
        supports_map=True,
        supports_resume=True,
        supports_versions=True,
        estimated_stages=6,
        icon="landmark",
        workspace_kind="full",
    ),
    AnalysisCapability(
        id="spatial-programming-matrix",
        display_name="空间功能策划矩阵",
        description="比较关键空间的候选功能、成立条件、排除理由和实施约束。",
        category="planning",
        status="available",
        executor_type="skill",
        executor_id="urban-strategy-stage1",
        input_requirements=[
            CapabilityRequirement(id="evidence", label="项目资料或分析证据")
        ],
        output_contract=["空间诊断", "候选功能比较", "组合与时序检查"],
        supports_map=True,
        supports_resume=True,
        estimated_stages=4,
        icon="layout-grid",
        workspace_kind="full",
    ),
    AnalysisCapability(
        id="evidence-audit",
        display_name="证据与结论审计",
        description="检查结论来源、比较基准、代理指标越界、冲突和待核验任务。",
        category="governance",
        status="available",
        executor_type="skill",
        executor_id="urban-strategy-stage1",
        input_requirements=[
            CapabilityRequirement(id="evidence", label="待审计证据或分析结果")
        ],
        output_contract=["Claim-Evidence 台账", "质量问题", "验证任务"],
        supports_resume=True,
        estimated_stages=3,
        icon="shield-check",
    ),
    AnalysisCapability(
        id="ppt-planning",
        display_name="成果 PPT",
        description="将已审定的分析成果组织为可编辑演示文稿。",
        category="delivery",
        status="available",
        executor_type="service",
        executor_id="ppt-planning",
        input_requirements=[
            CapabilityRequirement(id="approved_report", label="已审定报告或分析成果")
        ],
        output_contract=["叙事结构", "页面规格", "可编辑 PPT"],
        supports_resume=True,
        supports_versions=True,
        estimated_stages=4,
        icon="presentation",
        workspace_kind="full",
    ),
)


def list_analysis_capabilities() -> list[AnalysisCapability]:
    return [item.model_copy(deep=True) for item in _CAPABILITIES]


def get_analysis_capability(capability_id: str) -> AnalysisCapability:
    item = next((item for item in _CAPABILITIES if item.id == capability_id), None)
    if item is None:
        raise ValueError(f"未知分析能力：{capability_id}")
    return item.model_copy(deep=True)


def evaluate_capability_readiness(
    capability_id: str, payload: AgentTurnRequest
) -> CapabilityReadiness:
    capability = get_analysis_capability(capability_id)
    if capability.status != "available":
        return CapabilityReadiness(capability_id=capability.id, status="unavailable")
    if capability.executor_id == "urban-strategy-stage1":
        result: dict[str, Any] = evaluate_readiness(payload)
        return CapabilityReadiness(
            capability_id=capability.id,
            status="ready" if result["ready"] else "blocked",
            satisfied=list(result.get("satisfied") or []),
            missing_required=list(result.get("missing") or []),
            missing_optional=list(result.get("missing_optional") or []),
            conflicts=list(result.get("conflicts") or []),
            actions=[CapabilityAction(**item) for item in result.get("actions") or []],
            limited_mode_allowed=False,
        )
