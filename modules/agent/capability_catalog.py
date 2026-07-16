from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .capability_inputs import CapabilityInputResolution, resolve_capability_inputs
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
    input_kind: Literal["current_context", "upstream_artifact"] = "current_context"
    upstream_capability_id: str = ""
    required_artifact_ids: list[str] = Field(default_factory=list)
    selection_modes: list[
        Literal["latest_successful", "specific_run", "recalculate", "ignore_optional"]
    ] = Field(default_factory=list)
    default_selection_mode: Literal[
        "latest_successful", "specific_run", "recalculate", "ignore_optional"
    ] = "latest_successful"

    @model_validator(mode="after")
    def validate_upstream_contract(self):
        if self.input_kind == "current_context":
            if self.upstream_capability_id or self.required_artifact_ids or self.selection_modes:
                raise ValueError("current_context_requirement_has_upstream_configuration")
            return self
        if not self.upstream_capability_id or not self.required_artifact_ids:
            raise ValueError("upstream_requirement_source_contract_required")
        if not self.selection_modes or self.default_selection_mode not in self.selection_modes:
            raise ValueError("upstream_requirement_selection_contract_invalid")
        if self.required and "ignore_optional" in self.selection_modes:
            raise ValueError("required_upstream_requirement_cannot_be_ignored")
        return self


class AnalysisCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str
    category: Literal["planning", "analysis", "delivery", "governance"]
    status: Literal["available", "planned", "unavailable"]
    executor_type: Literal["skill", "service", "none"]
    executor_id: str = ""
    intent_phrases: list[str] = Field(default_factory=list)
    availability_note: str = ""
    activation_requirements: list[str] = Field(default_factory=list)
    input_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    output_contract: list[str] = Field(default_factory=list)
    supports_map: bool = False
    supports_resume: bool = False
    supports_versions: bool = False
    estimated_stages: int = 1
    icon: str
    workspace_kind: Literal["composer", "full"] = "composer"

    @model_validator(mode="after")
    def validate_availability_contract(self):
        if self.status == "available":
            if self.executor_type == "none" or not self.executor_id:
                raise ValueError("available_capability_requires_executor")
            return self
        if self.executor_type != "none" or self.executor_id:
            raise ValueError("non_executable_capability_cannot_register_executor")
        if not self.availability_note or not self.activation_requirements:
            raise ValueError("non_executable_capability_requires_explanation")
        return self


class CapabilityReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    status: Literal["ready", "limited", "blocked", "unavailable"]
    satisfied: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    actions: list[CapabilityAction] = Field(default_factory=list)
    input_resolutions: list[CapabilityInputResolution] = Field(default_factory=list)
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
        intent_phrases=[
            "执行城市更新第一阶段策划",
            "生成城市更新第一阶段报告",
            "生成第一阶段策划报告",
        ],
        input_requirements=[
            CapabilityRequirement(id="project_scope", label="项目空间范围"),
            CapabilityRequirement(id="project_brief", label="项目摘要与决策问题"),
            CapabilityRequirement(id="evidence", label="项目资料或分析证据"),
        ],
        output_contract=[
            "证据节点",
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
        intent_phrases=[
            "生成空间功能策划矩阵",
            "生成空间功能策划决策矩阵",
            "打开空间功能策划矩阵",
        ],
        input_requirements=[
            CapabilityRequirement(id="project_scope", label="项目空间范围"),
            CapabilityRequirement(id="project_brief", label="项目摘要与决策问题"),
            CapabilityRequirement(
                id="stage1_basis",
                label="Stage 1 分析依据",
                input_kind="upstream_artifact",
                upstream_capability_id="urban-strategy-stage1",
                required_artifact_ids=[
                    "stage1-evidence-nodes",
                    "stage1-strategy-options",
                    "stage1-decision-matrix",
                ],
                selection_modes=["latest_successful", "specific_run", "recalculate"],
            ),
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
        intent_phrases=[
            "审计当前项目证据",
            "检查证据闭环",
            "运行证据与结论审计",
        ],
        input_requirements=[
            CapabilityRequirement(id="evidence", label="当前项目证据或分析结果"),
            CapabilityRequirement(
                id="stage1_audit_target",
                label="Stage 1 历史成果",
                required=False,
                input_kind="upstream_artifact",
                upstream_capability_id="urban-strategy-stage1",
                required_artifact_ids=[
                    "stage1-evidence-nodes",
                    "stage1-report",
                    "stage1-run-manifest",
                ],
                selection_modes=[
                    "latest_successful",
                    "specific_run",
                    "recalculate",
                    "ignore_optional",
                ],
                default_selection_mode="ignore_optional",
            ),
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
        intent_phrases=[
            "生成成果PPT",
            "基于分析成果生成PPT",
            "打开PPT工作台",
        ],
        input_requirements=[
            CapabilityRequirement(
                id="approved_report",
                label="已审定报告或分析成果",
                input_kind="upstream_artifact",
                upstream_capability_id="urban-strategy-stage1",
                required_artifact_ids=[
                    "stage1-report",
                    "stage1-evidence-appendix",
                    "stage1-design-handoff",
                ],
                selection_modes=["latest_successful", "specific_run", "recalculate"],
            )
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
        return CapabilityReadiness(
            capability_id=capability.id,
            status="unavailable",
            missing_required=list(capability.activation_requirements),
            conflicts=[capability.availability_note],
        )
    resolved_inputs = resolve_capability_inputs(capability.id, payload)
    if capability.executor_id == "urban-strategy-stage1":
        result: dict[str, Any] = evaluate_readiness(payload)
        if capability.id == "spatial-programming-matrix" and any(
            item.state == "resolved" for item in resolved_inputs.resolutions
        ):
            result["missing"] = [
                item
                for item in result.get("missing", [])
                if item != "核心项目文档或已选分析证据"
            ]
            result["actions"] = [
                item
                for item in result.get("actions", [])
                if item.get("target") != "analysis-sources"
            ]
            if "Stage 1 分析依据" not in result["satisfied"]:
                result["satisfied"].append("Stage 1 分析依据")
            result["ready"] = not result["missing"]
        missing_required = list(result.get("missing") or [])
        missing_optional = list(result.get("missing_optional") or [])
        for item in resolved_inputs.resolutions:
            if item.state in {"resolved", "ignored"}:
                continue
            target = missing_required if item.required else missing_optional
            if item.label not in target:
                target.append(item.label)
        actions = [CapabilityAction(**item) for item in result.get("actions") or []]
        actions.extend(
            CapabilityAction(
                id=f"resolve-{item.requirement_id}",
                label=(
                    f"重新运行{item.label}"
                    if item.selection_mode == "recalculate"
                    else f"选择{item.label}版本"
                ),
                target=f"capability-input:{item.requirement_id}",
            )
            for item in resolved_inputs.resolutions
            if item.state not in {"resolved", "ignored"}
        )
        ready = bool(result["ready"]) and not resolved_inputs.blocking_diagnostics
        return CapabilityReadiness(
            capability_id=capability.id,
            status="ready" if ready else "blocked",
            satisfied=list(result.get("satisfied") or []),
            missing_required=missing_required,
            missing_optional=missing_optional,
            conflicts=[
                *list(result.get("conflicts") or []),
                *resolved_inputs.blocking_diagnostics,
            ],
            actions=actions,
            input_resolutions=resolved_inputs.public_resolutions(),
            limited_mode_allowed=False,
        )
    return CapabilityReadiness(
        capability_id=capability.id,
        status="ready" if not resolved_inputs.blocking_diagnostics else "blocked",
        missing_required=[
            item.label
            for item in resolved_inputs.resolutions
            if item.required and item.state not in {"resolved", "ignored"}
        ],
        missing_optional=[
            item.label
            for item in resolved_inputs.resolutions
            if not item.required and item.state not in {"resolved", "ignored"}
        ],
        conflicts=resolved_inputs.blocking_diagnostics,
        input_resolutions=resolved_inputs.public_resolutions(),
    )
