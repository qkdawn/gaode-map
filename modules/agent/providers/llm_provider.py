from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from core.config import settings

from ..context_builder import build_context_summary
from ..gate import _clarification_options, latest_user_message, run_gate
from ..governance import check_tool_governance
from ..planner import build_planning_fallback
from ..schemas import (
    AuditResult,
    AuditVerdict,
    AgentMessage,
    AgentTurnOutput,
    AnalysisSnapshot,
    ContextBundle,
    ExecutionTraceItem,
    GateDecision,
    PlanStep,
    PlanningResult,
    ToolLoopResult,
    ToolResult,
    WorkingMemory,
)
from ..tools import RegisteredTool
from .chat_parser import (
    extract_chat_completion_text as _extract_chat_completion_text_from_module,
    extract_json_object as _extract_json_object_from_module,
    extract_text_content as _extract_text_content_from_module,
    finalize_tool_calls as _finalize_tool_calls_from_module,
    merge_tool_call_delta as _merge_tool_call_delta_from_module,
    parse_chat_completion_response as _parse_chat_completion_response_from_module,
)
from .client import (
    LLMProviderClient,
    LLMProviderSpec,
    get_llm_provider_client as _get_llm_provider_client_from_module,
    get_llm_provider_spec as _get_llm_provider_spec_from_module,
    is_llm_enabled as _is_llm_enabled_from_module,
)
from .prompts import (
    auditor_system_prompt as _auditor_system_prompt_from_module,
    gate_system_prompt as _gate_system_prompt_from_module,
    loop_system_prompt as _loop_system_prompt_from_module,
    planner_system_prompt as _planner_system_prompt_from_module,
    synthesizer_system_prompt as _synthesizer_system_prompt_from_module,
)
from .tool_loop import (
    artifact_digest,
    chat_completion_tools,
    context_digest,
    is_reusable_tool_call,
    llm_visible_registry,
    planner_question_archetype,
    planner_tool_routing_hints,
    snapshot_digest,
    summarize_tool_arguments,
    summarize_tool_result,
    tool_cache_key,
    tool_catalog,
    tool_output_payload,
    trim_messages as _trim_messages_from_module,
)
from .tool_call_execution import execute_tool_call_step, tool_finish_trace_payload, tool_start_trace_payload

LoopEmit = Callable[[str, Dict[str, Any]], Awaitable[None] | None]


def get_llm_provider_spec(provider: Optional[str] = None) -> Optional[LLMProviderSpec]:
    return _get_llm_provider_spec_from_module(provider)


def is_llm_enabled() -> bool:
    return _is_llm_enabled_from_module()


def get_llm_provider_client(provider: Optional[str] = None) -> Optional[LLMProviderClient]:
    return _get_llm_provider_client_from_module(provider)


def _trim_messages(messages: List[AgentMessage]) -> List[Dict[str, str]]:
    return _trim_messages_from_module(messages)


def _extract_text_content(payload: Dict[str, Any]) -> str:
    return _extract_text_content_from_module(payload)

def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    return _extract_json_object_from_module(raw_text)

async def generate_title_with_llm(
    *,
    first_user_message: str,
    assistant_summary: str,
    status: str,
) -> str:
    system_prompt = (
        "你是 gaode-map 的对话标题生成器。"
        "请根据用户首轮问题和当前对话结果，生成一个简短、自然、可读的中文标题。"
        "要求："
        "1. 只输出标题本身，不要加引号、编号、解释或标点包装；"
        "2. 标题长度控制在 6 到 18 个汉字左右，最长不超过 24 个字符；"
        "3. 优先概括分析主题，不要复述完整问题；"
        "4. 如果结果是澄清、风险确认或失败，也要尽量概括用户想做的分析。"
    )
    user_payload = {
        "first_user_message": str(first_user_message or "").strip(),
        "assistant_summary": str(assistant_summary or "").strip(),
        "status": str(status or "").strip(),
    }
    base_url = str(settings.ai_base_url or "").rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    request_body = {
        "model": settings.ai_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    async with httpx.AsyncClient(timeout=float(settings.ai_timeout_s or 60)) as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=request_body)
        response.raise_for_status()
        payload = response.json()
    content = _extract_text_content(payload)
    title = str(content or "").strip().strip("\"'“”‘’").splitlines()[0].strip()
    if not title:
        raise ValueError("empty_title_completion")
    return title[:24]


