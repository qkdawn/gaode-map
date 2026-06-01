from __future__ import annotations

import asyncio
import inspect
from contextlib import suppress
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List

from core.config import settings

from .auditor import audit_execution
from .context_builder import build_context_bundle, build_context_summary
from .gate import latest_user_message
from .memory import create_working_memory
from .llm_digest import summarize_tool_result
from .providers.langgraph_react import run_langgraph_react_loop
from .providers.llm_provider import (
    generate_answer_output_with_llm,
    generate_translation_pack_with_llm,
    is_llm_enabled,
    run_gate_with_llm,
)
from .schemas import (
    AgentPlanEnvelope,
    AgentTranslationPack,
    AgentThinkingItem,
    AgentTurnDiagnostics,
    AgentTurnOutput,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentTurnStreamEvent,
    AuditResult,
)
from .state_machine import AgentStateMachine
from .synthesizer import (
    build_answer_evidence_payload,
    build_answer_fallback,
    build_citations,
    enrich_answer_output,
)
from .tools import get_tool_registry

StreamEmit = Callable[[str, dict[str, Any]], Awaitable[None] | None]

_VISUAL_SNAPSHOT_LIMIT = 12
_VISUAL_SNAPSHOT_MAX_DATA_URL_CHARS = 2_500_000


def _visual_snapshot_inputs(payload: AgentTurnRequest) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    images: List[Dict[str, Any]] = []
    metadata: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for raw in list(payload.visual_snapshots or [])[:_VISUAL_SNAPSHOT_LIMIT]:
        kind = str(raw.kind or "").strip()
        title = str(raw.title or kind or "地图快照").strip()
        data_url = str(raw.data_url or "").strip()
        item_warnings = [str(item).strip() for item in (raw.warnings or []) if str(item).strip()]
        if not data_url.startswith("data:image/"):
            warnings.extend(item_warnings)
            if kind or title:
                warnings.append(f"{title} 未传入有效图片，已跳过。")
            continue
        if len(data_url) > _VISUAL_SNAPSHOT_MAX_DATA_URL_CHARS:
            warnings.extend(item_warnings)
            warnings.append(f"{title} 图片过大，已跳过直传。")
            continue
        meta = {
            "snapshot_id": str(raw.snapshot_id or "").strip(),
            "kind": kind,
            "title": title,
            "source": str(raw.source or "frontend_map").strip(),
            "captured_at": str(raw.captured_at or "").strip(),
            "bounds": dict(raw.bounds or {}),
            "warnings": item_warnings,
        }
        metadata.append(meta)
        images.append({**meta, "data_url": data_url})
    if len(payload.visual_snapshots or []) > _VISUAL_SNAPSHOT_LIMIT:
        warnings.append(f"地图视觉快照超过 {_VISUAL_SNAPSHOT_LIMIT} 张，已只使用前 {_VISUAL_SNAPSHOT_LIMIT} 张。")
    return images, metadata, warnings

_STAGE_LABELS = {
    "gating": "门卫判断",
    "clarifying": "生成追问",
    "executing": "执行工具",
    "synthesizing": "综合分析",
    "answered": "已完成",
    "failed": "失败",
    "requires_clarification": "需要补充信息",
    "requires_risk_confirmation": "等待风险确认",
}

_GENERIC_TOOL_RESULT_TEXT = {"", "执行成功", "成功", "已完成", "完成", "ok", "OK", "无结果"}


def _tool_result_display_text(result) -> str:
    if result.status == "failed":
        return str(result.error or "执行失败")
    summary = summarize_tool_result(result)
    return "" if str(summary or "").strip() in _GENERIC_TOOL_RESULT_TEXT else str(summary or "").strip()


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
    payload.setdefault("display_text", "")
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
        "display_text": str(payload.get("display_text") or ""),
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
    translation_pack: AgentTranslationPack | None = None,
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
        translation_pack=translation_pack or AgentTranslationPack(),
        error=str(error or ""),
    )


