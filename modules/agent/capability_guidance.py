from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .capability_catalog import (
    CapabilityAction,
    CapabilityReadiness,
    evaluate_capability_readiness,
    list_analysis_capabilities,
)
from .capability_run_service import list_capability_runs
from .capability_runs import CapabilityRun
from .schemas import AgentTurnRequest


CapabilityCardState = Literal[
    "ready",
    "limited",
    "blocked",
    "running",
    "completed",
    "stale",
    "failed",
    "unavailable",
]
RecommendationAction = Literal[
    "inspect_run",
    "resolve_inputs",
    "run",
    "rerun",
    "review_result",
]

_ACTIVE_RUN_STATUSES = {"queued", "running", "waiting_for_user"}
_SUCCESS_RUN_STATUSES = {"completed", "completed_with_warnings"}
_FAILED_RUN_STATUSES = {"failed", "cancelled"}
_WORKFLOW_PRIORITY = {
    "urban-strategy-stage1": 10,
    "spatial-programming-matrix": 20,
    "esri-business-analyst-report": 25,
    "ppt-planning": 30,
    "evidence-audit": 40,
}


class CapabilityWorkbenchCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    state: CapabilityCardState
    readiness: CapabilityReadiness
    latest_run: CapabilityRun | None = None
    run_count: int = 0


class CapabilityRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    action: RecommendationAction
    reason: str
    missing_required: list[str] = Field(default_factory=list)
    actions: list[CapabilityAction] = Field(default_factory=list)
    run_id: str = ""


class CapabilityWorkbenchOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards: list[CapabilityWorkbenchCard] = Field(default_factory=list)
    recent_runs: list[CapabilityRun] = Field(default_factory=list)
    recommendation: CapabilityRecommendation | None = None


def _card_state(
    readiness: CapabilityReadiness,
    latest_run: CapabilityRun | None,
) -> CapabilityCardState:
    if latest_run is not None:
        if latest_run.status in _ACTIVE_RUN_STATUSES:
            return "running"
        if latest_run.status == "stale":
            return "stale"
        if latest_run.status in _FAILED_RUN_STATUSES:
            return "failed"
        if latest_run.status in _SUCCESS_RUN_STATUSES:
            return "completed"
    if readiness.status == "unavailable":
        return "unavailable"
    if readiness.status == "limited":
        return "limited"
    if readiness.status == "ready":
        return "ready"
    return "blocked"


def _recommendation(cards: list[CapabilityWorkbenchCard]) -> CapabilityRecommendation | None:
    if not cards:
        return None

    by_priority = sorted(
        cards,
        key=lambda card: (
            _WORKFLOW_PRIORITY.get(card.capability_id, 999),
            card.capability_id,
        ),
    )
    active = [card for card in cards if card.state == "running" and card.latest_run]
    if active:
        card = max(active, key=lambda item: item.latest_run.created_at)
        return CapabilityRecommendation(
            capability_id=card.capability_id,
            action="inspect_run",
            reason="该能力已有正在执行或等待处理的任务，应先查看当前阶段与诊断，避免重复发起。",
            run_id=card.latest_run.run_id,
        )

    for card in by_priority:
        if card.state == "stale" and card.latest_run:
            changed = "、".join(card.latest_run.stale_input_artifact_ids)
            suffix = f"（{changed}）" if changed else ""
            return CapabilityRecommendation(
                capability_id=card.capability_id,
                action="rerun",
                reason=f"该能力的历史成果所依赖的上游输入已更新{suffix}，建议检查差异后生成新版本。",
                run_id=card.latest_run.run_id,
            )

    for card in by_priority:
        has_success = card.latest_run is not None and card.latest_run.status in _SUCCESS_RUN_STATUSES
        if card.readiness.status == "ready" and not has_success:
            return CapabilityRecommendation(
                capability_id=card.capability_id,
                action="run",
                reason="当前必需输入已就绪，且本项目尚无该能力的成功版本，可进入运行前摘要并确认执行。",
            )

    for card in by_priority:
        if card.readiness.status == "blocked" and card.readiness.missing_required:
            missing = "、".join(card.readiness.missing_required)
            return CapabilityRecommendation(
                capability_id=card.capability_id,
                action="resolve_inputs",
                reason=f"建议先补齐该能力的必需输入：{missing}。完成后系统会重新检查是否可运行。",
                missing_required=list(card.readiness.missing_required),
                actions=list(card.readiness.actions),
            )

    completed = [card for card in cards if card.state == "completed" and card.latest_run]
    if completed:
        card = max(completed, key=lambda item: item.latest_run.completed_at or item.latest_run.created_at)
        return CapabilityRecommendation(
            capability_id=card.capability_id,
            action="review_result",
            reason="当前项目的主要能力已有成功版本，可先复核最新成果、质量诊断和证据，再决定是否重跑或进入下游交付。",
            run_id=card.latest_run.run_id,
        )
    return None


def build_capability_workbench_overview(
    payload: AgentTurnRequest,
) -> CapabilityWorkbenchOverview:
    """Build one project-level capability view with centralized readiness and guidance."""

    runs = list_capability_runs(payload.history_id) if payload.history_id else []
    runs = sorted(
        runs,
        key=lambda run: (run.completed_at or run.created_at, run.run_id),
        reverse=True,
    )
    runs_by_capability: dict[str, list[CapabilityRun]] = {}
    for run in runs:
        runs_by_capability.setdefault(run.capability_id, []).append(run)

    cards: list[CapabilityWorkbenchCard] = []
    for capability in list_analysis_capabilities():
        readiness = evaluate_capability_readiness(capability.id, payload)
        capability_runs = runs_by_capability.get(capability.id, [])
        latest_run = capability_runs[0] if capability_runs else None
        cards.append(
            CapabilityWorkbenchCard(
                capability_id=capability.id,
                state=_card_state(readiness, latest_run),
                readiness=readiness,
                latest_run=latest_run,
                run_count=len(capability_runs),
            )
        )

    return CapabilityWorkbenchOverview(
        cards=cards,
        recent_runs=runs[:5],
        recommendation=_recommendation(cards),
    )
