from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx

from .providers.client import get_llm_provider_client, is_llm_enabled
from .schemas import AgentContextAskRequest, AgentContextAskResponse, ContextAskTarget


CONTEXT_ASK_SYSTEM_PROMPT = """
你是 Geo-Agent 的上下文解释器。只解释用户当前点击的 target，不重新规划、不调用工具、不虚构新数据。
回答必须围绕当前区域上下文，引用已有 EvidenceNode、source_id 或 artifact_refs；如果证据不足，要明确说明缺口。
输出 JSON：answer, evidence, citations, warnings。answer 包含直接回答、依据、不确定性、可继续追问建议。
""".strip()


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _compact_items(items: List[Any], limit: int = 8) -> List[Any]:
    compacted: List[Any] = []
    for item in list(items or [])[:limit]:
        if isinstance(item, dict):
            compacted.append({str(k): v for k, v in list(item.items())[:8]})
        else:
            text = _as_text(item)
            if text:
                compacted.append(text[:500])
    return compacted


def _source_evidence_nodes(item: Dict[str, Any]) -> List[Any]:
    nodes = item.get("evidence_nodes") if isinstance(item.get("evidence_nodes"), list) else item.get("evidenceNodes")
    if isinstance(nodes, list) and nodes:
        return nodes
    evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
    return evidence


def _compact_evidence_nodes(nodes: List[Any], *, limit: int = 3) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for node in list(nodes or [])[:limit]:
        if not isinstance(node, dict):
            text = _as_text(node)
            if text:
                compacted.append({"content": text[:220]})
            continue
        summary = _as_text(node.get("summary"))
        content = _as_text(node.get("content") or node.get("text"))
        compacted_node: Dict[str, Any] = {
            "id": _as_text(node.get("id") or node.get("node_id") or node.get("nodeId")),
            "source_id": _as_text(node.get("source_id") or node.get("sourceId")),
            "source_type": _as_text(node.get("source_type") or node.get("sourceType")),
            "title": _as_text(node.get("title"))[:160],
        }
        if summary:
            compacted_node["summary"] = summary[:220]
        elif content:
            compacted_node["content"] = content[:220]
        locator = node.get("locator")
        if isinstance(locator, dict):
            compacted_node["locator"] = _compact_value(locator, depth=1, list_limit=4, string_limit=120)
        citation = node.get("citation")
        if isinstance(citation, dict):
            compacted_node["citation"] = _compact_value(citation, depth=1, list_limit=4, string_limit=120)
        compacted.append({key: value for key, value in compacted_node.items() if value not in ("", None, [], {})})
    return compacted


def _compact_value(value: Any, *, depth: int = 2, list_limit: int = 8, string_limit: int = 500) -> Any:
    if depth <= 0:
        if isinstance(value, (dict, list, tuple)):
            return f"{type(value).__name__}({len(value)})"
        text = _as_text(value)
        return text[:string_limit] if text else value
    if isinstance(value, dict):
        compacted: Dict[str, Any] = {}
        for key, item in list(value.items())[:16]:
            compacted[str(key)] = _compact_value(item, depth=depth - 1, list_limit=list_limit, string_limit=string_limit)
        return compacted
    if isinstance(value, (list, tuple)):
        return [
            _compact_value(item, depth=depth - 1, list_limit=list_limit, string_limit=string_limit)
            for item in list(value)[:list_limit]
        ]
    if isinstance(value, str):
        return value[:string_limit]
    return value


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
    return _compact_value(selected, depth=2, list_limit=6, string_limit=300)


def _compact_target(target: ContextAskTarget) -> Dict[str, Any]:
    data = target.model_dump(mode="json")
    data["summary"] = _as_text(data.get("summary"))[:1200]
    data["evidence"] = _compact_items(list(target.evidence or []), limit=6)
    data["payload"] = _compact_value(target.payload, depth=3, list_limit=6, string_limit=400)
    return data


