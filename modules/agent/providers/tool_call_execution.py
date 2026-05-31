from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable

from ..executor import execute_plan_step
from ..governance import check_tool_governance
from ..llm_digest import summarize_tool_arguments, summarize_tool_result
from ..schemas import AnalysisSnapshot, ExecutionTraceItem, PlanStep, ToolResult
from ..tools import RegisteredTool


@dataclass
class ToolCallExecution:
    result: ToolResult
    trace: ExecutionTraceItem
    registered_tool: RegisteredTool | None = None


_GENERIC_TOOL_RESULT_TEXT = {"", "执行成功", "成功", "已完成", "完成", "ok", "OK", "无结果"}


def _tool_result_display_text(result: ToolResult) -> str:
    if result.status == "failed":
        return str(result.error or "执行失败")
    summary = summarize_tool_result(result)
    return "" if str(summary or "").strip() in _GENERIC_TOOL_RESULT_TEXT else str(summary or "").strip()


def tool_start_trace_payload(*, trace_id: str, call_id: str, step: PlanStep) -> Dict[str, Any]:
    return {
        "id": trace_id,
        "call_id": str(call_id or ""),
        "tool_name": step.tool_name,
        "status": "start",
        "reason": step.reason,
        "message": "开始执行工具",
        "display_text": step.reason or "",
        "arguments_summary": summarize_tool_arguments(step.arguments),
        "produced_artifacts": list(step.expected_artifacts or []),
    }


def tool_finish_trace_payload(
    *,
    trace_id: str,
    call_id: str,
    step: PlanStep,
    execution: ToolCallExecution,
) -> Dict[str, Any]:
    result = execution.result
    trace = execution.trace
    display_text = _tool_result_display_text(result)
    return {
        "id": trace_id,
        "call_id": str(call_id or ""),
        "tool_name": step.tool_name,
        "status": trace.status if trace.status == "blocked" else result.status,
        "reason": step.reason,
        "message": trace.message or ("执行成功" if result.status == "success" else "执行失败"),
        "display_text": display_text,
        "arguments_summary": summarize_tool_arguments(step.arguments),
        "result_summary": display_text or summarize_tool_result(result),
        "evidence_count": len(result.evidence or []),
        "warning_count": len(result.warnings or []),
        "produced_artifacts": list((result.artifacts or {}).keys())[:12],
    }


async def execute_tool_call_step(
    *,
    registered_tool: RegisteredTool | None,
    step: PlanStep,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
    governance_mode: str,
    confirmed_tools: Iterable[str] | None = None,
) -> ToolCallExecution:
    if registered_tool is None:
        result = ToolResult(tool_name=step.tool_name, status="failed", error=f"unknown_tool:{step.tool_name}")
        trace = ExecutionTraceItem(
            tool_name=step.tool_name,
            status="failed",
            reason=step.reason,
            message=result.error,
            evidence_count=0,
            warning_count=1,
        )
        return ToolCallExecution(result=result, trace=trace)

    governance_prompt = check_tool_governance(
        mode=governance_mode,
        spec=registered_tool.spec,
        confirmed_tools=confirmed_tools,
    )
    if governance_prompt:
        result = ToolResult(
            tool_name=registered_tool.spec.name,
            status="failed",
            warnings=[governance_prompt],
            error="governance_blocked",
        )
        trace = ExecutionTraceItem(
            tool_name=registered_tool.spec.name,
            status="blocked",
            reason=step.reason,
            message=governance_prompt,
            cost_level=registered_tool.spec.cost_level,
            risk_level=registered_tool.spec.risk_level,
            evidence_count=0,
            warning_count=1,
        )
        return ToolCallExecution(result=result, trace=trace, registered_tool=registered_tool)

    result, trace = await execute_plan_step(
        registered_tool=registered_tool,
        step=step,
        snapshot=snapshot,
        artifacts=artifacts,
        question=question,
    )
    return ToolCallExecution(result=result, trace=trace, registered_tool=registered_tool)
