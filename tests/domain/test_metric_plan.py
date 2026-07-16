from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.agent.analysis_runs import (
    AnalysisArtifactRef,
    AnalysisRun,
    AnalysisRunRecorder,
    DecisionHypothesis,
    DecisionQuestion,
    MetricAttempt,
    MetricPlan,
    MetricPlanActivation,
    MetricPlanEntry,
    PlannedSpatialTarget,
    ProjectDecisionAgenda,
    SpatialTargetRef,
    build_metric_plan_diagnostics,
)


def _question():
    return DecisionQuestion(
        question_id="q:entrance",
        text="哪个入口适合作为日常入口？",
        decision_target="entrance",
        hypotheses=[
            DecisionHypothesis(
                hypothesis_id="h:north",
                statement="北侧入口具有更高日常接触机会。",
                disconfirming_condition="入口计数不支持北侧。",
            )
        ],
    )


def _entry(entry_id="entry:primary", *, role="primary", metric_id="road.integration", unit="entrance", **updates):
    payload = dict(
        plan_entry_id=entry_id,
        metric_id=metric_id,
        role=role,
        decision_question_id="q:entrance",
        hypothesis_ids=["h:north"],
        planned_spatial_target=PlannedSpatialTarget(unit=unit, source="project_entrances"),
        selection_reason="直接改变入口选择。" if role != "excluded" else "",
        expected_decision_use="排序入口候选。" if role != "excluded" else "",
        exclusion_reason="本次不满足输入要求。" if role == "excluded" else "",
    )
    payload.update(updates)
    return MetricPlanEntry(**payload)


def _plan(*entries):
    return MetricPlan(decision_questions=[_question()], entries=list(entries or [_entry()]))


def _run(plan, attempts, status="completed"):
    return AnalysisRun(
        run_id="run:test",
        capability_id="spatial-business-analyst",
        catalog_version="2.0.0",
        decision_agenda=ProjectDecisionAgenda(
            agenda_id="agenda:test",
            user_question="测试问题",
            decision_questions=plan.decision_questions,
        ),
        metric_plan=plan,
        metric_attempts=attempts,
        status=status,
        created_at="2026-07-16T00:00:00Z",
    )


def test_metric_plan_requires_primary_and_exclusion_reason():
    with pytest.raises(ValidationError, match="requires a primary"):
        _plan(_entry(role="supporting"))
    with pytest.raises(ValidationError, match="requires exclusion_reason"):
        _entry(role="excluded", exclusion_reason="")
    assert _plan(_entry(role="excluded")).entries[0].role == "excluded"


def test_metric_plan_allows_questions_without_entries_or_partial_metric_coverage():
    first = _question()
    second = DecisionQuestion(
        question_id="q:operations",
        text="哪些运营承诺仍需验证？",
        decision_target="operations",
        hypotheses=[
            DecisionHypothesis(
                hypothesis_id="h:pilot",
                statement="可逆试运营可降低承诺风险。",
                disconfirming_condition="运营主体已具备完整承诺。",
            )
        ],
    )
    question_only = MetricPlan(decision_questions=[first], entries=[])
    assert question_only.entries == []
    assert _run(question_only, []).metric_plan.decision_questions == [first]
    partial = MetricPlan(decision_questions=[first, second], entries=[_entry()])
    assert [item.question_id for item in partial.decision_questions] == ["q:entrance", "q:operations"]
    assert {item.decision_question_id for item in partial.entries} == {"q:entrance"}


def test_metric_plan_entries_still_require_known_questions():
    with pytest.raises(ValidationError, match="entries require decision_questions"):
        MetricPlan(decision_questions=[], entries=[_entry()])
    with pytest.raises(ValidationError, match="unknown question"):
        MetricPlan(
            decision_questions=[_question()],
            entries=[_entry(decision_question_id="q:unknown")],
        )


def test_conditional_activation_requires_sources_and_rule():
    with pytest.raises(ValidationError, match="conditional activation"):
        MetricPlanActivation(type="if_primary_blocked")
    activation = MetricPlanActivation(
        type="if_primary_blocked",
        source_entry_ids=["entry:primary"],
        rule="主指标阻塞时启用。",
    )
    diagnostic = _entry(
        "entry:diagnostic",
        role="diagnostic",
        metric_id="road.entrance_distance",
        activation=activation,
    )
    assert _plan(_entry(), diagnostic).entries[1].activation.type == "if_primary_blocked"


def test_attempt_alignment_allows_multiple_targets_but_rejects_unplanned_or_unit_mismatch():
    plan = _plan()
    attempts = [
        MetricAttempt(
            plan_entry_id="entry:primary",
            metric_id="road.integration",
            spatial_target=SpatialTargetRef(unit="entrance", target_id="entrance:north"),
            execution_status="succeeded",
            evidence_node_ids=["e:north"],
        ),
        MetricAttempt(
            plan_entry_id="entry:primary",
            metric_id="road.integration",
            spatial_target=SpatialTargetRef(unit="entrance", target_id="entrance:south"),
            execution_status="succeeded",
            evidence_node_ids=["e:south"],
        ),
    ]
    assert len(_run(plan, attempts).metric_attempts) == 2
    with pytest.raises(ValidationError, match="not planned"):
        _run(plan, [attempts[0].model_copy(update={"plan_entry_id": "entry:unknown"})])
    with pytest.raises(ValidationError, match="spatial unit mismatch"):
        _run(plan, [attempts[0].model_copy(update={"spatial_target": SpatialTargetRef(unit="route", target_id="r:1")})])


