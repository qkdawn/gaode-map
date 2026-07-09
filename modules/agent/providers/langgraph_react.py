from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from core.config import settings

from ..context_builder import build_context_bundle
from ..llm_digest import compact_for_llm, context_digest, snapshot_digest, summarize_tool_result
from ..schemas import (
    AgentMessage,
    AnalysisSnapshot,
    ContextBundle,
    PlanStep,
    ToolLoopResult,
    ToolResult,
)
from ..selected_sources import source_id_from_item, source_items_from_artifacts, source_kind_from_item
from ..tools import RegisteredTool
from .prompts import loop_system_prompt
from .tool_loop import chat_completion_tools, select_react_tool_registry
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
    max_steps: Optional[int]
    max_errors: int
    step_count: int
    consecutive_errors: int
    result: ToolLoopResult
    final_message: str
    stop_reason: str
    initial_artifacts: Dict[str, Any]


def _optional_positive_limit(value: Any) -> Optional[int]:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return max(1, parsed) if parsed > 0 else None


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _react_context_digest(context: ContextBundle) -> Dict[str, Any]:
    digest = context_digest(context)
    analysis = digest.get("analysis") if isinstance(digest.get("analysis"), dict) else {}
    frontend_analysis = analysis.get("frontend_analysis") if isinstance(analysis.get("frontend_analysis"), dict) else {}
    if frontend_analysis:
        analysis["frontend_analysis"] = {
            "available_sections": list(frontend_analysis.keys())[:20],
            "section_count": len(frontend_analysis),
        }
    digest["analysis"] = analysis
    return compact_for_llm(digest, max_depth=5)


