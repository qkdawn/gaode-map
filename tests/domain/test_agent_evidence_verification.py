from datetime import date

from modules.agent.evidence_verification import verify_evidence_ledger
from modules.agent.schemas import AnalysisSnapshot


def snapshot(**values):
    return AnalysisSnapshot(**values)


def evidence(**overrides):
    node = {
        "id": "evidence-1",
        "claim": "项目包含历史建筑院落",
        "evidence_type": "F",
        "status": "verified",
        "source_ref": "项目资料 p.12",
        "scope": "项目红线",
        "comparison_baseline": "",
        "confidence": "high",
        "limitation": "仍需逐栋勘察",
    }
    node.update(overrides)
    return node


def test_known_document_source_preserves_verified_status():
    ledger, summary = verify_evidence_ledger(
        [evidence()],
        selected_sources=[{"source_id": "project-doc", "title": "项目资料"}],
        snapshot=snapshot(),
        as_of=date(2026, 7, 12),
    )

    assert ledger[0]["status"] == "verified"
    assert ledger[0]["confidence"] == "high"
    assert summary.status == "passed"
    assert summary.report_allowed is True
    assert summary.tasks == []


def test_unlocatable_verified_claim_is_downgraded_before_synthesis():
    ledger, summary = verify_evidence_ledger(
        [evidence(source_ref="未知报告 p.3")],
        selected_sources=[],
        snapshot=snapshot(),
        as_of=date(2026, 7, 12),
    )

    assert ledger[0]["status"] == "inferred"
    assert ledger[0]["confidence"] == "medium"
    assert summary.status == "passed_with_gaps"
    assert any("来源无法" in note for note in summary.notes)


def test_relative_claim_without_baseline_cannot_remain_verified():
    ledger, summary = verify_evidence_ledger(
        [evidence(claim="项目路网整合度较高", source_ref="analysis_snapshot.road")],
        selected_sources=[],
        snapshot=snapshot(road={"mean_integration": 0.63}),
        as_of=date(2026, 7, 12),
    )

    assert ledger[0]["status"] == "inferred"
    assert ledger[0]["confidence"] == "medium"
    assert any("没有比较基准" in note for note in summary.notes)


def test_past_future_plan_becomes_structured_authority_task():
    ledger, summary = verify_evidence_ledger(
        [evidence(claim="项目计划于2024年12月完成改造")],
        selected_sources=[{"title": "项目资料"}],
        snapshot=snapshot(),
        as_of=date(2026, 7, 12),
    )

    assert ledger[0]["status"] == "blocked"
    assert ledger[0]["temporal_status"] == "current_status_unknown"
    assert ledger[0]["confidence"] == "low"
    assert summary.status == "passed_with_gaps"
    task = summary.tasks[0]
    assert task.executor == "manual_authority"
    assert task.responsible_party == "项目方或主管部门"
    assert task.verification_method == task.next_action
    assert "不得进入已验证结论" in task.decision_impact
    assert "2026-07-12" in task.missing_input


def test_fieldwork_task_exposes_responsibility_method_and_decision_impact():
    _, summary = verify_evidence_ledger(
        [
            evidence(
                status="fieldwork_required",
                missing_input="礼堂消防疏散实测记录",
                blocking_reason="数字资料不能替代现场核验",
                next_action="由消防顾问完成现场踏勘并签字",
            )
        ],
        selected_sources=[{"source_id": "project-doc", "title": "项目资料"}],
        snapshot=snapshot(),
        as_of=date(2026, 7, 12),
    )

    task = summary.tasks[0]
    assert task.executor == "fieldwork"
    assert task.responsible_party == "现场调研负责人"
    assert task.verification_method == "由消防顾问完成现场踏勘并签字"
    assert "不能作为确定性设计条件" in task.decision_impact


def test_empty_ledger_fails_gate_and_stops_report():
    ledger, summary = verify_evidence_ledger(
        [], selected_sources=[], snapshot=snapshot(), as_of=date(2026, 7, 12)
    )

    assert ledger == []
    assert summary.status == "failed"
    assert summary.report_allowed is False
    assert summary.blocking_reasons == ["模型未生成可审计的证据节点。"]
