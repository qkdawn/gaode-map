from modules.agent.capability_runs import (
    CapabilityRunRecorder,
    artifact_ref,
    content_digest,
)


def test_content_digest_is_stable_across_mapping_order():
    assert content_digest({"b": 2, "a": 1}) == content_digest({"a": 1, "b": 2})
    assert content_digest({"a": 1}) != content_digest({"a": 2})


def test_capability_run_locks_configuration_stages_and_artifact_lineage():
    project_context = {"scope": {"scope_id": "scope-1"}}
    configuration = {"question": "形成第一阶段报告", "threshold": 0.6}
    recorder = CapabilityRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context=project_context,
        configuration_snapshot=configuration,
        execution_profile={
            "model_profile_id": "model-1",
            "skill_id": "urban-strategy-stage1",
        },
        run_id="caprun-test",
        created_at="2026-07-12T00:00:00Z",
    )
    project_context["scope"]["scope_id"] = "changed"
    configuration["threshold"] = 0.9

    input_ref = artifact_ref(
        artifact_id="document:brief",
        artifact_type="structured_data",
        title="项目摘要",
        source_run_id="",
        payload={"node": "p12"},
    )
    recorder.set_input_artifacts([input_ref])
    recorder.record_stage("readiness", "资料完整性检查")
    recorder.record_stage("evidence-ledger", "建立证据台账", summary="2 条证据")
    output_ref = artifact_ref(
        artifact_id="stage1-evidence-ledger",
        artifact_type="evidence_ledger",
        title="证据台账",
        source_run_id="caprun-test",
        filename="evidence_ledger.jsonl",
        payload=[{"id": "e1"}],
        source_artifact_refs=["document:brief"],
        evidence_refs=["e1"],
    )
    run = recorder.finish(
        "completed_with_warnings",
        current_stage="evidence-ledger",
        diagnostics=["结构条件待现场核验"],
        output_artifacts=[output_ref],
    )

    assert run.project_context["scope"]["scope_id"] == "scope-1"
    assert run.configuration_snapshot["threshold"] == 0.6
    assert [item.stage_id for item in run.stage_records] == [
        "readiness",
        "evidence-ledger",
    ]
    assert run.input_artifact_refs[0].artifact_id == "document:brief"
    assert run.output_artifact_refs[0].source_artifact_refs == ["document:brief"]
    assert run.output_artifact_refs[0].content_digest.startswith("sha256:")
    assert run.status == "completed_with_warnings"
    assert run.completed_at


def test_capability_run_waiting_state_preserves_blocking_diagnostics():
    recorder = CapabilityRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context={},
        configuration_snapshot={},
        execution_profile={},
        run_id="caprun-waiting",
        created_at="2026-07-12T00:00:00Z",
    )
    recorder.record_stage(
        "readiness",
        "资料完整性检查",
        status="waiting_for_user",
        diagnostics=["缺少项目范围"],
    )
    run = recorder.finish(
        "waiting_for_user",
        current_stage="readiness",
        diagnostics=["缺少项目范围"],
    )

    assert run.status == "waiting_for_user"
    assert run.stage_records[0].status == "waiting_for_user"
    assert run.diagnostics == ["缺少项目范围"]
