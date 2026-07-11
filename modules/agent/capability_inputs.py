from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .capability_runs import CapabilityArtifactRef, CapabilityArtifactSnapshot
from .schemas import AgentTurnRequest, CapabilityInputSelection

_RESOLVABLE_STATUSES = {"completed", "completed_with_warnings"}


class CapabilityInputVersionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    created_at: str = ""
    completed_at: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    stale: bool = False


class CapabilityInputResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    label: str
    required: bool
    upstream_capability_id: str
    selection_mode: Literal[
        "latest_successful", "specific_run", "recalculate", "ignore_optional"
    ]
    state: Literal[
        "resolved", "missing", "invalid", "recalculate_required", "ignored"
    ]
    selected_run_id: str = ""
    artifact_refs: list[CapabilityArtifactRef] = Field(default_factory=list)
    available_versions: list[CapabilityInputVersionOption] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ResolvedCapabilityInputs(BaseModel):
    """Resolved upstream versions plus private immutable payloads for execution."""

    model_config = ConfigDict(extra="forbid")

    resolutions: list[CapabilityInputResolution] = Field(default_factory=list)
    blocking_diagnostics: list[str] = Field(default_factory=list)
    artifact_payloads: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @property
    def input_artifact_refs(self) -> list[CapabilityArtifactRef]:
        return [
            item.model_copy(deep=True)
            for resolution in self.resolutions
            for item in resolution.artifact_refs
        ]

    def public_resolutions(self) -> list[CapabilityInputResolution]:
        return [item.model_copy(deep=True) for item in self.resolutions]

    def configuration_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "requirement_id": item.requirement_id,
                "selection_mode": item.selection_mode,
                "selected_run_id": item.selected_run_id,
                "state": item.state,
                "artifact_ids": [ref.artifact_id for ref in item.artifact_refs],
            }
            for item in self.resolutions
        ]


def _selection_map(payload: AgentTurnRequest) -> tuple[dict[str, CapabilityInputSelection], list[str]]:
    selections: dict[str, CapabilityInputSelection] = {}
    diagnostics: list[str] = []
    for item in payload.capability_input_selections:
        if item.requirement_id in selections:
            diagnostics.append(f"上游输入 {item.requirement_id} 被重复选择。")
            continue
        selections[item.requirement_id] = item
    return selections, diagnostics


def _artifact_snapshots(detail: Any, artifact_ids: set[str]) -> list[CapabilityArtifactSnapshot]:
    return [
        item
        for item in detail.artifacts
        if item.direction == "output" and item.artifact.artifact_id in artifact_ids
    ]


def _run_artifact_ids(run: Any) -> set[str]:
    return {str(item.artifact_id) for item in run.output_artifact_refs}


def _version_options(
    runs: list[Any], required_artifact_ids: list[str]
) -> list[CapabilityInputVersionOption]:
    required = set(required_artifact_ids)
    return [
        CapabilityInputVersionOption(
            run_id=run.run_id,
            status=run.status,
            created_at=run.created_at,
            completed_at=run.completed_at,
            artifact_ids=list(required_artifact_ids),
            stale=run.status == "stale",
        )
        for run in runs
        if run.status in {*_RESOLVABLE_STATUSES, "stale"}
        and required.issubset(_run_artifact_ids(run))
    ]


