from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..llm_digest import snapshot_digest
from ..providers.client import LLMRuntimeConfig, get_llm_provider_client
from ..schemas import (
    AgentContextSummary, AgentPlanEnvelope, AgentThinkingItem, AgentTurnDiagnostics,
    AgentTurnOutput, AgentTurnRequest, AgentTurnResponse, EffectiveExecutionProfile,
)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


def evaluate_readiness(payload: AgentTurnRequest) -> dict[str, Any]:
    snapshot = payload.analysis_snapshot
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    sources = payload.selected_sources_context.source_items()
    project_text = " ".join(str(value) for value in context.values() if isinstance(value, (str, int, float)))
    missing: list[str] = []
    if not scope:
        missing.append("可识别的项目空间范围")
    if len(project_text.strip()) < 20:
        missing.append("项目摘要与核心决策问题")
    if not sources and not any((snapshot.frontend_analysis, snapshot.poi_summary, snapshot.population, snapshot.nightlight)):
        missing.append("核心项目文档或已选分析证据")
    return {"ready": not missing, "missing": missing, "source_count": len(sources)}


async def execute(
    payload: AgentTurnRequest,
    *,
    runtime: LLMRuntimeConfig,
    profile: EffectiveExecutionProfile,
    emit: Emit | None = None,
) -> AgentTurnResponse:
    readiness = evaluate_readiness(payload)
    if emit:
        await emit("thinking", {"id": "stage1-readiness", "phase": "gating", "title": "检查 Stage 1 资料完整性", "detail": "核对项目范围、摘要、核心文档和分析证据。", "state": "completed"})
    if not readiness["ready"]:
        missing = "、".join(readiness["missing"])
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question=f"执行城市区域策划第一阶段前，还需要补充：{missing}。请补齐后再生成完整报告。",
                clarification_options=["补充项目范围", "补充项目摘要与目标", "选择核心文档或分析结果"],
                panel_payloads={"stage1_readiness": readiness},
            ),
            diagnostics=AgentTurnDiagnostics(research_notes=["Stage 1 readiness 未通过，已停止完整报告生成。"]),
            context_summary=AgentContextSummary(),
            plan=AgentPlanEnvelope(),
            effective_execution_profile=profile,
        )
    client = get_llm_provider_client(runtime=runtime)
    if client is None:
        raise ValueError("所选模型 Provider 不可用")
    question = str(payload.messages[-1].content if payload.messages else "").strip()
    evidence = {
        "question": question,
        "snapshot": snapshot_digest(payload.analysis_snapshot),
        "selected_sources": payload.selected_sources_context.source_items(),
        "rules": ["区分事实、推断和假设", "保留冲突，不伪造精确指标", "所有结论给出证据来源或缺口"],
    }
    if emit:
        await emit("thinking", {"id": "stage1-workpacks", "phase": "executing", "title": "形成四类专家工作包", "detail": "区域结构、人群需求、文化文旅、存量更新与商业运营共享同一证据底座。", "state": "active"})
    workpacks = await client.chat_json(
        system_prompt="你是城市策划证据分析负责人。输出 JSON：workpacks 数组，必须覆盖 spatial、culture_tourism、renewal、commercial_operations；每项包含 findings、evidence_refs、uncertainties。不得补造数据。",
        user_payload=evidence, emit=emit, phase="executing", title="生成四类专家工作包", reasoning_id="stage1-workpacks-model",
    )
    if emit:
        await emit("thinking", {"id": "stage1-options", "phase": "executing", "title": "生成定位选项与决策矩阵", "detail": "比较定位适配度、差异化、实施难度、运营可持续性和风险。", "state": "active"})
    options = await client.chat_json(
        system_prompt="你是城市更新决策顾问。基于共享工作包输出 JSON：options（至少3个定位）、decision_matrix、recommended_option、rejection_reasons、invalidation_conditions。禁止引入输入之外的事实。",
        user_payload={"question": question, "workpacks": workpacks}, emit=emit, phase="executing", title="比较定位方案", reasoning_id="stage1-options-model",
    )
    report = await client.chat_json(
        system_prompt="你是城市区域策划总顾问。输出 JSON，字段 answer（专业中文 Markdown 报告）、claims（claim/evidence/status）、sources。报告必须含总判断、证据边界、推荐定位、客群、功能组合、空间策略、运营治理、分期、风险、设计任务书。明确事实/推断/待验证，不写建筑形态设计。",
        user_payload={"evidence": evidence, "workpacks": workpacks, "options": options}, emit=emit, phase="synthesizing", title="形成 Stage 1 决策报告", reasoning_id="stage1-report-model",
    )
    answer = str(report.get("answer") or "").strip()
    return AgentTurnResponse(
        status="answered", stage="answered",
        output=AgentTurnOutput(answer=answer, panel_payloads={"stage1_readiness": readiness, "stage1_workpacks": workpacks, "stage1_options": options, "claim_evidence": report.get("claims") or [], "sources_used": report.get("sources") or []}),
        diagnostics=AgentTurnDiagnostics(research_notes=["全部 Stage 1 阶段使用同一模型配置。"]),
        context_summary=AgentContextSummary(), plan=AgentPlanEnvelope(),
        effective_execution_profile=profile,
    )