def _with_thinking_mode(request_body: Dict[str, Any]) -> Dict[str, Any]:
    body = dict(request_body or {})
    model = str(body.get("model") or settings.ai_model or "").strip()
    if bool(settings.ai_thinking_enabled) and model != "deepseek-reasoner":
        body["thinking"] = {"type": "enabled"}
    return body


async def _iter_sse_data(response: httpx.Response):
    data_lines: List[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


def _merge_tool_call_delta(accumulator: List[Dict[str, Any]], raw_call: Dict[str, Any]) -> None:
    _merge_tool_call_delta_from_module(accumulator, raw_call)

def _finalize_tool_calls(accumulator: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _finalize_tool_calls_from_module(accumulator)

async def _stream_chat_completion(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    request_body: Dict[str, Any],
    emit: LoopEmit | None = None,
    reasoning_id: str = "llm-reasoning",
    phase: str = "planned",
    title: str = "模型思考",
) -> Dict[str, Any]:
    body = _with_thinking_mode({**request_body, "stream": True})
    response_id = ""
    finish_reason = ""
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_call_accumulator: List[Dict[str, Any]] = []

    async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=body) as response:
        response.raise_for_status()
        async for raw_data in _iter_sse_data(response):
            if raw_data.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid_chat_completion_stream_chunk:{exc}") from exc
            if chunk.get("id"):
                response_id = str(chunk.get("id") or response_id)
            choices = chunk.get("choices") if isinstance(chunk.get("choices"), list) else []
            if not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            if choice.get("finish_reason"):
                finish_reason = str(choice.get("finish_reason") or "")
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            reasoning_delta = delta.get("reasoning_content")
            if isinstance(reasoning_delta, str) and reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                await _maybe_emit(
                    emit,
                    "reasoning_delta",
                    {
                        "id": reasoning_id,
                        "phase": phase,
                        "title": title,
                        "delta": reasoning_delta,
                        "state": "active",
                    },
                )
            content_delta = delta.get("content")
            if isinstance(content_delta, str) and content_delta:
                content_parts.append(content_delta)
            for raw_call in delta.get("tool_calls") or []:
                _merge_tool_call_delta(tool_call_accumulator, raw_call)

    if reasoning_parts:
        await _maybe_emit(
            emit,
            "reasoning_delta",
            {
                "id": reasoning_id,
                "phase": phase,
                "title": title,
                "delta": "",
                "state": "completed",
            },
        )
    return {
        "id": response_id,
        "choices": [
            {
                "finish_reason": finish_reason or "stop",
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "reasoning_content": "".join(reasoning_parts),
                    "tool_calls": _finalize_tool_calls(tool_call_accumulator),
                },
            }
        ],
    }


def _loop_system_prompt() -> str:
    return _loop_system_prompt_from_module()

def _parse_chat_completion_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _parse_chat_completion_response_from_module(payload)

def _extract_chat_completion_text(payload: Dict[str, Any]) -> str:
    return _extract_chat_completion_text_from_module(payload)

async def _maybe_emit(emit: LoopEmit | None, event_type: str, payload: Dict[str, Any]) -> None:
    if emit is None:
        return
    outcome = emit(event_type, payload)
    if inspect.isawaitable(outcome):
        await outcome


