from __future__ import annotations

import asyncio
import inspect
from contextlib import suppress
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List

from core.config import settings

from .auditor import audit_execution
from .context_builder import build_context_bundle, build_context_summary
from .gate import latest_user_message
from .governance import check_tool_governance
from .memory import create_working_memory
from .providers.llm_provider import (
    audit_with_llm,
    generate_answer_output_with_llm,
    is_llm_enabled,
    plan_with_llm,
    run_gate_with_llm,
)
from .review_contract import build_review_contract
from .schemas import (
    AgentPlanEnvelope,
    AgentThinkingItem,
    AgentTurnDiagnostics,
    AgentTurnOutput,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentTurnStreamEvent,
    AuditResult,
    PlanStep,
    PlanningResult,
)
from .state_machine import AgentStateMachine
from .synthesizer import (
    build_cards,
    build_citations,
    build_next_suggestions,
    build_synthesis_payload,
    enrich_answer_output,
)
from .tool_service import run_registered_tool
from .tools import get_tool_registry

StreamEmit = Callable[[str, dict[str, Any]], Awaitable[None] | None]

_STAGE_LABELS = {
    "gating": "门卫判断",
    "clarifying": "生成追问",
    "context_ready": "整理上下文",
    "planning": "规划分析步骤",
    "executing": "执行工具",
    "auditing": "审计结果",
    "replanning": "根据审计重新规划",
    "synthesizing": "综合分析",
    "answered": "已完成",
    "failed": "失败",
    "requires_clarification": "需要补充信息",
    "requires_risk_confirmation": "等待风险确认",
}


async def _maybe_emit(emit: StreamEmit | None, event_type: str, payload: dict[str, Any]) -> None:
    if emit is None:
        return
    outcome = emit(event_type, payload)
    if inspect.isawaitable(outcome):
        await outcome


async def _emit_status(emit: StreamEmit | None, stage: str) -> None:
    await _maybe_emit(emit, "status", {"stage": stage, "label": _STAGE_LABELS.get(stage, stage)})


def _timeline_item(seed: dict[str, Any], fallback_id: str) -> AgentThinkingItem:
    payload = dict(seed or {})
    payload.setdefault("id", fallback_id)
    payload.setdefault("phase", "")
    payload.setdefault("title", "处理中")
    payload.setdefault("detail", "")
    payload.setdefault("state", "pending")
    return AgentThinkingItem(**payload)


