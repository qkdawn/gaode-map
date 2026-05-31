from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

from core.spatial import round_float
from modules.nightlight.service import get_nightlight_layer
from modules.population.service import get_population_grid, get_population_layer
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from modules.spatial_cells.service import (
    apply_layer_cell_values,
    apply_nightlight_cell_values,
    apply_poi_cell_metrics,
    apply_road_cell_metrics,
    shared_raster_cells_from_grid,
)

from .arcgis_bridge import ArcGISGwrBridgeError, run_arcgis_gwr_analysis

VARIABLES: list[dict[str, str]] = [
    {"key": "poi_density_per_km2", "label": "POI 密度", "unit": "个/km²"},
    {"key": "population_density", "label": "人口密度", "unit": "人/km²"},
    {"key": "road_integration", "label": "路网整合度", "unit": ""},
    {"key": "road_connectivity", "label": "路网连通度", "unit": ""},
    {"key": "road_length_km_per_km2", "label": "路网长度密度", "unit": "km/km²"},
]


def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None:
            return default
        num = float(value)
        return num if math.isfinite(num) else default
    except Exception:
        return default


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_m = 6371008.8
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def _cell_area_km2(geom: BaseGeometry) -> float:
    if geom.is_empty:
        return 0.0
    pts = list(geom.exterior.coords) if getattr(geom, "exterior", None) else []
    if len(pts) < 4:
        return 0.0
    mean_lat = math.radians(sum(float(pt[1]) for pt in pts) / len(pts))
    xs: list[float] = []
    ys: list[float] = []
    for lng, lat in pts:
        xs.append(math.radians(float(lng)) * 6371.0088 * math.cos(mean_lat))
        ys.append(math.radians(float(lat)) * 6371.0088)
    area = 0.0
    for idx in range(len(xs) - 1):
        area += xs[idx] * ys[idx + 1] - xs[idx + 1] * ys[idx]
    return abs(area) / 2.0


def _line_length_km(line: BaseGeometry) -> float:
    if line.is_empty:
        return 0.0
    if line.geom_type == "MultiLineString":
        return sum(_line_length_km(part) for part in line.geoms)
    coords = list(getattr(line, "coords", []) or [])
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        total += _haversine_m(float(a[0]), float(a[1]), float(b[0]), float(b[1])) / 1000.0
    return total


def _build_base_cells(grid_payload: dict[str, Any]) -> list[dict[str, Any]]:
    cells = shared_raster_cells_from_grid(grid_payload)
    for cell in cells:
        cell["predictors"] = {
            "poi_density_per_km2": 0.0,
            "population_density": 0.0,
            "road_integration": 0.0,
            "road_connectivity": 0.0,
            "road_length_km_per_km2": 0.0,
        }
    return cells


def _poi_point(poi: dict[str, Any], coord_type: str) -> Point | None:
    loc = poi.get("location") if isinstance(poi.get("location"), list) else None
    lng = loc[0] if loc and len(loc) >= 2 else poi.get("lng")
    lat = loc[1] if loc and len(loc) >= 2 else poi.get("lat")
    lon = _safe_float(lng, None)
    la = _safe_float(lat, None)
    if lon is None or la is None:
        return None
    if coord_type == "wgs84":
        lon, la = wgs84_to_gcj02(float(lon), float(la))
    return Point(float(lon), float(la))


def _apply_poi_predictors(cells: list[dict[str, Any]], pois: list[dict[str, Any]], poi_coord_type: str) -> None:
    if not cells:
        return
    for cell in cells:
        cell.setdefault("predictors", {})
    apply_poi_cell_metrics(cells, pois or [], poi_coord_type=poi_coord_type)
    for cell in cells:
        cell["predictors"]["poi_density_per_km2"] = round_float(cell.get("density_poi_per_km2"), 6)


def _apply_layer_values(cells: list[dict[str, Any]], layer: dict[str, Any], target_key: str) -> None:
    apply_layer_cell_values(cells, layer, target_key)
    for cell in cells:
        cell.setdefault("predictors", {})
        cell["predictors"][target_key] = round_float(cell.get(target_key), 6)


def _apply_nightlight(cells: list[dict[str, Any]], layer: dict[str, Any]) -> None:
    apply_nightlight_cell_values(cells, layer)


def _road_feature_line(feature: dict[str, Any]) -> LineString | None:
    try:
        geom = shape(feature.get("geometry") or {})
    except Exception:
        return None
    if geom.is_empty or geom.geom_type not in {"LineString", "MultiLineString"}:
        return None
    return geom


def _apply_road_predictors(cells: list[dict[str, Any]], road_features: list[dict[str, Any]]) -> None:
    if not cells:
        return
    apply_road_cell_metrics(cells, road_features or [])
    for cell in cells:
        cell.setdefault("predictors", {})
        cell["predictors"]["road_integration"] = round_float(cell.get("road_integration"), 6)
        cell["predictors"]["road_connectivity"] = round_float(cell.get("road_connectivity"), 6)
        cell["predictors"]["road_length_km_per_km2"] = round_float(cell.get("road_length_km_per_km2"), 6)


