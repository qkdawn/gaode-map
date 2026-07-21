from modules.agent.analysis_runs import (
    AnalysisRun,
    DecisionHypothesis,
    DecisionQuestion,
    MetricAttempt,
    MetricPlan,
    MetricPlanEntry,
    PlannedSpatialTarget,
    ProjectDecisionAgenda,
    SpatialTargetRef,
)
from modules.agent.report_validation import ReportArtifact, generate_validated_report, validate_report
from modules.evidence_retrieval.schemas import EvidenceNode


def _run() -> AnalysisRun:
    question = DecisionQuestion(
        question_id="q:location",
        text="哪个局部区域适合优先布置功能？",
        decision_target="program_location",
        hypotheses=[
            DecisionHypothesis(
                hypothesis_id="h:density",
                statement="高密度区域具有更多设施接触机会。",
                disconfirming_condition="现场到达观测不支持。",
            )
        ],
    )
    return AnalysisRun(
        run_id="run:test",
        capability_id="urban-strategy-stage1",
        status="completed",
        created_at="2026-07-14T00:00:00Z",
        decision_agenda=ProjectDecisionAgenda(
            agenda_id="agenda:location",
            user_question="选择优先功能位置",
            decision_questions=[question],
        ),
        metric_plan=MetricPlan(
            decision_questions=[question],
            entries=[
                MetricPlanEntry(
                    plan_entry_id="entry:poi-density",
                    metric_id="poi.grid_density",
                    role="primary",
                    decision_question_id="q:location",
                    hypothesis_ids=["h:density"],
                    planned_spatial_target=PlannedSpatialTarget(unit="grid_cell", source="h3_grid"),
                    selection_reason="直接定位局部设施集中。",
                    expected_decision_use="改变功能位置候选。",
                )
            ],
        ),
        metric_attempts=[
            MetricAttempt(
                plan_entry_id="entry:poi-density",
                metric_id="poi.grid_density",
                spatial_target=SpatialTargetRef(unit="grid_cell", target_id="cell:test"),
                execution_status="succeeded",
                evidence_node_ids=["evidence:poi"],
            )
        ],
    )


def _node() -> EvidenceNode:
    return EvidenceNode(
        id="evidence:poi",
        kind="spatial_metric",
        run_id="run:test",
        source_ids=["current:dataset:poi@sha256:test"],
        metric_ids=["poi.grid_density"],
        title="POI 密度",
        data={"value": 990.15, "unit": "poi_per_km2"},
        time_scope={"year": 2024},
        spatial_scope={"scope_id": "scope:test"},
        method="reachable_polygon_area_normalization_v2",
    )


def test_report_accepts_current_run_succeeded_metric_citation():
    report = ReportArtifact(
        report_id="report:test",
        run_id="run:test",
        markdown="当前范围 POI 密度为 990.15 个/km²。[E3]",
        citations={"E3": ["evidence:poi"]},
    )
    result = validate_report(report, run=_run(), evidence_nodes=[_node()])
    assert result.publishable is True
    assert result.report == report


def test_report_rejects_missing_baseline_and_cross_run_node():
    node = _node().model_copy(update={"run_id": "run:other"})
    report = ReportArtifact(
        report_id="report:test",
        run_id="run:test",
        markdown="当前范围 POI 密度较高。[E3]",
        citations={"E3": ["evidence:poi"]},
    )
    result = validate_report(report, run=_run(), evidence_nodes=[node])
    assert result.publishable is False
    assert {item.code for item in result.violations} >= {"cross_run_citation", "comparison_baseline_missing"}


def test_report_rejects_catalog_semantic_overreach():
    report = ReportArtifact(
        report_id="report:test",
        run_id="run:test",
        markdown="POI 密度证明该范围客流充足。[E3]",
        citations={"E3": ["evidence:poi"]},
    )
    result = validate_report(report, run=_run(), evidence_nodes=[_node()])
    assert result.publishable is False
    assert "catalog_semantic_overreach" in {item.code for item in result.violations}


def test_report_rejects_missing_evidence_citations():
    report = ReportArtifact(
        report_id="report:test",
        run_id="run:test",
        markdown="当前范围 POI 密度为 990.15 个/km²。",
        citations={},
    )
    result = validate_report(report, run=_run(), evidence_nodes=[_node()])
    assert result.publishable is False
    assert "report_citations_missing" in {item.code for item in result.violations}


def test_report_generation_stops_after_two_rewrites():
    calls = []

    def generator(violations):
        calls.append(violations)
        return ReportArtifact(
            report_id="report:test",
            run_id="run:test",
            markdown="当前范围 POI 密度较高。[E3]",
            citations={"E3": ["evidence:poi"]},
        )

    result = generate_validated_report(generator, run=_run(), evidence_nodes=[_node()])
    assert result.publishable is False
    assert result.report is None
    assert result.attempts == 3
    assert len(calls) == 3
