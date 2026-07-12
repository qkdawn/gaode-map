from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .quality_audit import AuditIssue, QualityAuditResult
from .stage1_hard_constraints import build_hard_constraint_screening
from .stage1_spatial_matrix import (
    SpatialMatrixContractError,
    compile_spatial_programming_matrix,
)

RepairScope = Literal["workpacks", "strategy", "spatial_matrix"]


class Stage1RepairTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    scope: RepairScope
    message: str
    repair_instruction: str


class Stage1RepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_needed", "automatic", "external_input_required"]
    attempt_limit: int = Field(default=1, ge=0, le=1)
    automatic_tasks: list[Stage1RepairTask] = Field(default_factory=list)
    external_issues: list[AuditIssue] = Field(default_factory=list)

    @property
    def can_run_automatically(self) -> bool:
        return self.status == "automatic" and bool(self.automatic_tasks)


@dataclass(frozen=True)
class Stage1RepairCandidate:
    workpacks: list[dict[str, Any]]
    hard_constraint_screening: dict[str, Any]
    strategy: dict[str, Any]
    spatial_matrix: dict[str, Any]


class Stage1RepairContractError(ValueError):
    def __init__(self, diagnostics: list[str]):
        self.diagnostics = diagnostics
        super().__init__("；".join(diagnostics))


_REPAIR_SCOPE_BY_CODE: dict[str, RepairScope] = {
    "workpacks_incomplete": "workpacks",
    "hard_constraint_screening_invalid": "workpacks",
    "strategy_competition_missing": "strategy",
    "strategy_falsification_missing": "strategy",
    "decision_evidence_strength_invalid": "strategy",
    "matrix_positioning_mismatch": "spatial_matrix",
    "hard_constraint_application_invalid": "spatial_matrix",
    "space_decisions_incomplete": "spatial_matrix",
    "space_design_handoff_incomplete": "spatial_matrix",
    "portfolio_check_missing": "spatial_matrix",
    "spatial_hierarchy_invalid": "spatial_matrix",
    "spatial_decision_map_dimensions_missing": "spatial_matrix",
    "spatial_map_presentation_incomplete": "spatial_matrix",
    "spatial_movement_systems_incomplete": "spatial_matrix",
    "spatial_movement_references_invalid": "spatial_matrix",
    "spatial_movement_presentation_incomplete": "spatial_matrix",
    "spatial_map_binding_invalid": "spatial_matrix",
    "evidence_reference_invalid": "spatial_matrix",
    "proxy_overreach": "strategy",
}


def build_stage1_repair_plan(audit: QualityAuditResult) -> Stage1RepairPlan:
    blocking = audit.blocking_issues
    if not blocking:
        return Stage1RepairPlan(status="not_needed", attempt_limit=0)

    automatic_tasks: list[Stage1RepairTask] = []
    external_issues: list[AuditIssue] = []
    seen: set[tuple[str, str]] = set()
    for issue in blocking:
        scope = _REPAIR_SCOPE_BY_CODE.get(issue.code)
        if scope is None:
            external_issues.append(issue)
            continue
        key = (issue.code, scope)
        if key in seen:
            continue
        seen.add(key)
        automatic_tasks.append(
            Stage1RepairTask(
                code=issue.code,
                scope=scope,
                message=issue.message,
                repair_instruction=issue.repair_hint or issue.message,
            )
        )

    # Do not let a model rewrite around missing evidence, unresolved provenance,
    # authoritative geometry gaps, or fieldwork. Mixed failures remain external.
    if external_issues or not automatic_tasks:
        return Stage1RepairPlan(
            status="external_input_required",
            attempt_limit=0,
            automatic_tasks=automatic_tasks,
            external_issues=external_issues,
        )
    return Stage1RepairPlan(
        status="automatic",
        automatic_tasks=automatic_tasks,
    )


def compile_stage1_repair_candidate(
    payload: Any,
    *,
    evidence_ids: set[str],
    spatial_object_registry: dict[str, dict[str, Any]],
) -> Stage1RepairCandidate:
    node = dict(payload) if isinstance(payload, dict) else {}
    diagnostics: list[str] = []

    raw_workpacks = node.get("workpacks")
    workpacks = (
        [dict(item) for item in raw_workpacks if isinstance(item, dict)]
        if isinstance(raw_workpacks, list)
        else []
    )
    if not workpacks:
        diagnostics.append("修复结果缺少 workpacks。")

    raw_strategy = node.get("strategy")
    strategy = dict(raw_strategy) if isinstance(raw_strategy, dict) else {}
    if not strategy:
        diagnostics.append("修复结果缺少 strategy。")

    if not isinstance(node.get("hard_constraint_screening"), (dict, list)):
        diagnostics.append("修复结果缺少 hard_constraint_screening。")
    hard_constraint_screening = build_hard_constraint_screening(
        node.get("hard_constraint_screening"),
        evidence_ids=evidence_ids,
    ).model_dump(mode="json")

    raw_matrix = node.get("spatial_matrix")
    if not isinstance(raw_matrix, dict):
        diagnostics.append("修复结果缺少 spatial_matrix。")
        spatial_matrix: dict[str, Any] = {}
    else:
        try:
            spatial_matrix = compile_spatial_programming_matrix(
                raw_matrix,
                spatial_object_registry,
            )
        except SpatialMatrixContractError as error:
            diagnostics.extend(error.diagnostics)
            spatial_matrix = {}

    if diagnostics:
        raise Stage1RepairContractError(diagnostics)
    return Stage1RepairCandidate(
        workpacks=workpacks,
        hard_constraint_screening=hard_constraint_screening,
        strategy=strategy,
        spatial_matrix=spatial_matrix,
    )
