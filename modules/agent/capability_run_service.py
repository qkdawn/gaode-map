from __future__ import annotations

from copy import deepcopy
from typing import Any

from .capability_run_comparison import CapabilityRunComparison, compare_run_details
from .capability_runs import CapabilityRun, CapabilityRunDetail
from .schemas import AgentTurnRequest, AgentTurnResponse
from store.capability_run_repo import capability_run_repo

_STALE_ELIGIBLE_STATUSES = {"completed", "completed_with_warnings"}


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _artifact_payloads(
    response: AgentTurnResponse, run: CapabilityRun
) -> dict[str, Any]:
    panels = _mapping(response.output.panel_payloads)
    deliverables = _mapping(panels.get("stage1_deliverables"))
    payloads: dict[str, Any] = {
        "stage1-project-brief": panels.get("stage1_project_brief"),
        "stage1-source-readiness": panels.get("stage1_readiness"),
        "stage1-evidence-ledger": panels.get("stage1_evidence_ledger"),
        "stage1-conflict-register": panels.get("stage1_conflict_register"),
        "stage1-hard-constraint-screening": panels.get("stage1_hard_constraint_screening"),
        "stage1-quality-audit": panels.get("stage1_quality_audit"),
        "stage1-strategy-options": panels.get("stage1_strategy"),
        "stage1-decision-matrix": panels.get("stage1_spatial_matrix"),
        "stage1-spatial-object-registry": panels.get("stage1_spatial_object_registry"),
        "stage1-report": deliverables.get("report_markdown") or response.output.answer,
        "stage1-evidence-appendix": deliverables.get("evidence_appendix_markdown"),
        "stage1-design-handoff": deliverables.get("design_handoff"),
        "stage1-run-manifest": run.model_dump(mode="json"),
    }
    for index, workpack in enumerate(panels.get("stage1_workpacks") or []):
        if not isinstance(workpack, dict):
            continue
        workpack_type = str(workpack.get("type") or f"workpack-{index + 1}").strip()
        payloads[f"stage1-workpack-{workpack_type}"] = deepcopy(workpack)
    output_ids = {item.artifact_id for item in run.output_artifact_refs}
    return {
        artifact_id: deepcopy(payload)
        for artifact_id, payload in payloads.items()
        if artifact_id in output_ids and payload is not None
    }


def persist_capability_run_response(
    payload: AgentTurnRequest,
    response: AgentTurnResponse,
    *,
    repo=capability_run_repo,
) -> AgentTurnResponse:
    """Persist a capability run and its resolved artifact payloads exactly once."""

    manifest = _mapping(response.output.panel_payloads.get("capability_run"))
    history_id = str(
        payload.history_id
        or manifest.get("configuration_snapshot", {}).get("history_id")
        or ""
    ).strip()
    if not manifest or not history_id:
        return response
    run = CapabilityRun(**manifest)
    repo.save(
        history_id=history_id,
        manifest=run.model_dump(mode="json"),
        artifact_payloads=_artifact_payloads(response, run),
    )
    return response


def _mark_stale(run: CapabilityRun, *, history_id: str, repo) -> CapabilityRun:
    if run.status not in _STALE_ELIGIBLE_STATUSES:
        return run
    changed = repo.changed_input_artifact_ids(
        history_id=history_id,
        run_id=run.run_id,
        input_artifacts=[
            item.model_dump(mode="json") for item in run.input_artifact_refs
        ],
    )
    if not changed:
        return run
    message = f"上游输入已更新：{'、'.join(changed)}。历史结果保留，但重新运行前不应作为最新结论。"
    return run.model_copy(
        update={
            "status": "stale",
            "stale_input_artifact_ids": changed,
            "diagnostics": [*run.diagnostics, message],
        },
        deep=True,
    )


def list_capability_runs(
    history_id: str,
    *,
    capability_id: str = "",
    repo=capability_run_repo,
) -> list[CapabilityRun]:
    manifests = repo.list(history_id, capability_id=capability_id)
    return [
        _mark_stale(CapabilityRun(**item), history_id=history_id, repo=repo)
        for item in manifests
    ]


def get_capability_run(
    run_id: str,
    *,
    repo=capability_run_repo,
) -> CapabilityRunDetail | None:
    payload = repo.get(run_id)
    if not isinstance(payload, dict):
        return None
    detail = CapabilityRunDetail(**payload)
    return detail.model_copy(
        update={
            "run": _mark_stale(detail.run, history_id=detail.history_id, repo=repo),
        },
        deep=True,
    )

def compare_capability_runs(
    base_run_id: str,
    target_run_id: str,
    *,
    repo=capability_run_repo,
) -> CapabilityRunComparison | None:
    """Compare two immutable Runs only when both records exist."""

    base = get_capability_run(base_run_id, repo=repo)
    target = get_capability_run(target_run_id, repo=repo)
    if base is None or target is None:
        return None
    return compare_run_details(base, target)
