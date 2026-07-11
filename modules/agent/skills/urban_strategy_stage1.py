from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..evidence_verification import verify_evidence_ledger
from ..llm_digest import snapshot_digest
from ..providers.client import LLMRuntimeConfig, get_llm_provider_client
from ..quality_audit import QualityAuditResult, audit_stage1_package
from ..stage1_contracts import VerificationSummary
from ..schemas import (
    AgentContextSummary,
    AgentPlanEnvelope,
    AgentTurnDiagnostics,
    AgentTurnOutput,
    AgentTurnRequest,
    AgentTurnResponse,
    EffectiveExecutionProfile,
)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


def evaluate_readiness(payload: AgentTurnRequest) -> dict[str, Any]:
    snapshot = payload.analysis_snapshot
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    sources = payload.selected_sources_context.source_items()
    project_text = " ".join(
        str(value) for value in context.values() if isinstance(value, (str, int, float))
    )
    has_evidence = bool(sources) or any(
        (
            snapshot.frontend_analysis,
            snapshot.poi_summary,
            snapshot.population,
            snapshot.nightlight,
            snapshot.h3,
            snapshot.road,
        )
    )
    checks = (
        (
            bool(scope),
            "项目空间范围",
            "可识别的项目空间范围",
            "select-scope",
            "选择项目范围",
            "scope-selection",
        ),
        (
            len(project_text.strip()) >= 20,
            "项目摘要与决策问题",
            "项目摘要与核心决策问题",
            "edit-project-brief",
            "补充项目摘要",
            "project-brief",
        ),
        (
            has_evidence,
            "项目资料或分析证据",
            "核心项目文档或已选分析证据",
            "select-analysis-sources",
            "选择资料与分析结果",
            "analysis-sources",
        ),
    )
    satisfied: list[str] = []
    missing: list[str] = []
    actions: list[dict[str, str]] = []
    for passed, label, missing_label, action_id, action_label, target in checks:
        if passed:
            satisfied.append(label)
        else:
            missing.append(missing_label)
            actions.append({"id": action_id, "label": action_label, "target": target})

    missing_optional: list[str] = []
    if not sources:
        missing_optional.append("带页码或章节定位的核心项目文档")
    if not context.get("ownership_summary"):
        missing_optional.append("产权、居民与运营边界核验")
    if not context.get("building_condition_summary"):
        missing_optional.append("逐栋结构、消防与机电条件核验")
    conflicts = context.get("evidence_conflicts")
    return {
        "ready": not missing,
        "satisfied": satisfied,
        "missing": missing,
        "missing_optional": missing_optional,
        "conflicts": list(conflicts) if isinstance(conflicts, list) else [],
        "actions": actions,
        "source_count": len(sources),
    }


