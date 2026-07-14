from modules.agent.analysis_run_comparison import compare_run_details
from modules.agent.analysis_runs import (
    AnalysisArtifactRef,
    AnalysisArtifactSnapshot,
    AnalysisRun,
    AnalysisRunDetail,
    AnalysisStageRecord,
    content_digest,
)


def _artifact(artifact_id, payload, *, title="产物", direction="output"):
    ref = AnalysisArtifactRef(
        artifact_id=artifact_id,
        artifact_type="structured_data" if direction == "output" else "structured_data",
        title=title,
        version=content_digest(payload)[:24],
        source_run_id="",
        content_digest=content_digest(payload),
    )
    return ref, AnalysisArtifactSnapshot(
        direction=direction,
        artifact=ref,
        payload=payload,
    )


def _detail(run_id, *, question, option, space_role, quality_score, history_id="history-1", capability_id="urban-strategy-stage1"):
    input_ref, input_snapshot = _artifact(
        "document:brief",
        {"revision": 1 if run_id == "run-1" else 2},
        title="项目摘要",
        direction="input",
    )
    strategy_payload = {
        "recommended_option_id": option,
        "options": [
            {"id": "option-a", "name": "社区文化客厅", "recommendation_status": "conditional"},
            {"id": "option-b", "name": "青年创新社区", "recommendation_status": "strong" if option == "option-b" else "alternative"},
        ],
    }
    matrix_payload = {
        "matrix_version": "2.0" if run_id == "run-2" else "1.0",
        "positioning_option_id": option,
        "space_decisions": [
            {"space_id": "unit-1", "space_name": "原礼堂", "future_role": space_role},
            *([{"space_id": "unit-2", "space_name": "庭院", "future_role": "公共活动场"}] if run_id == "run-2" else []),
        ],
    }
    quality_payload = {
        "status": "passed",
        "score": quality_score,
        "checks_passed": 19 if quality_score == 100 else 18,
        "checks_total": 19,
        "issues": [] if quality_score == 100 else [{"code": "source_gap", "message": "来源仍有缺口"}],
    }
    output_pairs = [
        _artifact("stage1-strategy-options", strategy_payload, title="定位方案"),
        _artifact("stage1-decision-matrix", matrix_payload, title="空间矩阵"),
        _artifact("stage1-quality-audit", quality_payload, title="质量审计"),
    ]
    output_refs = [item[0] for item in output_pairs]
    snapshots = [input_snapshot, *[item[1] for item in output_pairs]]
    run = AnalysisRun(
        run_id=run_id,
        capability_id=capability_id,
        project_context={},
        configuration_snapshot={
            "history_id": history_id,
            "question": question,
            "analysis_snapshot_digest": f"digest-{run_id}",
        },
        execution_profile={"model_profile_id": "model-1", "skill_id": capability_id},
        input_artifact_refs=[input_ref],
        status="completed",
        current_stage="formal-deliverables",
        stage_records=[
            AnalysisStageRecord(
                stage_id="quality-audit",
                title="质量审计",
                status="completed",
                summary=f"质量分 {quality_score}",
            )
        ],
        output_artifact_refs=output_refs,
        created_at="2026-07-12T00:00:00Z",
        completed_at="2026-07-12T00:01:00Z",
    )
    return AnalysisRunDetail(history_id=history_id, run=run, artifacts=snapshots)


def test_run_comparison_exposes_configuration_artifact_outcome_and_entity_changes():
    comparison = compare_run_details(
        _detail("run-1", question="形成初步策划", option="option-a", space_role="文化锚点", quality_score=95),
        _detail("run-2", question="补充运营约束后复算", option="option-b", space_role="文化与创新复合锚点", quality_score=100),
    )

    assert comparison.history_id == "history-1"
    assert comparison.base_run.run_id == "run-1"
    assert comparison.target_run.run_id == "run-2"
    assert comparison.has_changes is True
    assert {item.field for item in comparison.configuration_changes} >= {
        "configuration_snapshot.question",
        "configuration_snapshot.analysis_snapshot_digest",
    }
    assert {item.artifact_id for item in comparison.artifact_changes} >= {
        "document:brief",
        "stage1-strategy-options",
        "stage1-decision-matrix",
        "stage1-quality-audit",
    }
    assert {item.label for item in comparison.outcome_changes} >= {
        "推荐定位方案",
        "矩阵定位方案",
        "决策矩阵版本",
        "质量审计分数",
    }
    entities = {(item.category, item.entity_id): item for item in comparison.entity_changes}
    assert entities[("strategy_option", "option-b")].changed_fields == ["recommendation_status"]
    assert entities[("space_decision", "unit-1")].changed_fields == ["future_role"]
    assert entities[("space_decision", "unit-2")].change_type == "added"
    assert entities[("quality_issue", "source_gap")].change_type == "removed"
    assert any("核心结果" in item for item in comparison.summary)


def test_run_comparison_rejects_same_run_history_or_capability_mismatch():
    base = _detail("run-1", question="A", option="option-a", space_role="文化", quality_score=95)

    try:
        compare_run_details(base, base)
    except ValueError as exc:
        assert str(exc) == "analysis_run_comparison_requires_distinct_runs"
    else:
        raise AssertionError("same run should be rejected")

    other_history = _detail("run-2", question="B", option="option-b", space_role="创新", quality_score=100, history_id="history-2")
    try:
        compare_run_details(base, other_history)
    except ValueError as exc:
        assert str(exc) == "analysis_run_history_mismatch"
    else:
        raise AssertionError("history mismatch should be rejected")

    other_capability = _detail("run-3", question="C", option="option-b", space_role="创新", quality_score=100, capability_id="evidence-audit")
    try:
        compare_run_details(base, other_capability)
    except ValueError as exc:
        assert str(exc) == "analysis_run_capability_mismatch"
    else:
        raise AssertionError("capability mismatch should be rejected")
