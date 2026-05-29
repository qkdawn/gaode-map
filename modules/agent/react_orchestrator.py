from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from .context_builder import build_context_bundle
from .providers.langgraph_react import run_langgraph_react_loop
from .providers.client import is_llm_enabled
from .providers.llm_provider import run_llm_tool_loop
from .review_contract import build_review_contract
from .schemas import (
    AgentMessage,
    AgentReactEvent,
    AgentReactOptions,
    AgentReactRunRequest,
    AgentReactRunResponse,
    AnalysisSnapshot,
    AuditResult,
)
from .tools import get_tool_registry


REACT_SAFE_TOOL_NAMES = {
    "read_current_scope",
    "read_current_results",
    "search_analysis_context",
    "read_analysis_chunk",
    "search_report_context",
    "read_report_chunk",
    "fetch_pois_in_scope",
    "compute_h3_metrics_from_scope_and_pois",
    "compute_population_overview_from_scope",
    "compute_nightlight_overview_from_scope",
    "compute_road_syntax_from_scope",
    "get_area_data_bundle",
    "analyze_poi_structure",
    "analyze_spatial_structure",
    "infer_area_labels",
    "run_area_character_pack",
    "read_poi_structure_analysis",
    "read_h3_structure_analysis",
    "read_road_pattern_analysis",
    "read_population_profile_analysis",
    "read_nightlight_pattern_analysis",
    "analyze_poi_mix_from_scope",
    "detect_commercial_hotspots",
    "analyze_target_supply_gap",
}
REACT_TOOL_LABELS = {
    "read_current_scope": "读取当前分析范围",
    "read_current_results": "读取已有分析结果",
    "search_analysis_context": "搜索分析上下文",
    "read_analysis_chunk": "读取分析证据块",
    "search_report_context": "搜索报告上下文",
    "read_report_chunk": "读取报告证据块",
    "fetch_pois_in_scope": "抓取范围内 POI",
    "compute_h3_metrics_from_scope_and_pois": "计算 POI H3 网格指标",
    "compute_population_overview_from_scope": "计算人口概览",
    "compute_nightlight_overview_from_scope": "计算夜光活力",
    "compute_road_syntax_from_scope": "计算路网句法",
    "get_area_data_bundle": "汇总区域数据包",
    "analyze_poi_structure": "分析 POI 结构",
    "analyze_spatial_structure": "分析空间结构",
    "infer_area_labels": "推断区域标签",
    "run_area_character_pack": "生成区域画像",
    "read_poi_structure_analysis": "读取 POI 结构分析",
    "read_h3_structure_analysis": "读取 H3 结构分析",
    "read_road_pattern_analysis": "读取路网模式分析",
    "read_population_profile_analysis": "读取人口画像分析",
    "read_nightlight_pattern_analysis": "读取夜光模式分析",
    "analyze_poi_mix_from_scope": "分析业态混合",
    "detect_commercial_hotspots": "识别商业热点",
    "analyze_target_supply_gap": "分析目标业态供需缺口",
}
DEFAULT_MAX_STEPS = 8
DEFAULT_STAGNATION_LIMIT = 2
DEFAULT_TOOL_TIMEOUT_SECONDS = 20
DEFAULT_MAX_TOOL_FAILURES = 2
MAX_ALLOWED_STEPS = 12
MAX_ALLOWED_TOOL_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ReactConfig:
    max_steps: int = DEFAULT_MAX_STEPS
    stagnation_limit: int = DEFAULT_STAGNATION_LIMIT
    tool_timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS
    max_tool_failures: int = DEFAULT_MAX_TOOL_FAILURES


@dataclass
class ReactRun:
    run_id: str
    request: AgentReactRunRequest
    config: ReactConfig
    queue: asyncio.Queue[Optional[AgentReactEvent]]
    task: Optional[asyncio.Task[None]] = None
    cancelled: bool = False