def _artifact_catalog(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    catalog: Dict[str, Any] = {}
    if artifacts.get("frontend_map_search_context"):
        context = artifacts.get("frontend_map_search_context") if isinstance(artifacts.get("frontend_map_search_context"), dict) else {}
        spatial = context.get("spatial_anchors") if isinstance(context.get("spatial_anchors"), dict) else {}
        place = context.get("place_anchors") if isinstance(context.get("place_anchors"), dict) else {}
        catalog["frontend_map_search_context"] = {
            "purpose": "本轮前端地图结构化对象可检索源，需要 search_analysis_context/read_analysis_evidence_node 读取 EvidenceNode 后才能引用具体对象。",
            "place_group_count": len(place.get("groups") or []) if isinstance(place, dict) else 0,
            "place_name_count": len(place.get("names") or []) if isinstance(place, dict) else 0,
            "domains": [
                key
                for key in ("poi", "h3", "road", "population", "nightlight")
                if key == "poi" or (isinstance(spatial.get(key), dict) and spatial.get(key))
            ],
        }
    if artifacts.get("selected_sources_context"):
        sources = source_items_from_artifacts(artifacts)
        catalog["selected_sources_context"] = {
            "purpose": "本轮已选分析来源可检索源；分析来源时先 list_selected_sources，再 search_selected_source_evidence/read_selected_source_evidence_node。",
            "source_count": len(sources),
            "source_ids": [source_id_from_item(item) for item in sources[:20] if source_id_from_item(item)],
            "source_kinds": list(dict.fromkeys([source_kind_from_item(item) for item in sources if source_kind_from_item(item)])),
        }
    if artifacts.get("business_analyst_skeleton"):
        ba_skeleton = artifacts.get("business_analyst_skeleton") if isinstance(artifacts.get("business_analyst_skeleton"), dict) else {}
        selected_skill = ba_skeleton.get("selected_skill") if isinstance(ba_skeleton.get("selected_skill"), dict) else {}
        model_graph = ba_skeleton.get("model_graph") if isinstance(ba_skeleton.get("model_graph"), dict) else {}
        catalog["business_analyst_skeleton"] = {
            "purpose": "本轮 Business Analyst 分析骨架；用于决定商业分析模型路径、可选分支和对应工具，不是输出模板。",
            "status": str(ba_skeleton.get("status") or ""),
            "selected_skill": {
                "skill_id": str(selected_skill.get("skill_id") or ""),
                "title": str(selected_skill.get("title") or ""),
                "purpose": str(selected_skill.get("purpose") or ""),
            },
            "graph_id": str(model_graph.get("graph_id") or selected_skill.get("uses_model_graph") or ""),
            "recommended_path": list(ba_skeleton.get("recommended_path") or [])[:8],
            "path_relations": list(ba_skeleton.get("path_relations") or [])[:8],
            "optional_branch_keys": list((ba_skeleton.get("optional_branches") or {}).keys())[:8]
            if isinstance(ba_skeleton.get("optional_branches"), dict)
            else [],
            "model_tool_map": ba_skeleton.get("model_tool_map") if isinstance(ba_skeleton.get("model_tool_map"), dict) else {},
            "skip_conditions": ba_skeleton.get("skip_conditions") if isinstance(ba_skeleton.get("skip_conditions"), dict) else {},
            "guardrails": list(ba_skeleton.get("guardrails") or [])[:12],
            "answer_guidance": list(ba_skeleton.get("answer_guidance") or [])[:8],
        }
    return catalog


def _react_tool_result_payload(result: ToolResult) -> str:
    payload = {
        "tool_name": result.tool_name,
        "status": result.status,
        "result_summary": summarize_tool_result(result),
        "result": compact_for_llm(result.result, max_depth=4),
        "evidence": compact_for_llm(result.evidence, max_depth=4),
        "warnings": list(result.warnings or [])[:8],
        "error": result.error,
        "artifact_keys": list((result.artifacts or {}).keys())[:20],
    }
    return _safe_json(payload)


def _initial_payload(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    context: ContextBundle,
    registry: Dict[str, RegisteredTool],
    artifacts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "question": question,
        "analysis_snapshot_digest": compact_for_llm(snapshot_digest(snapshot), max_depth=5),
        "context_digest": _react_context_digest(context),
        "artifact_catalog": _artifact_catalog(dict(artifacts or {})),
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
    initial_artifacts: Optional[Dict[str, Any]] = None,
) -> ToolLoopResult:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, StateGraph

    question = str(messages[-1].content if messages else "").strip()
    context_bundle = context or build_context_bundle(snapshot)
    max_steps = _optional_positive_limit(max_steps_override if max_steps_override is not None else settings.ai_max_tool_steps)
    max_errors = max(1, int(max_errors_override or settings.ai_max_tool_errors or 2))
    visible_registry = select_react_tool_registry(
        registry,
        question=question,
        artifacts=dict(initial_artifacts or {}),
        include_secondary=include_secondary_tools,
    )
    tool_schemas = chat_completion_tools(visible_registry)
    model = ChatOpenAI(
        model=str(settings.ai_model or "").strip(),
        api_key=str(settings.ai_api_key or ""),
        base_url=str(settings.ai_base_url or "").rstrip("/") or None,
        timeout=None,
    ).bind_tools(tool_schemas)

    async def preflight(_state: LangGraphReactState) -> Dict[str, Any]:
        if emit:
            await emit(
                "thinking",
                {
                    "phase": "preflight",
                    "source": "langgraph_react",
                    "title": "整理执行边界",
                    "detail": "正在确认当前问题、范围与可用工具后进入工具循环。",
                    "state": "completed",
                },
            )
        return {}

    async def think(state: LangGraphReactState) -> Dict[str, Any]:
        result = state["result"]
        if emit:
            await emit(
                "thinking",
                {
                    "phase": "planned",
                    "source": "langgraph_react",
                    "title": "判断下一步",
                    "detail": "我正在根据已有观察和工具目录判断是否继续调用工具，还是已经可以回答问题。",
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
            max_steps_limit = state.get("max_steps")
            if max_steps_limit is not None and step_count >= int(max_steps_limit):
                result.status = "failed"
                result.stop_reason = "max_tool_steps_exceeded"
                result.error = f"工具调用步数超过上限 {max_steps_limit}"
                break

            tool_name = str(call.get("name") or "").strip()
            arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
            registered = visible_registry.get(tool_name)
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
            if trace.status == "blocked":
                result.status = "requires_risk_confirmation"
                result.stop_reason = "governance_blocked"
                result.risk_prompt = str(trace.message or tool_result.error or "工具调用需要风险确认")
                result.error = ""
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
                break
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
                    content=_react_tool_result_payload(tool_result),
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

    async def assess(state: LangGraphReactState) -> Dict[str, Any]:
        result = state["result"]
        if emit:
            await emit(
                "thinking",
                {
                    "phase": "assess",
                    "source": "langgraph_react",
                    "title": "检查证据是否足够",
                    "detail": "正在根据刚拿到的工具结果判断证据是否已够用。",
                    "state": "completed" if result.status == "completed" else "active",
                },
            )
        return {"result": result}

    async def finalize(state: LangGraphReactState) -> Dict[str, Any]:
        result = state["result"]
        if emit:
            await emit(
                "thinking",
                {
                    "phase": "answering",
                    "source": "langgraph_react",
                    "title": "进入最终回答",
                    "detail": "工具循环已收敛，正在把证据整理成最终回答。",
                    "state": "active" if result.status == "completed" else "completed",
                },
            )
        if result.status != "completed" and not result.assistant_summary:
            result.assistant_summary = result.error or result.stop_reason or "工具循环未能稳定完成。"
        return {"result": result, "final_message": result.assistant_summary}

    def route_after_preflight(_state: LangGraphReactState) -> str:
        return "think"

    def route_after_think(state: LangGraphReactState) -> str:
        if state["result"].status != "failed" and _tool_calls_from_message(state["messages"][-1]):
            return "act_tools"
        return "finalize"

    def route_after_tools(state: LangGraphReactState) -> str:
        if state["result"].status in {"failed", "requires_risk_confirmation"}:
            return "finalize"
        return "assess"

    def route_after_assess(state: LangGraphReactState) -> str:
        if state["result"].status in {"failed", "requires_risk_confirmation"}:
            return "finalize"
        return "think"

    graph = StateGraph(LangGraphReactState)
    graph.add_node("preflight", preflight)
    graph.add_node("think", think)
    graph.add_node("act_tools", act_tools)
    graph.add_node("assess", assess)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("preflight")
    graph.add_conditional_edges("preflight", route_after_preflight, {"think": "think"})
    graph.add_conditional_edges("think", route_after_think, {"act_tools": "act_tools", "finalize": "finalize"})
    graph.add_conditional_edges("act_tools", route_after_tools, {"assess": "assess", "finalize": "finalize"})
    graph.add_conditional_edges("assess", route_after_assess, {"think": "think", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    app = graph.compile()

    result = ToolLoopResult(status="completed", artifacts=dict(initial_artifacts or {}))
    initial_messages = [
        SystemMessage(content=loop_system_prompt()),
        HumanMessage(content=_safe_json(_initial_payload(question=question, snapshot=snapshot, context=context_bundle, registry=visible_registry, artifacts=initial_artifacts))),
    ]
    final_state = await app.ainvoke(
        {
            "messages": initial_messages,
            "snapshot": snapshot,
            "context": context_bundle,
            "registry": visible_registry,
            "question": question,
            "governance_mode": governance_mode,
            "confirmed_tools": list(confirmed_tools or []),
            "max_steps": max_steps,
            "max_errors": max_errors,
            "step_count": 0,
            "consecutive_errors": 0,
            "result": result,
            "initial_artifacts": dict(initial_artifacts or {}),
        },
        {"recursion_limit": max(100, (max_steps or 32) * 3 + 4)},
    )
    return final_state.get("result") or result
