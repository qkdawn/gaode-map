from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx

from .providers.client import get_llm_provider_client, is_llm_enabled
from .schemas import AgentContextAskRequest, AgentContextAskResponse, ContextAskTarget


CONTEXT_ASK_SYSTEM_PROMPT = """
你是 Geo-Agent 的上下文解释器。只解释用户当前点击的 target，不重新规划、不调用工具、不虚构新数据。
回答必须围绕当前区域上下文，引用已有 evidence 或 artifact_refs；如果证据不足，要明确说明缺口。
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
    data["payload"] = _compact_value(target.payload, depth=2, list_limit=6, string_limit=400)
    return data


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
    user_payload = {
        "question": payload.question,
        "conversation_id": payload.conversation_id,
        "history_id": payload.history_id,
        "target": _compact_target(target),
        "analysis_snapshot_summary": _compact_snapshot(payload),
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


async def answer_context_ask(payload: AgentContextAskRequest) -> AgentContextAskResponse:
    question = _as_text(payload.question)
    if not question:
        return AgentContextAskResponse(status="failed", error="invalid_question", warnings=["question 不能为空"])

    target = payload.target
    if not _as_text(target.title):
        target.title = "当前上下文"

    if not is_llm_enabled():
        return _fallback_answer(question, target, "AI 未启用，已返回规则解释。")

    client = get_llm_provider_client()
    if not client:
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
        return _fallback_answer(question, target, f"{_format_ai_error(exc)}，已返回规则解释。")

    if not isinstance(data, dict):
        return _fallback_answer(question, target, "AI 返回格式异常，已返回规则解释。")

    answer = _as_text(data.get("answer"))
    if not answer:
        return _fallback_answer(question, target, "AI 返回缺少 answer，已返回规则解释。")

    return AgentContextAskResponse(
        status="success",
        answer=answer,
        evidence=_compact_items(list(data.get("evidence") or target.evidence or [])),
        citations=list(data.get("citations") or target.artifact_refs or []),
        warnings=[_as_text(item) for item in list(data.get("warnings") or []) if _as_text(item)],
    )