def _trace_to_thinking_payload(seed: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    payload = dict(seed or {})
    tool_name = str(payload.get("tool_name") or "unknown_tool").strip()
    status = str(payload.get("status") or "").strip()
    state = "completed" if status == "success" else ("failed" if status in {"failed", "blocked", "skipped"} else "active")
    title_status = {
        "start": "开始调用",
        "success": "执行成功",
        "failed": "执行失败",
        "blocked": "等待确认",
        "skipped": "已跳过",
    }.get(status, status or "执行中")
    items: List[str] = []
    arguments_summary = str(payload.get("arguments_summary") or "").strip()
    result_summary = str(payload.get("result_summary") or "").strip()
    produced_artifacts = [str(item) for item in (payload.get("produced_artifacts") or []) if str(item).strip()]
    if arguments_summary:
        items.append(f"参数：{arguments_summary}")
    if result_summary:
        items.append(f"结果：{result_summary}")
    if payload.get("evidence_count") not in (None, ""):
        items.append(f"证据：{payload.get('evidence_count')} 条")
    if payload.get("warning_count") not in (None, "", 0):
        items.append(f"警告：{payload.get('warning_count')} 条")
    if produced_artifacts:
        items.append(f"产物：{'、'.join(produced_artifacts[:6])}")
    phase = str(payload.get("phase") or "executing")
    return {
        "id": str(payload.get("id") or payload.get("call_id") or fallback_id),
        "phase": phase,
        "title": f"{title_status} {tool_name}",
        "detail": str(payload.get("message") or payload.get("reason") or ""),
        "items": items,
        "meta": {
            "tool_name": tool_name,
            "status": status,
            "call_id": str(payload.get("call_id") or ""),
        },
        "state": state,
    }


async def _emit_preflight_trace(
    *,
    emit: StreamEmit | None,
    step_tool_name: str,
    step_index: int,
    data_readiness: Dict[str, Any],
) -> None:
    if not emit or not isinstance(data_readiness, dict):
        return
    reused = [str(item) for item in (data_readiness.get("reused") or []) if str(item).strip()]
    fetched = [str(item) for item in (data_readiness.get("fetched") or []) if str(item).strip()]
    ready = bool(data_readiness.get("ready"))
    await _maybe_emit(
        emit,
        "trace",
        {
            "id": f"precheck:{step_tool_name}:{step_index}",
            "tool_name": "analysis_preflight",
            "phase": "precheck",
            "status": "success" if data_readiness.get("checked") else "failed",
            "reason": "checked",
            "message": "已完成现有数据检查",
            "result_summary": f"复用: {', '.join(reused) if reused else '无'}",
            "produced_artifacts": ["current_data_readiness"],
        },
    )
    await _maybe_emit(
        emit,
        "trace",
        {
            "id": f"fetch-missing:{step_tool_name}:{step_index}",
            "tool_name": "analysis_preflight",
            "phase": "fetch_missing",
            "status": "success" if ready else "failed",
            "reason": "fetched_missing",
            "message": "已按缺失维度补齐数据" if ready else "缺失维度补齐失败",
            "result_summary": f"补齐: {', '.join(fetched) if fetched else '无'}",
            "produced_artifacts": ["current_area_data_bundle", "current_data_readiness"],
        },
    )
    await _maybe_emit(
        emit,
        "trace",
        {
            "id": f"analysis-start:{step_tool_name}:{step_index}",
            "tool_name": "analysis_preflight",
            "phase": "analysis",
            "status": "start" if ready else "failed",
            "reason": "analysis_started",
            "message": "数据就绪，开始分析" if ready else "数据未就绪，阻止进入分析",
            "produced_artifacts": ["current_data_readiness"],
        },
    )


def _build_diagnostics(
    *,
    memory,
    used_tools: List[str] | None = None,
    citations: List[str] | None = None,
    error: str = "",
    thinking_timeline: List[AgentThinkingItem] | None = None,
    research_notes: List[str] | None = None,
    planning_summary: str = "",
    audit_summary: str = "",
    review_contract: Dict[str, Any] | None = None,
    replan_count: int = 0,
) -> AgentTurnDiagnostics:
    return AgentTurnDiagnostics(
        execution_trace=list(memory.execution_trace or []),
        used_tools=list(used_tools or []),
        citations=list(citations or []),
        research_notes=list(research_notes if research_notes is not None else (memory.research_notes or [])),
        audit_issues=list(memory.audit_issues or []),
        thinking_timeline=list(thinking_timeline or []),
        planning_summary=str(planning_summary or ""),
        audit_summary=str(audit_summary or ""),
        review_contract=dict(review_contract or {}),
        replan_count=int(replan_count or 0),
        error=str(error or ""),
    )


async def _execute_planned_steps(
    *,
    plan: PlanningResult,
    payload: AgentTurnRequest,
    question: str,
    memory,
    used_tools: List[str],
    thinking_timeline: List[AgentThinkingItem],
    plan_envelope: AgentPlanEnvelope,
    planning_summary: str,
    audit_summary: str,
    replan_count: int,
    emit: StreamEmit | None = None,
) -> AgentTurnResponse | None:
    snapshot = payload.analysis_snapshot
    registry = get_tool_registry()
    for step in plan.steps:
        registered = registry.get(step.tool_name)
        await _maybe_emit(
            emit,
            "trace",
            {
                "id": f"plan:{step.tool_name}:{len(used_tools) + 1}",
                "tool_name": step.tool_name,
                "status": "start",
                "reason": step.reason,
                "message": step.evidence_goal or step.reason or "开始执行规划步骤",
                "arguments_summary": "无参数" if not step.arguments else str(step.arguments),
                "produced_artifacts": list(step.expected_artifacts or []),
            },
        )
        if registered is None:
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    error=f"unknown_tool:{step.tool_name}",
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=plan_envelope,
            )
        prompt = check_tool_governance(
            mode=payload.governance_mode,
            spec=registered.spec,
            confirmed_tools=payload.risk_confirmations,
        )
        if prompt:
            return AgentTurnResponse(
                status="requires_risk_confirmation",
                stage="requires_risk_confirmation",
                output=AgentTurnOutput(risk_prompt=prompt),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=plan_envelope,
            )
        execution = await run_registered_tool(
            registry=registry,
            step=step,
            snapshot=snapshot,
            artifacts=memory.artifacts,
            question=question,
            caller="internal",
        )
        result = execution.result
        trace = execution.trace
        data_readiness = dict(result.result.get("data_readiness") or {}) if isinstance(result.result, dict) else {}
        if data_readiness.get("checked"):
            await _emit_preflight_trace(
                emit=emit,
                step_tool_name=step.tool_name,
                step_index=len(used_tools) + 1,
                data_readiness=data_readiness,
            )
        await _maybe_emit(
            emit,
            "trace",
            {
                "id": f"plan:{step.tool_name}:{len(used_tools) + 1}",
                "tool_name": step.tool_name,
                "phase": "analysis" if data_readiness.get("checked") else "executing",
                "status": result.status,
                "reason": step.reason,
                "message": trace.message or ("执行成功" if result.status == "success" else "执行失败"),
                "arguments_summary": "无参数" if not step.arguments else str(step.arguments),
                "result_summary": result.error or ("执行成功" if result.status == "success" else "执行失败"),
                "evidence_count": len(result.evidence or []),
                "warning_count": len(result.warnings or []),
                "produced_artifacts": list((result.artifacts or {}).keys())[:12],
            },
        )
        memory.execution_trace.append(trace)
        used_tools.append(step.tool_name)
        memory.tool_results.append(result)
        if result.artifacts:
            memory.artifacts.update(result.artifacts)
        if result.warnings:
            memory.research_notes.extend([str(item) for item in result.warnings if str(item).strip()])
        if result.status == "failed" and not step.optional:
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    error=str(result.error or "tool_execution_failed"),
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=plan_envelope,
            )
    return None