async def _emit_preflight_trace(
    *,
    emit: LoopEmit | None,
    trace_id: str,
    data_readiness: Dict[str, Any],
) -> None:
    if emit is None or not isinstance(data_readiness, dict):
        return
    reused = [str(item) for item in (data_readiness.get("reused") or []) if str(item).strip()]
    fetched = [str(item) for item in (data_readiness.get("fetched") or []) if str(item).strip()]
    ready = bool(data_readiness.get("ready"))
    await _maybe_emit(
        emit,
        "trace",
        {
            "id": f"{trace_id}:precheck",
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
            "id": f"{trace_id}:fetch_missing",
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
            "id": f"{trace_id}:analysis",
            "tool_name": "analysis_preflight",
            "phase": "analysis",
            "status": "start" if ready else "failed",
            "reason": "analysis_started",
            "message": "数据就绪，开始分析" if ready else "数据未就绪，阻止进入分析",
            "produced_artifacts": ["current_data_readiness"],
        },
    )


async def _invoke_json_role(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    emit: LoopEmit | None,
    phase: str,
    title: str,
    reasoning_id: str,
) -> Dict[str, Any]:
    base_url = str(settings.ai_base_url or "").rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    request_body = {
        "model": settings.ai_model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    async with httpx.AsyncClient(timeout=float(settings.ai_timeout_s or 60)) as client:
        payload = await _stream_chat_completion(
            client=client,
            base_url=base_url,
            headers=headers,
            request_body=request_body,
            emit=emit,
            reasoning_id=reasoning_id,
            phase=phase,
            title=title,
        )
    return _extract_json_object(_extract_chat_completion_text(payload))


def _gate_system_prompt() -> str:
    return _gate_system_prompt_from_module()

def _planner_system_prompt() -> str:
    return _planner_system_prompt_from_module()

def _auditor_system_prompt() -> str:
    return _auditor_system_prompt_from_module()

def _synthesizer_system_prompt() -> str:
    return _synthesizer_system_prompt_from_module()

def _merge_plan_steps(primary: List[PlanStep], fallback: List[PlanStep]) -> List[PlanStep]:
    merged: List[PlanStep] = []
    lookup: Dict[tuple[str, str], PlanStep] = {}
    ordered_steps = list(primary or []) + list(fallback or [])
    priority = {"read_current_scope": 0, "read_current_results": 1}
    ordered_steps.sort(key=lambda step: priority.get(step.tool_name, 10))
    for step in ordered_steps:
        arguments = step.arguments if isinstance(step.arguments, dict) else {}
        key = (
            str(step.tool_name or "").strip(),
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str),
        )
        if not key[0]:
            continue
        if key in lookup:
            current = lookup[key]
            if not current.reason and step.reason:
                current.reason = step.reason
            if not current.evidence_goal and step.evidence_goal:
                current.evidence_goal = step.evidence_goal
            if not current.expected_artifacts and step.expected_artifacts:
                current.expected_artifacts = list(step.expected_artifacts or [])
            current.optional = current.optional and step.optional
            continue
        normalized = step.model_copy(deep=True)
        normalized.arguments = arguments
        lookup[key] = normalized
        merged.append(normalized)
    return merged


async def run_gate_with_llm(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    emit: LoopEmit | None = None,
) -> GateDecision:
    rule_decision = run_gate(messages, snapshot)
    if rule_decision.status in {"clarify", "block"}:
        return rule_decision
    payload = await _invoke_json_role(
        system_prompt=_gate_system_prompt(),
        user_payload={
            "messages": _trim_messages(messages),
            "latest_user_message": latest_user_message(messages),
            "analysis_snapshot_digest": snapshot_digest(snapshot),
            "context_digest": context_digest(context),
            "context_summary": context.context_summary.model_dump(),
        },
        emit=emit,
        phase="gating",
        title="门卫判断问题是否清晰",
        reasoning_id="gatekeeper-reasoning",
    )
    decision = GateDecision(**payload)
    if decision.status == "clarify":
        fallback_options = _clarification_options(latest_user_message(messages), snapshot)[:3]
        normalized_options = [str(item).strip() for item in (decision.clarification_options or []) if str(item).strip()]
        decision.clarification_options = normalized_options[:3] if normalized_options else fallback_options
    if rule_decision.status == "pass" and decision.status == "pass" and not decision.summary:
        decision.summary = rule_decision.summary
    return decision