def _compact_ppt_sources(target: ContextAskTarget) -> Dict[str, Any]:
    payload = target.payload if isinstance(target.payload, dict) else {}
    sources = list(payload.get("sources") or [])
    compacted_sources: List[Dict[str, Any]] = []
    for item in sources[:24]:
        if not isinstance(item, dict):
            continue
        compacted_sources.append({
            "source_id": _as_text(item.get("source_id") or item.get("sourceId") or item.get("id")),
            "title": _as_text(item.get("title")),
            "source_kind": _as_text(item.get("source_kind") or item.get("sourceKind")),
            "included": list(item.get("included") or [])[:8],
            "scope": _compact_value(item.get("scope"), depth=2, list_limit=4, string_limit=200),
            "metrics": _compact_value(item.get("metrics"), depth=1, list_limit=4, string_limit=160),
            "metric_gaps": _compact_value(item.get("metric_gaps") or item.get("metricGaps"), depth=1, list_limit=4, string_limit=160),
            "evidence_count": len(_source_evidence_nodes(item)),
            "evidence_nodes": _compact_evidence_nodes(_source_evidence_nodes(item), limit=3),
            "visual_specs_count": len(list(item.get("visual_specs") or item.get("visualSpecs") or [])),
            "policy": _as_text(item.get("policy"))[:240],
            "transport_status": _as_text(item.get("transport_status") or item.get("transportStatus")),
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
    evidence = _compact_items(target.evidence)
    citations = list(target.artifact_refs or [])
    summary = _as_text(target.summary) or "当前对象没有传入完整摘要，需要结合原始证据继续核对。"
    evidence_text = f"已有 {len(evidence)} 条证据" if evidence else "当前上下文没有结构化证据"
    citation_text = f"，关联 {len(citations)} 个产物引用" if citations else ""
    warnings = [
        "本次回答没有重新运行工具，只解释当前 target。",
    ]
    if reason:
        warnings.append(reason)
    return AgentContextAskResponse(
        status="success",
        answer=(
            f"直接回答：围绕“{target.title or '当前对象'}”，{summary}\n"
            f"依据：{evidence_text}{citation_text}。\n"
            "不确定性/缺口：如果原始证据缺失、指标口径不完整或图表只展示聚合结果，需要打开证据抽屉核对。\n"
            f"可继续追问：可以继续问“这个判断最关键的证据是什么？”或“{_as_text(question) or '这个结论'}的风险在哪里？”"
        ),
        evidence=evidence,
        citations=citations,
        warnings=warnings,
    )


def _build_user_payload(payload: AgentContextAskRequest) -> Dict[str, Any]:
    target = payload.target
    is_ppt_sources = _as_text(target.type) == "ppt_sources"
    user_payload = {
        "question": payload.question,
        "conversation_id": payload.conversation_id,
        "history_id": payload.history_id,
        "target": _compact_target(target),
        "analysis_snapshot_summary": _compact_snapshot(payload),
        "ppt_sources_summary": _compact_ppt_sources(target) if is_ppt_sources else {},
        "instructions": [
            "只解释 target，不延伸到无关区域。",
            "不能说使用了没有出现在 evidence/artifact_refs/payload/snapshot_summary 中的数据。",
            "证据不足时必须说明不确定性。",
        ],
    }
    if _json_size(user_payload) > 60000:
        user_payload["analysis_snapshot_summary"] = {
            "context": _compact_value(payload.analysis_snapshot.context, depth=1, list_limit=4, string_limit=200),
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


async def answer_context_ask(payload: AgentContextAskRequest) -> AgentContextAskResponse:
    question = _as_text(payload.question)
    if not question:
        return AgentContextAskResponse(status="failed", error="invalid_question", warnings=["question 不能为空"])

    target = payload.target
    if not _as_text(target.title):
        target.title = "当前上下文"

    require_ai = bool(payload.require_ai)

    if not is_llm_enabled():
        if require_ai:
            return _strict_ai_failure("ai_unavailable", "AI 未启用，无法回答。")
        return _fallback_answer(question, target, "AI 未启用，已返回规则解释。")

    client = get_llm_provider_client()
    if not client:
        if require_ai:
            return _strict_ai_failure("ai_unavailable", "AI provider 未配置，无法回答。")
        return _fallback_answer(question, target, "AI provider 未配置，已返回规则解释。")

    try:
        data = await client.chat_json(
            system_prompt=CONTEXT_ASK_SYSTEM_PROMPT,
            user_payload=_build_user_payload(payload),
            phase="context_ask",
            title="上下文追问",
            reasoning_id="context-ask",
        )
    except Exception as exc:
        message = _format_ai_error(exc)
        if require_ai:
            return _strict_ai_failure("ai_call_failed", message)
        return _fallback_answer(question, target, f"{message}，已返回规则解释。")

    if not isinstance(data, dict):
        if require_ai:
            return _strict_ai_failure("ai_invalid_response", "AI 返回格式异常。")
        return _fallback_answer(question, target, "AI 返回格式异常，已返回规则解释。")

    answer = _as_text(data.get("answer"))
    if not answer:
        if require_ai:
            return _strict_ai_failure("ai_invalid_response", "AI 返回缺少 answer。")
        return _fallback_answer(question, target, "AI 返回缺少 answer，已返回规则解释。")

    return AgentContextAskResponse(
        status="success",
        answer=answer,
        evidence=_compact_items(list(data.get("evidence") or target.evidence or [])),
        citations=list(data.get("citations") or target.artifact_refs or []),
        warnings=[_as_text(item) for item in list(data.get("warnings") or []) if _as_text(item)],
    )
