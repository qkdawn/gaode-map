from __future__ import annotations

from .context_ask_compaction import as_text, compact_items, merge_unique
from .context_ask_service import answer_context_ask
from .schemas import AgentContextAskRequest, AgentContextAskResponse
from .selected_sources import is_analysis_sources_type
from .source_qa_loop import run_source_qa_loop


async def _answer_selected_sources_with_mini_loop(payload: AgentContextAskRequest) -> tuple[AgentContextAskResponse | None, str]:
    source_qa = await run_source_qa_loop(payload)
    if source_qa.status == "success" and as_text(source_qa.answer):
        warnings = list(source_qa.warnings or [])
        if source_qa.used_tools:
            warnings.append(f"来源问答已使用工具: {', '.join(source_qa.used_tools)}")
        return (
            AgentContextAskResponse(
                status="success",
                answer=source_qa.answer,
                evidence=compact_items(merge_unique(list(source_qa.evidence or []))),
                citations=merge_unique(list(source_qa.citations or [])),
                warnings=merge_unique([as_text(item) for item in warnings if as_text(item)]),
            ),
            "",
        )
    if source_qa.error and source_qa.status != "skipped":
        return None, f"来源问答工具循环未完成：{source_qa.error}"
    return None, ""


async def answer_analysis_quick_question(payload: AgentContextAskRequest) -> AgentContextAskResponse:
    tool_warning = ""
    if is_analysis_sources_type(payload.target.type):
        try:
            tool_answer, tool_warning = await _answer_selected_sources_with_mini_loop(payload)
            if tool_answer is not None:
                return tool_answer
        except Exception as exc:
            tool_warning = f"来源问答工具循环失败：{type(exc).__name__}"
            if as_text(str(exc)):
                tool_warning = f"{tool_warning}({as_text(str(exc))[:120]})"
    return await answer_context_ask(payload, tool_warning=tool_warning)
