from modules.agent.analysis_runs import (
    AnalysisRunRecorder,
    artifact_ref,
    content_digest,
)
from modules.agent.schemas import AgentTurnRequest, EffectiveExecutionProfile
from modules.agent.stage1_runs import start_stage1_run


def test_content_digest_is_stable_across_mapping_order():
    assert content_digest({"b": 2, "a": 1}) == content_digest({"a": 1, "b": 2})
    assert content_digest({"a": 1}) != content_digest({"a": 2})


def test_analysis_run_locks_configuration_stages_and_artifact_lineage():
    project_context = {"scope": {"scope_id": "scope-1"}}
    configuration = {"question": "形成第一阶段报告", "threshold": 0.6}
    recorder = AnalysisRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context=project_context,
        configuration_snapshot=configuration,
        execution_profile={
            "model_profile_id": "model-1",
            "skill_id": "urban-strategy-stage1",
        },
        run_id="run-test",
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
    recorder.record_stage("evidence-nodes", "建立证据节点", summary="2 条证据")
    output_ref = artifact_ref(
        artifact_id="stage1-evidence-nodes",
        artifact_type="evidence_nodes",
        title="证据节点",
        source_run_id="run-test",
        filename="evidence_nodes.json",
        payload=[{"id": "e1"}],
        source_artifact_refs=["document:brief"],
        evidence_refs=["e1"],
    )
    run = recorder.finish(
        "completed_with_warnings",
        current_stage="evidence-nodes",
        diagnostics=["结构条件待现场核验"],
        output_artifacts=[output_ref],
    )

    assert run.project_context["scope"]["scope_id"] == "scope-1"
    assert run.configuration_snapshot["threshold"] == 0.6
    assert [item.stage_id for item in run.stage_records] == [
        "readiness",
        "evidence-nodes",
    ]
    assert run.input_artifact_refs[0].artifact_id == "document:brief"
    assert run.output_artifact_refs[0].source_artifact_refs == ["document:brief"]
    assert run.output_artifact_refs[0].content_digest.startswith("sha256:")
    assert run.status == "completed_with_warnings"
    assert run.completed_at
    assert run.manifest_sha256 == run.canonical_manifest_sha256()


def test_analysis_run_waiting_state_preserves_blocking_diagnostics():
    recorder = AnalysisRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context={},
        configuration_snapshot={},
        execution_profile={},
        run_id="run-waiting",
        created_at="2026-07-12T00:00:00Z",
    )
    recorder.record_stage(
        "readiness",
        "资料完整性检查",
        status="waiting_for_user",
        diagnostics=["缺少分析范围"],
    )
    run = recorder.finish(
        "waiting_for_user",
        current_stage="readiness",
        diagnostics=["缺少分析范围"],
    )

    assert run.status == "waiting_for_user"
    assert run.stage_records[0].status == "waiting_for_user"
    assert run.diagnostics == ["缺少分析范围"]


def test_stage1_run_locks_wgs84_origin_and_source_versions():
    payload = AgentTurnRequest(
        history_id="history-1",
        analysis_snapshot={
            "scope": {"scope_id": "scope-1"},
            "param_bundles": {"center": [112.9863, 28.2208]},
            "h3": {"year": 2024, "summary": {"cell_count": 18}},
        },
    )
    profile = EffectiveExecutionProfile(
        model_profile_id="model-1",
        skill_id="urban-strategy-stage1",
    )
    recorder = start_stage1_run(
        payload,
        profile=profile,
        question="空间定位研究",
        selected_sources=[
            {
                "source_id": "current:dataset:poi",
                "year": 2024,
                "content_sha256": "sha256:poi",
                "scope_fingerprint": "scope:poi",
                "record_count": 2635,
            }
        ],
    )
    run = recorder.snapshot()

    assert run.project_location == (112.9863, 28.2208)
    assert run.scope_origin == run.project_location
    assert run.partition_origin == run.project_location
    assert run.source_versions[0].model_dump() == {
        "source_id": "current:dataset:poi",
        "year": 2024,
        "sha256": "sha256:poi",
        "scope_fingerprint": "scope:poi",
        "record_count": 2635,
    }
    assert run.source_versions[1].source_id == "current:dataset:h3"
    assert run.source_versions[1].year == 2024
    assert run.source_versions[1].sha256.startswith("sha256:")
