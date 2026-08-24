from __future__ import annotations

from typing import Any, Dict

from ..schemas import AnalysisSnapshot, ToolResult


async def read_persisted_road_syntax(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    result = artifacts.get("current_road")
    if not isinstance(result, dict) or not result:
        result = snapshot.road if isinstance(snapshot.road, dict) else {}
    summary = artifacts.get("current_road_summary")
    if not isinstance(summary, dict) or not summary:
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if not result or not summary:
        return ToolResult(
            tool_name="read_persisted_road_syntax",
            status="failed",
            warnings=["当前分析尚未持久化路网句法结果；请先完成正式路网分析任务。"],
            error="road_analysis_not_persisted",
        )
    return ToolResult(
        tool_name="read_persisted_road_syntax",
        status="success",
        result={
            "node_count": int(summary.get("node_count") or 0),
            "edge_count": int(summary.get("edge_count") or 0),
        },
        evidence=[
            {"field": "road.summary.node_count", "value": int(summary.get("node_count") or 0)},
            {"field": "road.summary.edge_count", "value": int(summary.get("edge_count") or 0)},
            {"field": "road.summary.avg_choice", "value": summary.get("avg_choice")},
        ],
        artifacts={
            "current_road": result,
            "current_road_summary": summary,
        },
        warnings=["已复用当前持久化路网句法结果，未重新运行 depthmapX。"],
    )