def _valid_rows(cells: list[dict[str, Any]], variable_keys: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in cells:
        y = _safe_float(cell.get("nightlight_radiance"), None)
        if y is None:
            continue
        predictors = cell.get("predictors") or {}
        if not any(abs(float(_safe_float(predictors.get(key), 0.0) or 0.0)) > 1e-12 for key in variable_keys):
            continue
        rows.append(cell)
    return rows


def _empty_response(status: str, cells: list[dict[str, Any]], engine: str = "arcgis") -> dict[str, Any]:
    return {
        "summary": {
            "ok": False,
            "status": status,
            "engine": engine,
            "sample_count": 0,
            "cell_count": len(cells),
            "variable_count": len(VARIABLES),
            "r2": None,
            "adjusted_r2": None,
            "mean_abs_residual": 0.0,
            "rmse": 0.0,
            "top_variables": [],
        },
        "variables": VARIABLES,
        "cells": [],
        "feature_collection": {"type": "FeatureCollection", "features": [], "count": 0},
        "diagnostics": {"scatter": []},
        "engine_status": status,
    }


def _arcgis_rows(rows: list[dict[str, Any]], variable_keys: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("feature", {}).get("properties") or {}
        out.append(
            {
                "cell_id": row["cell_id"],
                "nightlight_radiance": row["nightlight_radiance"],
                "predictors": {key: row["predictors"].get(key, 0.0) for key in variable_keys},
                "centroid": {
                    "lng": row["centroid"][0],
                    "lat": row["centroid"][1],
                },
                "geometry": row.get("feature", {}).get("geometry") or {},
                "row": props.get("row"),
                "col": props.get("col"),
            }
        )
    return out


def _merge_arcgis_result(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
    variable_keys: list[str],
    engine_status: str,
) -> dict[str, Any] | None:
    raw_cells = result.get("cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        return None
    by_id = {str((item or {}).get("cell_id") or ""): item for item in raw_cells if isinstance(item, dict)}
    cells = []
    features = []
    for row in rows:
        raw = by_id.get(row["cell_id"])
        if not raw:
            continue
        coefficients = raw.get("coefficients") if isinstance(raw.get("coefficients"), dict) else {}
        item = {
            "cell_id": row["cell_id"],
            "observed": _safe_float(raw.get("observed"), _safe_float(row.get("nightlight_radiance"), None)),
            "predicted": _safe_float(raw.get("predicted"), None),
            "residual": _safe_float(raw.get("residual"), None),
            "local_r2": _safe_float(raw.get("local_r2"), None),
            "coefficients": {key: round_float(coefficients.get(key), 6) for key in variable_keys if coefficients.get(key) is not None},
            "predictors": {key: round_float(row["predictors"].get(key, 0.0), 6) for key in variable_keys},
        }
        cells.append(item)
        feature = dict(row["feature"])
        props = dict(feature.get("properties") or {})
        props.update(
            {
                "gwr_observed": item["observed"],
                "gwr_predicted": item["predicted"],
                "gwr_residual": item["residual"],
                "gwr_local_r2": item["local_r2"],
            }
        )
        props.update({f"gwr_coef_{key}": value for key, value in item["coefficients"].items()})
        props.update({f"gwr_x_{key}": value for key, value in item["predictors"].items()})
        feature["properties"] = props
        features.append(feature)
    if not cells:
        return None
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    return {
        "summary": {
            "ok": True,
            "status": str(summary.get("status") or result.get("status") or "ArcGIS GWR 计算完成"),
            "engine": "arcgis",
            "sample_count": len(cells),
            "cell_count": len(rows),
            "variable_count": len(variable_keys),
            "r2": _safe_float(summary.get("r2"), None),
            "adjusted_r2": _safe_float(summary.get("adjusted_r2"), None),
            "mean_abs_residual": round_float(summary.get("mean_abs_residual"), 6),
            "rmse": round_float(summary.get("rmse"), 6),
            "top_variables": summary.get("top_variables") if isinstance(summary.get("top_variables"), list) else [],
        },
        "variables": VARIABLES,
        "cells": cells,
        "feature_collection": {"type": "FeatureCollection", "features": features, "count": len(features)},
        "diagnostics": result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {},
        "engine_status": engine_status,
    }


def analyze_nightlight_gwr(
    *,
    polygon: list,
    coord_type: str = "gcj02",
    population_year: str = "2026",
    nightlight_year: int | None = None,
    pois: Optional[list[dict[str, Any]]] = None,
    poi_coord_type: str = "gcj02",
    road_features: Optional[list[dict[str, Any]]] = None,
    arcgis_timeout_sec: int = 240,
) -> dict[str, Any]:
    grid = get_population_grid(polygon, coord_type, population_year)
    cells = _build_base_cells(grid)
    if not cells:
        return _empty_response("当前范围没有可用统一格网", cells)

    variable_keys = [item["key"] for item in VARIABLES]
    _apply_poi_predictors(cells, pois or [], poi_coord_type)
    population_layer = get_population_layer(polygon, coord_type, population_year, scope_id=grid.get("scope_id"), view="density")
    _apply_layer_values(cells, population_layer, "population_density")
    _apply_road_predictors(cells, road_features or [])
    nightlight_layer = get_nightlight_layer(
        polygon=polygon,
        coord_type=coord_type,
        year=nightlight_year,
        view="radiance",
    )
    _apply_nightlight(cells, nightlight_layer)

    rows = _valid_rows(cells, variable_keys)
    min_samples = max(12, len(variable_keys) + 4)
    if len(rows) < min_samples:
        return _empty_response(f"有效样本不足：{len(rows)}/{min_samples}", cells)

    try:
        arcgis_result = run_arcgis_gwr_analysis(
            rows=_arcgis_rows(rows, variable_keys),
            variables=VARIABLES,
            timeout_sec=arcgis_timeout_sec,
        )
    except ArcGISGwrBridgeError as exc:
        return _empty_response(f"ArcGIS GWR 不可用：{exc}", cells, engine="arcgis")
    else:
        merged = _merge_arcgis_result(arcgis_result, rows, variable_keys, "ArcGIS GWR")
        if merged is not None:
            return merged
        return _empty_response("ArcGIS GWR 返回结果不完整", cells, engine="arcgis")