def test_completed_run_requires_attempt_and_conditional_not_triggered_is_explicit():
    diagnostic = _entry(
        "entry:diagnostic",
        role="diagnostic",
        metric_id="road.entrance_distance",
        activation=MetricPlanActivation(
            type="if_primary_blocked",
            source_entry_ids=["entry:primary"],
            rule="主指标阻塞时启用。",
        ),
    )
    plan = _plan(_entry(), diagnostic)
    primary = MetricAttempt(
        plan_entry_id="entry:primary",
        metric_id="road.integration",
        spatial_target=SpatialTargetRef(unit="entrance", target_id="entrance:north"),
        execution_status="succeeded",
        evidence_node_ids=["e:north"],
    )
    with pytest.raises(ValidationError, match="unattempted"):
        _run(plan, [primary])
    not_applicable = MetricAttempt(
        plan_entry_id="entry:diagnostic",
        metric_id="road.entrance_distance",
        spatial_target=SpatialTargetRef(unit="entrance", target_id="entrance:north"),
        execution_status="not_applicable",
        reason="condition_not_met",
    )
    assert _run(plan, [primary, not_applicable]).metric_attempts[-1].reason == "condition_not_met"


def test_recorder_locks_plan_when_ready_or_execution_starts():
    recorder = AnalysisRunRecorder(
        capability_id="spatial-business-analyst",
        project_context={},
        configuration_snapshot={},
        execution_profile={},
    )
    plan = _plan()
    recorder.set_decision_agenda(
        ProjectDecisionAgenda(
            agenda_id="agenda:recorder",
            user_question="选择入口",
            decision_questions=plan.decision_questions,
        )
    )
    recorder.set_metric_plan(plan)
    recorder.finish("ready", current_stage="ready")
    with pytest.raises(ValueError, match="metric_plan_locked"):
        recorder.set_metric_plan(_plan())


def test_recorder_rejects_plan_without_matching_agenda():
    recorder = AnalysisRunRecorder(
        capability_id="spatial-business-analyst",
        project_context={},
        configuration_snapshot={},
        execution_profile={},
    )
    with pytest.raises(ValueError, match="must exactly match"):
        recorder.set_metric_plan(_plan())


@pytest.mark.parametrize("status", ["chapter_failed", "publication_blocked", "system_failed"])
def test_recorder_supports_distinct_terminal_failure_statuses(status):
    recorder = AnalysisRunRecorder(
        capability_id="spatial-business-analyst",
        project_context={},
        configuration_snapshot={},
        execution_profile={},
    )
    run = recorder.finish(status, current_stage="report", diagnostics=["test failure"])
    assert run.status == status
    assert run.completed_at


def test_analysis_run_requires_exact_agenda_and_metric_plan_questions():
    plan = _plan()
    with pytest.raises(ValidationError, match="must exactly match"):
        AnalysisRun(
            run_id="run:mismatch",
            capability_id="spatial-business-analyst",
            metric_plan=plan,
            status="running",
            created_at="2026-07-16T00:00:00Z",
        )


def test_metric_plan_diagnostics_aggregates_concrete_targets():
    excluded = _entry("entry:excluded", role="excluded", metric_id="road.choice")
    plan = _plan(_entry(), excluded)
    blocked = MetricAttempt(
        plan_entry_id="entry:primary",
        metric_id="road.integration",
        spatial_target=SpatialTargetRef(unit="entrance", target_id="entrance:north"),
        execution_status="blocked",
        reason="depthmapx_unavailable",
    )
    run = _run(plan, [blocked], status="running")
    diagnostics = build_metric_plan_diagnostics(run)
    assert diagnostics.role_counts == {"excluded": 1, "primary": 1}
    assert diagnostics.blocked_primary_entry_ids == ["entry:primary"]
    assert diagnostics.excluded_entry_ids == ["entry:excluded"]


def test_full_project_agenda_accepts_dynamic_questions_and_requires_unique_ids():
    question = _question()
    agenda = ProjectDecisionAgenda(
        agenda_id="agenda:full",
        user_question="完整项目报告",
        analysis_scope="full_project",
        decision_questions=[question],
    )
    assert agenda.decision_questions == [question]
    with pytest.raises(ValidationError, match="ids must be unique"):
        ProjectDecisionAgenda(
            agenda_id="agenda:full",
            user_question="完整项目报告",
            analysis_scope="full_project",
            decision_questions=[question, question],
        )


def test_full_project_agenda_requires_questions_but_focused_default_stays_empty():
    with pytest.raises(ValidationError, match="requires decision_questions"):
        ProjectDecisionAgenda(analysis_scope="full_project")
    assert ProjectDecisionAgenda().decision_questions == []


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"question_id": " "}, "requires question_id"),
        ({"text": " "}, "requires text"),
        ({"decision_target": " "}, "requires decision_target"),
        ({"hypotheses": []}, "at least 1 item"),
    ],
)
def test_decision_question_requires_complete_content(updates, message):
    payload = _question().model_dump(mode="python")
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        DecisionQuestion.model_validate(payload)


def test_decision_question_rejects_removed_agenda_area():
    payload = _question().model_dump(mode="python")
    payload["agenda_area"] = "spatial_program_access"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DecisionQuestion.model_validate(payload)


@pytest.mark.parametrize("artifact_type", ["report_visual", "report_chapter"])
def test_report_artifact_types_are_supported(artifact_type):
    artifact = AnalysisArtifactRef(
        artifact_id="visual:report-cover",
        artifact_type=artifact_type,
        title="报告封面图",
    )
    assert artifact.artifact_type == artifact_type


def test_locked_plan_allows_unavailable_sources_to_be_blocked_at_execution():
    plan = _plan(
        _entry(
            metric_id="population.total",
            required_source_ids=["current:dataset:population"],
        )
    )
    run = _run(plan, [], status="running")
    assert run.metric_plan.entries[0].required_source_ids == ["current:dataset:population"]