_RUNS: Dict[str, ReactRun] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_int(value: Optional[int], default: int, *, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _build_config(options: AgentReactOptions) -> ReactConfig:
    return ReactConfig(
        max_steps=_clamp_int(options.max_steps, DEFAULT_MAX_STEPS, minimum=1, maximum=MAX_ALLOWED_STEPS),
        stagnation_limit=_clamp_int(options.stagnation_limit, DEFAULT_STAGNATION_LIMIT, minimum=1, maximum=5),
        tool_timeout_seconds=_clamp_int(
            options.tool_timeout_seconds,
            DEFAULT_TOOL_TIMEOUT_SECONDS,
            minimum=1,
            maximum=MAX_ALLOWED_TOOL_TIMEOUT_SECONDS,
        ),
        max_tool_failures=_clamp_int(options.max_tool_failures, DEFAULT_MAX_TOOL_FAILURES, minimum=1, maximum=5),
    )


def _event(run_id: str, step: int, event_type: str, payload: Dict[str, Any]) -> AgentReactEvent:
    return AgentReactEvent(run_id=run_id, step=step, type=event_type, ts=_utc_now(), payload=payload)


def _merge_scope(snapshot: AnalysisSnapshot, scope: Dict[str, Any]) -> AnalysisSnapshot:
    if not scope:
        return snapshot
    payload = snapshot.model_dump()
    payload["scope"] = {**dict(payload.get("scope") or {}), **dict(scope or {})}
    return AnalysisSnapshot(**payload)


def _latest_user_question(request: AgentReactRunRequest) -> str:
    return str(request.question or "").strip()


def _react_tool_registry() -> Dict[str, Any]:
    registry = get_tool_registry()
    return {name: registered for name, registered in registry.items() if name in REACT_SAFE_TOOL_NAMES}


def _tool_label(tool_name: str) -> str:
    name = str(tool_name or "").strip()
    if not name:
        return "工具"
    return REACT_TOOL_LABELS.get(name, name)


def _trace_action_summary(tool_name: str, payload: Dict[str, Any]) -> str:
    label = _tool_label(tool_name)
    argument_summary = str(payload.get("arguments_summary") or "").strip()
    if argument_summary and argument_summary != "无参数":
        return f"我正在调用「{label}」，参数是：{argument_summary}。"
    return f"我正在调用「{label}」，先拿到这一步需要的证据。"


def _trace_observation_summary(tool_name: str, payload: Dict[str, Any], *, failed: bool = False) -> str:
    label = _tool_label(tool_name)
    result_summary = str(payload.get("result_summary") or payload.get("message") or payload.get("reason") or "").strip()
    if failed:
        return f"「{label}」没有顺利返回可用结果：{result_summary or '工具执行失败'}。"
    if result_summary:
        return f"「{label}」返回了观察结果：{result_summary}。"
    evidence_count = payload.get("evidence_count")
    if evidence_count not in (None, ""):
        return f"「{label}」已返回观察结果，包含 {evidence_count} 条证据。"
    return f"「{label}」已返回观察结果。"


def _format_react_brain_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    raw_detail = ""
    if response is not None:
        try:
            raw_detail = str(getattr(response, "text", "") or "")
        except Exception:
            raw_detail = ""
    if not raw_detail:
        raw_detail = str(getattr(exc, "body", "") or getattr(exc, "message", "") or exc)

    detail = re.sub(r"<[^>]+>", " ", raw_detail)
    detail = " ".join(detail.split())[:240]
    if status_code:
        if int(status_code) == 403:
            return "LLM provider 返回 HTTP 403 Forbidden：上游拒绝访问，请检查 AI_BASE_URL、AI_API_KEY、AI_MODEL，以及服务端 IP 白名单/访问权限。"
        return f"LLM provider 返回 HTTP {status_code}" + (f"：{detail}" if detail else "")
    if "<html" in raw_detail.lower() or "openresty" in raw_detail.lower():
        return "LLM provider 返回了网关错误页面：请检查 AI_BASE_URL 是否指向正确的兼容接口，以及服务端访问权限。"
    return f"LLM provider 调用失败：{type(exc).__name__}" + (f"：{detail}" if detail else "")


def _final_payload(
    question: str,
    observations: List[Dict[str, Any]],
    event_steps: List[int],
    *,
    snapshot: AnalysisSnapshot | None = None,
) -> Dict[str, Any]:
    success = [item for item in observations if item.get("status") == "success"]
    failed = [item for item in observations if item.get("status") != "success"]
    poi = next((item for item in success if item.get("tool") == "fetch_pois_in_scope"), None)
    road = next((item for item in success if item.get("tool") == "compute_road_syntax_from_scope"), None)
    scope = next((item for item in success if item.get("tool") == "read_current_scope"), None)

    conclusion_parts = []
    if scope:
        conclusion_parts.append("当前问题已落到可分析的地图范围。")
    if poi:
        conclusion_parts.append(str(poi.get("summary") or "POI 证据已纳入判断。"))
    if road:
        conclusion_parts.append(str(road.get("summary") or "路网证据已纳入判断。"))
    if not conclusion_parts:
        conclusion_parts.append("当前证据不足，优先补齐等时圈范围和 POI 基础数据。")

    if len(success) >= 3 and not failed:
        evidence_status = "证据较完整"
    elif success:
        evidence_status = "证据可用但仍需补充"
    else:
        evidence_status = "证据不足"

    review_contract = build_review_contract(
        question=question,
        snapshot=snapshot or AnalysisSnapshot(),
        artifacts={},
        tool_results=[],
        audit=AuditResult(passed=bool(success), missing_evidence=[] if success else ["ReAct 工具观察"]),
        decision_summary="；".join(conclusion_parts),
    )
    return {
        "summary": "；".join(conclusion_parts),
        "conclusion": f"针对“{question}”，" + "；".join(conclusion_parts),
        "evidence_status": evidence_status,
        "review_contract": review_contract,
        "evidence_steps": event_steps,
    }


def _llm_final_payload(
    *,
    question: str,
    assistant_summary: str,
    observations: List[Dict[str, Any]],
    event_steps: List[int],
    snapshot: AnalysisSnapshot | None = None,
    error: str = "",
) -> Dict[str, Any]:
    fallback = _final_payload(question, observations, event_steps, snapshot=snapshot)
    conclusion = str(assistant_summary or "").strip() or str(fallback.get("conclusion") or "")
    if error and not assistant_summary:
        conclusion = f"ReAct Brain 未能完成：{error}"
    return {
        **fallback,
        "summary": conclusion,
        "conclusion": conclusion,
        "evidence_steps": list(event_steps or fallback.get("evidence_steps") or []),
        "meta": {
            "mode": "llm_react",
            "error": error,
        },
    }


async def _put(run: ReactRun, step: int, event_type: str, payload: Dict[str, Any]) -> AgentReactEvent:
    event = _event(run.run_id, step, event_type, payload)
    await run.queue.put(event)
    return event


async def _execute_llm_react_run(run: ReactRun, *, question: str, snapshot: AnalysisSnapshot) -> bool:
    if not is_llm_enabled():
        error_message = "LLM provider 未启用或配置不完整，ReAct Brain 无法执行。"
        await _put(run, 0, "error", {"summary": error_message})
        await _put(
            run,
            1,
            "final",
            _llm_final_payload(
                question=question,
                assistant_summary="",
                observations=[],
                event_steps=[],
                snapshot=snapshot,
                error=error_message,
            ),
        )
        return True

    step_no = 0
    observations: List[Dict[str, Any]] = []
    evidence_steps: List[int] = []
    await _put(
        run,
        step_no,
        "status",
        {"summary": "ReAct Brain 已启动", "state": "running", "meta": {"mode": "llm_react"}},
    )

    async def emit(source_type: str, payload: Dict[str, Any]) -> None:
        nonlocal step_no
        if run.cancelled:
            return
        if source_type == "reasoning_delta":
            return
        if source_type == "thinking":
            phase = str(payload.get("phase") or "")
            title = str(payload.get("title") or "").strip()
            if phase == "executing" and title.startswith("准备调用"):
                return
            step_no += 1
            await _put(
                run,
                step_no,
                "thought",
                {
                    "summary": str(payload.get("detail") or title or "正在判断下一步行动。"),
                    "meta": {"source": str(payload.get("source") or "react_brain"), "phase": phase},
                },
            )
            return
        if source_type != "trace":
            return

        status = str(payload.get("status") or "").strip()
        tool_name = str(payload.get("tool_name") or "").strip()
        summary = str(payload.get("message") or payload.get("result_summary") or payload.get("reason") or "").strip()
        if status in {"start", "blocked"}:
            step_no += 1
            label = _tool_label(tool_name)
            await _put(
                run,
                step_no,
                "action" if status == "start" else "error",
                {
                    "summary": _trace_action_summary(tool_name, payload) if status == "start" else (summary or f"「{label}」被安全策略拦截。"),
                    "raw": {
                        "tool": tool_name,
                        "tool_label": label,
                        "arguments_summary": payload.get("arguments_summary"),
                    },
                    "meta": {"tool": tool_name, "tool_label": label, "status": status},
                },
            )
            return

        step_no += 1
        event_type = "observation" if status in {"success", "skipped"} else "error"
        label = _tool_label(tool_name)
        event = await _put(
            run,
            step_no,
            event_type,
            {
                "summary": _trace_observation_summary(tool_name, payload, failed=event_type == "error"),
                "raw": {
                    "tool": tool_name,
                    "tool_label": label,
                    "result_summary": payload.get("result_summary"),
                    "warning_count": payload.get("warning_count"),
                    "evidence_count": payload.get("evidence_count"),
                },
                "meta": {"tool": tool_name, "tool_label": label, "status": status},
                "quality": "usable" if event_type == "observation" else "limited",
            },
        )
        observations.append(
            {
                "tool": tool_name,
                "status": "success" if event_type == "observation" else "failed",
                "summary": summary,
                "step": event.step,
            }
        )
        if event_type == "observation":
            evidence_steps.append(event.step)

    try:
        try:
            result = await run_langgraph_react_loop(
                messages=[AgentMessage(role="user", content=question)],
                snapshot=snapshot,
                context=build_context_bundle(snapshot),
                registry=_react_tool_registry(),
                governance_mode="auto",
                emit=emit,
                include_secondary_tools=True,
                max_steps_override=run.config.max_steps,
                max_errors_override=run.config.max_tool_failures,
            )
        except ImportError:
            result = await run_llm_tool_loop(
                messages=[AgentMessage(role="user", content=question)],
                snapshot=snapshot,
                context=build_context_bundle(snapshot),
                registry=_react_tool_registry(),
                governance_mode="auto",
                emit=emit,
                include_secondary_tools=True,
                max_steps_override=run.config.max_steps,
                max_errors_override=run.config.max_tool_failures,
            )
    except Exception as exc:
        error_message = _format_react_brain_error(exc)
        await _put(run, step_no + 1, "error", {"summary": f"ReAct Brain 执行失败：{error_message}"})
        await _put(
            run,
            step_no + 2,
            "final",
            _llm_final_payload(question=question, assistant_summary="", observations=observations, event_steps=evidence_steps, snapshot=snapshot, error=error_message),
        )
        return True

    if result.status != "completed":
        await _put(
            run,
            step_no + 1,
            "error",
            {"summary": result.error or result.risk_prompt or result.stop_reason or "ReAct Brain 未完成"},
        )
    await _put(
        run,
        step_no + 2,
        "final",
        _llm_final_payload(
            question=question,
            assistant_summary=result.assistant_summary,
            observations=observations,
            event_steps=evidence_steps,
            error=result.error,
            snapshot=snapshot,
        ),
    )
    return True


async def _execute_react_run(run: ReactRun) -> None:
    question = _latest_user_question(run.request)
    snapshot = _merge_scope(run.request.analysis_snapshot, run.request.scope)
    try:
        await _execute_llm_react_run(run, question=question, snapshot=snapshot)
    finally:
        await run.queue.put(None)


async def create_react_run(request: AgentReactRunRequest) -> AgentReactRunResponse:
    question = _latest_user_question(request)
    if not question:
        raise ValueError("question_required")
    run_id = uuid4().hex
    run = ReactRun(
        run_id=run_id,
        request=request,
        config=_build_config(request.options),
        queue=asyncio.Queue(),
    )
    _RUNS[run_id] = run
    run.task = asyncio.create_task(_execute_react_run(run))
    return AgentReactRunResponse(run_id=run_id)


async def stream_react_run(run_id: str) -> AsyncIterator[AgentReactEvent]:
    run = _RUNS.get(str(run_id or "").strip())
    if not run:
        raise KeyError("run_not_found")
    try:
        while True:
            event = await run.queue.get()
            if event is None:
                break
            yield event
    finally:
        if run.task and run.task.done():
            _RUNS.pop(run.run_id, None)


def cancel_react_run(run_id: str) -> bool:
    run = _RUNS.get(str(run_id or "").strip())
    if not run:
        return False
    run.cancelled = True
    if run.task and not run.task.done():
        run.task.cancel()
    _RUNS.pop(run.run_id, None)
    return True
