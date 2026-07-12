from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Tuple

import httpx
from fastapi import HTTPException

from .context_ask_compaction import as_text, compact_items, compact_value, merge_unique
from .context_ask_datasets import build_scoped_dataset_context
from .context_ask_prompts import CONTEXT_ASK_FAST_SYSTEM_PROMPT, CONTEXT_ASK_SYSTEM_PROMPT
from .model_profiles import resolve_model_runtime
from .providers.client import get_llm_provider_client, is_llm_enabled
from .schemas import AgentContextAskRequest, AgentContextAskResponse, ContextAskTarget
from .selected_sources import (
    is_analysis_sources_type,
    source_items_from_target,
    selected_sources_summary_from_items,
)


def _compact_snapshot(payload: AgentContextAskRequest) -> Dict[str, Any]:
    snapshot = payload.analysis_snapshot.model_dump(mode="json")
    selected = {
        "context": snapshot.get("context") or {},
        "active_panel": snapshot.get("active_panel") or "",
        "current_filters": snapshot.get("current_filters") or {},
        "scope": snapshot.get("scope") or {},
        "poi_summary": snapshot.get("poi_summary") or {},
        "h3": snapshot.get("h3") or {},
        "road": snapshot.get("road") or {},
        "population": snapshot.get("population") or {},
        "nightlight": snapshot.get("nightlight") or {},
    }
    return compact_value(selected, depth=2, list_limit=6, string_limit=300)


def _compact_target(target: ContextAskTarget) -> Dict[str, Any]:
    data = target.model_dump(mode="json")
    data["summary"] = as_text(data.get("summary"))[:1200]
    data["evidence"] = compact_items(list(target.evidence or []), limit=6)
    data["payload"] = compact_value(target.payload, depth=5, list_limit=6, string_limit=400)
    return data


def _json_size(value: Dict[str, Any]) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


def _fallback_answer(question: str, target: ContextAskTarget, reason: str = "") -> AgentContextAskResponse:
    evidence = compact_items(target.evidence)
    citations = list(target.artifact_refs or [])
    summary = as_text(target.summary) or "当前对象没有传入完整摘要，需要结合原始证据继续核对。"
    evidence_text = f"已有 {len(evidence)} 条证据" if evidence else "当前上下文没有结构化证据"
    citation_text = f"，关联 {len(citations)} 个产物引用" if citations else ""
    warnings = [
        "本次回答没有重新运行工具，只解释当前 target。",
    ]
    if reason:
        warnings.append(reason)
    if target.type == "capability_run":
        run_payload = target.payload if isinstance(target.payload, dict) else {}
        run_id = as_text(run_payload.get("run_id") or target.id) or "未标识运行"
        version_kind = as_text(run_payload.get("version_kind"))
        version_text = "不可变历史版本" if version_kind == "immutable_history" else "当前运行结果"
        status = as_text(run_payload.get("status")) or "未记录"
        stale_inputs = [as_text(item) for item in list(run_payload.get("stale_input_artifact_ids") or []) if as_text(item)]
        stale_text = (
            f"该版本的上游产物已更新（{'、'.join(stale_inputs)}），只能用于解释和审计，不能表述为当前最新结论。"
            if stale_inputs
            else "当前上下文没有记录上游失效项，但这不等于已重新核验底层数据。"
        )
        answer = (
            f"围绕运行版本 `{run_id}`，本次解释锁定的是{version_text}，记录状态为 `{status}`。{summary}\n\n"
            f"版本边界：{stale_text}\n\n"
            f"证据边界：{evidence_text}{citation_text}。运行诊断、阶段状态和产物元数据只能说明该次执行过程，不能替代产物中的正式证据。\n\n"
            f"针对“{as_text(question) or '当前问题'}”，应优先核对该 Run 关联的输出产物、evidence_refs 和诊断；如果需要得到当前结论，应回到能力工作台重算或明确选择最新成功版本。本次没有重新运行工具，也没有把其他版本结果混入回答。"
        )
    elif is_analysis_sources_type(target.type):
        answer = (
            f"围绕“{target.title or '已选分析来源'}”，当前只能基于已传入的来源摘要和证据节点做解释；{summary}\n\n"
            f"证据边界：当前上下文包含{evidence_text}{citation_text}。本次没有重新运行来源工具，也没有补充外部基准，因此不能把摘要中的指标直接扩展成新的空间结论。\n\n"
            f"继续核对时，建议把“{as_text(question) or '当前问题'}”拆成可验证的分析任务：先确认已选来源覆盖哪些 current:dataset，再分别做 POI 业态结构、H3 热点分布、人口承载、夜光活力和路网可达性的交叉验证；每一步都应输出可引用的 EvidenceNode、年份、source_id 和空间定位。\n\n"
            "如果需要具体判断优劣、短板或策略优先级，应切换深度模式补充证据，或打开证据抽屉核对原始明细；当前降级回答只适合作为解释框架，不应作为最终分析结论。"
        )
    else:
        answer = (
            f"围绕“{target.title or '当前对象'}”，{summary}\n\n"
            f"证据边界：{evidence_text}{citation_text}。\n\n"
            f"如果原始证据缺失、指标口径不完整或图表只展示聚合结果，需要打开证据抽屉核对。可继续问“这个判断最关键的证据是什么？”或“{as_text(question) or '这个结论'}的风险在哪里？”"
        )
    return AgentContextAskResponse(
        status="success",
        answer=answer,
        evidence=evidence,
        citations=citations,
        warnings=warnings,
    )


