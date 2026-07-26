from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from core.config import settings

from ..gate import _clarification_options, latest_user_message, run_gate
from ..llm_digest import (
    compact_context_summary_dump,
    context_digest,
    snapshot_digest,
    trim_messages as _trim_messages_from_module,
)
from ..schemas import AgentMessage, AgentTranslationPack, AgentTurnOutput, AnalysisSnapshot, ContextBundle, GateDecision, ToolAllocationDecision
from .chat_parser import (
    extract_chat_completion_text as _extract_chat_completion_text_from_module,
    extract_json_object as _extract_json_object_from_module,
    extract_text_content as _extract_text_content_from_module,
    finalize_tool_calls as _finalize_tool_calls_from_module,
    merge_tool_call_delta as _merge_tool_call_delta_from_module,
)
from .client import (
    LLMProviderClient,
    LLMRuntimeConfig,
    LLMProviderSpec,
    get_llm_provider_client as _get_llm_provider_client_from_module,
    get_llm_provider_spec as _get_llm_provider_spec_from_module,
    is_llm_enabled as _is_llm_enabled_from_module,
)
from .prompts import (
    gate_system_prompt as _gate_system_prompt_from_module,
    synthesizer_system_prompt as _synthesizer_system_prompt_from_module,
    tool_allocator_system_prompt as _tool_allocator_system_prompt_from_module,
)

LoopEmit = Callable[[str, Dict[str, Any]], Awaitable[None] | None]


def get_llm_provider_spec(provider: Optional[str] = None) -> Optional[LLMProviderSpec]:
    return _get_llm_provider_spec_from_module(provider)


def is_llm_enabled() -> bool:
    return _is_llm_enabled_from_module()


def get_llm_provider_client(
    provider: Optional[str] = None, *, runtime: LLMRuntimeConfig | None = None
) -> Optional[LLMProviderClient]:
    return _get_llm_provider_client_from_module(provider, runtime=runtime)


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
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=request_body)
        response.raise_for_status()
        payload = response.json()
    content = _extract_text_content(payload)
    title = str(content or "").strip().strip("\"'“”‘’").splitlines()[0].strip()
    if not title:
        raise ValueError("empty_title_completion")
    return title[:24]


def _with_provider_thinking(request_body: Dict[str, Any], *, enabled: bool) -> Dict[str, Any]:
    body = dict(request_body or {})
    model = str(body.get("model") or settings.ai_model or "").strip()
    if enabled and model != "deepseek-reasoner":
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


async def _maybe_emit(emit: LoopEmit | None, event_type: str, payload: Dict[str, Any]) -> None:
    if emit is None:
        return
    outcome = emit(event_type, payload)
    if inspect.isawaitable(outcome):
        await outcome


async def _stream_chat_completion(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    request_body: Dict[str, Any],
    emit: LoopEmit | None = None,
    content_emit: LoopEmit | None = None,
    reasoning_id: str = "llm-reasoning",
    phase: str = "executing",
    title: str = "模型思考",
    enable_thinking: bool = True,
) -> Dict[str, Any]:
    base_body = {**request_body, "stream": True}
    body = _with_provider_thinking(base_body, enabled=enable_thinking)
    response_id = ""
    finish_reason = ""
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_call_accumulator: List[Dict[str, Any]] = []

    async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=body) as response:
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code >= 400:
            error_body = (await response.aread()).decode("utf-8", errors="replace").strip()
            detail = error_body[:800] if error_body else str(getattr(response, "reason_phrase", "LLM provider error"))
            raise httpx.HTTPStatusError(
                f"LLM provider returned HTTP {status_code}: {detail}",
                request=response.request,
                response=response,
            )
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
                await _maybe_emit(
                    content_emit,
                    "content_delta",
                    {"delta": content_delta},
                )
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


