from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import store.capability_run_repo as capability_run_repo_module
from modules.agent.capability_run_service import (
    get_capability_run,
    list_capability_runs,
    persist_capability_run_response,
)
from modules.agent.capability_runs import CapabilityRunRecorder, artifact_ref
from modules.agent.schemas import AgentTurnRequest, AgentTurnResponse
import modules.agent.session_service as session_service
from store.models import Base


@pytest.fixture
def run_repo(monkeypatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(capability_run_repo_module, "SessionLocal", factory)
    return capability_run_repo_module.capability_run_repo


def _completed_run(
    run_id: str,
    *,
    history_id: str = "history-1",
    source_payload: dict | None = None,
):
    source_payload = source_payload or {"revision": 1}
    recorder = CapabilityRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context={"scope_id": "scope-1"},
        configuration_snapshot={"history_id": history_id},
        execution_profile={"skill_id": "urban-strategy-stage1"},
        run_id=run_id,
        created_at="2026-07-12T00:00:00Z",
    )
    recorder.set_input_artifacts(
        [
            artifact_ref(
                artifact_id="document:project-brief",
                artifact_type="structured_data",
                title="项目简报来源",
                payload=source_payload,
            )
        ]
    )
    recorder.record_stage("readiness", "资料完整性检查")
    report = f"# 第一阶段报告\n\nRun: {run_id}"
    project_brief = {"project_name": "测试项目", **source_payload}
    quality_audit = {"status": "passed", "score": 100, "checks_passed": 19, "checks_total": 19, "issues": []}
    output_refs = [
        artifact_ref(
            artifact_id="stage1-project-brief",
            artifact_type="structured_data",
            title="项目简报",
            source_run_id=run_id,
            payload=project_brief,
        ),
        artifact_ref(
            artifact_id="stage1-report",
            artifact_type="report",
            title="第一阶段报告",
            source_run_id=run_id,
            payload=report,
        ),
        artifact_ref(
            artifact_id="stage1-quality-audit",
            artifact_type="diagnostic_report",
            title="交付质量审计",
            source_run_id=run_id,
            payload=quality_audit,
        ),
    ]
    run = recorder.finish(
        "completed",
        current_stage="report",
        output_artifacts=output_refs,
    )
    return run, project_brief, report


def _persist(run_repo, run, project_brief, report, *, history_id="history-1"):
    response = AgentTurnResponse(
        status="answered",
        output={
            "answer": report,
            "panel_payloads": {
                "capability_run": run.model_dump(mode="json"),
                "stage1_project_brief": project_brief,
                "stage1_quality_audit": {"status": "passed", "score": 100, "checks_passed": 19, "checks_total": 19, "issues": []},
                "stage1_deliverables": {"report_markdown": report},
            },
        },
    )
    request = AgentTurnRequest(history_id=history_id)
    persist_capability_run_response(request, response, repo=run_repo)
    return response


def test_persisted_run_keeps_immutable_manifest_and_output_payloads(run_repo):
    run, project_brief, report = _completed_run("caprun-1")

    _persist(run_repo, run, project_brief, report)
    detail = get_capability_run("caprun-1", repo=run_repo)

    assert detail is not None
    assert detail.history_id == "history-1"
    assert detail.run.run_id == "caprun-1"
    snapshots = {item.artifact.artifact_id: item for item in detail.artifacts}
    assert snapshots["stage1-project-brief"].payload == project_brief
    assert snapshots["stage1-report"].payload == report
    assert snapshots["document:project-brief"].direction == "input"
    assert snapshots["document:project-brief"].payload is None
    assert snapshots["stage1-report"].artifact.version == "caprun-1"
    assert snapshots["stage1-quality-audit"].payload["checks_passed"] == 19


def test_identical_save_is_idempotent_but_run_payload_and_owner_are_immutable(run_repo):
    run, project_brief, report = _completed_run("caprun-immutable")
    response = _persist(run_repo, run, project_brief, report)

    persist_capability_run_response(
        AgentTurnRequest(history_id="history-1"),
        response,
        repo=run_repo,
    )
    assert len(list_capability_runs("history-1", repo=run_repo)) == 1

    modified = response.model_copy(deep=True)
    modified.output.panel_payloads["stage1_deliverables"]["report_markdown"] = (
        "tampered report"
    )
    with pytest.raises(ValueError, match="capability_run_immutable"):
        persist_capability_run_response(
            AgentTurnRequest(history_id="history-1"),
            modified,
            repo=run_repo,
        )

    with pytest.raises(ValueError, match="capability_run_immutable"):
        persist_capability_run_response(
            AgentTurnRequest(history_id="history-2"),
            response,
            repo=run_repo,
        )