async def _run_agent_turn(payload: AgentTurnRequest, *, emit: StreamEmit | None = None) -> AgentTurnResponse:
    snapshot = payload.analysis_snapshot
    question = latest_user_message(payload.messages)
    is_deep_review_turn = "执行模式：深度思考" in question or "深度思考继续分析任务" in question
    state = AgentStateMachine()
    thinking_timeline: List[AgentThinkingItem] = []

    async def emit_event(event_type: str, event_payload: dict[str, Any]) -> None:
        if event_type == "trace":
            await _maybe_emit(emit, event_type, event_payload)
            event_payload = _trace_to_thinking_payload(
                event_payload,
                f"trace-{len(thinking_timeline) + 1}",
            )
        elif event_type != "thinking":
            await _maybe_emit(emit, event_type, event_payload)
            return
        item = _timeline_item(event_payload, str(event_payload.get("id") or f"thinking-{len(thinking_timeline) + 1}"))
        existing_index = next((index for index, current in enumerate(thinking_timeline) if current.id == item.id), -1)
        if existing_index >= 0:
            thinking_timeline[existing_index] = item
        else:
            thinking_timeline.append(item)
        await _maybe_emit(emit, "thinking", item.model_dump(mode="json"))

    async def emit_thinking(seed: dict[str, Any], fallback_id: str) -> None:
        payload = dict(seed or {})
        payload.setdefault("id", fallback_id)
        await emit_event("thinking", payload)

    context = build_context_bundle(snapshot)
    memory = create_working_memory()
    used_tools: List[str] = []
    initial_plan_steps: List[PlanStep] = []
    replan_steps: List[PlanStep] = []
    planning_summary = ""
    audit_summary = ""
    latest_rule_audit = AuditResult()
    replan_count = 0
    audit_feedback: dict[str, Any] = {}
    max_replans = max(0, int(settings.ai_max_replans or 2))

    await _maybe_emit(emit, "meta", {"conversation_id": str(payload.conversation_id or "")})
    await _emit_status(emit, state.stage)
    await emit_thinking(
        {
            "phase": "gating",
            "title": "门卫判断",
            "detail": "正在判断问题是否清晰、范围是否可执行。",
            "state": "active",
        },
        "gating-check",
    )

    if not is_llm_enabled():
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=AgentTurnDiagnostics(
                error="LLM provider 未启用或配置不完整，当前版本要求 DeepSeek chat completions 多角色编排。",
                thinking_timeline=list(thinking_timeline or []),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(),
        )

    try:
        gate = await run_gate_with_llm(
            messages=payload.messages,
            snapshot=snapshot,
            context=context,
            emit=emit_event,
        )
    except Exception as exc:
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=AgentTurnDiagnostics(
                error=f"Gatekeeper 调用失败：{exc}",
                thinking_timeline=list(thinking_timeline or []),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(),
        )

    if gate.status == "clarify":
        state.move_to("clarifying")
        await _emit_status(emit, "clarifying")
        await emit_thinking(
            {
                "phase": "clarifying",
                "title": "需要先补充信息",
                "detail": gate.summary or gate.clarification_question,
                "items": list(gate.clarification_questions or []),
                "state": "failed",
            },
            "clarify-question",
        )
        await _emit_status(emit, "requires_clarification")
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question=gate.clarification_question,
                clarification_options=list(gate.clarification_options or []),
            ),
            diagnostics=AgentTurnDiagnostics(
                research_notes=list(gate.research_notes or []) + list(gate.missing_information or []),
                thinking_timeline=list(thinking_timeline or []),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(summary=gate.summary or ""),
        )
    if gate.status == "block":
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=AgentTurnDiagnostics(
                error=gate.blocked_reason or gate.summary or "当前请求被门卫节点阻断",
                thinking_timeline=list(thinking_timeline or []),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(summary=gate.summary or ""),
        )

    await emit_thinking(
        {
            "phase": "gating",
            "title": "门卫通过",
            "detail": gate.summary or "问题已明确，可以进入规划阶段。",
            "state": "completed",
        },
        "gating-check",
    )

    while True:
        stage_name = "planning" if replan_count == 0 else "replanning"
        state.move_to(stage_name)
        await _emit_status(emit, stage_name)
        await emit_thinking(
            {
                "phase": stage_name,
                "title": "规划本轮分析步骤" if replan_count == 0 else "根据审计重新规划",
                "detail": "正在决定本轮应调用哪些工具、补哪些证据。",
                "state": "active",
            },
            f"plan-{replan_count}",
        )
        try:
            plan = await plan_with_llm(
                messages=payload.messages,
                snapshot=snapshot,
                context=context,
                registry=get_tool_registry(),
                memory=memory,
                audit_feedback=audit_feedback,
                emit=emit_event,
            )
        except Exception as exc:
            await _emit_status(emit, "failed")
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    error=f"Planner 调用失败：{exc}",
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=AgentPlanEnvelope(summary=planning_summary),
            )
        planning_summary = plan.summary
        if replan_count == 0:
            initial_plan_steps = list(plan.steps or [])
        else:
            replan_steps.extend(list(plan.steps or []))
        await emit_thinking(
            {
                "phase": stage_name,
                "title": "规划完成" if replan_count == 0 else "重新规划完成",
                "detail": plan.summary or "已形成下一步执行计划。",
                "items": [step.reason or step.tool_name for step in (plan.steps or [])[:6]],
                "state": "completed",
            },
            f"plan-{replan_count}",
        )

        state.move_to("executing")
        await _emit_status(emit, "executing")
        await emit_thinking(
            {
                "phase": "executing",
                "title": "执行工具",
                "detail": "正在按规划步骤执行工具并收集证据。",
                "state": "active",
            },
            f"executing-{replan_count}",
        )
        current_plan_envelope = AgentPlanEnvelope(
            steps=list(initial_plan_steps or []),
            followup_steps=list(replan_steps or []),
            followup_applied=bool(replan_steps),
            summary=planning_summary,
        )
        await _maybe_emit(
            emit,
            "plan",
            current_plan_envelope.model_dump(mode="json"),
        )
        execution_failure = await _execute_planned_steps(
            plan=plan,
            payload=payload,
            question=question,
            memory=memory,
            used_tools=used_tools,
            thinking_timeline=thinking_timeline,
            plan_envelope=current_plan_envelope,
            planning_summary=planning_summary,
            audit_summary=audit_summary,
            replan_count=replan_count,
            emit=emit_event,
        )
        if execution_failure is not None:
            return execution_failure
        await emit_thinking(
            {
                "phase": "executing",
                "title": "执行完成",
                "detail": "本轮工具执行结束，准备进入审计。",
                "state": "completed",
            },
            f"executing-{replan_count}",
        )

        state.move_to("auditing")
        await _emit_status(emit, "auditing")
        await emit_thinking(
            {
                "phase": "auditing",
                "title": "审计结果",
                "detail": "正在检查证据是否足够回答用户问题。",
                "state": "active",
            },
            f"audit-{replan_count}",
        )
        latest_rule_audit = audit_execution(question=question, snapshot=snapshot, context=context, memory=memory)
        try:
            verdict = await audit_with_llm(
                question=question,
                snapshot=snapshot,
                context=context,
                memory=memory,
                plan=plan,
                rule_audit=latest_rule_audit,
                replan_count=replan_count,
                emit=emit_event,
            )
        except Exception as exc:
            await _emit_status(emit, "failed")
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    error=f"Auditor 调用失败：{exc}",
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=current_plan_envelope,
            )
        audit_summary = verdict.summary
        memory.audit_issues = list(verdict.issues or [])
        if verdict.status == "pass" and verdict.should_answer:
            await emit_thinking(
                {
                    "phase": "auditing",
                    "title": "审计通过",
                    "detail": verdict.summary or "当前证据足以支持回答。",
                    "state": "completed",
                },
                f"audit-{replan_count}",
            )
            break
        if verdict.status == "fail":
            await _emit_status(emit, "failed")
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    error=verdict.summary or "审计未通过",
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=current_plan_envelope,
            )
        if replan_count >= max_replans:
            await _emit_status(emit, "failed")
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=_build_diagnostics(
                    memory=memory,
                    used_tools=used_tools,
                    error=verdict.summary or f"重规划超过上限 {max_replans}",
                    thinking_timeline=thinking_timeline,
                    planning_summary=planning_summary,
                    audit_summary=audit_summary,
                    replan_count=replan_count,
                ),
                context_summary=build_context_summary(snapshot, memory.artifacts),
                plan=current_plan_envelope,
            )
        await emit_thinking(
            {
                "phase": "auditing",
                "title": "审计要求补充证据",
                "detail": verdict.summary or "当前证据还不够，需要重新规划。",
                "items": list(verdict.missing_evidence or []),
                "state": "failed",
            },
            f"audit-{replan_count}",
        )
        replan_count += 1
        audit_feedback = {
            "summary": verdict.summary,
            "issues": list(verdict.issues or []),
            "missing_evidence": list(verdict.missing_evidence or []),
            "replan_instructions": verdict.replan_instructions,
        }

    synthesis_payload = build_synthesis_payload(
        question=question,
        snapshot=snapshot,
        artifacts=memory.artifacts,
        tool_results=memory.tool_results,
        research_notes=list(memory.research_notes or []),
        audit=latest_rule_audit,
    )
    citations = build_citations(snapshot, memory.artifacts)
    state.move_to("synthesizing")
    await _emit_status(emit, "synthesizing")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "综合分析",
            "detail": "正在组织最终判断、证据依据与建议。",
            "state": "active",
        },
        "synthesizing-final",
    )
    try:
        answer_output = await generate_answer_output_with_llm(
            messages=payload.messages,
            snapshot=snapshot,
            context=context,
            synthesis_payload=synthesis_payload,
            emit=emit_event,
        )
    except Exception:
        cards = build_cards(
            question=question,
            snapshot=snapshot,
            artifacts=memory.artifacts,
            tool_results=memory.tool_results,
            research_notes=list(memory.research_notes or []),
            audit=latest_rule_audit,
        )
        answer_output = AgentTurnOutput(
            cards=cards,
            next_suggestions=build_next_suggestions(question, latest_rule_audit),
        )

    state.move_to("answered")
    await _emit_status(emit, "answered")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "综合分析完成",
            "detail": "已生成最终判断、证据与建议。",
            "state": "completed",
        },
        "synthesizing-final",
    )
    answer_output = enrich_answer_output(
        output=answer_output,
        question=question,
        snapshot=snapshot,
        artifacts=memory.artifacts,
        tool_results=memory.tool_results,
        research_notes=list(memory.research_notes or []),
        audit=latest_rule_audit,
    )
    review_contract: Dict[str, Any] = {}
    if is_deep_review_turn:
        review_contract = build_review_contract(
            question=question,
            snapshot=snapshot,
            artifacts=memory.artifacts,
            tool_results=memory.tool_results,
            audit=latest_rule_audit,
            decision_summary=answer_output.decision.summary,
        )
        answer_output.review_contract = review_contract
    else:
        answer_output.review_contract = {}
    return AgentTurnResponse(
        status="answered",
        stage="answered",
        output=answer_output,
        diagnostics=_build_diagnostics(
            memory=memory,
            used_tools=used_tools,
            citations=citations,
            thinking_timeline=thinking_timeline,
            planning_summary=planning_summary,
            audit_summary=audit_summary,
            review_contract=review_contract,
            replan_count=replan_count,
        ),
        context_summary=build_context_summary(snapshot, memory.artifacts),
        plan=AgentPlanEnvelope(
            steps=list(initial_plan_steps or []),
            followup_steps=list(replan_steps or []),
            followup_applied=bool(replan_steps),
            summary=planning_summary,
        ),
    )


