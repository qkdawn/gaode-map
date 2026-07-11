from __future__ import annotations

from typing import Any, Awaitable, Callable

from modules.documents import ProjectEvidenceDossier, build_project_evidence_dossier

from ..capability_inputs import resolve_capability_inputs
from ..evidence_verification import verify_evidence_ledger
from ..stage1_deliverables import (
    build_design_handoff,
    build_evidence_appendix,
    compile_stage1_deliverables,
)
from ..llm_digest import snapshot_digest
from ..providers.client import LLMRuntimeConfig, get_llm_provider_client
from ..quality_audit import QualityAuditResult, audit_stage1_package
from ..stage1_contracts import VerificationSummary
from ..stage1_data_quality import assess_stage1_data_quality
from ..stage1_provenance import (
    Stage1ProvenanceSummary,
    assess_provenance_bindings,
    bind_evidence_to_artifacts,
    build_provenance_registry,
    project_evidence_payload,
    provenance_registry_payload,
)
from ..stage1_runs import (
    bind_stage1_input_artifacts,
    build_stage1_output_artifacts,
    start_stage1_run,
)
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


def _conflict_register(
    selected_sources: list[dict[str, Any]],
    *,
    question: str,
    context_conflicts: list[Any],
    dossier: ProjectEvidenceDossier | None = None,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    document_sources = [
        source
        for source in selected_sources
        if str(source.get("source_id") or "").startswith("document:")
    ]
    if document_sources:
        resolved_dossier = dossier or build_project_evidence_dossier(
            document_sources, question=question
        )
        conflicts.extend(
            item.model_dump(mode="json") for item in resolved_dossier.conflicts
        )

    for index, item in enumerate(context_conflicts):
        if isinstance(item, dict):
            conflict = dict(item)
            conflict.setdefault("metric_key", f"context_conflict_{index + 1}")
            conflict.setdefault(
                "label",
                str(item.get("explanation") or item.get("metric_key") or "上下文冲突"),
            )
            conflict.setdefault("values", [])
            conflict.setdefault("evidence_ids", [])
            conflict.setdefault("unresolved", True)
            conflict.setdefault(
                "explanation",
                "当前分析上下文已标记该冲突，需保留不同口径并明确裁决依据。",
            )
        else:
            label = str(item or "").strip()
            if not label:
                continue
            conflict = {
                "metric_key": f"context_conflict_{index + 1}",
                "label": label,
                "values": [],
                "evidence_ids": [],
                "preferred_value": "",
                "preferred_evidence_id": "",
                "unresolved": True,
                "explanation": "当前分析上下文已标记该冲突，需保留不同口径并明确裁决依据。",
            }
        conflicts.append(conflict)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for conflict in conflicts:
        key = (str(conflict.get("metric_key") or ""), str(conflict.get("label") or ""))
        if key not in seen:
            seen.add(key)
            deduped.append(conflict)
    return deduped


def _audit_payload(audit: QualityAuditResult) -> dict[str, Any]:
    return audit.model_dump(mode="json")


def _critical_evidence_ids(
    strategy: dict[str, Any], spatial_matrix: dict[str, Any]
) -> set[str]:
    recommended_id = str(strategy.get("recommended_option_id") or "").strip()
    critical: set[str] = set()
    for option in strategy.get("options") or []:
        if (
            not isinstance(option, dict)
            or str(option.get("id") or "").strip() != recommended_id
        ):
            continue
        critical.update(
            str(item).strip()
            for item in option.get("evidence_refs") or []
            if str(item).strip()
        )
    for decision in spatial_matrix.get("space_decisions") or []:
        if not isinstance(decision, dict):
            continue
        if decision.get("recommendation_status") not in {"strong", "conditional"}:
            continue
        critical.update(
            str(item).strip()
            for item in decision.get("evidence_refs") or []
            if str(item).strip()
        )
    return critical


def _base_panels(
    readiness: dict[str, Any],
    package: dict[str, Any],
    audit: QualityAuditResult,
    verification: VerificationSummary,
    provenance: Stage1ProvenanceSummary,
) -> dict[str, Any]:
    return {
        "stage1_project_brief": package["project_brief"],
        "stage1_readiness": readiness,
        "stage1_evidence_ledger": package["evidence_ledger"],
        "stage1_conflict_register": package["conflict_register"],
        "stage1_data_quality": package["data_quality"],
        "stage1_provenance_binding": provenance.model_dump(mode="json"),
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
    question = str(payload.messages[-1].content if payload.messages else "").strip()
    selected_sources = payload.selected_sources_context.source_items()
    capability_id = str(payload.target_capability_id or "urban-strategy-stage1").strip()
    from ..capability_catalog import get_analysis_capability

    capability = get_analysis_capability(capability_id)
    if capability.executor_type != "skill" or capability.executor_id != "urban-strategy-stage1":
        raise ValueError("capability_executor_mismatch")
    resolved_inputs = resolve_capability_inputs(capability_id, payload)
    run = start_stage1_run(
        payload,
        profile=profile,
        question=question,
        selected_sources=selected_sources,
        capability_id=capability_id,
        resolved_inputs=resolved_inputs,
    )
    readiness = evaluate_readiness(payload)
    if capability_id == "spatial-programming-matrix" and any(
        item.state == "resolved" for item in resolved_inputs.resolutions
    ):
        readiness["missing"] = [
            item
            for item in readiness.get("missing", [])
            if item != "核心项目文档或已选分析证据"
        ]
        readiness["actions"] = [
            item
            for item in readiness.get("actions", [])
            if item.get("target") != "analysis-sources"
        ]
        if "Stage 1 分析依据" not in readiness["satisfied"]:
            readiness["satisfied"].append("Stage 1 分析依据")
        readiness["ready"] = not readiness["missing"]
    if resolved_inputs.blocking_diagnostics:
        readiness["ready"] = False
        readiness["missing"] = [
            *readiness.get("missing", []),
            *[
                item.label
                for item in resolved_inputs.resolutions
                if item.required and item.state not in {"resolved", "ignored"}
            ],
        ]
        readiness["conflicts"] = [
            *readiness.get("conflicts", []),
            *resolved_inputs.blocking_diagnostics,
        ]
    await _emit_phase(
        emit,
        phase_id="stage1-readiness",
        title="检查 Stage 1 资料完整性",
        detail="核对项目范围、摘要、核心文档和分析证据。",
        state="completed",
    )
    if not readiness["ready"]:
        missing = "、".join(readiness["missing"])
        run.record_stage(
            "readiness",
            "资料完整性检查",
            status="waiting_for_user",
            summary=f"缺少：{missing}",
            diagnostics=list(readiness["missing"]),
        )
        run_manifest = run.finish(
            "waiting_for_user",
            current_stage="readiness",
            diagnostics=list(readiness["missing"]),
        )
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question=f"执行城市区域策划第一阶段前，还需要补充：{missing}。",
                clarification_options=[
                    action["label"] for action in readiness["actions"]
                ],
                panel_payloads={
                    "stage1_readiness": readiness,
                    "capability_run": run_manifest.model_dump(mode="json"),
                },
            ),
            diagnostics=AgentTurnDiagnostics(
                research_notes=["Stage 1 readiness 未通过，未调用模型生成报告。"]
            ),
            context_summary=AgentContextSummary(),
            plan=AgentPlanEnvelope(),
            effective_execution_profile=profile,
        )

    run.record_stage(
        "readiness",
        "资料完整性检查",
        summary=f"满足 {len(readiness['satisfied'])} 项必需输入。",
    )
    client = get_llm_provider_client(runtime=runtime)
    if client is None:
        raise ValueError("所选模型 Provider 不可用")
    dossier = build_project_evidence_dossier(selected_sources, question=question)
    conflict_register = _conflict_register(
        selected_sources,
        question=question,
        context_conflicts=readiness["conflicts"],
        dossier=dossier,
    )
    provenance_registry = build_provenance_registry(
        selected_sources=selected_sources,
        snapshot=payload.analysis_snapshot,
        dossier=dossier,
    )
    input_artifacts = [
        *bind_stage1_input_artifacts(provenance_registry),
        *resolved_inputs.input_artifact_refs,
    ]
    run.set_input_artifacts(input_artifacts)
    input_artifact_ids = [item.artifact_id for item in input_artifacts]
    project_brief = {
        "question": question,
        "project_context": payload.analysis_snapshot.context,
        "scope": payload.analysis_snapshot.scope,
    }
    evidence_input = {
        "question": question,
        "project_context": payload.analysis_snapshot.context,
        "snapshot": snapshot_digest(payload.analysis_snapshot),
        "selected_sources": selected_sources,
        "project_evidence": project_evidence_payload(dossier),
        "authoritative_artifacts": provenance_registry_payload(provenance_registry),
        "known_conflicts": conflict_register,
        "optional_gaps": readiness["missing_optional"],
        "upstream_artifacts": [
            {
                "requirement_id": item.requirement_id,
                "source_run_id": item.selected_run_id,
                "artifact_refs": [ref.model_dump(mode="json") for ref in item.artifact_refs],
                "artifact_payloads": {
                    key: value
                    for key, value in resolved_inputs.artifact_payloads.items()
                    if key.startswith(f"{item.selected_run_id}:")
                },
                "diagnostics": item.diagnostics,
            }
            for item in resolved_inputs.resolutions
            if item.state == "resolved"
        ],
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
            "comparison_baseline、confidence(high/medium/low)、limitation、next_action、executor(agent/fieldwork)，"
            "以及 source_date、source_locator。G/P/V 分析证据还必须含 analysis_date、sample_size、missing_count、"
            "duplicate_count、anomaly_count、coordinate_system、coordinate_transform。"
            "source_artifact_id 必须保留文档节点或分析产物 ID，method 必须说明读取或计算方法。"
            "source_date/analysis_date 使用 ISO 日期或年份，无法确认时写 unknown，不得用当前日期猜测；"
            "source_locator 必须能下钻到页码、章节、节点或分析 artifact 结果键。"
            "没有页码时明确写来源路径或数据集；不得把夜光、POI、gap_score、周边人口解释为客流、消费或经营成功。"
            "已知冲突不得静默选边；若引用冲突证据，必须降级结论并保留冲突说明。"
        ),
        user_payload=evidence_input,
        emit=emit,
        phase="executing",
        title="构建 Claim-Evidence 台账",
        reasoning_id="stage1-evidence-model",
    )
    evidence_ledger, provenance_bindings = bind_evidence_to_artifacts(
        _list_from(evidence_result, "evidence_ledger"),
        registry=provenance_registry,
    )
    provenance = assess_provenance_bindings(provenance_bindings)
    evidence_ledger, verification = verify_evidence_ledger(
        evidence_ledger,
        selected_sources=selected_sources,
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
    run.record_stage(
        "evidence-ledger",
        "建立证据台账",
        summary=f"登记并绑定 {len(evidence_ledger)} 条证据。",
    )
    run.record_stage(
        "evidence-verification",
        "验证证据状态与时效",
        status="completed" if verification.report_allowed else "waiting_for_user",
        summary=f"门控状态：{verification.status}。",
        diagnostics=list(verification.blocking_reasons),
    )
    if not verification.report_allowed:
        verification_payload = verification.model_dump(mode="json")
        partial_package = {
            "project_brief": project_brief,
            "source_readiness": readiness,
            "evidence_ledger": evidence_ledger,
            "conflict_register": conflict_register,
        }
        output_artifacts = build_stage1_output_artifacts(
            run_id=run.run_id,
            package=partial_package,
            input_artifact_ids=input_artifact_ids,
        )
        run_manifest = run.finish(
            "waiting_for_user",
            current_stage="evidence-verification",
            diagnostics=list(verification.blocking_reasons),
            output_artifacts=output_artifacts,
        )
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question="证据台账未通过验证门控，已停止专业推演。请补充可定位证据后重新运行。",
                clarification_options=verification.blocking_reasons[:4],
                panel_payloads={
                    "stage1_project_brief": project_brief,
                    "stage1_readiness": readiness,
                    "stage1_evidence_ledger": evidence_ledger,
                    "stage1_conflict_register": conflict_register,
                    "stage1_provenance_binding": provenance.model_dump(mode="json"),
                    "stage1_evidence_verification": verification_payload,
                    "capability_run": run_manifest.model_dump(mode="json"),
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
    run.record_stage(
        "expert-workpacks",
        "形成专业工作包",
        summary=f"生成 {len(workpacks)} 个共享证据底座的专业工作包。",
    )

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
            "不得用文案包装替代方案竞争。首选方案必须至少引用一条 verified 或 cross_checked 证据，"
            "不得把未解决冲突作为唯一支撑。"
        ),
        user_payload={
            "question": question,
            "evidence_ledger": evidence_ledger,
            "conflict_register": conflict_register,
            "workpacks": workpacks,
        },
        emit=emit,
        phase="executing",
        title="生成定位竞争与决策矩阵",
        reasoning_id="stage1-options-model",
    )
    strategy = _mapping(strategy_result)
    run.record_stage(
        "strategy-options",
        "比较定位方案",
        summary=(
            f"比较 {len(strategy.get('options') or [])} 个定位方案，"
            f"推荐 {strategy.get('recommended_option_id') or '未确定'}。"
        ),
    )

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
            "strong 建议不得依赖未解决冲突证据；存在冲突时应降级为 conditional 并写明前置条件。"
        ),
        user_payload={
            "question": question,
            "evidence_ledger": evidence_ledger,
            "conflict_register": conflict_register,
            "workpacks": workpacks,
            "strategy": strategy,
        },
        emit=emit,
        phase="executing",
        title="生成空间功能策划矩阵",
        reasoning_id="stage1-spatial-matrix-model",
    )
    spatial_matrix = _mapping(matrix_result)
    run.record_stage(
        "spatial-decision-matrix",
        "形成空间功能决策矩阵",
        summary=(
            f"形成 {len(spatial_matrix.get('space_decisions') or [])} 个空间决策。"
        ),
    )
    critical_evidence_ids = _critical_evidence_ids(strategy, spatial_matrix)
    provenance = assess_provenance_bindings(
        provenance_bindings,
        critical_evidence_ids=critical_evidence_ids,
    )
    await _emit_phase(
        emit,
        phase_id="stage1-provenance-binding",
        title="绑定证据与真实数据资产",
        detail=(
            f"核对 {provenance.assessed_count} 条证据；"
            f"已验证 {provenance.status_counts.get('verified', 0)} 条、"
            f"修正 {provenance.status_counts.get('corrected', 0)} 条、"
            f"无法定位 {provenance.status_counts.get('unverifiable', 0)} 条。"
        ),
        state="completed" if provenance.status != "failed" else "failed",
    )
    data_quality = assess_stage1_data_quality(
        evidence_ledger,
        critical_evidence_ids=critical_evidence_ids,
    )
    await _emit_phase(
        emit,
        phase_id="stage1-data-quality",
        title="检查数据质量与时空口径",
        detail=(
            f"审计 {data_quality.assessed_count} 条证据；"
            f"发现 {len(data_quality.blocking_issues)} 项阻断和 "
            f"{len(data_quality.issues) - len(data_quality.blocking_issues)} 项提示。"
        ),
        state="completed" if data_quality.status != "failed" else "failed",
    )
    run.record_stage(
        "quality-and-provenance",
        "检查数据质量与产物来源",
        status="completed" if data_quality.status != "failed" else "failed",
        summary=(f"数据质量 {data_quality.status}；真实资产绑定 {provenance.status}。"),
        diagnostics=[item.message for item in data_quality.issues],
    )
    package = {
        "project_brief": project_brief,
        "source_readiness": readiness,
        "evidence_ledger": evidence_ledger,
        "conflict_register": conflict_register,
        "data_quality": data_quality.model_dump(mode="json"),
        "provenance_binding": provenance.model_dump(mode="json"),
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
    run.record_stage(
        "quality-audit",
        "执行交付前质量审计",
        status="completed" if audit.status == "passed" else "waiting_for_user",
        summary=f"通过 {audit.checks_passed}/{audit.checks_total} 项，质量分 {audit.score}。",
        diagnostics=[item.message for item in audit.blocking_issues],
    )
    panels = _base_panels(readiness, package, audit, verification, provenance)
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
        output_artifacts = build_stage1_output_artifacts(
            run_id=run.run_id,
            package=package,
            input_artifact_ids=input_artifact_ids,
        )
        run_manifest = run.finish(
            "waiting_for_user",
            current_stage="quality-audit",
            diagnostics=[item["message"] for item in repair_tasks],
            output_artifacts=output_artifacts,
        )
        panels["capability_run"] = run_manifest.model_dump(mode="json")
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

    design_handoff = build_design_handoff(package)
    evidence_appendix = build_evidence_appendix(package)
    report = await client.chat_json(
        system_prompt=(
            "你是城市区域策划总顾问。只输出 JSON：answer(专业中文 Markdown 报告)、sources。"
            "报告必须含总判断、证据边界、定位方案比较、推荐定位、客群场景、功能组合、空间策略、"
            "运营治理、分期、风险、验证计划和设计任务书。仅使用已审计包；必须分列已验证、推断、假设、"
            "阻塞与现场核验事项；必须披露 data_quality 中的时效、样本、坐标与来源定位缺口；"
            "inferred/hypothesis 不得写成事实，blocked/fieldwork_required 不得写成既定条件。"
        ),
        user_payload={
            "question": question,
            "stage1_package": package,
            "evidence_verification": verification.model_dump(mode="json"),
            "quality_audit": _audit_payload(audit),
            "evidence_appendix": evidence_appendix,
            "design_handoff": design_handoff.model_dump(mode="json"),
        },
        emit=emit,
        phase="synthesizing",
        title="编译 Stage 1 决策报告",
        reasoning_id="stage1-report-model",
    )
    answer = str(report.get("answer") or "").strip()
    run.record_stage(
        "stage1-report",
        "编译 Stage 1 决策报告",
        summary="最终报告只读取通过审计的 Stage 1 包。",
    )
    run.record_stage(
        "formal-deliverables",
        "编译正式交付物",
        summary="报告、证据附录、设计任务书与运行清单共享同一运行版本。",
    )
    handoff_payload = design_handoff.model_dump(mode="json")
    output_artifacts = build_stage1_output_artifacts(
        run_id=run.run_id,
        package=package,
        input_artifact_ids=input_artifact_ids,
        report_markdown=answer,
        evidence_appendix=evidence_appendix,
        design_handoff=handoff_payload,
        include_manifest=True,
    )
    warning_messages = [
        *list(readiness["missing_optional"]),
        *list(verification.notes),
        *[item.message for item in data_quality.issues],
    ]
    run_manifest = run.finish(
        "completed_with_warnings" if warning_messages else "completed",
        current_stage="formal-deliverables",
        diagnostics=warning_messages,
        output_artifacts=output_artifacts,
    )
    deliverables = compile_stage1_deliverables(
        package,
        report_markdown=answer,
        run_manifest=run_manifest,
    )
    await _emit_phase(
        emit,
        phase_id="stage1-deliverables",
        title="编译正式交付物",
        detail="主报告、证据附录、设计任务书与运行清单已从同一审计包生成。",
        state="completed",
    )
    panels["claim_evidence"] = evidence_ledger
    panels["sources_used"] = report.get("sources") or []
    panels["capability_run"] = run_manifest.model_dump(mode="json")
    panels["stage1_deliverables"] = deliverables.model_dump(mode="json")
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