def resolve_capability_inputs(
    capability_id: str,
    payload: AgentTurnRequest,
    *,
    list_runs=None,
    get_run=None,
) -> ResolvedCapabilityInputs:
    """Resolve every upstream requirement without exposing repository/file rules to callers."""

    from .capability_catalog import get_analysis_capability

    if list_runs is None or get_run is None:
        from .capability_run_service import get_capability_run, list_capability_runs

        list_runs = list_runs or list_capability_runs
        get_run = get_run or get_capability_run

    capability = get_analysis_capability(capability_id)
    requirements = [
        item for item in capability.input_requirements if item.input_kind == "upstream_artifact"
    ]
    if not requirements:
        return ResolvedCapabilityInputs()

    selection_by_id, blocking = _selection_map(payload)
    unknown = sorted(set(selection_by_id) - {item.id for item in requirements})
    blocking.extend(f"未知上游输入要求：{item}。" for item in unknown)
    resolutions: list[CapabilityInputResolution] = []
    payloads: dict[str, Any] = {}

    for requirement in requirements:
        selection = selection_by_id.get(requirement.id) or CapabilityInputSelection(
            requirement_id=requirement.id,
            mode=requirement.default_selection_mode,
        )
        required_artifact_ids = list(requirement.required_artifact_ids)
        artifact_ids = set(required_artifact_ids)
        common = {
            "requirement_id": requirement.id,
            "label": requirement.label,
            "required": requirement.required,
            "upstream_capability_id": requirement.upstream_capability_id,
            "selection_mode": selection.mode,
            "available_versions": [],
        }
        if selection.mode not in requirement.selection_modes:
            diagnostic = f"“{requirement.label}”不支持选择方式 {selection.mode}。"
            blocking.append(diagnostic)
            resolutions.append(
                CapabilityInputResolution(**common, state="invalid", diagnostics=[diagnostic])
            )
            continue

        if selection.mode == "ignore_optional":
            if requirement.required:
                diagnostic = f"必需输入“{requirement.label}”不能忽略。"
                blocking.append(diagnostic)
                resolutions.append(CapabilityInputResolution(**common, state="invalid", diagnostics=[diagnostic]))
            else:
                resolutions.append(CapabilityInputResolution(**common, state="ignored"))
            continue

        if selection.mode == "recalculate":
            diagnostic = f"需先重新运行“{requirement.label}”的上游能力。"
            blocking.append(diagnostic)
            resolutions.append(
                CapabilityInputResolution(
                    **common,
                    state="recalculate_required",
                    diagnostics=[diagnostic],
                )
            )
            continue

        runs = list_runs(
            payload.history_id,
            capability_id=requirement.upstream_capability_id,
        ) if payload.history_id else []
        common["available_versions"] = _version_options(runs, required_artifact_ids)
        selected_run = None
        detail = None
        if selection.mode == "specific_run":
            detail = get_run(selection.run_id)
            if (
                detail is None
                or detail.history_id != payload.history_id
                or detail.run.capability_id != requirement.upstream_capability_id
                or detail.run.status not in {*_RESOLVABLE_STATUSES, "stale"}
                or not artifact_ids.issubset(_run_artifact_ids(detail.run))
            ):
                diagnostic = f"指定版本不能作为“{requirement.label}”的输入。"
                blocking.append(diagnostic)
                resolutions.append(
                    CapabilityInputResolution(
                        **common, state="invalid", diagnostics=[diagnostic]
                    )
                )
                continue
            selected_run = detail.run
        else:
            for candidate in runs:
                if candidate.status not in _RESOLVABLE_STATUSES:
                    continue
                if not artifact_ids.issubset(_run_artifact_ids(candidate)):
                    continue
                candidate_detail = get_run(candidate.run_id)
                if candidate_detail is None:
                    continue
                candidate_snapshots = _artifact_snapshots(candidate_detail, artifact_ids)
                if {item.artifact.artifact_id for item in candidate_snapshots} == artifact_ids:
                    selected_run = candidate
                    detail = candidate_detail
                    break

        if selected_run is None or detail is None:
            diagnostic = f"“{requirement.label}”没有可用的成功版本。"
            if requirement.required:
                blocking.append(diagnostic)
            resolutions.append(CapabilityInputResolution(**common, state="missing", diagnostics=[diagnostic]))
            continue

        snapshots = _artifact_snapshots(detail, artifact_ids)
        snapshot_ids = {item.artifact.artifact_id for item in snapshots}
        if snapshot_ids != artifact_ids:
            missing_ids = [
                artifact_id
                for artifact_id in required_artifact_ids
                if artifact_id not in snapshot_ids
            ]
            diagnostic = (
                f"版本 {selected_run.run_id} 缺少“{requirement.label}”要求的产物："
                f"{', '.join(missing_ids)}。"
            )
            if requirement.required:
                blocking.append(diagnostic)
            resolutions.append(CapabilityInputResolution(**common, state="missing", selected_run_id=selected_run.run_id, diagnostics=[diagnostic]))
            continue

        diagnostics = []
        if selected_run.status == "stale":
            diagnostics.append("已显式选择过期历史版本；该版本仅代表当时输入快照。")
        refs = [item.artifact.model_copy(deep=True) for item in snapshots]
        for item in snapshots:
            payloads[f"{selected_run.run_id}:{item.artifact.artifact_id}"] = deepcopy(item.payload)
        resolutions.append(
            CapabilityInputResolution(
                **common,
                state="resolved",
                selected_run_id=selected_run.run_id,
                artifact_refs=refs,
                diagnostics=diagnostics,
            )
        )

    return ResolvedCapabilityInputs(
        resolutions=resolutions,
        blocking_diagnostics=blocking,
        artifact_payloads=payloads,
    )