async def process_agent_turn(payload: AgentTurnRequest) -> AgentTurnResponse:
    return await _run_agent_turn(payload)


async def stream_agent_turn(payload: AgentTurnRequest) -> AsyncIterator[AgentTurnStreamEvent]:
    queue: asyncio.Queue[AgentTurnStreamEvent | None] = asyncio.Queue()

    async def emit(event_type: str, event_payload: dict[str, Any]) -> None:
        await queue.put(AgentTurnStreamEvent(type=event_type, payload=event_payload))

    async def runner() -> None:
        try:
            response = await _run_agent_turn(payload, emit=emit)
            if response.status == "failed" and response.diagnostics.error:
                await emit("error", {"message": response.diagnostics.error})
            await queue.put(
                AgentTurnStreamEvent(
                    type="final",
                    payload={"response": response.model_dump(mode="json")},
                )
            )
        except Exception as exc:
            failed = AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=AgentTurnDiagnostics(error=f"Agent 流式执行失败：{exc}"),
                context_summary=build_context_summary(payload.analysis_snapshot),
                plan=AgentPlanEnvelope(),
            )
            await emit("error", {"message": failed.diagnostics.error})
            await queue.put(
                AgentTurnStreamEvent(
                    type="final",
                    payload={"response": failed.model_dump(mode="json")},
                )
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
