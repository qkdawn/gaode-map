from modules.agent.capability_catalog import (
    evaluate_capability_readiness,
    list_analysis_capabilities,
)
from modules.agent.schemas import AgentMessage, AgentTurnRequest


def test_catalog_only_exposes_real_registered_executors_as_available():
    capabilities = list_analysis_capabilities()

    assert {item.id for item in capabilities} == {
        "urban-strategy-stage1",
        "spatial-programming-matrix",
        "evidence-audit",
        "ppt-planning",
        "esri-business-analyst-report",
    }
    available = [item for item in capabilities if item.status == "available"]
    assert {(item.executor_type, item.executor_id) for item in available} <= {
        ("skill", "urban-strategy-stage1"),
        ("service", "ppt-planning"),
        ("service", "business-analyst-agent"),
    }
    assert all(item.intent_phrases for item in capabilities)

    business_report = next(item for item in capabilities if item.id == "esri-business-analyst-report")
    assert business_report.status == "available"
    assert business_report.executor_type == "service"
    assert business_report.executor_id == "business-analyst-agent"
    assert "BA Model Scorecard" in business_report.output_contract


def test_stage1_readiness_exposes_actions_for_missing_inputs():
    payload = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="生成第一阶段报告")]
    )

    readiness = evaluate_capability_readiness("urban-strategy-stage1", payload)

    assert readiness.status == "blocked"
    assert readiness.missing_required
    assert {action.target for action in readiness.actions} == {
        "scope-selection",
        "project-brief",
        "analysis-sources",
    }


def test_stage1_readiness_accepts_scope_brief_and_analysis_evidence():
    payload = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="生成第一阶段报告")],
        analysis_snapshot={
            "scope": {
                "polygon": [
                    [112.0, 28.0],
                    [112.1, 28.0],
                    [112.0, 28.1],
                ]
            },
            "context": {
                "project_summary": "长沙县政府原址城市更新项目，需要判断定位、运营与分期策略。"
            },
            "frontend_analysis": {"poi_total": 2635},
        },
    )

    readiness = evaluate_capability_readiness("urban-strategy-stage1", payload)

    assert readiness.status == "ready"
    assert readiness.missing_required == []
    assert len(readiness.satisfied) == 3


def test_business_analyst_report_readiness_requires_scope_and_evidence():
    payload = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="生成 ESRI Business Analyst 报告")]
    )

    readiness = evaluate_capability_readiness("esri-business-analyst-report", payload)

    assert readiness.status == "blocked"
    assert readiness.missing_required == [
        "分析范围或商圈边界",
        "POI、人口、夜光、路网或项目资料证据",
    ]


def test_business_analyst_report_readiness_accepts_current_scope_evidence():
    payload = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="生成 ESRI Business Analyst 报告")],
        analysis_snapshot={
            "scope": {"polygon": [[112.0, 28.0], [112.1, 28.0], [112.0, 28.1]]},
            "population": {"summary": {"total": 12000}},
            "poi_summary": {"total": 240},
        },
    )

    readiness = evaluate_capability_readiness("esri-business-analyst-report", payload)

    assert readiness.status == "ready"
    assert readiness.missing_required == []
    assert readiness.missing_optional