async def _invoke_json_role(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    image_inputs: List[Dict[str, Any]] | None = None,
    emit: LoopEmit | None,
    phase: str,
    title: str,
    reasoning_id: str,
    enable_thinking: bool = True,
    stream: bool = True,
    runtime: LLMRuntimeConfig | None = None,
) -> Dict[str, Any]:
    effective = runtime or LLMRuntimeConfig.from_settings()
    base_url = effective.base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {effective.api_key}",
        "Content-Type": "application/json",
    }
    user_content: Any = json.dumps(user_payload, ensure_ascii=False)
    cleaned_images = [
        item
        for item in (image_inputs or [])
        if isinstance(item, dict) and str(item.get("data_url") or "").startswith("data:image/")
    ]
    if cleaned_images:
        user_content = [{"type": "text", "text": user_content}]
        for item in cleaned_images:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": str(item.get("data_url") or "")},
                }
            )

    request_body = {
        "model": effective.model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    enable_thinking = bool(enable_thinking and effective.thinking_enabled)
    timeout_s = max(float(effective.timeout_s), 0.1)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        if stream:
            payload = await _stream_chat_completion(
                client=client,
                base_url=base_url,
                headers=headers,
                request_body=request_body,
                emit=emit,
                reasoning_id=reasoning_id,
                phase=phase,
                title=title,
                enable_thinking=enable_thinking,
            )
        else:
            body = _with_provider_thinking(request_body, enabled=enable_thinking)
            response = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
            if response.status_code >= 400:
                detail = response.text[:800] if response.text else str(getattr(response, "reason_phrase", "LLM provider error"))
                raise httpx.HTTPStatusError(
                    f"LLM provider returned HTTP {response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
            payload = response.json()
    return _extract_json_object(_extract_chat_completion_text_from_module(payload))


def _gate_system_prompt() -> str:
    return _gate_system_prompt_from_module()


async def run_gate_with_llm(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    emit: LoopEmit | None = None,
    runtime: LLMRuntimeConfig | None = None,
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
            "context_summary": compact_context_summary_dump(context.context_summary),
            "available_artifacts": list(context.available_artifacts or []),
        },
        emit=emit,
        phase="gating",
        title="门卫判断问题是否清晰",
        reasoning_id="gatekeeper-reasoning",
        runtime=runtime,
    )
    decision = GateDecision(**payload)
    if decision.status == "clarify":
        fallback_options = _clarification_options(latest_user_message(messages), snapshot)[:3]
        normalized_options = [str(item).strip() for item in (decision.clarification_options or []) if str(item).strip()]
        decision.clarification_options = normalized_options[:3] if normalized_options else fallback_options
    if rule_decision.status == "pass" and decision.status == "pass" and not decision.summary:
        decision.summary = rule_decision.summary
    return decision


async def run_tool_allocator_with_llm(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    agent_role: str,
    task: str,
    candidate_tools: List[Dict[str, Any]],
    emit: LoopEmit | None = None,
    runtime: LLMRuntimeConfig | None = None,
) -> ToolAllocationDecision:
    """Ask a tool-free specialist to make a bounded grant for one agent role."""

    payload = await _invoke_json_role(
        system_prompt=_tool_allocator_system_prompt_from_module(),
        user_payload={
            "agent_role": agent_role,
            "task": task,
            "latest_user_message": latest_user_message(messages),
            "analysis_snapshot_digest": snapshot_digest(snapshot),
            "context_summary": compact_context_summary_dump(context.context_summary),
            "available_artifacts": list(context.available_artifacts or []),
            "candidate_tools": candidate_tools,
        },
        emit=emit,
        phase="tool_allocation",
        title=f"分派工具：{agent_role}",
        reasoning_id=f"tool-allocation:{agent_role}",
        runtime=runtime,
    )
    return ToolAllocationDecision(**payload)


async def generate_answer_output_with_llm(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    answer_evidence_payload: Dict[str, Any],
    translation_pack: AgentTranslationPack | Dict[str, Any] | None = None,
    image_inputs: List[Dict[str, Any]] | None = None,
    emit: LoopEmit | None = None,
    runtime: LLMRuntimeConfig | None = None,
) -> AgentTurnOutput:
    translation_payload = (
        translation_pack.model_dump(mode="json")
        if isinstance(translation_pack, AgentTranslationPack)
        else dict(translation_pack or {})
    )
    parsed = await _invoke_json_role(
        system_prompt=_synthesizer_system_prompt_from_module(),
        user_payload={
            "messages": _trim_messages(messages),
            "analysis_snapshot_digest": snapshot_digest(snapshot),
            "context_digest": context_digest(context),
            "answer_evidence_payload": answer_evidence_payload,
            "translation_pack": translation_payload,
        },
        image_inputs=image_inputs,
        emit=emit,
        phase="synthesizing",
        title="综合分析并生成最终结论",
        reasoning_id="synthesizer-reasoning",
        runtime=runtime,
    )
    return AgentTurnOutput(**parsed)
