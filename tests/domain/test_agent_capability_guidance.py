from modules.agent.capability_catalog import CapabilityReadiness
from modules.agent.capability_guidance import build_capability_workbench_overview
from modules.agent.capability_runs import CapabilityRun
from modules.agent.schemas import AgentMessage, AgentTurnRequest


def _payload(**kwargs):
    return AgentTurnRequest(
        messages=[AgentMessage(role="user", content="检查下一步")],
        **kwargs,
    )


def _ready_payload(history_id=""):
    return _payload(
        history_id=history_id,
        analysis_snapshot={
            "scope": {"polygon": [[112.0, 28.0], [112.1, 28.0], [112.0, 28.1]]},
            "context": {"project_summary": "长沙县政府原址城市更新项目，需要判断定位、运营、空间功能与分期实施策略。"},
            "frontend_analysis": {"poi_total": 100},
        }
    )


def _all_ready(capability_id, payload):
    return CapabilityReadiness(capability_id=capability_id, status="ready")


def _run(capability_id, status, run_id="run-1", **kwargs):
    return CapabilityRun(
        run_id=run_id,
        capability_id=capability_id,
        status=status,
        created_at="2026-07-12T01:00:00Z",
        completed_at="2026-07-12T01:05:00Z" if status.startswith("completed") else "",
        **kwargs,
    )


def test_workbench_overview_recommends_first_ready_stage1(monkeypatch):
    monkeypatch.setattr("modules.agent.capability_guidance.list_capability_runs", lambda history_id: [])

    overview = build_capability_workbench_overview(_ready_payload())

    assert overview.recommendation is not None
    assert overview.recommendation.capability_id == "urban-strategy-stage1"
    assert overview.recommendation.action == "run"
    stage1 = next(item for item in overview.cards if item.capability_id == "urban-strategy-stage1")
    assert stage1.state == "ready"
    assert stage1.readiness.missing_required == []


def test_workbench_overview_explains_missing_inputs_instead_of_fabricating_readiness(monkeypatch):
    monkeypatch.setattr("modules.agent.capability_guidance.list_capability_runs", lambda history_id: [])

    overview = build_capability_workbench_overview(_payload())

    assert overview.recommendation is not None
    assert overview.recommendation.action == "resolve_inputs"
    assert overview.recommendation.capability_id == "urban-strategy-stage1"
    assert overview.recommendation.missing_required
    states = {item.capability_id: item.state for item in overview.cards}
    assert states["rsir-business-analysis"] == "unavailable"
    assert all(
        state == "blocked"
        for capability_id, state in states.items()
        if capability_id != "rsir-business-analysis"
    )


def test_workbench_overview_prioritizes_active_run_over_duplicate_execution(monkeypatch):
    monkeypatch.setattr(
        "modules.agent.capability_guidance.list_capability_runs",
        lambda history_id: [_run("urban-strategy-stage1", "running", run_id="run-active")],
    )

    monkeypatch.setattr("modules.agent.capability_guidance.evaluate_capability_readiness", _all_ready)
    overview = build_capability_workbench_overview(_ready_payload("history-1"))

    assert overview.recommendation is not None
    assert overview.recommendation.action == "inspect_run"
    assert overview.recommendation.run_id == "run-active"
    assert next(item for item in overview.cards if item.capability_id == "urban-strategy-stage1").state == "running"


def test_workbench_overview_surfaces_stale_lineage_for_rerun(monkeypatch):
    monkeypatch.setattr(
        "modules.agent.capability_guidance.list_capability_runs",
        lambda history_id: [
            _run(
                "urban-strategy-stage1",
                "stale",
                run_id="run-stale",
                stale_input_artifact_ids=["stage1-evidence-ledger"],
            )
        ],
    )

    monkeypatch.setattr("modules.agent.capability_guidance.evaluate_capability_readiness", _all_ready)
    overview = build_capability_workbench_overview(_ready_payload("history-1"))

    assert overview.recommendation is not None
    assert overview.recommendation.action == "rerun"
    assert overview.recommendation.run_id == "run-stale"
    assert next(item for item in overview.cards if item.capability_id == "urban-strategy-stage1").state == "stale"