async def _emit_phase(
    emit: Emit | None,
    *,
    phase_id: str,
    title: str,
    detail: str,
    state: str = "active",
) -> None:
    if emit:
        await emit(
            "thinking",
            {
                "id": phase_id,
                "phase": "executing",
                "title": title,
                "detail": detail,
                "state": state,
            },
        )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_from(value: Any, key: str) -> list[dict[str, Any]]:
    items = _mapping(value).get(key)
    return (
        [dict(item) for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )


def _audit_payload(audit: QualityAuditResult) -> dict[str, Any]:
    return audit.model_dump(mode="json")


def _base_panels(
    readiness: dict[str, Any],
    package: dict[str, Any],
    audit: QualityAuditResult,
    verification: VerificationSummary,
) -> dict[str, Any]:
    return {
        "stage1_readiness": readiness,
        "stage1_evidence_ledger": package["evidence_ledger"],
        "stage1_evidence_verification": verification.model_dump(mode="json"),
        "stage1_workpacks": package["workpacks"],
        "stage1_strategy": package["strategy"],
        "stage1_spatial_matrix": package["spatial_matrix"],
        "stage1_quality_audit": _audit_payload(audit),
    }


async def execute(
    payload: AgentTurnRequest,
    *,
    runtime: LLMRuntimeConfig,
    profile: EffectiveExecutionProfile,
    emit: Emit | None = None,
) -> AgentTurnResponse:
    readiness = evaluate_readiness(payload)
    await _emit_phase(
        emit,
        phase_id="stage1-readiness",
        title="检查 Stage 1 资料完整性",
        detail="核对项目范围、摘要、核心文档和分析证据。",
        state="completed",
    )
    if not readiness["ready"]:
        missing = "、".join(readiness["missing"])
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question=f"执行城市区域策划第一阶段前，还需要补充：{missing}。",
                clarification_options=[
                    action["label"] for action in readiness["actions"]
                ],
                panel_payloads={"stage1_readiness": readiness},
            ),
            diagnostics=AgentTurnDiagnostics(
                research_notes=["Stage 1 readiness 未通过，未调用模型生成报告。"]
            ),
            context_summary=AgentContextSummary(),
            plan=AgentPlanEnvelope(),
            effective_execution_profile=profile,
        )

    client = get_llm_provider_client(runtime=runtime)
    if client is None:
        raise ValueError("所选模型 Provider 不可用")
    question = str(payload.messages[-1].content if payload.messages else "").strip()
    evidence_input = {
        "question": question,
        "project_context": payload.analysis_snapshot.context,
        "snapshot": snapshot_digest(payload.analysis_snapshot),
        "selected_sources": payload.selected_sources_context.source_items(),
        "known_conflicts": readiness["conflicts"],
        "optional_gaps": readiness["missing_optional"],
    }

    await _emit_phase(
        emit,
        phase_id="stage1-evidence",
        title="建立证据台账",
        detail="逐条标注来源、适用范围、验证状态和限制。",
    )
    evidence_result = await client.chat_json(
        system_prompt=(
            "你是城市更新项目的证据审计负责人。只输出 JSON：evidence_ledger 数组。"
            "每项必须含 id、claim、evidence_type(F/G/P/H/V)、status(verified/cross_checked/"
            "inferred/hypothesis/blocked/fieldwork_required)、source_ref、source_artifact_id、scope、method、metric、value、"
            "comparison_baseline、confidence(high/medium/low)、limitation、next_action、executor(agent/fieldwork)。"
            "没有页码时明确写来源路径或数据集；不得把夜光、POI、gap_score、周边人口解释为客流、消费或经营成功。"
        ),
        user_payload=evidence_input,
        emit=emit,
        phase="executing",
        title="构建 Claim-Evidence 台账",
        reasoning_id="stage1-evidence-model",
    )
    evidence_ledger, verification = verify_evidence_ledger(
        _list_from(evidence_result, "evidence_ledger"),
        selected_sources=payload.selected_sources_context.source_items(),
        snapshot=payload.analysis_snapshot,
    )
    await _emit_phase(
        emit,
        phase_id="stage1-evidence-verification",
        title="验证证据状态与时效",
        detail=(
            f"证据门控{verification.status}；自动执行 {len(verification.automated_checks)} 项确定性核验，"
            f"仍有 {len(verification.tasks)} 项明确核验任务。"
        ),
        state="completed" if verification.report_allowed else "failed",
    )
    if not verification.report_allowed:
        verification_payload = verification.model_dump(mode="json")
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question="证据台账未通过验证门控，已停止专业推演。请补充可定位证据后重新运行。",
                clarification_options=verification.blocking_reasons[:4],
                panel_payloads={
                    "stage1_readiness": readiness,
                    "stage1_evidence_ledger": evidence_ledger,
                    "stage1_evidence_verification": verification_payload,
                },
            ),
            diagnostics=AgentTurnDiagnostics(
                audit_issues=verification.blocking_reasons,
                research_notes=["证据门控未通过，后续专业模型未被调用。"],
            ),
            context_summary=AgentContextSummary(),
            plan=AgentPlanEnvelope(),
            effective_execution_profile=profile,
        )

    await _emit_phase(
        emit,
        phase_id="stage1-workpacks",
        title="形成四类专业工作包",
        detail="区域结构、人群需求、文化文旅、存量更新与运营共享同一证据底座。",
    )
    workpack_result = await client.chat_json(
        system_prompt=(
            "你是城市策划证据分析负责人。只输出 JSON：workpacks 数组，必须且仅覆盖 spatial、audience、"
            "culture_tourism、renewal_operations。每项包含 type、findings、evidence_refs、counter_evidence、"
            "uncertainties、validation_actions。引用证据 ID，不得引入台账之外的事实。"
        ),
        user_payload={"question": question, "evidence_ledger": evidence_ledger},
        emit=emit,
        phase="executing",
        title="生成四类专家工作包",
        reasoning_id="stage1-workpacks-model",
    )
    workpacks = _list_from(workpack_result, "workpacks")

    await _emit_phase(
        emit,
        phase_id="stage1-options",
        title="比较定位方案",
        detail="形成至少三个实质不同且可证伪的定位选项。",
    )
    strategy_result = await client.chat_json(
        system_prompt=(
            "你是城市更新决策顾问。只输出 JSON，含 options(至少3个)、recommended_option_id、decision_matrix、"
            "rejection_reasons。每个 option 必须含稳定 id、name、proposition、differentiation、feasibility、"
            "operating_sustainability、evidence_refs、counter_evidence、invalidation_conditions、risks。"
            "不得用文案包装替代方案竞争。"
        ),
        user_payload={
            "question": question,
            "evidence_ledger": evidence_ledger,
            "workpacks": workpacks,
        },
        emit=emit,
        phase="executing",
        title="生成定位竞争与决策矩阵",
        reasoning_id="stage1-options-model",
    )
    strategy = _mapping(strategy_result)

    await _emit_phase(
        emit,
        phase_id="stage1-spatial-matrix",
        title="形成空间功能决策矩阵",
        detail="逐空间比较候选功能、排除项、成立条件和组合平衡。",
    )
    matrix_result = await client.chat_json(
        system_prompt=(
            "你是存量空间功能策划负责人。只输出 JSON：matrix_version、positioning_option_id、"
            "spatial_hierarchy、space_decisions、portfolio_checks。spatial_hierarchy 必须含 system/cluster/unit。"
            "每个 space_decision 必须含 space_id、current_state、change_logic、candidate_functions(至少2项)、"
            "preferred_function、excluded_functions、audience_scenarios、access_and_movement、operation_strategy、"
            "renovation_and_delivery、preconditions、evidence_refs、assumptions、validation_actions、"
            "recommendation_status(strong/conditional/alternative/excluded)、confidence(high/medium/low)。"
            "空间建议必须说明前置条件，不得虚构产权、结构或消防结论。"
        ),
        user_payload={
            "question": question,
            "evidence_ledger": evidence_ledger,
            "workpacks": workpacks,
            "strategy": strategy,
        },
        emit=emit,
        phase="executing",
        title="生成空间功能策划矩阵",
        reasoning_id="stage1-spatial-matrix-model",
    )
    spatial_matrix = _mapping(matrix_result)
    package = {
        "evidence_ledger": evidence_ledger,
        "workpacks": workpacks,
        "strategy": strategy,
        "spatial_matrix": spatial_matrix,
    }

    audit = audit_stage1_package(package)
    await _emit_phase(
        emit,
        phase_id="stage1-quality-audit",
        title="执行交付前质量审计",
        detail=f"通过 {audit.checks_passed}/{audit.checks_total} 项，质量分 {audit.score}。",
        state="completed" if audit.status == "passed" else "failed",
    )
    panels = _base_panels(readiness, package, audit, verification)
    if audit.status != "passed":
        repair_tasks = [
            {
                "code": issue.code,
                "message": issue.message,
                "repair_hint": issue.repair_hint,
            }
            for issue in audit.blocking_issues
        ]
        panels["stage1_repair_tasks"] = repair_tasks
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question="中间分析未通过交付质量审计，已停止生成完整报告。请按修复任务补证或重新运行。",
                clarification_options=[
                    item["repair_hint"] or item["message"] for item in repair_tasks[:4]
                ],
                panel_payloads=panels,
            ),
            diagnostics=AgentTurnDiagnostics(
                audit_issues=[item["message"] for item in repair_tasks],
                research_notes=["质量审计未通过，最终报告模型未被调用。"],
            ),
            context_summary=AgentContextSummary(),
            plan=AgentPlanEnvelope(),
            effective_execution_profile=profile,
        )

    report = await client.chat_json(
        system_prompt=(
            "你是城市区域策划总顾问。只输出 JSON：answer(专业中文 Markdown 报告)、sources。"
            "报告必须含总判断、证据边界、定位方案比较、推荐定位、客群场景、功能组合、空间策略、"
            "运营治理、分期、风险、验证计划和设计任务书。仅使用已审计包；必须分列已验证、推断、假设、"
            "阻塞与现场核验事项；inferred/hypothesis 不得写成事实，blocked/fieldwork_required 不得写成既定条件。"
        ),
        user_payload={
            "question": question,
            "stage1_package": package,
            "evidence_verification": verification.model_dump(mode="json"),
            "quality_audit": _audit_payload(audit),
        },
        emit=emit,
        phase="synthesizing",
        title="编译 Stage 1 决策报告",
        reasoning_id="stage1-report-model",
    )
    answer = str(report.get("answer") or "").strip()
    panels["claim_evidence"] = evidence_ledger
    panels["sources_used"] = report.get("sources") or []
    return AgentTurnResponse(
        status="answered",
        stage="answered",
        output=AgentTurnOutput(answer=answer, panel_payloads=panels),
        diagnostics=AgentTurnDiagnostics(
            research_notes=["全部 Stage 1 阶段使用同一轮锁定的模型配置。"],
            audit_summary=f"质量审计通过：{audit.score} 分。",
        ),
        context_summary=AgentContextSummary(),
        plan=AgentPlanEnvelope(),
        effective_execution_profile=profile,
    )
