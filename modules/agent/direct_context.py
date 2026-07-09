from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

from .context_ask_service import answer_context_ask
from .context_builder import build_context_summary
from .latency import LatencyRecorder
from .schemas import (
    AgentContextAskRequest,
    AgentThinkingItem,
    AgentTurnDiagnostics,
    AgentTurnOutput,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentPlanEnvelope,
)

StreamEmit = Callable[[str, dict[str, Any]], Awaitable[None] | None]

PREPROCESSED_SOURCE_TOOL = "context_ask_preprocessed_sources"


def _source_title(source: Dict[str, Any]) -> str:
    return str(source.get("title") or source.get("name") or source.get("source_id") or "").strip()


def build_preprocessed_sources_request(payload: AgentTurnRequest, question: str) -> AgentContextAskRequest | None:
    sources = payload.selected_sources_context.source_items()
    if not sources or not str(question or "").strip():
        return None
    titles = [_source_title(item) for item in sources if _source_title(item)]
    evidence_nodes: List[Any] = []
    artifact_refs: List[str] = []
    summaries: List[str] = []
    for item in sources:
        for node in list(item.get("evidence_nodes") or item.get("evidenceNodes") or [])[:4]:
            evidence_nodes.append(node)
        for ref in list(item.get("artifact_refs") or item.get("artifactRefs") or []):
            if ref:
                artifact_refs.append(ref)
        summary = str(item.get("summary") or item.get("description") or item.get("policy") or "").strip()
        if summary:
            summaries.append(summary)
    return AgentContextAskRequest(
        conversation_id=payload.conversation_id,
        history_id=payload.history_id,
        question=question,
        analysis_snapshot=payload.analysis_snapshot,
        target={
            "type": "analysis_sources",
            "id": "selected-sources",
            "title": "、".join(titles[:3]) or "已选分析来源",
            "source": "analysis",
            "summary": "\n".join(summaries[:6]),
            "evidence": evidence_nodes[:24],
            "artifact_refs": artifact_refs[:24],
            "payload": {"sources": sources},
        },
        require_ai=True,
    )


async def answer_preprocessed_sources(
    *,
    payload: AgentTurnRequest,
    question: str,
    memory_artifacts: Dict[str, Any],
    research_notes: List[str],
    thinking_timeline: List[AgentThinkingItem],
    latency: LatencyRecorder,
    emit_thinking: Callable[[dict[str, Any], str], Awaitable[None]],
) -> AgentTurnResponse | None:
    request = build_preprocessed_sources_request(payload, question)
    if request is None:
        return None

    sources = payload.selected_sources_context.source_items()
    await emit_thinking(
        {
            "phase": "preflight",
            "title": "使用已预处理来源",
            "detail": "本轮已携带前端整理好的分析来源和 EvidenceNode，直接进入上下文回答，跳过完整工具循环。",
            "display_text": "已使用预处理来源直接回答。",
            "items": [
                str(item.get("title") or item.get("source_id") or "").strip()
                for item in sources[:4]
                if str(item.get("title") or item.get("source_id") or "").strip()
            ],
            "state": "active",
        },
        "preprocessed-sources",
    )
    try:
        with latency.track("preprocessed_context_ask"):
            context_answer = await answer_context_ask(request)
    except Exception as exc:
        research_notes.append(f"预处理来源直答失败，已回退完整工具循环：{exc}")
        await emit_thinking(
            {
                "phase": "preflight",
                "title": "预处理来源直答未完成",
                "detail": "已回退完整工具循环。",
                "display_text": "已回退完整工具循环。",
                "state": "failed",
            },
            "preprocessed-sources",
        )
        return None

    if context_answer.status != "success" or not str(context_answer.answer or "").strip():
        research_notes.extend([str(item) for item in list(context_answer.warnings or []) if str(item).strip()])
        if context_answer.error:
            research_notes.append(f"预处理来源直答失败，已回退完整工具循环：{context_answer.error}")
        await emit_thinking(
            {
                "phase": "preflight",
                "title": "预处理来源直答未完成",
                "detail": context_answer.error or "已回退完整工具循环。",
                "display_text": "已回退完整工具循环。",
                "state": "failed",
            },
            "preprocessed-sources",
        )
        return None

    await emit_thinking(
        {
            "phase": "preflight",
            "title": "预处理来源回答完成",
            "detail": "已基于已选来源包生成回答，未重新运行 Agent 工具循环。",
            "display_text": "已基于已选来源包生成回答。",
            "state": "completed",
        },
        "preprocessed-sources",
    )
    note = "本轮使用 selected_sources_context 预处理来源直接回答，跳过 gate、ReAct 工具循环和最终综合 LLM。"
    return AgentTurnResponse(
        status="answered",
        stage="answered",
        output=AgentTurnOutput(answer=context_answer.answer),
        diagnostics=AgentTurnDiagnostics(
            used_tools=[PREPROCESSED_SOURCE_TOOL],
            citations=[str(item) for item in list(context_answer.citations or []) if str(item).strip()],
            research_notes=[note, *[str(item) for item in list(context_answer.warnings or []) if str(item).strip()]],
            thinking_timeline=list(thinking_timeline or []),
            planning_summary="已使用预处理分析来源直接回答。",
            latency_ms=latency.finish(),
        ),
        context_summary=build_context_summary(
            payload.analysis_snapshot,
            {
                **dict(memory_artifacts or {}),
                "selected_sources_context": {"sources": sources},
            },
        ),
        plan=AgentPlanEnvelope(summary="已使用预处理分析来源直接回答。"),
    )
