from __future__ import annotations

from copy import deepcopy
from typing import Any

from .analysis_run_comparison import AnalysisRunComparison, compare_run_details
from .analysis_runs import (
    AnalysisArtifactSnapshot,
    AnalysisRun,
    AnalysisRunDetail,
    AnalysisRunReadDetail,
    AnalysisRunV3,
    AnalysisRunV3Detail,
    EvidenceExecutionDiagnostics,
    LegacyAnalysisRunView,
    LegacyAnalysisRunV2View,
    build_metric_plan_diagnostics,
)
from .schemas import AgentTurnRequest, AgentTurnResponse
from store.analysis_run_repo import analysis_run_repo

_STALE_ELIGIBLE_STATUSES = {"completed", "completed_with_warnings"}


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _artifact_payloads(
    response: AgentTurnResponse, run: AnalysisRunV3 | AnalysisRun
) -> dict[str, Any]:
    panels = _mapping(response.output.panel_payloads)
    deliverables = _mapping(panels.get("stage1_deliverables"))
    payloads: dict[str, Any] = {
        "stage1-project-brief": panels.get("stage1_project_brief"),
        "stage1-source-readiness": panels.get("stage1_readiness"),
        "stage1-evidence-nodes": panels.get("stage1_evidence_nodes"),
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


def persist_analysis_run_response(
    payload: AgentTurnRequest,
    response: AgentTurnResponse,
    *,
    repo=analysis_run_repo,
) -> AgentTurnResponse:
    """Persist a capability run and its resolved artifact payloads exactly once."""

    manifest = _mapping(response.output.panel_payloads.get("analysis_run"))
    history_id = str(
        payload.history_id
        or manifest.get("configuration_snapshot", {}).get("history_id")
        or ""
    ).strip()
    if not manifest or not history_id:
        return response
    # The six-object report capability writes only v3. Other capability-owned
    # Run contracts migrate independently and must not be forced to fabricate
    # spatial report root artifacts.
    if str(manifest.get("capability_id") or "") == "spatial-business-analyst":
        run: AnalysisRunV3 | AnalysisRun = AnalysisRunV3(**manifest)
    elif _schema_v2(manifest):
        run = AnalysisRun(**manifest)
    else:
        run = AnalysisRunV3(**manifest)
    repo.save(
        history_id=history_id,
        manifest=run.model_dump(mode="json"),
        artifact_payloads=_artifact_payloads(response, run),
        execution_request=payload.model_dump(mode="json"),
    )
    return response


def _mark_stale(run: AnalysisRunV3, *, history_id: str, repo) -> AnalysisRunV3:
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


def _schema_v2(manifest: dict[str, Any]) -> bool:
    version = str(manifest.get("schema_version") or "")
    if version:
        return version == "2.0"
    try:
        AnalysisRun.model_validate(manifest)
    except (ValueError, TypeError):
        return False
    return True


def _schema_v3(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("schema_version") or "") == "3.0"


def _legacy_view(manifest: dict[str, Any]) -> LegacyAnalysisRunView:
    return LegacyAnalysisRunView.model_validate(
        {**deepcopy(manifest), "schema_version": "1.0", "read_only": True}
    )


def _legacy_v2_view(
    manifest: dict[str, Any], *, history_id: str, repo
) -> LegacyAnalysisRunV2View:
    payload = {**deepcopy(manifest), "schema_version": "2.0", "read_only": True}
    status = str(payload.get("status") or "")
    if status in _STALE_ELIGIBLE_STATUSES:
        changed = repo.changed_input_artifact_ids(
            history_id=history_id,
            run_id=str(payload.get("run_id") or ""),
            input_artifacts=list(payload.get("input_artifact_refs") or []),
        )
        if changed:
            payload["status"] = "stale"
            payload["stale_input_artifact_ids"] = changed
            payload["diagnostics"] = [
                *list(payload.get("diagnostics") or []),
                f"上游输入已更新：{'、'.join(changed)}。该 v2 Run 仅供历史审计。",
            ]
    return LegacyAnalysisRunV2View.model_validate(payload)


def _evidence_diagnostics(
    artifacts: list[AnalysisArtifactSnapshot],
) -> EvidenceExecutionDiagnostics:
    evidence_snapshot: dict[str, Any] = {}
    editorial_review: dict[str, Any] = {}
    for snapshot in artifacts:
        if snapshot.direction != "output" or not isinstance(snapshot.payload, dict):
            continue
        if snapshot.artifact.artifact_type == "evidence_snapshot":
            evidence_snapshot = snapshot.payload
        elif snapshot.artifact.artifact_type == "editorial_review":
            editorial_review = snapshot.payload
    lineage = evidence_snapshot.get("execution_lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    attempts = lineage.get("attempts")
    attempts = attempts if isinstance(attempts, list) else []
    status_counts: dict[str, int] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        status = str(attempt.get("execution_status") or attempt.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    readiness = evidence_snapshot.get("question_readiness")
    readiness = readiness if isinstance(readiness, dict) else {}
    readiness_counts: dict[str, int] = {}
    for value in readiness.values():
        state = str(value.get("state") if isinstance(value, dict) else value)
        readiness_counts[state] = readiness_counts.get(state, 0) + 1
    gaps = evidence_snapshot.get("gaps")
    return EvidenceExecutionDiagnostics(
        execution_status_counts=dict(sorted(status_counts.items())),
        gap_count=len(gaps) if isinstance(gaps, list) else 0,
        question_readiness_counts=dict(sorted(readiness_counts.items())),
        publication_decision=str(editorial_review.get("publication_decision") or ""),
    )


def list_analysis_runs(
    history_id: str,
    *,
    capability_id: str = "",
    repo=analysis_run_repo,
) -> list[AnalysisRunV3 | LegacyAnalysisRunView | LegacyAnalysisRunV2View]:
    manifests = repo.list(history_id, capability_id=capability_id)
    result: list[AnalysisRunV3 | LegacyAnalysisRunView | LegacyAnalysisRunV2View] = []
    for item in manifests:
        if _schema_v3(item):
            result.append(_mark_stale(AnalysisRunV3(**item), history_id=history_id, repo=repo))
        elif _schema_v2(item):
            result.append(_legacy_v2_view(item, history_id=history_id, repo=repo))
        else:
            result.append(_legacy_view(item))
    return result


def get_analysis_run(
    run_id: str,
    *,
    repo=analysis_run_repo,
) -> AnalysisRunV3Detail | AnalysisRunReadDetail | None:
    payload = repo.get(run_id)
    if not isinstance(payload, dict):
        return None
    run_payload = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    snapshots = [
        AnalysisArtifactSnapshot.model_validate(item)
        for item in payload.get("artifacts") or []
    ]
    history_id = str(payload.get("history_id") or "")
    if _schema_v3(run_payload):
        run = _mark_stale(AnalysisRunV3.model_validate(run_payload), history_id=history_id, repo=repo)
        return AnalysisRunV3Detail(
            history_id=history_id,
            run=run,
            artifacts=snapshots,
            evidence_diagnostics=_evidence_diagnostics(snapshots),
        )
    if _schema_v2(run_payload):
        detail = AnalysisRunDetail(**payload)
        return AnalysisRunReadDetail(
            history_id=detail.history_id,
            run=_legacy_v2_view(run_payload, history_id=detail.history_id, repo=repo),
            artifacts=detail.artifacts,
            metric_plan_diagnostics=build_metric_plan_diagnostics(detail.run),
        )
    return AnalysisRunReadDetail(
        history_id=history_id,
        run=_legacy_view(run_payload),
        artifacts=snapshots,
    )

def compare_analysis_runs(
    base_run_id: str,
    target_run_id: str,
    *,
    repo=analysis_run_repo,
) -> AnalysisRunComparison | None:
    """Compare two immutable Runs only when both records exist."""

    base = get_analysis_run(base_run_id, repo=repo)
    target = get_analysis_run(target_run_id, repo=repo)
    if base is None or target is None:
        return None
    if not isinstance(base, AnalysisRunV3Detail) or not isinstance(target, AnalysisRunV3Detail):
        raise ValueError("legacy_analysis_run_read_only")
    return compare_run_details(base, target)
