from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx

from .context_ask_compaction import as_text, compact_evidence_nodes, compact_items, compact_value, merge_unique
from .context_ask_datasets import build_scoped_dataset_context
from .context_ask_prompts import CONTEXT_ASK_SYSTEM_PROMPT
from .providers.client import get_llm_provider_client, is_llm_enabled
from .schemas import AgentContextAskRequest, AgentContextAskResponse, ContextAskTarget
from .selected_sources import (
    evidence_nodes_from_item,
    is_analysis_sources_type,
    source_id_from_item,
    source_items_from_target,
    source_kind_from_item,
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
    data["payload"] = compact_value(target.payload, depth=3, list_limit=6, string_limit=400)
    return data


def _compact_selected_sources(target: ContextAskTarget) -> Dict[str, Any]:
    sources = source_items_from_target(target)
    compacted_sources: List[Dict[str, Any]] = []
    for item in sources[:24]:
        evidence_nodes = evidence_nodes_from_item(item)
        compacted_sources.append({
            "source_id": source_id_from_item(item),
            "title": as_text(item.get("title")),
            "source_kind": source_kind_from_item(item),
            "included": list(item.get("included") or [])[:8],
            "scope": compact_value(item.get("scope"), depth=2, list_limit=4, string_limit=200),
            "metrics": compact_value(item.get("metrics"), depth=1, list_limit=4, string_limit=160),
            "metric_gaps": compact_value(item.get("metric_gaps") or item.get("metricGaps"), depth=1, list_limit=4, string_limit=160),
            "evidence_count": len(evidence_nodes),
            "evidence_nodes": compact_evidence_nodes(evidence_nodes, limit=3),
            "visual_specs_count": len(list(item.get("visual_specs") or item.get("visualSpecs") or [])),
            "policy": as_text(item.get("policy"))[:240],
            "transport_status": as_text(item.get("transport_status") or item.get("transportStatus")),
        })
    return {
        "source_count": len(sources),
        "sources": compacted_sources,
    }


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
    if is_analysis_sources_type(target.type):
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
        "selected_sources_summary": _compact_selected_sources(target) if is_selected_sources else {},
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


async def answer_context_ask(payload: AgentContextAskRequest, *, tool_warning: str = "") -> AgentContextAskResponse:
    question = as_text(payload.question)
    if not question:
        return AgentContextAskResponse(status="failed", error="invalid_question", warnings=["question 不能为空"])

    target = payload.target
    if not as_text(target.title):
        target.title = "当前上下文"

    require_ai = bool(payload.require_ai)

    if not is_llm_enabled():
        return _ai_failure_or_fallback(
            require_ai=require_ai,
            error="ai_unavailable",
            warning="AI 未启用，无法回答。" if require_ai else "AI 未启用，已返回规则解释。",
            question=question,
            target=target,
        )

    client = get_llm_provider_client()
    if not client:
        return _ai_failure_or_fallback(
            require_ai=require_ai,
            error="ai_unavailable",
            warning="AI provider 未配置，无法回答。" if require_ai else "AI provider 未配置，已返回规则解释。",
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

    scoped_evidence = list(scoped_dataset_context.get("evidence_nodes") or [])
    scoped_citations = list(scoped_dataset_context.get("citations") or [])
    scoped_warnings = [as_text(item) for item in list(scoped_dataset_context.get("warnings") or []) if as_text(item)]

    response_evidence = list(data.get("evidence") or target.evidence or []) + scoped_evidence
    response_citations = list(data.get("citations") or target.artifact_refs or []) + scoped_citations
    response_warnings = [as_text(item) for item in list(data.get("warnings") or []) if as_text(item)] + scoped_warnings

    return AgentContextAskResponse(
        status="success",
        answer=answer,
        evidence=compact_items(merge_unique(response_evidence)),
        citations=merge_unique(response_citations),
        warnings=merge_unique(response_warnings),
    )