async def plan_with_llm(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    registry: Dict[str, RegisteredTool],
    memory: WorkingMemory,
    audit_feedback: Dict[str, Any] | None = None,
    emit: LoopEmit | None = None,
) -> PlanningResult:
    question = latest_user_message(messages)
    visible_registry = llm_visible_registry(registry)
    fallback = build_planning_fallback(
        question=question,
        snapshot=snapshot,
        memory=memory,
        audit_feedback=audit_feedback,
    )
    question_archetype = planner_question_archetype(question)
    payload = await _invoke_json_role(
        system_prompt=_planner_system_prompt(),
        user_payload={
            "messages": _trim_messages(messages),
            "latest_user_message": question,
            "question_archetype": question_archetype,
            "analysis_snapshot_digest": snapshot_digest(snapshot),
            "context_digest": context_digest(context),
            "context_summary": context.context_summary.model_dump(),
            "artifact_digest": artifact_digest(snapshot, memory),
            "available_tools": tool_catalog(visible_registry),
            "available_artifacts": list(memory.artifacts.keys()),
            "tool_routing_hints": planner_tool_routing_hints(),
            "audit_feedback": dict(audit_feedback or {}),
            "fallback_plan": fallback.model_dump(mode="json"),
        },
        emit=emit,
        phase="planning",
        title="规划本轮分析步骤",
        reasoning_id="planner-reasoning",
    )
    plan = PlanningResult(**payload)
    plan.goal = plan.goal or fallback.goal
    plan.question_type = plan.question_type or fallback.question_type
    plan.summary = plan.summary or fallback.summary
    plan.stop_condition = plan.stop_condition or fallback.stop_condition
    plan.evidence_focus = list(plan.evidence_focus or fallback.evidence_focus)
    plan.steps = _merge_plan_steps(list(plan.steps or []), list(fallback.steps or []))
    plan.requires_tools = bool(plan.steps) if plan.requires_tools is False else (bool(plan.steps) or fallback.requires_tools)
    return plan


async def audit_with_llm(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    memory: WorkingMemory,
    plan: PlanningResult,
    rule_audit: AuditResult,
    replan_count: int,
    emit: LoopEmit | None = None,
) -> AuditVerdict:
    payload = await _invoke_json_role(
        system_prompt=_auditor_system_prompt(),
        user_payload={
            "question": question,
            "analysis_snapshot_digest": snapshot_digest(snapshot),
            "context_digest": context_digest(context),
            "plan": plan.model_dump(mode="json"),
            "tool_results": [item.model_dump(mode="json") for item in (memory.tool_results or [])],
            "execution_trace": [item.model_dump(mode="json") for item in (memory.execution_trace or [])],
            "available_artifacts": list(memory.artifacts.keys()),
            "rule_audit": rule_audit.model_dump(mode="json"),
            "replan_count": int(replan_count),
        },
        emit=emit,
        phase="auditing",
        title="审计本轮结果是否足够回答问题",
        reasoning_id="auditor-reasoning",
    )
    verdict = AuditVerdict(**payload)
    verdict.issues = list(dict.fromkeys(list(verdict.issues or []) + list(rule_audit.issues or [])))
    verdict.missing_evidence = list(
        dict.fromkeys(list(verdict.missing_evidence or []) + list(rule_audit.missing_evidence or []))
    )
    if verdict.missing_evidence:
        verdict.status = "replan"
        verdict.should_answer = False
        if not verdict.replan_instructions:
            verdict.replan_instructions = f"请优先补齐 {'、'.join(verdict.missing_evidence)}。"
        if not verdict.summary:
            verdict.summary = "当前证据还不能稳定回答用户问题，需要先补齐关键维度。"
    elif not verdict.summary:
        verdict.summary = "当前证据通过审计，可以进入综合分析。"
    return verdict


