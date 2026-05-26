from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from core.config import settings

from ..context_builder import build_context_bundle
from ..schemas import (
    AgentMessage,
    AnalysisSnapshot,
    ContextBundle,
    PlanStep,
    ToolLoopResult,
)
from ..tools import RegisteredTool
from .prompts import loop_system_prompt
from .tool_loop import (
    chat_completion_tools,
    tool_output_payload,
)
from .tool_call_execution import execute_tool_call_step, tool_finish_trace_payload, tool_start_trace_payload

GraphEmit = Callable[[str, Dict[str, Any]], Awaitable[None]]


class LangGraphReactState(TypedDict, total=False):
    messages: List[Any]
    snapshot: AnalysisSnapshot
    context: ContextBundle
    registry: Dict[str, RegisteredTool]
    question: str
    governance_mode: str
    confirmed_tools: List[str]
    max_steps: int
    max_errors: int
    step_count: int
    consecutive_errors: int
    result: ToolLoopResult
    final_message: str
    stop_reason: str


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _initial_payload(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    registry: Dict[str, RegisteredTool],
) -> Dict[str, Any]:
    return {
        "question": question,
        "analysis_snapshot": snapshot.model_dump(mode="json"),
        "context": {
            "facts": dict(context.facts or {}),
            "analysis": dict(context.analysis or {}),
            "limits": list(context.limits or []),
            "available_artifacts": list(context.available_artifacts or []),
            "context_summary": context.context_summary.model_dump(mode="json"),
        },
        "tool_catalog": [
            {
                "name": name,
                "description": registered.spec.description,
                "requires": list(registered.spec.requires or []),
                "produces": list(registered.spec.produces or []),
                "cautions": list(registered.spec.cautions or []),
            }
            for name, registered in registry.items()
        ],
    }


def _tool_calls_from_message(message: Any) -> List[Dict[str, Any]]:
    calls = getattr(message, "tool_calls", None)
    if isinstance(calls, list) and calls:
        normalized = []
        for call in calls:
            if not isinstance(call, dict):
                continue
            normalized.append(
                {
                    "id": str(call.get("id") or call.get("call_id") or call.get("name") or ""),
                    "name": str(call.get("name") or call.get("tool_name") or ""),
                    "args": call.get("args") if isinstance(call.get("args"), dict) else {},
                }
            )
        return [call for call in normalized if call["name"]]
    raw_calls = getattr(message, "additional_kwargs", {}).get("tool_calls") if hasattr(message, "additional_kwargs") else []
    if not isinstance(raw_calls, list):
        return []
    normalized = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        args: Dict[str, Any] = {}
        try:
            parsed = json.loads(function.get("arguments") or "{}")
            if isinstance(parsed, dict):
                args = parsed
        except Exception:
            args = {}
        name = str(function.get("name") or call.get("name") or "")
        if name:
            normalized.append({"id": str(call.get("id") or name), "name": name, "args": args})
    return normalized


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return str(content or "").strip()