def _tool_loop_limits(thinking_mode: str) -> tuple[int | None, int | None]:
    configured_steps = int(settings.ai_max_tool_steps or 0)
    max_steps = max(1, configured_steps) if configured_steps > 0 else None
    max_errors = max(1, int(settings.ai_max_tool_errors or 2))
    return max_steps, max_errors


def _build_loop_plan_summary(*, used_tools: List[str], assistant_summary: str = "") -> str:
    if used_tools:
        tool_text = " -> ".join(list(dict.fromkeys([str(item).strip() for item in used_tools if str(item).strip()]))[:5])
        return f"本轮按需调用工具补证据：{tool_text}。"
    if str(assistant_summary or "").strip():
        return "现有证据已基本够用，本轮未继续调用工具。"
    return "根据当前问题复用已有证据并按需补充必要工具。"


def _build_rule_audit_summary(audit: AuditResult) -> str:
    if list(audit.missing_evidence or []):
        missing = "、".join([str(item).strip() for item in list(audit.missing_evidence or [])[:3] if str(item).strip()])
        return f"当前回答仍有证据缺口：{missing}。"
    if list(audit.issues or []):
        issue = next((str(item).strip() for item in audit.issues if str(item).strip()), "")
        if issue:
            return f"当前回答需要标注边界：{issue}"
    return "当前证据足以支持直接回答，并已保留必要解释边界。"