def _build_user_payload(payload: AgentContextAskRequest, scoped_dataset_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    target = payload.target
    is_selected_sources = is_analysis_sources_type(target.type)
    user_payload = {
        "question": payload.question,
        "conversation_id": payload.conversation_id,
        "history_id": payload.history_id,
        "target": _compact_target(target),
        "analysis_snapshot_summary": _compact_snapshot(payload),
        "selected_sources_summary": selected_sources_summary_from_items(source_items_from_target(target)) if is_selected_sources else {},
        "scoped_dataset_context": compact_value(scoped_dataset_context or {}, depth=8, list_limit=12, string_limit=400) if is_selected_sources else {},
        "instructions": [
            "只解释 target，不延伸到无关区域。",
            "不能说使用了没有出现在 evidence/artifact_refs/payload/snapshot_summary/scoped_dataset_context 中的数据。",
            "如果 scoped_dataset_context.datasets 非空，优先用后端预处理好的当前范围数据回答具体对象、局部差异、TopN 和原因类问题。",
            "没有外部基准或规划阈值时，不得把当前范围内部排序直接说成整体优劣结论。",
            "证据不足时必须说明不确定性。",
            "已选分析来源回答可以使用 Markdown 小标题；复杂问题按需要说明判断、支撑证据、空间或商业含义、证据边界和下一步验证动作，但不要套用固定栏目。",
            "不要输出冒号串联的单行问答模板；标题和段落必须由当前问题与证据自然决定。",
            "下一步分析类问题必须给出分析目的、使用来源、方法动作、预期产出和优先级。",
        ],
    }
    if target.type == "capability_run":
        user_payload["instructions"].extend([
            "回答必须明确标识 target.payload.run_id，并锁定该运行版本，不得把其他版本或当前页面结果混入。",
            "version_kind=immutable_history 时，只解释保存的不可变快照；若 stale_input_artifact_ids 非空，必须明确该结果不是当前最新结论。",
            "diagnostics 和 stage 状态是执行审计信息，不得冒充结论证据；判断只能引用 evidence、artifact_refs 或 artifacts.evidence_refs。",
            "用户要求当前结论或重算时，应建议返回能力工作台选择最新成功版本或重新执行，而不是自行改写历史结果。",
        ])
    if _json_size(user_payload) > 60000:
        user_payload["analysis_snapshot_summary"] = {
            "context": compact_value(payload.analysis_snapshot.context, depth=1, list_limit=4, string_limit=200),
            "active_panel": payload.analysis_snapshot.active_panel,
        }
    return user_payload


def _format_ai_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else ""
        try:
            detail = exc.response.text[:240] if exc.response is not None else ""
        except Exception:
            detail = ""
        suffix = f"：{detail}" if detail else ""
        return f"AI 服务返回 HTTP {status}{suffix}"
    return f"AI 调用失败：{type(exc).__name__}"


def _strict_ai_failure(error: str, warning: str = "") -> AgentContextAskResponse:
    warnings = [warning] if warning else []
    return AgentContextAskResponse(status="failed", error=error, warnings=warnings)


def _ai_failure_or_fallback(
    *,
    require_ai: bool,
    error: str,
    warning: str,
    question: str,
    target: ContextAskTarget,
) -> AgentContextAskResponse:
    if require_ai:
        return _strict_ai_failure(error, warning)
    return _fallback_answer(question, target, warning)


def _client_for_request(payload: AgentContextAskRequest) -> tuple[Any | None, str]:
    """Honor an explicit model selection without changing legacy callers."""

    profile_id = as_text(payload.model_profile_id)
    if not profile_id:
        if not is_llm_enabled():
            return None, "AI 未启用，无法回答。"
        client = get_llm_provider_client()
        return (client, "") if client else (None, "AI provider 未配置，无法回答。")
    try:
        _, runtime = resolve_model_runtime(profile_id)
    except HTTPException as exc:
        return None, str(exc.detail or "所选模型不可用")
    client = get_llm_provider_client(runtime=runtime)
    return (client, "") if client else (None, "所选模型 Provider 未配置，无法回答。")


def _response_support(target: ContextAskTarget, scoped_dataset_context: Dict[str, Any]) -> Tuple[list[Any], list[Any], list[str]]:
    scoped_evidence = list(scoped_dataset_context.get("evidence_nodes") or [])
    scoped_citations = list(scoped_dataset_context.get("citations") or [])
    scoped_warnings = [as_text(item) for item in list(scoped_dataset_context.get("warnings") or []) if as_text(item)]
    evidence = compact_items(merge_unique(list(target.evidence or []) + scoped_evidence))
    citations = merge_unique(list(target.artifact_refs or []) + scoped_citations)
    return evidence, citations, merge_unique(scoped_warnings)


def _fast_messages(payload: AgentContextAskRequest, scoped_dataset_context: Dict[str, Any]) -> list[Dict[str, str]]:
    return [
        {"role": "system", "content": CONTEXT_ASK_FAST_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                _build_user_payload(payload, scoped_dataset_context),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


async def stream_context_ask(payload: AgentContextAskRequest, *, tool_warning: str = "") -> AsyncIterator[tuple[str, Dict[str, Any]]]:
    question = as_text(payload.question)
    if not question:
        yield "error", {"error": "invalid_question", "message": "question 不能为空"}
        return

    target = payload.target
    if not as_text(target.title):
        target.title = "当前上下文"
    client, client_error = _client_for_request(payload)
    if not client:
        yield "error", {"error": "ai_unavailable", "message": client_error}
        return

    scoped_dataset_context = build_scoped_dataset_context(payload)
    if tool_warning:
        scoped_dataset_context["warnings"] = merge_unique(list(scoped_dataset_context.get("warnings") or []) + [tool_warning])
    evidence, citations, warnings = _response_support(target, scoped_dataset_context)
    queue: asyncio.Queue[tuple[str, Dict[str, Any]] | None] = asyncio.Queue()

    async def emit_delta(delta: str) -> None:
        if delta:
            await queue.put(("answer_delta", {"delta": delta}))

    async def produce() -> None:
        try:
            answer = as_text(await client.stream_text(messages=_fast_messages(payload, scoped_dataset_context), emit_delta=emit_delta))
            if not answer:
                raise ValueError("ai_invalid_response")
            await queue.put((
                "complete",
                {
                    "answer": answer,
                    "evidence": evidence,
                    "citations": citations,
                    "warnings": warnings,
                },
            ))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(("error", {"error": "ai_call_failed", "message": _format_ai_error(exc)}))
        finally:
            await queue.put(None)

    producer = asyncio.create_task(produce())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if not producer.done():
            producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def answer_context_ask(payload: AgentContextAskRequest, *, tool_warning: str = "") -> AgentContextAskResponse:
    question = as_text(payload.question)
    if not question:
        return AgentContextAskResponse(status="failed", error="invalid_question", warnings=["question 不能为空"])

    target = payload.target
    if not as_text(target.title):
        target.title = "当前上下文"

    require_ai = bool(payload.require_ai)

    client, client_error = _client_for_request(payload)
    if not client:
        return _ai_failure_or_fallback(
            require_ai=require_ai,
            error="ai_unavailable",
            warning=client_error if require_ai else f"{client_error}，已返回规则解释。",
            question=question,
            target=target,
        )

    scoped_dataset_context = build_scoped_dataset_context(payload)
    if tool_warning:
        scoped_dataset_context["warnings"] = merge_unique(list(scoped_dataset_context.get("warnings") or []) + [tool_warning])

    try:
        data = await client.chat_json(
            system_prompt=CONTEXT_ASK_SYSTEM_PROMPT,
            user_payload=_build_user_payload(payload, scoped_dataset_context),
            phase="context_ask",
            title="上下文追问",
            reasoning_id="context-ask",
        )
    except Exception as exc:
        message = _format_ai_error(exc)
        return _ai_failure_or_fallback(
            require_ai=require_ai,
            error="ai_call_failed",
            warning=message if require_ai else f"{message}，已返回规则解释。",
            question=question,
            target=target,
        )

    if not isinstance(data, dict):
        return _ai_failure_or_fallback(
            require_ai=require_ai,
            error="ai_invalid_response",
            warning="AI 返回格式异常。" if require_ai else "AI 返回格式异常，已返回规则解释。",
            question=question,
            target=target,
        )

    answer = as_text(data.get("answer"))
    if not answer:
        return _ai_failure_or_fallback(
            require_ai=require_ai,
            error="ai_invalid_response",
            warning="AI 返回缺少 answer。" if require_ai else "AI 返回缺少 answer，已返回规则解释。",
            question=question,
            target=target,
        )

    response_evidence, response_citations, scoped_warnings = _response_support(target, scoped_dataset_context)
    response_evidence = compact_items(merge_unique(list(data.get("evidence") or []) + response_evidence))
    response_citations = merge_unique(list(data.get("citations") or []) + response_citations)
    response_warnings = merge_unique([as_text(item) for item in list(data.get("warnings") or []) if as_text(item)] + scoped_warnings)

    return AgentContextAskResponse(
        status="success",
        answer=answer,
        evidence=response_evidence,
        citations=response_citations,
        warnings=response_warnings,
    )
