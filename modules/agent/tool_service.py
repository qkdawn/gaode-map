from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from store.history_repo import HistoryRepo

from .executor import execute_plan_step
from .schemas import AgentToolSummary, AnalysisSnapshot, ExecutionTraceItem, PlanStep, ToolResult
from .tools import RegisteredTool, get_tool_registry

EXTERNAL_TOOL_NAMES = {
    "read_current_scope",
    "fetch_pois_in_scope",
    "build_h3_grid_from_scope",
    "compute_h3_metrics_from_scope_and_pois",
    "compute_road_syntax_from_scope",
    "get_area_data_bundle",
}

logger = logging.getLogger(__name__)


class ExternalToolRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    arguments: Dict[str, Any] = Field(default_factory=dict)
    analysis_snapshot: AnalysisSnapshot = Field(default_factory=AnalysisSnapshot)
    history_id: str = ""
    question: str = ""


@dataclass(frozen=True)
class ToolExecution:
    registered_tool: RegisteredTool
    result: ToolResult
    trace: ExecutionTraceItem


def summarize_registered_tool(name: str, registered: RegisteredTool) -> AgentToolSummary:
    spec = registered.spec
    return AgentToolSummary(
        name=name,
        description=spec.description,
        category=spec.category,
        layer=spec.layer,
        ui_tier=spec.ui_tier,
        data_domain=spec.data_domain,
        capability_type=spec.capability_type,
        scene_type=spec.scene_type,
        llm_exposure=spec.llm_exposure,
        toolkit_id=spec.toolkit_id,
        default_policy_key=spec.default_policy_key,
        evidence_contract=list(spec.evidence_contract or []),
        applicable_scenarios=list(spec.applicable_scenarios or []),
        cautions=list(spec.cautions or []),
        requires=list(spec.requires or []),
        produces=list(spec.produces or []),
        input_schema=dict(spec.input_schema or {}),
        output_schema=dict(spec.output_schema or {}),
        readonly=bool(spec.readonly),
        cost_level=spec.cost_level,
        risk_level=spec.risk_level,
        timeout_sec=int(spec.timeout_sec or 0),
        cacheable=bool(spec.cacheable),
    )


def list_external_tools() -> List[AgentToolSummary]:
    registry = get_tool_registry()
    return [
        summarize_registered_tool(name, registered)
        for name, registered in registry.items()
        if name in EXTERNAL_TOOL_NAMES
    ]


def list_agent_tools() -> List[AgentToolSummary]:
    return [
        summarize_registered_tool(name, registered)
        for name, registered in get_tool_registry().items()
    ]


def _snapshot_from_history_detail(detail: Dict[str, Any]) -> AnalysisSnapshot:
    params = detail.get("params") if isinstance(detail.get("params"), dict) else {}
    polygon = detail.get("polygon")
    scope: Dict[str, Any] = {}
    if isinstance(polygon, list) and polygon:
        scope["polygon"] = polygon
    if isinstance(params.get("drawn_polygon"), list) and params.get("drawn_polygon"):
        scope["drawn_polygon"] = params.get("drawn_polygon")
    return AnalysisSnapshot(
        context=dict(params or {}),
        scope=scope,
        pois=list(detail.get("pois") or []),
        poi_summary=dict(detail.get("poi_summary") or {}),
        current_filters={
            "poi_source": params.get("source"),
            "year": params.get("year"),
            "years": params.get("years") or [],
        },
    )


def _merge_snapshots(base: AnalysisSnapshot, overlay: AnalysisSnapshot) -> AnalysisSnapshot:
    base_payload = base.model_dump(mode="python")
    overlay_payload = overlay.model_dump(mode="python")
    for key, value in overlay_payload.items():
        if isinstance(value, dict):
            base_payload[key] = {**dict(base_payload.get(key) or {}), **value}
        elif isinstance(value, list):
            if value:
                base_payload[key] = value
        elif value not in (None, ""):
            base_payload[key] = value
    return AnalysisSnapshot(**base_payload)


def resolve_tool_snapshot(
    request: ExternalToolRunRequest,
    *,
    history_repo: Optional[HistoryRepo] = None,
) -> AnalysisSnapshot:
    snapshot = request.analysis_snapshot or AnalysisSnapshot()
    history_id = str(request.history_id or "").strip()
    if not history_id:
        return snapshot
    repo = history_repo or HistoryRepo()
    detail = repo.get_detail(history_id, include_pois=True)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="history_not_found")
    return _merge_snapshots(_snapshot_from_history_detail(detail), snapshot)


async def run_registered_tool(
    *,
    step: PlanStep,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    question: str,
    registry: Optional[Dict[str, RegisteredTool]] = None,
    run_preflight: bool = True,
    caller: str = "internal",
) -> ToolExecution:
    started_at = time.perf_counter()
    tool_registry = registry or get_tool_registry()
    tool_name = str(step.tool_name or "").strip()
    registered = tool_registry.get(tool_name)
    if registered is None:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.warning(
            "agent_tool_call caller=%s tool=%s status=unknown elapsed_ms=%.2f",
            caller,
            tool_name,
            elapsed_ms,
        )
        raise KeyError(tool_name)
    try:
        result, trace = await execute_plan_step(
            registered_tool=registered,
            step=step,
            snapshot=snapshot,
            artifacts=artifacts,
            question=question,
            run_preflight=run_preflight,
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info(
            "agent_tool_call caller=%s tool=%s status=%s elapsed_ms=%.2f warnings=%d error=%s cost=%s risk=%s",
            caller,
            tool_name,
            result.status,
            elapsed_ms,
            len(result.warnings or []),
            result.error or "",
            registered.spec.cost_level,
            registered.spec.risk_level,
        )
        return ToolExecution(registered_tool=registered, result=result, trace=trace)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.exception(
            "agent_tool_call caller=%s tool=%s status=exception elapsed_ms=%.2f cost=%s risk=%s",
            caller,
            tool_name,
            elapsed_ms,
            registered.spec.cost_level,
            registered.spec.risk_level,
        )
        raise


async def run_external_tool(
    tool_name: str,
    request: ExternalToolRunRequest,
    *,
    history_repo: Optional[HistoryRepo] = None,
) -> ToolResult:
    name = str(tool_name or "").strip()
    if name not in EXTERNAL_TOOL_NAMES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    registry = get_tool_registry()
    registered = registry.get(name)
    if registered is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool_not_found")
    snapshot = resolve_tool_snapshot(request, history_repo=history_repo)
    execution = await run_registered_tool(
        step=PlanStep(
            tool_name=name,
            arguments=dict(request.arguments or {}),
            reason="external_tool_api",
            expected_artifacts=list(registered.spec.produces or []),
        ),
        snapshot=snapshot,
        artifacts={},
        question=str(request.question or ""),
        registry=registry,
        run_preflight=False,
        caller="external",
    )
    return execution.result
