from modules.agent.quality_audit import AuditIssue, QualityAuditResult
from modules.agent.stage1_repair import (
    Stage1RepairContractError,
    build_stage1_repair_plan,
    compile_stage1_repair_candidate,
)


def _audit(*issues: AuditIssue) -> QualityAuditResult:
    return QualityAuditResult(
        status="failed" if any(item.severity == "error" for item in issues) else "passed",
        score=50,
        checks_passed=1,
        checks_total=2,
        issues=list(issues),
    )


def _issue(code: str, *, warning: bool = False) -> AuditIssue:
    return AuditIssue(
        code=code,
        severity="warning" if warning else "error",
        message=f"{code} message",
        repair_hint=f"repair {code}",
    )


def test_repair_plan_allows_only_model_output_failures():
    plan = build_stage1_repair_plan(
        _audit(_issue("strategy_competition_missing"), _issue("portfolio_check_missing"))
    )

    assert plan.status == "automatic"
    assert plan.can_run_automatically is True
    assert [item.scope for item in plan.automatic_tasks] == ["strategy", "spatial_matrix"]
    assert plan.attempt_limit == 1


def test_repair_plan_refuses_to_rewrite_around_external_evidence_failure():
    plan = build_stage1_repair_plan(
        _audit(_issue("strategy_competition_missing"), _issue("provenance_binding_missing"))
    )

    assert plan.status == "external_input_required"
    assert plan.can_run_automatically is False
    assert [item.code for item in plan.external_issues] == ["provenance_binding_missing"]
    assert plan.attempt_limit == 0


def test_repair_plan_ignores_warnings_when_no_blocking_issue_exists():
    plan = build_stage1_repair_plan(_audit(_issue("spatial_map_binding_incomplete", warning=True)))

    assert plan.status == "not_needed"
    assert plan.attempt_limit == 0


def test_compile_repair_candidate_requires_the_single_complete_contract():
    try:
        compile_stage1_repair_candidate({}, evidence_ids=set(), spatial_object_registry={})
    except Stage1RepairContractError as error:
        assert "workpacks" in error.diagnostics[0]
        assert any("spatial_matrix" in item for item in error.diagnostics)
    else:
        raise AssertionError("expected Stage1RepairContractError")