async def run_llm_tool_loop(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    registry: Dict[str, RegisteredTool],
    governance_mode: str,
    confirmed_tools: List[str] | None = None,
    emit: LoopEmit | None = None,
    include_secondary_tools: bool = False,
    max_steps_override: int | None = None,
    max_errors_override: int | None = None,
) -> ToolLoopResult:
    base_url = str(settings.ai_base_url or "").rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    initial_payload = {
        "messages": _trim_messages(messages),
        "analysis_snapshot_digest": snapshot_digest(snapshot),
        "context_digest": context_digest(context),
        "context_summary": build_context_summary(snapshot).model_dump(),
        "available_tools": tool_catalog(llm_visible_registry(registry)),
    }
    loop_result = ToolLoopResult(artifacts={})
    loop_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _loop_system_prompt()},
        {"role": "user", "content": json.dumps(initial_payload, ensure_ascii=False)},
    ]
    consecutive_tool_errors = 0
    max_steps = max(1, int(max_steps_override or settings.ai_max_tool_steps or 8))
    max_errors = max(1, int(max_errors_override or settings.ai_max_tool_errors or 2))
    reusable_tool_results: Dict[str, ToolResult] = {}

    async with httpx.AsyncClient(timeout=float(settings.ai_timeout_s or 60)) as client:
        for step_index in range(max_steps):
            analysis_item_id = f"llm-loop-analysis-{step_index + 1}"
            await _maybe_emit(
                emit,
                "thinking",
                {
                    "id": analysis_item_id,
                    "phase": "planned",
                    "title": f"分析当前证据（第 {step_index + 1} 轮）",
                    "detail": "正在判断是否需要继续调用工具。",
                    "state": "active",
                },
            )
            request_body: Dict[str, Any] = {
                "model": settings.ai_model,
                "messages": loop_messages,
                "tools": chat_completion_tools(registry, include_secondary=include_secondary_tools),
                "tool_choice": "auto",
            }
            payload = await _stream_chat_completion(
                client=client,
                base_url=base_url,
                headers=headers,
                request_body=request_body,
                emit=emit,
                reasoning_id=analysis_item_id,
                phase="planned",
                title=f"模型思考（第 {step_index + 1} 轮）",
            )

            loop_result.provider_response_id = str(payload.get("id") or loop_result.provider_response_id or "")

            parsed = _parse_chat_completion_response(payload)
            loop_result.warnings.extend([str(item) for item in parsed["warnings"] if str(item).strip()])
            if parsed["texts"]:
                loop_result.assistant_summary = "\n".join(parsed["texts"]).strip()

            function_calls = [item for item in parsed["function_calls"] if str(item.get("tool_name") or "").strip()]
            if not function_calls:
                if loop_result.assistant_summary:
                    loop_result.status = "completed"
                    loop_result.stop_reason = "assistant_completed"
                    await _maybe_emit(
                        emit,
                        "thinking",
                        {
                            "id": analysis_item_id,
                            "phase": "planned",
                            "title": f"工具调度完成（第 {step_index + 1} 轮）",
                            "detail": "当前证据已足够，准备进入结果审计。",
                            "state": "completed",
                        },
                    )
                    return loop_result
                loop_result.status = "failed"
                loop_result.stop_reason = "no_parseable_output"
                loop_result.error = "DeepSeek chat completions 返回了不可解析的输出"
                return loop_result

            choice_message = {}
            choices = payload.get("choices") or []
            if choices and isinstance(choices[0], dict) and isinstance(choices[0].get("message"), dict):
                choice_message = choices[0]["message"]
            assistant_message = {
                "role": "assistant",
                "content": choice_message.get("content") or "",
                "tool_calls": choice_message.get("tool_calls") or [],
            }
            if choice_message.get("reasoning_content"):
                assistant_message["reasoning_content"] = choice_message.get("reasoning_content")
            loop_messages.append(assistant_message)
            for call in function_calls:
                tool_name = str(call.get("tool_name") or "").strip()
                registered = registry.get(tool_name)
                step = PlanStep(
                    tool_name=tool_name,
                    arguments=call.get("arguments") if isinstance(call.get("arguments"), dict) else {},
                    reason="LLM tool call",
                    expected_artifacts=list(registered.spec.produces or []) if registered else [],
                )
                loop_result.steps.append(step)
                await _maybe_emit(
                    emit,
                    "thinking",
                    {
                        "id": f"tool-call:{tool_name}",
                        "phase": "executing",
                        "title": f"准备调用 {tool_name}",
                        "detail": str(registered.spec.description if registered else "正在尝试执行工具。"),
                        "state": "active",
                    },
                )
                await _maybe_emit(
                    emit,
                    "trace",
                    tool_start_trace_payload(
                        trace_id=f"tool-call:{call.get('call_id') or tool_name}",
                        call_id=str(call.get("call_id") or ""),
                        step=step,
                    ),
                )

                if registered is None:
                    execution = await execute_tool_call_step(
                        registered_tool=None,
                        step=step,
                        snapshot=snapshot,
                        artifacts=loop_result.artifacts,
                        question=str(messages[-1].content if messages else ""),
                        governance_mode=governance_mode,
                        confirmed_tools=confirmed_tools,
                    )
                    await _maybe_emit(
                        emit,
                        "trace",
                        tool_finish_trace_payload(
                            trace_id=f"tool-call:{call.get('call_id') or tool_name}",
                            call_id=str(call.get("call_id") or ""),
                            step=step,
                            execution=execution,
                        ),
                    )
                    loop_result.status = "failed"
                    loop_result.stop_reason = "unknown_tool"
                    loop_result.error = str(execution.result.error or f"unknown_tool:{tool_name}")
                    return loop_result

                prompt = check_tool_governance(
                    mode=governance_mode,
                    spec=registered.spec,
                    confirmed_tools=confirmed_tools,
                )
                if prompt:
                    loop_result.status = "requires_risk_confirmation"
                    loop_result.stop_reason = "governance_blocked"
                    loop_result.risk_prompt = prompt
                    await _maybe_emit(
                        emit,
                        "trace",
                        {
                            "id": f"tool-call:{call.get('call_id') or tool_name}",
                            "call_id": str(call.get("call_id") or ""),
                            "tool_name": tool_name,
                            "status": "blocked",
                            "reason": step.reason,
                            "message": prompt,
                            "arguments_summary": summarize_tool_arguments(step.arguments),
                            "produced_artifacts": list(step.expected_artifacts or []),
                        },
                    )
                    return loop_result

                argument_error = str(call.get("argument_error") or "").strip()
                if argument_error:
                    result = ToolResult(
                        tool_name=tool_name,
                        status="failed",
                        warnings=[argument_error],
                        error="invalid_tool_call_arguments",
                    )
                    loop_result.tool_results.append(result)
                    consecutive_tool_errors += 1
                    await _maybe_emit(
                        emit,
                        "trace",
                        {
                            "id": f"tool-call:{call.get('call_id') or tool_name}",
                            "call_id": str(call.get("call_id") or ""),
                            "tool_name": tool_name,
                            "status": "failed",
                            "reason": step.reason,
                            "message": argument_error,
                            "arguments_summary": summarize_tool_arguments(step.arguments),
                            "result_summary": argument_error,
                            "evidence_count": 0,
                            "warning_count": len(result.warnings or []),
                            "produced_artifacts": [],
                        },
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(call.get("call_id") or tool_name),
                            "content": tool_output_payload(result),
                        }
                    )
                    if consecutive_tool_errors >= max_errors:
                        loop_result.status = "failed"
                        loop_result.stop_reason = "too_many_tool_errors"
                        loop_result.error = "连续工具调用参数错误过多"
                        return loop_result
                    continue

                cache_key = tool_cache_key(step)
                if is_reusable_tool_call(registered, step) and cache_key in reusable_tool_results:
                    cached_result = reusable_tool_results[cache_key]
                    trace = ExecutionTraceItem(
                        tool_name=registered.spec.name,
                        status="skipped",
                        reason=step.reason,
                        message="复用已有工具结果",
                        cost_level=registered.spec.cost_level,
                        risk_level=registered.spec.risk_level,
                        evidence_count=len(cached_result.evidence or []),
                        warning_count=len(cached_result.warnings or []),
                    )
                    loop_result.execution_trace.append(trace)
                    await _maybe_emit(
                        emit,
                        "trace",
                        {
                            "id": f"tool-call:{call.get('call_id') or tool_name}",
                            "call_id": str(call.get("call_id") or ""),
                            "tool_name": tool_name,
                            "status": trace.status,
                            "reason": step.reason,
                            "message": trace.message,
                            "arguments_summary": summarize_tool_arguments(step.arguments),
                            "result_summary": summarize_tool_result(cached_result),
                            "evidence_count": len(cached_result.evidence or []),
                            "warning_count": len(cached_result.warnings or []),
                            "produced_artifacts": list((cached_result.artifacts or {}).keys())[:12],
                        },
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(call.get("call_id") or tool_name),
                            "content": tool_output_payload(cached_result),
                        }
                    )
                    consecutive_tool_errors = 0
                    continue

                execution = await execute_tool_call_step(
                    registered_tool=registered,
                    step=step,
                    snapshot=snapshot,
                    artifacts=loop_result.artifacts,
                    question=str(messages[-1].content if messages else ""),
                    governance_mode=governance_mode,
                    confirmed_tools=confirmed_tools,
                )
                result = execution.result
                trace = execution.trace
                data_readiness = dict(result.result.get("data_readiness") or {}) if isinstance(result.result, dict) else {}
                if data_readiness.get("checked"):
                    await _emit_preflight_trace(
                        emit=emit,
                        trace_id=f"tool-call:{call.get('call_id') or tool_name}",
                        data_readiness=data_readiness,
                    )
                loop_result.execution_trace.append(trace)
                loop_result.used_tools.append(tool_name)
                loop_result.tool_results.append(result)
                if result.artifacts:
                    loop_result.artifacts.update(result.artifacts)
                if result.status == "success" and is_reusable_tool_call(registered, step):
                    reusable_tool_results[cache_key] = result.model_copy(deep=True)
                if result.warnings:
                    loop_result.research_notes.extend([str(item) for item in result.warnings if str(item).strip()])
                await _maybe_emit(
                    emit,
                    "trace",
                    {
                        **tool_finish_trace_payload(
                            trace_id=f"tool-call:{call.get('call_id') or tool_name}",
                            call_id=str(call.get("call_id") or ""),
                            step=step,
                            execution=execution,
                        ),
                        "phase": "analysis" if data_readiness.get("checked") else "executing",
                    },
                )
                consecutive_tool_errors = consecutive_tool_errors + 1 if result.status == "failed" else 0
                loop_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("call_id") or tool_name),
                        "content": tool_output_payload(result),
                    }
                )
                if consecutive_tool_errors >= max_errors:
                    loop_result.status = "failed"
                    loop_result.stop_reason = "too_many_tool_errors"
                    loop_result.error = str(result.error or "tool_execution_failed")
                    return loop_result

        loop_result.status = "failed"
        loop_result.stop_reason = "max_tool_steps_exceeded"
        loop_result.error = f"工具调用步数超过上限 {max_steps}"
        return loop_result


async def generate_answer_output_with_llm(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    synthesis_payload: Dict[str, Any],
    emit: LoopEmit | None = None,
) -> AgentTurnOutput:
    parsed = await _invoke_json_role(
        system_prompt=_synthesizer_system_prompt(),
        user_payload={
            "messages": _trim_messages(messages),
            "analysis_snapshot_digest": snapshot_digest(snapshot),
            "context_digest": context_digest(context),
            "synthesis_payload": synthesis_payload,
        },
        emit=emit,
        phase="synthesizing",
        title="综合分析并生成最终结论",
        reasoning_id="synthesizer-reasoning",
    )
    return AgentTurnOutput(**parsed)
