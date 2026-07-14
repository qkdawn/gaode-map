from __future__ import annotations

import csv
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from shapely.geometry import LineString
from shapely.prepared import prep

from core.config import settings
from .depthmap import (
    resolve_depthmap_cli_path,
    run_depthmap_axial_pipeline,
    run_depthmap_cmd,
    run_depthmap_segment_pipeline,
    write_depthmap_lines_csv,
)
from .geometry import coords_to_wgs84_polygon, haversine_m, safe_round
from .overpass import (
    build_overpass_query,
    build_radius_arg,
    fetch_overpass_elements,
    normalize_label,
)
from .serialize import build_road_analysis_result, empty_result
from .grid import build_road_grid
from modules.population.service import get_population_grid

OverpassMode = Literal["walking", "bicycling", "driving"]
GraphModel = Literal["segment", "axial"]
HighwayFilter = Literal["mode", "all", "major"]

logger = logging.getLogger(__name__)

MAJOR_HIGHWAY_PRIORITY: Dict[str, int] = {
    "motorway": 0,
    "motorway_link": 1,
    "trunk": 2,
    "trunk_link": 3,
    "primary": 4,
    "primary_link": 5,
    "secondary": 6,
    "secondary_link": 7,
}

# Compatibility aliases for existing tests and patch points.
_coords_to_wgs84_polygon = coords_to_wgs84_polygon
_haversine_m = haversine_m
_safe_round = safe_round
_build_overpass_query = build_overpass_query
_build_radius_arg = build_radius_arg
_fetch_overpass_elements = fetch_overpass_elements
_normalize_label = normalize_label
_resolve_depthmap_cli_path = resolve_depthmap_cli_path
_run_depthmap_cmd = run_depthmap_cmd
_write_depthmap_lines_csv = write_depthmap_lines_csv
_run_depthmap_segment_pipeline = run_depthmap_segment_pipeline
_run_depthmap_axial_pipeline = run_depthmap_axial_pipeline
_empty_result = empty_result


def _major_edge_priority(highway: str) -> int:
    key = str(highway or "").strip().lower()
    return int(MAJOR_HIGHWAY_PRIORITY.get(key, 99))


