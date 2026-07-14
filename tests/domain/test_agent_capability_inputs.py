from modules.agent.capability_inputs import resolve_capability_inputs
from modules.agent.analysis_runs import (
    AnalysisArtifactSnapshot,
    AnalysisRun,
    AnalysisRunDetail,
    artifact_ref,
)
from modules.agent.schemas import AgentTurnRequest, CapabilityInputSelection, EffectiveExecutionProfile
from modules.agent.stage1_runs import start_stage1_run


def _run(
    run_id: str,
    *,
    status: str = "completed",
    capability_id: str = "urban-strategy-stage1",
    artifact_ids: tuple[str, ...] = (
        "stage1-report",
        "stage1-evidence-appendix",
        "stage1-design-handoff",
    ),
) -> AnalysisRun:
    artifacts = [
        artifact_ref(
            artifact_id=artifact_id,
            artifact_type="report" if artifact_id == "stage1-report" else "structured_data",
            title=artifact_id,
            source_run_id=run_id,
            payload=f"{artifact_id}:{run_id}",
        )
        for artifact_id in artifact_ids
    ]
    return AnalysisRun(
        run_id=run_id,
        capability_id=capability_id,
        status=status,
        output_artifact_refs=artifacts,
        created_at="2026-07-12T00:00:00Z",
        completed_at="2026-07-12T00:01:00Z",
    )


def _detail(run: AnalysisRun, history_id: str = "history-1") -> AnalysisRunDetail:
    return AnalysisRunDetail(
        history_id=history_id,
        run=run,
        artifacts=[
            AnalysisArtifactSnapshot(
                direction="output",
                artifact=artifact,
                payload=f"immutable:{run.run_id}:{artifact.artifact_id}",
            )
            for artifact in run.output_artifact_refs
        ],
    )


def _services(runs):
    details = {item.run_id: _detail(item) for item in runs}

    def list_runs(history_id, *, capability_id=""):
        assert history_id == "history-1"
        return [item for item in runs if not capability_id or item.capability_id == capability_id]

    return list_runs, details.get


def test_latest_successful_skips_stale_version_and_returns_immutable_artifact():
    stale = _run("run-stale", status="stale")
    current = _run("run-current")
    list_runs, get_run = _services([stale, current])

    result = resolve_capability_inputs(
        "ppt-planning",
        AgentTurnRequest(history_id="history-1"),
        list_runs=list_runs,
        get_run=get_run,
    )

    resolution = result.resolutions[0]
    assert result.blocking_diagnostics == []
    assert resolution.state == "resolved"
    assert resolution.selection_mode == "latest_successful"
    assert resolution.selected_run_id == "run-current"
    assert resolution.artifact_refs[0].artifact_id == "stage1-report"
    assert result.artifact_payloads["run-current:stage1-report"] == (
        "immutable:run-current:stage1-report"
    )
    assert [item.run_id for item in resolution.available_versions] == ["run-stale", "run-current"]


def test_latest_successful_skips_newer_run_missing_required_artifacts():
    incomplete = _run("run-incomplete", artifact_ids=("stage1-report",))
    complete = _run("run-complete")
    list_runs, get_run = _services([incomplete, complete])

    result = resolve_capability_inputs(
        "ppt-planning",
        AgentTurnRequest(history_id="history-1"),
        list_runs=list_runs,
        get_run=get_run,
    )

    resolution = result.resolutions[0]
    assert result.blocking_diagnostics == []
    assert resolution.selected_run_id == "run-complete"
    assert [item.run_id for item in resolution.available_versions] == ["run-complete"]
    assert [item.artifact_id for item in resolution.artifact_refs] == [
        "stage1-report",
        "stage1-evidence-appendix",
        "stage1-design-handoff",
    ]


def test_specific_stale_version_is_allowed_only_as_explicit_selection():
    stale = _run("run-stale", status="stale")
    list_runs, get_run = _services([stale])
    payload = AgentTurnRequest(
        history_id="history-1",
        capability_input_selections=[
            CapabilityInputSelection(
                requirement_id="approved_report",
                mode="specific_run",
                run_id="run-stale",
            )
        ],
    )

    result = resolve_capability_inputs(
        "ppt-planning", payload, list_runs=list_runs, get_run=get_run
    )

    assert result.blocking_diagnostics == []
    assert result.resolutions[0].state == "resolved"
    assert result.resolutions[0].selected_run_id == "run-stale"
    assert "过期历史版本" in result.resolutions[0].diagnostics[0]


def test_recalculate_blocks_downstream_execution_until_upstream_finishes():
    list_runs, get_run = _services([])
    payload = AgentTurnRequest(
        history_id="history-1",
        capability_input_selections=[
            CapabilityInputSelection(
                requirement_id="approved_report",
                mode="recalculate",
            )
        ],
    )

    result = resolve_capability_inputs(
        "ppt-planning", payload, list_runs=list_runs, get_run=get_run
    )

    assert result.resolutions[0].state == "recalculate_required"
    assert result.blocking_diagnostics == ["需先重新运行“已审定报告或分析成果”的上游能力。"]


def test_optional_audit_target_can_be_explicitly_ignored():
    list_runs, get_run = _services([])
    payload = AgentTurnRequest(
        history_id="history-1",
        capability_input_selections=[
            CapabilityInputSelection(
                requirement_id="stage1_audit_target",
                mode="ignore_optional",
            )
        ],
    )

    result = resolve_capability_inputs(
        "evidence-audit", payload, list_runs=list_runs, get_run=get_run
    )

    assert result.blocking_diagnostics == []
    assert result.resolutions[0].state == "ignored"


def test_stage1_run_manifest_locks_target_capability_and_resolved_policy():
    run = _run("run-upstream")
    list_runs, get_run = _services([run])
    payload = AgentTurnRequest(
        history_id="history-1",
        target_capability_id="ppt-planning",
        capability_input_selections=[
            CapabilityInputSelection(
                requirement_id="approved_report",
                mode="specific_run",
                run_id="run-upstream",
            )
        ],
    )
    resolved = resolve_capability_inputs(
        "ppt-planning", payload, list_runs=list_runs, get_run=get_run
    )

    recorder = start_stage1_run(
        payload,
        profile=EffectiveExecutionProfile(skill_id="urban-strategy-stage1"),
        question="生成下游成果",
        selected_sources=[],
        capability_id="ppt-planning",
        resolved_inputs=resolved,
    )
    manifest = recorder.snapshot()

    assert manifest.capability_id == "ppt-planning"
    assert manifest.configuration_snapshot["capability_input_selections"] == [
        {
            "requirement_id": "approved_report",
            "selection_mode": "specific_run",
            "selected_run_id": "run-upstream",
            "state": "resolved",
            "artifact_ids": [
                "stage1-report",
                "stage1-evidence-appendix",
                "stage1-design-handoff",
            ],
        }
    ]
