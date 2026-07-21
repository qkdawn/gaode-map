from __future__ import annotations

from copy import deepcopy
from typing import Any

from .analysis_runs import (
    AnalysisArtifactSnapshot,
    AnalysisRun,
    AnalysisRunDetail,
    build_metric_plan_diagnostics,
)
from .schemas import AgentTurnRequest, AgentTurnResponse
from store.analysis_run_repo import analysis_run_repo

_STALE_ELIGIBLE_STATUSES = {"completed", "completed_with_warnings"}
_CODEX_ONLY_CAPABILITIES = {"spatial-business-analyst"}


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _artifact_payloads(
    response: AgentTurnResponse,
    run: AnalysisRun,
) -> dict[str, Any]:
    panels = _mapping(response.output.panel_payloads)
    deliverables = _mapping(panels.get("stage1_deliverables"))
    payloads: dict[str, Any] = {
        "stage1-project-brief": panels.get("stage1_project_brief"),
        "stage1-source-readiness": panels.get("stage1_readiness"),
        "stage1-evidence-nodes": panels.get("stage1_evidence_nodes"),
        "stage1-conflict-register": panels.get("stage1_conflict_register"),
        "stage1-hard-constraint-screening": panels.get(
            "stage1_hard_constraint_screening"
        ),
        "stage1-quality-audit": panels.get("stage1_quality_audit"),
        "stage1-strategy-options": panels.get("stage1_strategy"),
        "stage1-decision-matrix": panels.get("stage1_spatial_matrix"),
        "stage1-spatial-object-registry": panels.get(
            "stage1_spatial_object_registry"
        ),
        "stage1-report": deliverables.get("report_markdown")
        or response.output.answer,
        "stage1-evidence-appendix": deliverables.get(
            "evidence_appendix_markdown"
        ),
        "stage1-design-handoff": deliverables.get("design_handoff"),
        "stage1-run-manifest": run.model_dump(mode="json"),
    }
    output_ids = {item.artifact_id for item in run.output_artifact_refs}
    return {
        artifact_id: deepcopy(payload)
        for artifact_id, payload in payloads.items()
        if artifact_id in output_ids and payload is not None
    }


def persist_analysis_run_response(
    payload: AgentTurnRequest,
    response: AgentTurnResponse,
    *,
    repo=analysis_run_repo,
) -> AgentTurnResponse:
    """Persist runs only for capabilities owned by the application runtime."""
    manifest = _mapping(response.output.panel_payloads.get("analysis_run"))
    history_id = str(
        payload.history_id
        or manifest.get("configuration_snapshot", {}).get("history_id")
        or ""
    ).strip()
    if not manifest or not history_id:
        return response
    if str(manifest.get("capability_id") or "") in _CODEX_ONLY_CAPABILITIES:
        return response
    run = AnalysisRun.model_validate(manifest)
    repo.save(
        history_id=history_id,
        manifest=run.model_dump(mode="json"),
        artifact_payloads=_artifact_payloads(response, run),
        execution_request=payload.model_dump(mode="json"),
    )
    return response


def _mark_stale(
    run: AnalysisRun,
    *,
    history_id: str,
    repo,
) -> AnalysisRun:
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
    return run.model_copy(
        update={
            "status": "stale",
            "stale_input_artifact_ids": changed,
            "diagnostics": [
                *run.diagnostics,
                f"上游输入已更新：{'、'.join(changed)}。历史结果保留，但重新运行前不应作为最新结论。",
            ],
        },
        deep=True,
    )


def list_analysis_runs(
    history_id: str,
    *,
    capability_id: str = "",
    repo=analysis_run_repo,
) -> list[AnalysisRun]:
    runs: list[AnalysisRun] = []
    for manifest in repo.list(history_id, capability_id=capability_id):
        if str(manifest.get("capability_id") or "") in _CODEX_ONLY_CAPABILITIES:
            continue
        run = AnalysisRun.model_validate(manifest)
        runs.append(_mark_stale(run, history_id=history_id, repo=repo))
    return runs


def get_analysis_run(
    run_id: str,
    *,
    repo=analysis_run_repo,
) -> AnalysisRunDetail | None:
    payload = repo.get(run_id)
    if not isinstance(payload, dict):
        return None
    manifest = _mapping(payload.get("run"))
    if str(manifest.get("capability_id") or "") in _CODEX_ONLY_CAPABILITIES:
        return None
    history_id = str(payload.get("history_id") or "")
    run = _mark_stale(
        AnalysisRun.model_validate(manifest),
        history_id=history_id,
        repo=repo,
    )
    snapshots = [
        AnalysisArtifactSnapshot.model_validate(item)
        for item in payload.get("artifacts") or []
    ]
    return AnalysisRunDetail(
        history_id=history_id,
        run=run,
        artifacts=snapshots,
        metric_plan_diagnostics=build_metric_plan_diagnostics(run),
    )