def _prune_major_edges_for_global(edge_inputs: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    if cap <= 0 or len(edge_inputs) <= cap:
        return edge_inputs
    ranked = sorted(
        edge_inputs,
        key=lambda edge: (
            _major_edge_priority(str(edge.get("highway") or "")),
            -float(edge.get("length_m") or 0.0),
            int(edge.get("ref") or 0),
        ),
    )
    selected = [dict(item) for item in ranked[:cap]]
    selected.sort(key=lambda edge: int(edge.get("ref") or 0))
    for idx, item in enumerate(selected, start=1):
        item["ref"] = idx
    return selected


def analyze_road_syntax(
    polygon: list,
    coord_type: Literal["gcj02", "wgs84"] = "gcj02",
    mode: OverpassMode = "walking",
    graph_model: GraphModel = "segment",
    highway_filter: HighwayFilter = "all",
    include_geojson: bool = True,
    max_edge_features: Optional[int] = None,
    radii_m: Optional[List[int]] = None,
    metric: Literal["choice", "integration"] = "choice",
    tulip_bins: Optional[int] = None,
    merge_geojson_edges: bool = True,
    merge_bucket_step: float = 0.025,
    use_arcgis_webgl: bool = False,
    arcgis_timeout_sec: int = 300,
    arcgis_metric_field: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    normalized_graph_model = "axial" if str(graph_model or "").strip().lower() == "axial" else "segment"
    analysis_engine_label = "depthmapxcli-axial" if normalized_graph_model == "axial" else "depthmapxcli"
    total_steps = 9

    def _report_progress(
        stage: str,
        message: str,
        step: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if progress_callback is None:
            return
        payload: Dict[str, Any] = {
            "stage": str(stage or ""),
            "message": str(message or ""),
            "step": int(step) if step is not None else None,
            "total": total_steps,
            "elapsed_ms": safe_round((time.perf_counter() - started_at) * 1000.0, 2),
            "extra": dict(extra or {}),
        }
        try:
            progress_callback(payload)
        except Exception:
            pass

    _report_progress("init", "准备路网句法计算", step=1)
    base_radii = [600, 800] if radii_m is None else list(radii_m)
    local_radii = sorted({int(value) for value in base_radii if int(value) > 0})[:5]
    requested_local_labels = [normalize_label(value) for value in local_radii]
    render_metric = "integration" if metric == "integration" else "choice"

    output_wgs_poly = _coords_to_wgs84_polygon(polygon, coord_type=coord_type)
    if output_wgs_poly.is_empty:
        return _empty_result(
            mode,
            coord_type="gcj02",
            radii_m=local_radii,
            metric=render_metric,
            analysis_engine=analysis_engine_label,
            webgl_status="disabled:invalid_output_polygon",
        )
    context_wgs_poly = _coords_to_wgs84_polygon(polygon, coord_type=coord_type)
    if context_wgs_poly.is_empty:
        context_wgs_poly = output_wgs_poly

    minx, miny, maxx, maxy = context_wgs_poly.bounds
    overpass_query_timeout_s = int(getattr(settings, "overpass_query_timeout_s", 60) or 60)
    query = _build_overpass_query(
        (miny, minx, maxy, maxx),
        mode=mode,
        highway_filter=highway_filter,
        query_timeout_s=overpass_query_timeout_s,
    )

    _report_progress("overpass_request", "正在抓取等时圈范围路网", step=2)
    elements = _fetch_overpass_elements(query)
    _report_progress(
        "overpass_received",
        "路网数据已返回，正在解析",
        step=2,
        extra={"element_count": len(elements)},
    )

    node_coords: Dict[int, tuple[float, float]] = {}
    ways: List[Dict[str, Any]] = []
    for elem in elements:
        elem_type = elem.get("type")
        if elem_type == "node":
            try:
                node_id = int(elem.get("id"))
                lon = float(elem.get("lon"))
                lat = float(elem.get("lat"))
            except (TypeError, ValueError):
                continue
            node_coords[node_id] = (lon, lat)
            continue
        if elem_type == "way":
            if not elem.get("tags", {}).get("highway"):
                continue
            node_ids = elem.get("nodes") or []
            geom = elem.get("geometry") or []
            if len(node_ids) < 2 and len(geom) < 2:
                continue
            ways.append(elem)

    if not ways:
        return _empty_result(
            mode,
            coord_type="gcj02",
            radii_m=local_radii,
            metric=render_metric,
            analysis_engine=analysis_engine_label,
            webgl_status="disabled:no_ways_in_context",
        )

    _report_progress("build_edges", "正在构建线段拓扑", step=3)
    prepared_context = prep(context_wgs_poly)
    seen_edges = set()
    edge_inputs: List[Dict[str, Any]] = []

    def _edge_key_by_coord(
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        a = (safe_round(lon1, 7), safe_round(lat1, 7))
        b = (safe_round(lon2, 7), safe_round(lat2, 7))
        return (a, b) if a <= b else (b, a)

    for way in ways:
        tags = way.get("tags") or {}
        highway = str(tags.get("highway") or "")
        node_ids = way.get("nodes") or []
        used_node_segments = False
        if node_ids and node_coords:
            for u_raw, v_raw in zip(node_ids, node_ids[1:]):
                try:
                    u = int(u_raw)
                    v = int(v_raw)
                except (TypeError, ValueError):
                    continue
                if u == v or u not in node_coords or v not in node_coords:
                    continue
                used_node_segments = True
                lon1, lat1 = node_coords[u]
                lon2, lat2 = node_coords[v]
                line = LineString([(lon1, lat1), (lon2, lat2)])
                if line.is_empty or not prepared_context.intersects(line):
                    continue
                edge_key = _edge_key_by_coord(lon1, lat1, lon2, lat2)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                length_m = _haversine_m(lon1, lat1, lon2, lat2)
                if length_m <= 0:
                    continue
                edge_inputs.append(
                    {
                        "ref": len(edge_inputs) + 1,
                        "x1": lon1,
                        "y1": lat1,
                        "x2": lon2,
                        "y2": lat2,
                        "highway": highway,
                        "length_m": length_m,
                    }
                )

        if used_node_segments:
            continue

        coords: List[tuple[float, float]] = []
        for pt in (way.get("geometry") or []):
            if not isinstance(pt, dict):
                continue
            try:
                lon = float(pt.get("lon"))
                lat = float(pt.get("lat"))
            except (TypeError, ValueError):
                continue
            coords.append((lon, lat))
        if len(coords) < 2:
            continue

        for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
            if lon1 == lon2 and lat1 == lat2:
                continue
            line = LineString([(lon1, lat1), (lon2, lat2)])
            if line.is_empty or not prepared_context.intersects(line):
                continue
            edge_key = _edge_key_by_coord(lon1, lat1, lon2, lat2)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            length_m = _haversine_m(lon1, lat1, lon2, lat2)
            if length_m <= 0:
                continue
            edge_inputs.append(
                {
                    "ref": len(edge_inputs) + 1,
                    "x1": lon1,
                    "y1": lat1,
                    "x2": lon2,
                    "y2": lat2,
                    "highway": highway,
                    "length_m": length_m,
                }
            )

    if not edge_inputs:
        return _empty_result(
            mode,
            coord_type="gcj02",
            radii_m=local_radii,
            metric=render_metric,
            analysis_engine=analysis_engine_label,
            webgl_status="disabled:no_edge_inputs",
        )

    _report_progress(
        "edges_ready",
        "输入线段构建完成，正在准备分析",
        step=4,
        extra={"context_edge_count": len(edge_inputs)},
    )

    if normalized_graph_model != "axial" and highway_filter == "major":
        raw_count = len(edge_inputs)
        global_edge_cap = int(getattr(settings, "road_syntax_global_edge_cap", 22000) or 22000)
        global_edge_cap = max(1000, global_edge_cap)
        if raw_count > global_edge_cap:
            edge_inputs = _prune_major_edges_for_global(edge_inputs, global_edge_cap)
            logger.info(
                "[road-syntax] major global edge prune applied raw=%d pruned=%d cap=%d",
                raw_count,
                len(edge_inputs),
                global_edge_cap,
            )

    _report_progress(
        "edges_filtered",
        "路网筛选完成，准备运行分析引擎",
        step=4,
        extra={"context_edge_count": len(edge_inputs)},
    )

    cli_path = _resolve_depthmap_cli_path()
    timeout_s = int(getattr(settings, "depthmapx_timeout_s", 300) or 300)
    tulip_bins_value = int(getattr(settings, "depthmapx_tulip_bins", 1024) or 1024) if tulip_bins is None else int(tulip_bins)
    tulip_bins_value = max(4, min(1024, tulip_bins_value))
    rows: List[Dict[str, Any]] = []
    fieldnames: List[str] = []

    with tempfile.TemporaryDirectory(prefix="road_syntax_depthmapx_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        lines_csv = tmpdir / "input_lines.csv"
        graph_imported = tmpdir / "01_import.graph"
        graph_analysed = tmpdir / "03_analysed.graph"
        result_csv = tmpdir / "04_shapegraph_map.csv"

        _write_depthmap_lines_csv(lines_csv, edge_inputs)

        _report_progress("depthmap_import", "正在导入 depthmapX 图", step=5)
        _run_depthmap_cmd(
            cli_path,
            ["-m", "IMPORT", "-f", str(lines_csv), "-o", str(graph_imported), "-it", "drawing"],
            tmpdir,
            timeout_s,
        )

        if normalized_graph_model == "axial":
            _report_progress("axial_compute", "正在执行轴线计算", step=6)
            try:
                _run_depthmap_axial_pipeline(
                    cli_path=cli_path,
                    tmpdir=tmpdir,
                    graph_imported=graph_imported,
                    graph_analysed=graph_analysed,
                    timeout_s=timeout_s,
                    local_radii=local_radii,
                    build_radius_arg=_build_radius_arg,
                    run_cmd=_run_depthmap_cmd,
                )
            except RuntimeError as exc:
                logger.exception("[road-syntax] axial pipeline failed")
                raise RuntimeError(
                    "轴线图计算失败：当前数据在轴线流程中未能完成，请改用线段图或缩小范围后重试。"
                ) from exc
        else:
            _report_progress("segment_compute", "正在执行线段计算", step=6)
            _run_depthmap_segment_pipeline(
                cli_path=cli_path,
                tmpdir=tmpdir,
                graph_imported=graph_imported,
                graph_analysed=graph_analysed,
                timeout_s=timeout_s,
                tulip_bins_value=tulip_bins_value,
                local_radii=local_radii,
                build_radius_arg=_build_radius_arg,
                run_cmd=_run_depthmap_cmd,
            )

        _report_progress("depthmap_export", "正在导出分析结果", step=7)
        _run_depthmap_cmd(
            cli_path,
            ["-m", "EXPORT", "-f", str(graph_analysed), "-o", str(result_csv), "-em", "shapegraph-map-csv"],
            tmpdir,
            timeout_s,
        )

        with result_csv.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

    if not rows:
        return _empty_result(
            mode,
            coord_type="gcj02",
            radii_m=local_radii,
            metric=render_metric,
            analysis_engine=analysis_engine_label,
            webgl_status="disabled:no_analysis_rows",
        )

    _report_progress(
        "metrics_parse",
        "结果已导出，正在计算整合度/选择度",
        step=8,
        extra={"result_row_count": len(rows)},
    )

    result = build_road_analysis_result(
        rows=rows,
        fieldnames=fieldnames,
        context_wgs_poly=context_wgs_poly,
        output_wgs_poly=output_wgs_poly,
        mode=mode,
        local_radii=local_radii,
        requested_local_labels=requested_local_labels,
        render_metric=render_metric,
        include_geojson=include_geojson,
        max_edge_features=max_edge_features,
        merge_geojson_edges=merge_geojson_edges,
        merge_bucket_step=merge_bucket_step,
        use_arcgis_webgl=use_arcgis_webgl,
        arcgis_timeout_sec=arcgis_timeout_sec,
        arcgis_metric_field=arcgis_metric_field,
        analysis_engine_label=analysis_engine_label,
        started_at=started_at,
        report_progress=_report_progress,
    )
    road_edges = (result.get("road_edges") or {}).get("features") or []
    try:
        shared_grid = get_population_grid(polygon, coord_type)
        road_grid, road_grid_summary = build_road_grid(road_edges, shared_grid)
        result["road_grid"] = road_grid
        result["summary"]["road_grid"] = road_grid_summary
    except Exception:
        logger.exception("[road-syntax] shared road grid aggregation failed")
    logger.info(
        "[road-syntax] completed graph_model=%s edge_count=%d rendered_edge_count=%d elapsed_ms=%.2f",
        normalized_graph_model,
        int((result.get("summary") or {}).get("edge_count") or 0),
        int((result.get("summary") or {}).get("rendered_edge_count") or 0),
        safe_round((time.perf_counter() - started_at) * 1000.0, 2),
    )
    return result
