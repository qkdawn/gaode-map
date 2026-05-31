from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

from core.spatial import round_float
from modules.nightlight.service import get_nightlight_layer
from modules.poi.aggregation import build_category_matchers, normalize_type_code, resolve_category_id
from modules.population.service import get_population_grid, get_population_layer
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02


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
    xs: List[float] = []
    ys: List[float] = []
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


def _poi_point(poi: Dict[str, Any], coord_type: str) -> Point | None:
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


def _fallback_category_id(type_text: Any) -> str:
    code = normalize_type_code(type_text)
    if len(code) >= 2:
        return f"{code[:2]}0000"
    return code


def _category_name(cat_id: str, category_names: Dict[str, str]) -> str:
    return str(category_names.get(cat_id) or cat_id)


def shared_raster_cells_from_grid(grid_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    cells: List[Dict[str, Any]] = []
    for feature in grid_payload.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        cell_id = str(props.get("cell_id") or props.get("h3_id") or "").strip()
        if not cell_id:
            continue
        try:
            geom = shape(feature.get("geometry") or {})
        except Exception:
            continue
        if geom.is_empty:
            continue
        centroid = props.get("centroid_gcj02") or []
        if not (isinstance(centroid, list) and len(centroid) >= 2):
            centroid = [geom.centroid.x, geom.centroid.y]
        area_km2 = max(_cell_area_km2(geom), 1e-9)
        cells.append(
            {
                "cell_id": cell_id,
                "feature": feature,
                "geometry": geom,
                "centroid": [float(centroid[0]), float(centroid[1])],
                "area_km2": area_km2,
                "poi_count": 0,
                "category_counts": {},
                "category_names": {},
                "dominant_category": "",
                "dominant_category_name": "",
                "density_poi_per_km2": 0.0,
                "population_density": 0.0,
                "nightlight_radiance": None,
                "road_integration": 0.0,
                "road_connectivity": 0.0,
                "road_length_km_per_km2": 0.0,
            }
        )
    return cells


def apply_poi_cell_metrics(
    cells: List[Dict[str, Any]],
    pois: List[Dict[str, Any]],
    *,
    poi_coord_type: str = "gcj02",
    categories: List[Any] | None = None,
) -> Dict[str, Any]:
    matchers = build_category_matchers(categories or [])
    category_names = {cat_id: str(matcher.get("name") or cat_id) for cat_id, matcher in matchers.items()}
    assigned_count = 0
    points = [(poi, _poi_point(poi, poi_coord_type)) for poi in pois or []]
    valid_points = [(poi, point) for poi, point in points if point is not None]

    for cell in cells:
        geom = cell["geometry"]
        counts: Dict[str, int] = {}
        poi_count = 0
        for poi, point in valid_points:
            if not geom.covers(point):
                continue
            poi_count += 1
            assigned_count += 1
            cat_id = resolve_category_id(poi.get("type"), matchers) if matchers else _fallback_category_id(poi.get("type"))
            if cat_id:
                counts[cat_id] = int(counts.get(cat_id, 0)) + 1
                category_names.setdefault(cat_id, str(poi.get("type") or cat_id))
        cell["poi_count"] = poi_count
        cell["category_counts"] = counts
        if counts:
            dominant = max(counts.items(), key=lambda item: int(item[1] or 0))[0]
            cell["dominant_category"] = dominant
            cell["dominant_category_name"] = _category_name(dominant, category_names)
        cell["density_poi_per_km2"] = round_float(poi_count / max(float(cell["area_km2"]), 1e-9), 6)

    total_category_counts: Dict[str, int] = {}
    for cell in cells:
        for cat_id, count in (cell.get("category_counts") or {}).items():
            total_category_counts[cat_id] = int(total_category_counts.get(cat_id, 0)) + int(count or 0)
    return {
        "poi_count": len(pois or []),
        "assigned_poi_count": assigned_count,
        "category_counts": [
            {"id": cat_id, "name": _category_name(cat_id, category_names), "count": count}
            for cat_id, count in sorted(total_category_counts.items(), key=lambda item: int(item[1]), reverse=True)
        ],
    }


def apply_layer_cell_values(cells: List[Dict[str, Any]], layer: Dict[str, Any], target_key: str) -> None:
    value_by_id = {
        str(item.get("cell_id") or ""): _safe_float(item.get("value"), 0.0)
        for item in (layer.get("cells") or [])
        if isinstance(item, dict)
    }
    for cell in cells:
        cell[target_key] = round_float(value_by_id.get(cell["cell_id"], 0.0), 6)


def apply_nightlight_cell_values(cells: List[Dict[str, Any]], layer: Dict[str, Any]) -> None:
    value_by_id = {
        str(item.get("cell_id") or ""): _safe_float(item.get("value"), None)
        for item in (layer.get("cells") or [])
        if isinstance(item, dict)
    }
    for cell in cells:
        value = value_by_id.get(cell["cell_id"])
        cell["nightlight_radiance"] = None if value is None else round_float(value, 6)


def _road_feature_line(feature: Dict[str, Any]) -> BaseGeometry | None:
    try:
        geom = shape(feature.get("geometry") or {})
    except Exception:
        return None
    if geom.is_empty or geom.geom_type not in {"LineString", "MultiLineString"}:
        return None
    return geom


def apply_road_cell_metrics(cells: List[Dict[str, Any]], road_features: List[Dict[str, Any]]) -> None:
    if not cells or not road_features:
        return
    roads: List[tuple[BaseGeometry, Dict[str, Any]]] = []
    for feature in road_features:
        if not isinstance(feature, dict):
            continue
        line = _road_feature_line(feature)
        if line is None:
            continue
        roads.append((line, feature.get("properties") or {}))
    if not roads:
        return
    for cell in cells:
        geom = cell["geometry"]
        total_len = 0.0
        integ_sum = 0.0
        conn_sum = 0.0
        for line, props in roads:
            if not geom.intersects(line):
                continue
            clipped = geom.intersection(line)
            length_km = _line_length_km(clipped)
            if length_km <= 1e-9:
                continue
            total_len += length_km
            integ_sum += length_km * float(_safe_float(props.get("integration_score"), 0.0) or 0.0)
            conn_sum += length_km * float(_safe_float(props.get("connectivity_score"), 0.0) or 0.0)
        if total_len > 1e-9:
            cell["road_integration"] = round_float(integ_sum / total_len, 6)
            cell["road_connectivity"] = round_float(conn_sum / total_len, 6)
            cell["road_length_km_per_km2"] = round_float(total_len / max(float(cell["area_km2"]), 1e-9), 6)


def _cell_feature(cell: Dict[str, Any]) -> Dict[str, Any]:
    feature = dict(cell.get("feature") or {})
    props = dict(feature.get("properties") or {})
    props.update(
        {
            "cell_id": cell["cell_id"],
            "h3_id": cell["cell_id"],
            "grid_type": "shared_raster",
            "area_km2": round_float(cell.get("area_km2"), 6),
            "poi_count": int(cell.get("poi_count") or 0),
            "density_poi_per_km2": round_float(cell.get("density_poi_per_km2"), 6),
            "category_counts": dict(cell.get("category_counts") or {}),
            "dominant_category": str(cell.get("dominant_category") or ""),
            "dominant_category_name": str(cell.get("dominant_category_name") or ""),
            "population_density": round_float(cell.get("population_density"), 6),
            "nightlight_radiance": cell.get("nightlight_radiance"),
            "road_length_km_per_km2": round_float(cell.get("road_length_km_per_km2"), 6),
            "road_integration": round_float(cell.get("road_integration"), 6),
            "road_connectivity": round_float(cell.get("road_connectivity"), 6),
        }
    )
    feature["properties"] = props
    return feature


def _top_cells(cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = sorted(
        cells,
        key=lambda cell: (
            int(cell.get("poi_count") or 0),
            float(cell.get("population_density") or 0.0),
            float(cell.get("nightlight_radiance") or 0.0),
            float(cell.get("road_length_km_per_km2") or 0.0),
        ),
        reverse=True,
    )
    return [
        {
            "cell_id": cell["cell_id"],
            "poi_count": int(cell.get("poi_count") or 0),
            "density_poi_per_km2": round_float(cell.get("density_poi_per_km2"), 6),
            "population_density": round_float(cell.get("population_density"), 6),
            "nightlight_radiance": cell.get("nightlight_radiance"),
            "road_length_km_per_km2": round_float(cell.get("road_length_km_per_km2"), 6),
            "road_integration": round_float(cell.get("road_integration"), 6),
            "dominant_category": str(cell.get("dominant_category") or ""),
            "dominant_category_name": str(cell.get("dominant_category_name") or ""),
        }
        for cell in ranked[:12]
    ]


def _summary(cells: List[Dict[str, Any]], poi_metrics: Dict[str, Any]) -> Dict[str, Any]:
    cell_count = len(cells)
    active_poi = sum(1 for cell in cells if int(cell.get("poi_count") or 0) > 0)
    lit = sum(1 for cell in cells if _safe_float(cell.get("nightlight_radiance"), 0.0) and float(cell.get("nightlight_radiance") or 0.0) > 0)
    road_covered = sum(1 for cell in cells if float(cell.get("road_length_km_per_km2") or 0.0) > 0)
    population_cells = sum(1 for cell in cells if float(cell.get("population_density") or 0.0) > 0)
    return {
        "cell_count": cell_count,
        "active_poi_cell_count": active_poi,
        "lit_cell_count": lit,
        "road_covered_cell_count": road_covered,
        "population_cell_count": population_cells,
        "poi_count": int(poi_metrics.get("poi_count") or 0),
        "assigned_poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
        "category_counts": list(poi_metrics.get("category_counts") or []),
        "top_cells": _top_cells(cells),
        "coverage": {
            "active_poi_cell_ratio": round_float(active_poi / cell_count if cell_count else 0.0, 6),
            "lit_cell_ratio": round_float(lit / cell_count if cell_count else 0.0, 6),
            "road_covered_cell_ratio": round_float(road_covered / cell_count if cell_count else 0.0, 6),
            "population_cell_ratio": round_float(population_cells / cell_count if cell_count else 0.0, 6),
            "poi_assignment_ratio": round_float(
                int(poi_metrics.get("assigned_poi_count") or 0) / max(int(poi_metrics.get("poi_count") or 0), 1),
                6,
            ),
        },
    }


def build_unified_spatial_cells(
    *,
    polygon: list,
    coord_type: str = "gcj02",
    population_year: str = "2026",
    nightlight_year: int | None = None,
    pois: List[Dict[str, Any]] | None = None,
    poi_coord_type: str = "gcj02",
    road_features: List[Dict[str, Any]] | None = None,
    categories: List[Any] | None = None,
) -> Dict[str, Any]:
    grid = get_population_grid(polygon, coord_type, population_year)
    cells = shared_raster_cells_from_grid(grid)
    if not cells:
        return {
            "type": "FeatureCollection",
            "grid_type": "shared_raster",
            "cell_id_source": "population_nightlight_shared_cell_id",
            "cell_count": 0,
            "features": [],
            "summary": _summary([], {"poi_count": len(pois or []), "assigned_poi_count": 0, "category_counts": []}),
        }

    poi_metrics = apply_poi_cell_metrics(cells, pois or [], poi_coord_type=poi_coord_type, categories=categories)
    population_layer = get_population_layer(polygon, coord_type, population_year, scope_id=grid.get("scope_id"), view="density")
    apply_layer_cell_values(cells, population_layer, "population_density")
    nightlight_layer = get_nightlight_layer(polygon=polygon, coord_type=coord_type, year=nightlight_year, view="radiance")
    apply_nightlight_cell_values(cells, nightlight_layer)
    apply_road_cell_metrics(cells, road_features or [])

    features = [_cell_feature(cell) for cell in cells]
    return {
        "type": "FeatureCollection",
        "grid_type": "shared_raster",
        "cell_id_source": "population_nightlight_shared_cell_id",
        "scope_id": grid.get("scope_id"),
        "cell_count": len(features),
        "features": features,
        "summary": _summary(cells, poi_metrics),
    }