async def run_langgraph_react_loop(
    *,
    messages: List[AgentMessage],
    snapshot: AnalysisSnapshot,
    context: Optional[ContextBundle],
    registry: Dict[str, RegisteredTool],
    governance_mode: str,
    confirmed_tools: Optional[List[str]] = None,
    emit: Optional[GraphEmit] = None,
    include_secondary_tools: bool = False,
    max_steps_override: Optional[int] = None,
    max_errors_override: Optional[int] = None,
) -> ToolLoopResult:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, StateGraph

    question = str(messages[-1].content if messages else "").strip()
    context_bundle = context or build_context_bundle(snapshot)
    max_steps = max(1, int(max_steps_override or settings.ai_max_tool_steps or 8))
    max_errors = max(1, int(max_errors_override or settings.ai_max_tool_errors or 2))
    tool_schemas = chat_completion_tools(registry, include_secondary=include_secondary_tools)
    model = ChatOpenAI(
        model=str(settings.ai_model or "").strip(),
        api_key=str(settings.ai_api_key or ""),
        base_url=str(settings.ai_base_url or "").rstrip("/") or None,
        timeout=float(settings.ai_timeout_s or 60),
    ).bind_tools(tool_schemas)

    async def think(state: LangGraphReactState) -> Dict[str, Any]:
        result = state["result"]
        if emit:
            await emit(
                "thinking",
                {
                    "phase": "planned",
                    "source": "langgraph_react",
                    "title": "判断下一步",
                    "detail": "我正在根据已有观察和工具目录判断是否继续调用工具。",
                    "state": "active",
                },
            )
        response = await model.ainvoke(state["messages"])
        text = _message_text(response)
        updates: Dict[str, Any] = {"messages": [*state["messages"], response]}
        if not _tool_calls_from_message(response):
            result.assistant_summary = text
            result.status = "completed"
            updates["result"] = result
            updates["final_message"] = text
        return updates

    async def act_tools(state: LangGraphReactState) -> Dict[str, Any]:
        last_message = state["messages"][-1]
        tool_calls = _tool_calls_from_message(last_message)
        result = state["result"]
        next_messages = list(state["messages"])
        consecutive_errors = int(state.get("consecutive_errors") or 0)
        step_count = int(state.get("step_count") or 0)
        artifacts = result.artifacts if isinstance(result.artifacts, dict) else {}

        for call in tool_calls:
            if step_count >= int(state["max_steps"]):
                result.status = "failed"
                result.stop_reason = "max_tool_steps_exceeded"
                result.error = f"工具调用步数超过上限 {state['max_steps']}"
                break

            tool_name = str(call.get("name") or "").strip()
            arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
            registered = state["registry"].get(tool_name)
            step = PlanStep(
                tool_name=tool_name,
                arguments=arguments,
                reason="LangGraph ReAct tool call",
                expected_artifacts=list(registered.spec.produces or []) if registered else [],
            )
            result.steps.append(step)
            if emit:
                await emit(
                    "trace",
                    tool_start_trace_payload(
                        trace_id=f"langgraph-tool:{call.get('id') or tool_name}",
                        call_id=str(call.get("id") or ""),
                        step=step,
                    ),
                )

            execution = await execute_tool_call_step(
                registered_tool=registered,
                step=step,
                snapshot=state["snapshot"],
                artifacts=artifacts,
                question=state["question"],
                governance_mode=str(state.get("governance_mode") or "auto"),
                confirmed_tools=list(state.get("confirmed_tools") or []),
            )
            tool_result = execution.result
            trace = execution.trace

            result.execution_trace.append(trace)
            result.tool_results.append(tool_result)
            if tool_result.status == "success":
                result.used_tools.append(tool_name)
                consecutive_errors = 0
            else:
                consecutive_errors += 1
            if tool_result.artifacts:
                artifacts.update(tool_result.artifacts)
                result.artifacts = artifacts
            if tool_result.warnings:
                result.research_notes.extend([str(item) for item in tool_result.warnings if str(item).strip()])
            if emit:
                await emit(
                    "trace",
                    tool_finish_trace_payload(
                        trace_id=f"langgraph-tool:{call.get('id') or tool_name}",
                        call_id=str(call.get("id") or ""),
                        step=step,
                        execution=execution,
                    ),
                )

            next_messages.append(
                ToolMessage(
                    content=tool_output_payload(tool_result),
                    tool_call_id=str(call.get("id") or tool_name),
                    name=tool_name,
                )
            )
            step_count += 1
            if consecutive_errors >= int(state["max_errors"]):
                result.status = "failed"
                result.stop_reason = "too_many_tool_errors"
                result.error = str(tool_result.error or "tool_execution_failed")
                break

        return {
            "messages": next_messages,
            "result": result,
            "step_count": step_count,
            "consecutive_errors": consecutive_errors,
        }

    async def finalize(state: LangGraphReactState) -> Dict[str, Any]:
        result = state["result"]
        if result.status != "completed" and not result.assistant_summary:
            result.assistant_summary = result.error or result.stop_reason or "LangGraph ReAct 未能稳定完成。"
        return {"result": result, "final_message": result.assistant_summary}

    def route_after_think(state: LangGraphReactState) -> str:
        if state["result"].status != "failed" and _tool_calls_from_message(state["messages"][-1]):
            return "act_tools"
        return "finalize"

    def route_after_tools(state: LangGraphReactState) -> str:
        if state["result"].status == "failed":
            return "finalize"
        return "think"

    graph = StateGraph(LangGraphReactState)
    graph.add_node("think", think)
    graph.add_node("act_tools", act_tools)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("think")
    graph.add_conditional_edges("think", route_after_think, {"act_tools": "act_tools", "finalize": "finalize"})
    graph.add_conditional_edges("act_tools", route_after_tools, {"think": "think", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    app = graph.compile()

    result = ToolLoopResult(status="completed")
    initial_messages = [
        SystemMessage(content=loop_system_prompt()),
        HumanMessage(content=_safe_json(_initial_payload(question=question, snapshot=snapshot, context=context_bundle, registry=registry))),
    ]
    final_state = await app.ainvoke(
        {
            "messages": initial_messages,
            "snapshot": snapshot,
            "context": context_bundle,
            "registry": registry,
            "question": question,
            "governance_mode": governance_mode,
            "confirmed_tools": list(confirmed_tools or []),
            "max_steps": max_steps,
            "max_errors": max_errors,
            "step_count": 0,
            "consecutive_errors": 0,
            "result": result,
        },
        {"recursion_limit": max(6, max_steps * 3 + 4)},
    )
    return final_state.get("result") or result