async def _run_agent_turn(payload: AgentTurnRequest, *, emit: StreamEmit | None = None) -> AgentTurnResponse:
    snapshot = payload.analysis_snapshot
    question = latest_user_message(payload.messages)
    thinking_mode = str(payload.thinking_mode or "quick").strip() or "quick"
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
    map_search_context = dict(payload.map_search_context or {}) if isinstance(payload.map_search_context, dict) else {}
    if map_search_context:
        memory.artifacts["frontend_map_search_context"] = map_search_context
        context.available_artifacts.append("frontend_map_search_context")
        context.context_summary.available_context_sources.append("analysis:frontend_map_search_context")
        context.limits.append(
            "frontend_map_search_context 是本轮可检索地图空间对象源；最终回答只能引用 search_analysis_context/read_analysis_chunk 已读取到的具体地名、格子、线段或 cell。"
        )
    visual_image_inputs, visual_snapshot_meta, visual_snapshot_warnings = _visual_snapshot_inputs(payload)
    if visual_snapshot_meta:
        memory.artifacts["visual_snapshots"] = visual_snapshot_meta
        context.available_artifacts.append("frontend_visual_snapshots")
        context.context_summary.available_context_sources.append("visual:frontend_map_snapshots")
        context.limits.append("地图视觉快照只能作为可见图层证据，不能伪装成后端指标计算结果。")
    for warning in visual_snapshot_warnings:
        memory.research_notes.append(warning)
    attachment_ids = [str(item).strip() for item in (payload.attachment_ids or []) if str(item).strip()]
    if attachment_ids:
        memory.artifacts["uploaded_attachment_ids"] = attachment_ids
        memory.artifacts["uploaded_attachment_conversation_id"] = str(payload.conversation_id or "")
        context.available_artifacts.append("uploaded_attachments")
        context.context_summary.available_context_sources.append("attachment:uploaded")
        context.limits.append("用户上传附件只能作为附件证据引用，不能伪装成地图分析计算结果。")
    used_tools: List[str] = []
    planning_summary = ""
    audit_summary = ""
    latest_rule_audit = AuditResult()
    current_plan_envelope = AgentPlanEnvelope()
    translation_pack = AgentTranslationPack(status="skipped")

    await _maybe_emit(emit, "meta", {"conversation_id": str(payload.conversation_id or "")})
    await _emit_status(emit, state.stage)
    if visual_snapshot_meta:
        snapshot_titles = [
            str(item.get("title") or item.get("kind") or "").strip()
            for item in visual_snapshot_meta
            if str(item.get("title") or item.get("kind") or "").strip()
        ]
        await emit_thinking(
            {
                "phase": "preflight",
                "title": "地图视觉快照已接收",
                "detail": f"本轮已收到 {len(visual_snapshot_meta)} 张前端地图快照：{'、'.join(snapshot_titles[:6])}。",
                "display_text": f"本轮已收到 {len(visual_snapshot_meta)} 张前端地图快照。",
                "items": snapshot_titles[:6],
                "state": "completed",
            },
            "visual-snapshots",
        )
    elif visual_snapshot_warnings:
        await emit_thinking(
            {
                "phase": "preflight",
                "title": "地图视觉快照未传入",
                "detail": "本轮未收到可直传模型的地图快照，已继续使用结构化指标分析。",
                "display_text": "本轮未收到可直传模型的地图快照。",
                "items": list(visual_snapshot_warnings or [])[:6],
                "state": "completed",
            },
            "visual-snapshots",
        )
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
                error="LLM provider 未启用或配置不完整，当前版本要求统一主链路工具循环与自然回答。",
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
                "display_text": gate.summary or "",
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
            "detail": gate.summary or "问题已明确，可以继续收集证据并回答。",
            "display_text": gate.summary or "",
            "state": "completed",
        },
        "gating-check",
    )

    state.move_to("executing")
    await _emit_status(emit, "executing")
    await emit_thinking(
        {
            "phase": "executing",
            "title": "执行工具循环",
            "detail": "正在按需调用工具补证据，证据足够后会直接收敛到回答。",
            "state": "active",
        },
        "tool-loop",
    )
    try:
        max_steps_override, max_errors_override = _tool_loop_limits(thinking_mode)
        loop_result = await run_langgraph_react_loop(
            messages=payload.messages,
            snapshot=snapshot,
            context=context,
            registry=get_tool_registry(),
            governance_mode=payload.governance_mode,
            confirmed_tools=list(payload.risk_confirmations or []),
            emit=emit_event,
            include_secondary_tools=True,
            max_steps_override=max_steps_override,
            max_errors_override=max_errors_override,
            thinking_mode=thinking_mode,
            initial_artifacts=dict(memory.artifacts or {}),
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
                error=f"工具循环调用失败：{exc}",
                thinking_timeline=thinking_timeline,
            ),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=AgentPlanEnvelope(),
        )

    used_tools = list(loop_result.used_tools or [])
    memory.execution_trace = list(loop_result.execution_trace or [])
    memory.tool_results = list(loop_result.tool_results or [])
    memory.artifacts.update(dict(loop_result.artifacts or {}))
    memory.research_notes.extend([str(item) for item in list(loop_result.research_notes or []) if str(item).strip()])
    planning_summary = _build_loop_plan_summary(
        used_tools=used_tools,
        assistant_summary=str(loop_result.assistant_summary or ""),
    )
    current_plan_envelope = AgentPlanEnvelope(
        steps=list(loop_result.steps or []),
        followup_steps=[],
        followup_applied=False,
        summary=planning_summary,
    )
    await _maybe_emit(emit, "plan", current_plan_envelope.model_dump(mode="json"))

    if loop_result.status == "requires_risk_confirmation":
        await emit_thinking(
            {
                "phase": "executing",
                "title": "等待风险确认",
                "detail": loop_result.risk_prompt or "存在需要确认的高成本工具调用。",
                "state": "failed",
            },
            "tool-loop",
        )
        await _emit_status(emit, "requires_risk_confirmation")
        return AgentTurnResponse(
            status="requires_risk_confirmation",
            stage="requires_risk_confirmation",
            output=AgentTurnOutput(risk_prompt=loop_result.risk_prompt),
            diagnostics=_build_diagnostics(
                memory=memory,
                used_tools=used_tools,
                thinking_timeline=thinking_timeline,
                planning_summary=planning_summary,
            ),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=current_plan_envelope,
        )

    if loop_result.status == "failed":
        await emit_thinking(
            {
                "phase": "executing",
                "title": "工具循环失败",
                "detail": loop_result.error or loop_result.stop_reason or "工具循环未能稳定完成。",
                "state": "failed",
            },
            "tool-loop",
        )
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=_build_diagnostics(
                memory=memory,
                used_tools=used_tools,
                error=loop_result.error or loop_result.stop_reason or "tool_loop_failed",
                thinking_timeline=thinking_timeline,
                planning_summary=planning_summary,
            ),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=current_plan_envelope,
        )

    latest_rule_audit = audit_execution(question=question, snapshot=snapshot, context=context, memory=memory)
    memory.audit_issues = list(latest_rule_audit.issues or [])
    audit_summary = _build_rule_audit_summary(latest_rule_audit)
    await emit_thinking(
        {
            "phase": "assess",
            "title": "证据检查完成",
            "detail": audit_summary,
            "display_text": audit_summary,
            "items": list(latest_rule_audit.missing_evidence or [])[:3],
            "state": "completed",
        },
        "audit-check",
    )

    answer_evidence_payload = build_answer_evidence_payload(
        question=question,
        snapshot=snapshot,
        artifacts=memory.artifacts,
        tool_results=memory.tool_results,
        research_notes=list(memory.research_notes or []),
        audit=latest_rule_audit,
    )
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "转译指标含义",
            "detail": "正在把关键指标转成空间现象、人的体验和策划含义。",
            "state": "active",
        },
        "translation-layer",
    )
    try:
        translation_pack = await generate_translation_pack_with_llm(
            messages=payload.messages,
            snapshot=snapshot,
            context=context,
            answer_evidence_payload=answer_evidence_payload,
            image_inputs=visual_image_inputs,
            thinking_mode=thinking_mode,
            emit=emit_event,
        )
        await emit_thinking(
            {
                "phase": "synthesizing",
                "title": "指标转译完成",
                "detail": translation_pack.summary or "已完成关键指标的空间体验与策划含义转译。",
                "display_text": translation_pack.summary or "",
                "items": [
                    str(item.planning_implication or item.spatial_phenomenon or item.metric)
                    for item in list(translation_pack.items or [])[:3]
                    if str(item.planning_implication or item.spatial_phenomenon or item.metric).strip()
                ],
                "state": "completed",
            },
            "translation-layer",
        )
    except Exception as exc:
        translation_pack = AgentTranslationPack(status="failed", error=str(exc))
        note = f"指标转译层调用失败，已继续使用原始证据回答：{exc}"
        memory.research_notes.append(note)
        await emit_thinking(
            {
                "phase": "synthesizing",
                "title": "指标转译失败",
                "detail": note,
                "state": "failed",
            },
            "translation-layer",
        )
    citations = build_citations(snapshot, memory.artifacts)
    state.move_to("synthesizing")
    await _emit_status(emit, "synthesizing")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "综合分析",
            "detail": "正在基于现有证据组织自然回答。",
            "state": "active",
        },
        "synthesizing-final",
    )
    synthesis_error = ""
    try:
        answer_output = await generate_answer_output_with_llm(
            messages=payload.messages,
            snapshot=snapshot,
            context=context,
            answer_evidence_payload=answer_evidence_payload,
            translation_pack=translation_pack,
            image_inputs=visual_image_inputs,
            thinking_mode=thinking_mode,
            emit=emit_event,
        )
    except Exception as exc:
        synthesis_error = f"综合回答 LLM 调用失败，已切换到服务端兜底：{exc}"
        memory.research_notes.append(synthesis_error)
        answer_output = AgentTurnOutput(
            answer=build_answer_fallback(
                question=question,
                snapshot=snapshot,
                artifacts=memory.artifacts,
                tool_results=memory.tool_results,
                research_notes=list(memory.research_notes or []),
                audit=latest_rule_audit,
            )
        )
    if not str(answer_output.answer or "").strip():
        answer_output.answer = build_answer_fallback(
            question=question,
            snapshot=snapshot,
            artifacts=memory.artifacts,
            tool_results=memory.tool_results,
            research_notes=list(memory.research_notes or []),
            audit=latest_rule_audit,
        )

    state.move_to("answered")
    await _emit_status(emit, "answered")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "回答生成完成",
            "detail": "已生成最终自然回答。",
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
            translation_pack=translation_pack,
            error=synthesis_error,
        ),
        context_summary=build_context_summary(snapshot, memory.artifacts),
        plan=current_plan_envelope,
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
