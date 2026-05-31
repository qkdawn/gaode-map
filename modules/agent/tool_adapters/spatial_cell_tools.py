from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from modules.road.core import analyze_road_syntax
from modules.spatial_cells.service import build_unified_spatial_cells

from ..schemas import AnalysisSnapshot, ToolResult
from .scope_tools import extract_scope_polygon


def _road_features_from_artifacts(artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    current = artifacts.get("current_road") if isinstance(artifacts.get("current_road"), dict) else {}
    roads = current.get("roads") if isinstance(current.get("roads"), dict) else {}
    features = roads.get("features") if isinstance(roads.get("features"), list) else []
    return [feature for feature in features if isinstance(feature, dict)]


async def _compute_road_features(
    *,
    polygon: list,
    coord_type: str,
    mode: str,
) -> List[Dict[str, Any]]:
    result = await asyncio.to_thread(
        analyze_road_syntax,
        polygon=polygon,
        coord_type=coord_type,
        mode=mode,
        graph_model="segment",
        highway_filter="all",
        include_geojson=True,
        max_edge_features=None,
        radii_m=None,
        metric="choice",
        tulip_bins=None,
        merge_geojson_edges=False,
        merge_bucket_step=0.025,
        use_arcgis_webgl=False,
        arcgis_timeout_sec=60,
        arcgis_metric_field=None,
    )
    roads = result.get("roads") if isinstance(result.get("roads"), dict) else {}
    features = roads.get("features") if isinstance(roads.get("features"), list) else []
    return [feature for feature in features if isinstance(feature, dict)]


async def build_unified_spatial_cells_tool(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    local_artifacts = dict(artifacts or {})
    polygon = local_artifacts.get("scope_polygon") or extract_scope_polygon(snapshot)
    if not polygon:
        return ToolResult(
            tool_name="build_unified_spatial_cells",
            status="failed",
            warnings=["缺少分析范围，无法构建统一空间结构"],
            error="missing_scope_polygon",
        )

    coord_type = str(arguments.get("coord_type") or "gcj02")
    population_year = str(arguments.get("population_year") or "2026")
    raw_nightlight_year = arguments.get("nightlight_year")
    try:
        nightlight_year = int(raw_nightlight_year) if raw_nightlight_year not in (None, "") else None
    except (TypeError, ValueError):
        nightlight_year = None
    poi_coord_type = str(arguments.get("poi_coord_type") or "gcj02")
    road_mode = str(arguments.get("road_mode") or snapshot.context.get("mode") or "walking")

    road_features = _road_features_from_artifacts(local_artifacts)
    road_source = "reused_current_road_features" if road_features else "computed_for_unified_cells"
    if not road_features:
        road_features = await _compute_road_features(polygon=polygon, coord_type=coord_type, mode=road_mode)

    pois = list(local_artifacts.get("current_pois") or snapshot.pois or [])
    payload = await asyncio.to_thread(
        build_unified_spatial_cells,
        polygon=polygon,
        coord_type=coord_type,
        population_year=population_year,
        nightlight_year=nightlight_year,
        pois=pois,
        poi_coord_type=poi_coord_type,
        road_features=road_features,
    )
    summary = dict(payload.get("summary") or {})
    return ToolResult(
        tool_name="build_unified_spatial_cells",
        status="success",
        result={
            "grid_type": payload.get("grid_type"),
            "cell_id_source": payload.get("cell_id_source"),
            "cell_count": int(summary.get("cell_count") or payload.get("cell_count") or 0),
            "active_poi_cell_count": int(summary.get("active_poi_cell_count") or 0),
            "lit_cell_count": int(summary.get("lit_cell_count") or 0),
            "road_covered_cell_count": int(summary.get("road_covered_cell_count") or 0),
            "road_source": road_source,
        },
        evidence=[
            {"field": "unified_spatial_cells.cell_id_source", "value": payload.get("cell_id_source")},
            {"field": "unified_spatial_cells.summary.cell_count", "value": int(summary.get("cell_count") or 0)},
            {"field": "unified_spatial_cells.summary.active_poi_cell_count", "value": int(summary.get("active_poi_cell_count") or 0)},
            {"field": "unified_spatial_cells.summary.lit_cell_count", "value": int(summary.get("lit_cell_count") or 0)},
            {"field": "unified_spatial_cells.summary.road_covered_cell_count", "value": int(summary.get("road_covered_cell_count") or 0)},
            {
                "field": "unified_spatial_cells.boundary",
                "value": "空间同格对齐证据只能支持供给、人口、夜光与路网的空间关系判断，不能直接推断客流、消费力、营业额或收益。",
            },
        ],
        artifacts={
            "current_unified_spatial_cells": payload,
            "current_unified_spatial_cells_summary": summary,
        },
    )
