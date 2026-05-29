from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from modules.h3.analysis import analyze_h3_grid
from modules.h3.core import build_h3_grid_feature_collection

from ..schemas import AnalysisSnapshot, ToolResult


async def build_h3_grid_from_scope(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    polygon = artifacts.get("scope_polygon") or []
    if not polygon:
        return ToolResult(
            tool_name="build_h3_grid_from_scope",
            status="failed",
            warnings=["缺少分析范围，无法生成 H3 网格"],
            error="missing_scope_polygon",
        )
    resolution = int(arguments.get("resolution") or snapshot.current_filters.get("h3_resolution") or 10)
    include_mode = str(arguments.get("include_mode") or "intersects")
    grid = await asyncio.to_thread(
        build_h3_grid_feature_collection,
        polygon,
        resolution,
        "gcj02",
        include_mode,
        0.0,
    )
    return ToolResult(
        tool_name="build_h3_grid_from_scope",
        status="success",
        result={"grid_count": int(grid.get("count") or 0), "resolution": resolution},
        evidence=[{"field": "h3.grid_count", "value": int(grid.get("count") or 0)}],
        warnings=[] if int(grid.get("count") or 0) > 0 else ["当前范围未生成可用 H3 网格"],
        artifacts={"current_h3_base_grid": grid},
    )


async def compute_h3_metrics_from_scope_and_pois(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    polygon = artifacts.get("scope_polygon") or []
    pois: List[Dict[str, Any]] = list(artifacts.get("current_pois") or snapshot.pois or [])
    if not polygon:
        return ToolResult(
            tool_name="compute_h3_metrics_from_scope_and_pois",
            status="failed",
            warnings=["缺少分析范围，无法计算 H3 指标"],
            error="missing_scope_polygon",
        )
    result = await asyncio.to_thread(
        analyze_h3_grid,
        polygon=polygon,
        resolution=int(arguments.get("resolution") or snapshot.current_filters.get("h3_resolution") or 10),
        coord_type="gcj02",
        include_mode=str(arguments.get("include_mode") or "intersects"),
        min_overlap_ratio=float(arguments.get("min_overlap_ratio") or 0.0),
        pois=pois,
        poi_coord_type="gcj02",
        neighbor_ring=int(arguments.get("neighbor_ring") or 1),
        use_arcgis=False,
        arcgis_neighbor_ring=1,
        arcgis_knn_neighbors=None,
        arcgis_export_image=False,
        arcgis_timeout_sec=240,
    )
    summary = result.get("summary") or {}
    return ToolResult(
        tool_name="compute_h3_metrics_from_scope_and_pois",
        status="success",
        result={
            "grid_count": int(summary.get("grid_count") or 0),
            "poi_count": int(summary.get("poi_count") or 0),
        },
        evidence=[
            {"field": "h3.summary.grid_count", "value": int(summary.get("grid_count") or 0)},
            {"field": "h3.summary.poi_count", "value": int(summary.get("poi_count") or 0)},
            {"field": "h3.summary.avg_density_poi_per_km2", "value": summary.get("avg_density_poi_per_km2")},
        ],
        artifacts={
            "current_poi_h3": result,
            "current_poi_h3_grid": result.get("grid") or {},
            "current_poi_h3_summary": summary,
            "current_poi_h3_charts": result.get("charts") or {},
        },
    )
