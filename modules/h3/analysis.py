from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, Optional

from .arcgis_facade import run_h3_arcgis_analysis
from .arcgis_report_map import render_h3_structure_report_maps
from .category_rules import empty_category_counts
from .core import build_h3_grid_feature_collection
from .stats import (
    aggregate_pois_to_h3,
    build_chart_payload,
    build_gi_render_meta,
    build_lisa_render_meta,
    build_local_spatial_stats_from_arcgis,
    calc_continuous_stats,
    compute_cell_metrics,
    compute_global_moran_i,
    compute_neighbor_metrics,
    has_density_variance,
    new_local_spatial_stat,
    safe_float,
    safe_round,
)


def analyze_h3_grid(
    polygon: list,
    resolution: int = 10,
    coord_type: Literal["gcj02", "wgs84"] = "gcj02",
    include_mode: Literal["intersects", "inside"] = "intersects",
    min_overlap_ratio: float = 0.0,
    pois: Optional[List[Dict[str, Any]]] = None,
    poi_coord_type: Literal["gcj02", "wgs84"] = "gcj02",
    use_arcgis: bool = False,
    arcgis_timeout_sec: int = 240,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    def report(stage: str, message: str, step: int, total: int, extra: Optional[Dict[str, Any]] = None) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "stage": stage,
                "message": message,
                "step": step,
                "total": total,
                "extra": dict(extra or {}),
            }
        )

    total_steps = 8
    report("build_grid", "正在生成 H3 网格", 1, total_steps, {"resolution": resolution, "arcgis_enabled": bool(use_arcgis)})
    grid = build_h3_grid_feature_collection(
        polygon_coords=polygon,
        resolution=resolution,
        coord_type=coord_type,
        include_mode=include_mode,
        min_overlap_ratio=min_overlap_ratio,
    )
    features = grid.get("features") or []
    grid_ids = [feature.get("properties", {}).get("h3_id") for feature in features if feature.get("properties", {}).get("h3_id")]
    if not grid_ids:
        empty_charts = build_chart_payload(empty_category_counts(), [])
        empty_gi_stats = calc_continuous_stats([])
        empty_lisa_stats = calc_continuous_stats([])
        return {
            "grid": grid,
            "summary": {
                "grid_count": 0,
                "poi_count": 0,
                "avg_density_poi_per_km2": 0.0,
                "avg_local_entropy": 0.0,
                "global_moran_i_density": None,
                "global_moran_z_score": None,
                "analysis_engine": "arcgis",
                "arcgis_status": None,
                "arcgis_report_maps": {},
                "gi_render_meta": build_gi_render_meta(),
                "lisa_render_meta": build_lisa_render_meta(empty_lisa_stats),
                "gi_z_stats": empty_gi_stats,
                "lisa_i_stats": empty_lisa_stats,
            },
            "charts": empty_charts,
        }

    report("aggregate_poi", "正在聚合 POI 到网格", 2, total_steps, {"resolution": resolution, "grid_count": len(grid_ids), "arcgis_enabled": bool(use_arcgis)})
    stats_by_cell, assigned_poi_count, global_category_counts = aggregate_pois_to_h3(
        grid_ids=grid_ids,
        pois=pois or [],
        resolution=resolution,
        poi_coord_type=poi_coord_type,
    )
    report(
        "compute_metrics",
        "正在计算密度、熵和邻域指标",
        3,
        total_steps,
        {
            "resolution": resolution,
            "grid_count": len(grid_ids),
            "poi_count": assigned_poi_count,
            "arcgis_enabled": bool(use_arcgis),
        },
    )
    compute_cell_metrics(stats_by_cell, resolution=resolution)
    compute_neighbor_metrics(stats_by_cell)

    arcgis_status: Optional[str] = None
    spatial_statistics_method: Dict[str, Any] = {}
    arcgis_report_maps: Dict[str, Dict[str, Any]] = {}
    global_moran_i: Optional[float] = compute_global_moran_i(stats_by_cell)
    global_moran_z_score: Optional[float] = None
    local_spatial_stats = {cell_id: new_local_spatial_stat() for cell_id in stats_by_cell.keys()}

    if not use_arcgis:
        for stat in local_spatial_stats.values():
            stat.update(
                {
                    "lisa_i": 0.0,
                    "lisa_z_score": 0.0,
                    "gi_star_value": 0.0,
                    "gi_star_z_score": 0.0,
                }
            )
        arcgis_status = "ArcGIS未启用，返回原生统计结果"
    elif has_density_variance(stats_by_cell):
        report(
            "arcgis_prepare",
            "正在准备 ArcGIS 空间统计",
            4,
            total_steps,
            {
                "resolution": resolution,
                "grid_count": len(grid_ids),
                "poi_count": assigned_poi_count,
                "arcgis_enabled": True,
            },
        )
        try:
            report(
                "arcgis_running",
                "正在计算热点、LISA 和 Moran",
                5,
                total_steps,
                {
                    "resolution": resolution,
                    "grid_count": len(grid_ids),
                    "poi_count": assigned_poi_count,
                    "arcgis_enabled": True,
                    "arcgis_status": "running",
                },
            )
            arcgis_result = run_h3_arcgis_analysis(
                features=features,
                stats_by_cell=stats_by_cell,
                timeout_sec=arcgis_timeout_sec,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"ArcGIS不可用，H3 空间结构分析已停止：{exc}") from exc
        else:
            global_moran = arcgis_result.get("global_moran") or {}
            global_moran_i = safe_round(safe_float(global_moran.get("i")), 6)
            global_moran_z_score = safe_round(safe_float(global_moran.get("z_score")), 6)
            local_spatial_stats, _ = build_local_spatial_stats_from_arcgis(
                stats_by_cell,
                arcgis_result.get("cells") or [],
            )
            arcgis_status = str(arcgis_result.get("status") or "ArcGIS计算完成")
            spatial_statistics_method = dict(arcgis_result.get("method") or {})
    else:
        for stat in local_spatial_stats.values():
            stat.update(
                {
                    "lisa_i": 0.0,
                    "lisa_z_score": 0.0,
                    "gi_star_value": 0.0,
                    "gi_star_z_score": 0.0,
                }
            )
        arcgis_status = "ArcGIS已跳过：密度无差异"

    report(
        "finalize",
        "正在整理 H3 分析结果",
        6,
        total_steps,
        {
            "resolution": resolution,
            "grid_count": len(grid_ids),
            "poi_count": assigned_poi_count,
            "arcgis_enabled": bool(use_arcgis),
            "arcgis_status": arcgis_status,
            "spatial_statistics_method": spatial_statistics_method,
        },
    )
    density_values: List[float] = []
    entropy_values: List[float] = []
    gi_z_values: List[Optional[float]] = []
    lisa_i_values: List[Optional[float]] = []
    for feature in features:
        props = feature.setdefault("properties", {})
        cell_id = props.get("h3_id")
        cell_stats = stats_by_cell.get(cell_id)
        if not cell_stats:
            continue
        local_stats = local_spatial_stats.get(cell_id, {})
        density = float(cell_stats["density_poi_per_km2"])
        entropy = float(cell_stats["local_entropy"])
        density_values.append(density)
        entropy_values.append(entropy)
        gi_z_values.append(safe_float(local_stats.get("gi_star_z_score")))
        lisa_i_values.append(safe_float(local_stats.get("lisa_i")))
        props.update(
            {
                "poi_count": int(cell_stats["poi_count"]),
                "density_poi_per_km2": safe_round(density, 6) or 0.0,
                "local_entropy": safe_round(entropy, 6) or 0.0,
                "neighbor_mean_density": safe_round(cell_stats["neighbor_mean_density"], 6) or 0.0,
                "neighbor_mean_entropy": safe_round(cell_stats["neighbor_mean_entropy"], 6) or 0.0,
                "neighbor_count": int(cell_stats["neighbor_count"]),
                "category_counts": cell_stats["category_counts"],
                "subcategory_counts": cell_stats.get("subcategory_counts") or {},
                "lisa_i": local_stats.get("lisa_i"),
                "lisa_z_score": local_stats.get("lisa_z_score"),
                "gi_star_value": local_stats.get("gi_star_value"),
                "gi_star_z_score": local_stats.get("gi_star_z_score"),
            }
        )

    if grid_count := len(features):
        report(
            "render_report_map",
            "正在由 ArcGIS 生成正式专题图",
            7,
            total_steps,
            {"resolution": resolution, "grid_count": grid_count, "arcgis_enabled": bool(use_arcgis)},
        )
        try:
            arcgis_report_maps = render_h3_structure_report_maps(
                grid_features=features, polygon=polygon, coord_type=coord_type, resolution=resolution,
            )
        except Exception as exc:
            arcgis_report_maps = {
                mode: {
                    "status": "failed", "mode": mode, "asset_id": "", "title": "",
                    "summary": "ArcGIS 专题图生成失败。", "limitations": [str(exc)], "svg": None,
                    "visual_manifest": None,
                }
                for mode in ("gi_z", "lisa_i")
            }

    grid_count = len(features)
    avg_density = (sum(density_values) / grid_count) if grid_count else 0.0
    avg_entropy = (sum(entropy_values) / grid_count) if grid_count else 0.0
    gi_z_stats = calc_continuous_stats(gi_z_values)
    lisa_i_stats = calc_continuous_stats(lisa_i_values)
    result = {
        "grid": {"type": "FeatureCollection", "features": features, "count": grid_count},
        "summary": {
            "grid_count": grid_count,
            "poi_count": assigned_poi_count,
            "avg_density_poi_per_km2": safe_round(avg_density, 6) or 0.0,
            "avg_local_entropy": safe_round(avg_entropy, 6) or 0.0,
            "global_moran_i_density": global_moran_i,
            "global_moran_z_score": global_moran_z_score,
            "analysis_engine": "arcgis",
            "arcgis_status": arcgis_status,
            "spatial_statistics_method": spatial_statistics_method,
            "arcgis_report_maps": arcgis_report_maps,
            "gi_render_meta": build_gi_render_meta(),
            "lisa_render_meta": build_lisa_render_meta(lisa_i_stats),
            "gi_z_stats": gi_z_stats,
            "lisa_i_stats": lisa_i_stats,
        },
        "charts": build_chart_payload(global_category_counts, density_values),
    }
    report(
        "completed",
        "H3 网格分析计算完成",
        8,
        total_steps,
        {
            "resolution": resolution,
            "grid_count": grid_count,
            "poi_count": assigned_poi_count,
            "arcgis_enabled": bool(use_arcgis),
            "arcgis_status": arcgis_status,
        },
    )
    return result