def test_newer_changed_input_marks_only_older_run_in_same_history_stale(run_repo):
    old_run, old_brief, old_report = _completed_run(
        "caprun-old", source_payload={"revision": 1}
    )
    _persist(run_repo, old_run, old_brief, old_report)

    before = list_capability_runs("history-1", repo=run_repo)
    assert before[0].status == "completed"

    new_run, new_brief, new_report = _completed_run(
        "caprun-new", source_payload={"revision": 2}
    )
    _persist(run_repo, new_run, new_brief, new_report)

    runs = {
        item.run_id: item
        for item in list_capability_runs(
            "history-1",
            capability_id="urban-strategy-stage1",
            repo=run_repo,
        )
    }
    assert runs["caprun-old"].status == "stale"
    assert runs["caprun-old"].stale_input_artifact_ids == ["document:project-brief"]
    assert "上游输入已更新" in runs["caprun-old"].diagnostics[-1]
    assert runs["caprun-new"].status == "completed"

    other_run, other_brief, other_report = _completed_run(
        "caprun-other-history",
        history_id="history-2",
        source_payload={"revision": 3},
    )
    _persist(
        run_repo,
        other_run,
        other_brief,
        other_report,
        history_id="history-2",
    )
    assert list_capability_runs("history-2", repo=run_repo)[0].status == "completed"
    assert runs["caprun-new"].status == "completed"


def test_artifact_ref_uses_digest_or_source_run_as_meaningful_version():
    input_ref = artifact_ref(
        artifact_id="input-1",
        artifact_type="structured_data",
        title="输入",
        payload={"value": 1},
    )
    output_ref = artifact_ref(
        artifact_id="output-1",
        artifact_type="report",
        title="输出",
        source_run_id="caprun-version",
        payload="report",
    )

    assert input_ref.version == input_ref.content_digest[:24]
    assert input_ref.version != "1"
    assert output_ref.version == "caprun-version"


class _RecordingSessionRepo:
    def __init__(self):
        self.records = {}

    def get_record(self, session_id):
        return self.records.get(session_id)

    def upsert_record(self, session_id, **record):
        self.records[session_id] = {"id": session_id, **record}
        return self.records[session_id]

    def update_metadata(self, session_id, **metadata):
        self.records[session_id].update(metadata)
        return self.records[session_id]


def test_agent_turn_persists_session_and_capability_run_together(run_repo, monkeypatch):
    run, project_brief, report = _completed_run("caprun-session")
    response = AgentTurnResponse(
        status="answered",
        output={
            "answer": report,
            "panel_payloads": {
                "capability_run": run.model_dump(mode="json"),
                "stage1_project_brief": project_brief,
                "stage1_quality_audit": {"status": "passed", "score": 100, "checks_passed": 19, "checks_total": 19, "issues": []},
                "stage1_deliverables": {"report_markdown": report},
            },
        },
    )
    request = AgentTurnRequest(
        conversation_id="agent-session",
        history_id="history-1",
        messages=[{"role": "user", "content": "生成第一阶段报告"}],
    )
    session_repo = _RecordingSessionRepo()

    async def no_generated_title(_payload, _response):
        return None

    monkeypatch.setattr(
        session_service, "generate_agent_session_title", no_generated_title
    )
    result = asyncio.run(
        session_service.persist_main_agent_loop_response(
            request, response, session_repo
        )
    )

    assert result.status == "answered"
    assert session_repo.records["agent-session"]["history_id"] == "history-1"
    detail = get_capability_run("caprun-session", repo=run_repo)
    assert detail is not None
    assert detail.run.status == "completed"


def test_capability_run_persists_without_conversation_session(run_repo):
    run, project_brief, report = _completed_run("caprun-no-session")
    response = AgentTurnResponse(
        status="answered",
        output={
            "answer": report,
            "panel_payloads": {
                "capability_run": run.model_dump(mode="json"),
                "stage1_project_brief": project_brief,
                "stage1_quality_audit": {"status": "passed", "score": 100, "checks_passed": 19, "checks_total": 19, "issues": []},
                "stage1_deliverables": {"report_markdown": report},
            },
        },
    )

    result = asyncio.run(
        session_service.persist_main_agent_loop_response(
            AgentTurnRequest(history_id="history-1"), response, object()
        )
    )

    assert result is response
    assert get_capability_run("caprun-no-session", repo=run_repo) is not None
