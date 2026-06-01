from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

from core.spatial import round_float
from modules.h3.arcgis_facade import run_h3_arcgis_analysis
from modules.h3.stats import build_gi_render_meta, build_lisa_render_meta, calc_continuous_stats
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
        raw_row = _safe_float(props.get("row"), None)
        raw_col = _safe_float(props.get("col"), None)
        cells.append(
            {
                "cell_id": cell_id,
                "feature": feature,
                "geometry": geom,
                "centroid": [float(centroid[0]), float(centroid[1])],
                "row": int(raw_row) if raw_row is not None else -1,
                "col": int(raw_col) if raw_col is not None else -1,
                "area_km2": area_km2,
                "poi_count": 0,
                "category_counts": {},
                "subcategory_counts": {},
                "category_names": {},
                "dominant_category": "",
                "dominant_category_name": "",
                "density_poi_per_km2": 0.0,
                "local_entropy": 0.0,
                "neighbor_mean_density": 0.0,
                "neighbor_mean_entropy": 0.0,
                "neighbor_count": 0,
                "lisa_i": None,
                "lisa_z_score": None,
                "gi_star_value": None,
                "gi_star_z_score": None,
                "population_density": 0.0,
                "nightlight_radiance": None,
                "road_integration": 0.0,
                "road_connectivity": 0.0,
                "road_length_km_per_km2": 0.0,
            }
        )
    return cells


def _shannon_entropy(counts: Dict[str, int]) -> float:
    positive = [float(value) for value in (counts or {}).values() if float(value or 0) > 0]
    if not positive:
        return 0.0
    total = sum(positive)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for value in positive:
        p = value / total
        entropy -= p * math.log(p)
    return float(entropy)


def _normalized_ring(value: Any, default: int = 1) -> int:
    try:
        ring = int(float(value))
    except Exception:
        ring = int(default)
    return max(1, min(3, ring))


def _shared_ring_to_arcgis_knn(value: Any) -> int:
    ring = _normalized_ring(value, default=1)
    return {1: 8, 2: 24, 3: 48}.get(ring, 8)


def _build_shared_neighbor_map(cells: List[Dict[str, Any]], ring: int) -> Dict[str, List[str]]:
    normalized_ring = _normalized_ring(ring, default=1)
    coord_to_id: Dict[Tuple[int, int], str] = {}
    for cell in cells:
        row = int(cell.get("row", -1))
        col = int(cell.get("col", -1))
        if row < 0 or col < 0:
            continue
        coord_to_id[(row, col)] = str(cell.get("cell_id") or "")
    neighbor_map: Dict[str, List[str]] = {}
    for cell in cells:
        cell_id = str(cell.get("cell_id") or "")
        row = int(cell.get("row", -1))
        col = int(cell.get("col", -1))
        if not cell_id:
            continue
        if row < 0 or col < 0:
            neighbor_map[cell_id] = []
            continue
        neighbors: List[str] = []
        for dr in range(-normalized_ring, normalized_ring + 1):
            for dc in range(-normalized_ring, normalized_ring + 1):
                if dr == 0 and dc == 0:
                    continue
                if max(abs(dr), abs(dc)) > normalized_ring:
                    continue
                neighbor_id = coord_to_id.get((row + dr, col + dc))
                if neighbor_id:
                    neighbors.append(neighbor_id)
        neighbor_map[cell_id] = neighbors
    return neighbor_map


def _compute_shared_neighbor_metrics(cells: List[Dict[str, Any]], neighbor_ring: int) -> Dict[str, List[str]]:
    neighbor_map = _build_shared_neighbor_map(cells, neighbor_ring)
    cell_by_id = {str(cell.get("cell_id") or ""): cell for cell in cells}
    for cell in cells:
        cell_id = str(cell.get("cell_id") or "")
        neighbor_ids = neighbor_map.get(cell_id) or []
        cell["neighbor_count"] = len(neighbor_ids)
        if not neighbor_ids:
            cell["neighbor_mean_density"] = 0.0
            cell["neighbor_mean_entropy"] = 0.0
            continue
        density_sum = 0.0
        entropy_sum = 0.0
        for neighbor_id in neighbor_ids:
            neighbor = cell_by_id.get(neighbor_id) or {}
            density_sum += float(neighbor.get("density_poi_per_km2") or 0.0)
            entropy_sum += float(neighbor.get("local_entropy") or 0.0)
        neighbor_count = max(len(neighbor_ids), 1)
        cell["neighbor_mean_density"] = density_sum / neighbor_count
        cell["neighbor_mean_entropy"] = entropy_sum / neighbor_count
    return neighbor_map


def _compute_shared_global_moran_i(
    cells: List[Dict[str, Any]],
    neighbor_map: Dict[str, List[str]],
    value_key: str = "density_poi_per_km2",
) -> Optional[float]:
    if len(cells) < 2:
        return None
    values = {str(cell.get("cell_id") or ""): float(cell.get(value_key) or 0.0) for cell in cells}
    mean_value = sum(values.values()) / len(values)
    denominator = sum((value - mean_value) ** 2 for value in values.values())
    if denominator <= 0:
        return None
    numerator = 0.0
    s0 = 0
    for cell_id, value in values.items():
        for neighbor_id in neighbor_map.get(cell_id) or []:
            neighbor_value = values.get(neighbor_id)
            if neighbor_value is None:
                continue
            numerator += (value - mean_value) * (neighbor_value - mean_value)
            s0 += 1
    if s0 <= 0:
        return None
    return round_float((len(values) / s0) * (numerator / denominator), 6)


def _has_density_variance(cells: List[Dict[str, Any]], tol: float = 1e-12) -> bool:
    if len(cells) < 2:
        return False
    values = [float(cell.get("density_poi_per_km2") or 0.0) for cell in cells]
    return (max(values) - min(values)) > float(tol)


def _build_shared_chart_payload(
    category_rows: List[Dict[str, Any]],
    density_values: List[float],
) -> Dict[str, Any]:
    labels = [str(item.get("name") or item.get("id") or "") for item in (category_rows or [])]
    values = [int(item.get("count") or 0) for item in (category_rows or [])]
    edges = [0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0]
    bins = [f"{int(edges[idx])}-{int(edges[idx + 1])}" for idx in range(len(edges) - 1)] + [f">={int(edges[-1])}"]
    counts = [0 for _ in bins]
    for density in density_values:
        value = float(density or 0.0)
        bucket = len(bins) - 1
        for idx in range(len(edges) - 1):
            if value < edges[idx + 1]:
                bucket = idx
                break
        counts[bucket] += 1
    return {
        "category_distribution": {"labels": labels, "values": values},
        "density_histogram": {"bins": bins, "counts": counts},
    }


def _build_shared_local_spatial_stats(arcgis_cells: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for item in arcgis_cells or []:
        cell_id = str((item or {}).get("h3_id") or (item or {}).get("cell_id") or "")
        if not cell_id:
            continue
        gi_z = _safe_float((item or {}).get("gi_star_z_score"), None)
        if gi_z is None:
            gi_z = _safe_float((item or {}).get("gi_z_score"), None)
        gi_value = _safe_float((item or {}).get("gi_star_value"), None)
        if gi_value is None:
            gi_value = gi_z
        stats[cell_id] = {
            "lisa_i": None if _safe_float((item or {}).get("lisa_i"), None) is None else round_float((item or {}).get("lisa_i"), 6),
            "lisa_z_score": None if _safe_float((item or {}).get("lisa_z_score"), None) is None else round_float((item or {}).get("lisa_z_score"), 6),
            "gi_star_value": None if gi_value is None else round_float(gi_value, 6),
            "gi_star_z_score": None if gi_z is None else round_float(gi_z, 6),
        }
    return stats


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
        subcategory_counts: Dict[str, int] = {}
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
            point_type = str(poi.get("type") or "").strip()
            if point_type:
                subcategory_counts[point_type] = int(subcategory_counts.get(point_type, 0)) + 1
        cell["poi_count"] = poi_count
        cell["category_counts"] = counts
        cell["subcategory_counts"] = subcategory_counts
        if counts:
            dominant = max(counts.items(), key=lambda item: int(item[1] or 0))[0]
            cell["dominant_category"] = dominant
            cell["dominant_category_name"] = _category_name(dominant, category_names)
        cell["density_poi_per_km2"] = round_float(poi_count / max(float(cell["area_km2"]), 1e-9), 6)
        cell["local_entropy"] = round_float(_shannon_entropy(counts), 6)

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
            "row": int(cell.get("row") or 0),
            "col": int(cell.get("col") or 0),
            "area_km2": round_float(cell.get("area_km2"), 6),
            "poi_count": int(cell.get("poi_count") or 0),
            "density_poi_per_km2": round_float(cell.get("density_poi_per_km2"), 6),
            "local_entropy": round_float(cell.get("local_entropy"), 6),
            "neighbor_mean_density": round_float(cell.get("neighbor_mean_density"), 6),
            "neighbor_mean_entropy": round_float(cell.get("neighbor_mean_entropy"), 6),
            "neighbor_count": int(cell.get("neighbor_count") or 0),
            "category_counts": dict(cell.get("category_counts") or {}),
            "subcategory_counts": dict(cell.get("subcategory_counts") or {}),
            "dominant_category": str(cell.get("dominant_category") or ""),
            "dominant_category_name": str(cell.get("dominant_category_name") or ""),
            "lisa_i": cell.get("lisa_i"),
            "lisa_z_score": cell.get("lisa_z_score"),
            "gi_star_value": cell.get("gi_star_value"),
            "gi_star_z_score": cell.get("gi_star_z_score"),
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


def _empty_shared_grid_metrics(
    *,
    scope_id: Optional[str] = None,
    poi_count: int = 0,
) -> Dict[str, Any]:
    empty_stats = calc_continuous_stats([])
    return {
        "grid": {
            "type": "FeatureCollection",
            "grid_type": "shared_raster",
            "cell_id_source": "population_nightlight_shared_cell_id",
            "scope_id": scope_id,
            "count": 0,
            "cell_count": 0,
            "features": [],
        },
        "summary": {
            "grid_count": 0,
            "poi_count": int(poi_count or 0),
            "avg_density_poi_per_km2": 0.0,
            "avg_local_entropy": 0.0,
            "global_moran_i_density": None,
            "global_moran_z_score": None,
            "analysis_engine": "arcgis",
            "arcgis_status": None,
            "arcgis_image_url": None,
            "arcgis_image_url_gi": None,
            "arcgis_image_url_lisa": None,
            "gi_render_meta": build_gi_render_meta(),
            "lisa_render_meta": build_lisa_render_meta(empty_stats),
            "gi_z_stats": empty_stats,
            "lisa_i_stats": empty_stats,
        },
        "charts": _build_shared_chart_payload([], []),
    }


def analyze_shared_grid(
    *,
    polygon: list,
    coord_type: str = "gcj02",
    pois: List[Dict[str, Any]] | None = None,
    poi_coord_type: str = "gcj02",
    categories: List[Any] | None = None,
    year: int | None = None,
    neighbor_ring: int = 1,
    arcgis_neighbor_ring: int = 1,
    arcgis_export_image: bool = True,
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

    del year
    total_steps = 7
    report("build_grid", "正在生成共享栅格底座", 1, total_steps, {"arcgis_enabled": True})
    grid = get_population_grid(polygon, coord_type)
    cells = shared_raster_cells_from_grid(grid)
    if not cells:
        report("completed", "当前范围没有可用共享栅格", total_steps, total_steps, {"grid_count": 0, "poi_count": len(pois or [])})
        return _empty_shared_grid_metrics(scope_id=grid.get("scope_id"), poi_count=len(pois or []))

    report("aggregate_poi", "正在聚合 POI 到共享栅格", 2, total_steps, {"grid_count": len(cells), "arcgis_enabled": True})
    poi_metrics = apply_poi_cell_metrics(cells, pois or [], poi_coord_type=poi_coord_type, categories=categories)
    neighbor_ring = _normalized_ring(neighbor_ring, default=1)
    report(
        "compute_metrics",
        "正在计算密度、熵和邻域指标",
        3,
        total_steps,
        {
            "grid_count": len(cells),
            "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
            "arcgis_enabled": True,
        },
    )
    neighbor_map = _compute_shared_neighbor_metrics(cells, neighbor_ring)
    global_moran_i = _compute_shared_global_moran_i(cells, neighbor_map)
    global_moran_z_score: Optional[float] = None
    arcgis_status: Optional[str] = None
    arcgis_image_url: Optional[str] = None
    arcgis_image_url_gi: Optional[str] = None
    arcgis_image_url_lisa: Optional[str] = None

    if _has_density_variance(cells):
        arcgis_knn = _shared_ring_to_arcgis_knn(arcgis_neighbor_ring or neighbor_ring)
        report(
            "arcgis_prepare",
            "正在准备 ArcGIS 结构分析输入",
            4,
            total_steps,
            {
                "grid_count": len(cells),
                "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
                "arcgis_knn": arcgis_knn,
                "arcgis_enabled": True,
            },
        )
        base_features = [_cell_feature(cell) for cell in cells]
        stats_by_cell = {
            str(cell.get("cell_id") or ""): {
                "density_poi_per_km2": float(cell.get("density_poi_per_km2") or 0.0),
            }
            for cell in cells
        }
        report(
            "arcgis_running",
            "正在执行 ArcGIS 热点与局部空间统计",
            5,
            total_steps,
            {
                "grid_count": len(cells),
                "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
                "arcgis_knn": arcgis_knn,
                "arcgis_enabled": True,
            },
        )
        try:
            arcgis_result = run_h3_arcgis_analysis(
                features=base_features,
                stats_by_cell=stats_by_cell,
                knn_neighbors=arcgis_knn,
                timeout_sec=arcgis_timeout_sec,
                export_image=arcgis_export_image,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"ArcGIS不可用，共享网格空间结构分析已停止：{exc}") from exc
        global_moran = arcgis_result.get("global_moran") or {}
        global_moran_i = None if _safe_float(global_moran.get("i"), None) is None else round_float(global_moran.get("i"), 6)
        global_moran_z_score = None if _safe_float(global_moran.get("z_score"), None) is None else round_float(global_moran.get("z_score"), 6)
        local_stats = _build_shared_local_spatial_stats(arcgis_result.get("cells") or [])
        for cell in cells:
            stats = local_stats.get(str(cell.get("cell_id") or "")) or {}
            cell["lisa_i"] = stats.get("lisa_i")
            cell["lisa_z_score"] = stats.get("lisa_z_score")
            cell["gi_star_value"] = stats.get("gi_star_value")
            cell["gi_star_z_score"] = stats.get("gi_star_z_score")
        arcgis_status = str(arcgis_result.get("status") or "ArcGIS计算完成")
        arcgis_image_url = arcgis_result.get("image_url")
        arcgis_image_url_gi = arcgis_result.get("image_url_gi") or arcgis_image_url
        arcgis_image_url_lisa = arcgis_result.get("image_url_lisa")
    else:
        report(
            "arcgis_running",
            "共享栅格密度无差异，跳过 ArcGIS 结构分析",
            5,
            total_steps,
            {
                "grid_count": len(cells),
                "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
                "arcgis_enabled": False,
            },
        )
        for cell in cells:
            cell["lisa_i"] = 0.0
            cell["lisa_z_score"] = 0.0
            cell["gi_star_value"] = 0.0
            cell["gi_star_z_score"] = 0.0
        arcgis_status = "ArcGIS已跳过：密度无差异"

    features = [_cell_feature(cell) for cell in cells]
    density_values = [float(cell.get("density_poi_per_km2") or 0.0) for cell in cells]
    entropy_values = [float(cell.get("local_entropy") or 0.0) for cell in cells]
    gi_z_stats = calc_continuous_stats([cell.get("gi_star_z_score") for cell in cells])
    lisa_i_stats = calc_continuous_stats([cell.get("lisa_i") for cell in cells])
    grid_count = len(features)
    avg_density = (sum(density_values) / grid_count) if grid_count else 0.0
    avg_entropy = (sum(entropy_values) / grid_count) if grid_count else 0.0
    report(
        "finalize",
        "正在整理共享栅格分析结果",
        6,
        total_steps,
        {
            "grid_count": grid_count,
            "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
            "arcgis_enabled": bool(_has_density_variance(cells)),
        },
    )
    result = {
        "grid": {
            "type": "FeatureCollection",
            "grid_type": "shared_raster",
            "cell_id_source": "population_nightlight_shared_cell_id",
            "scope_id": grid.get("scope_id"),
            "count": grid_count,
            "cell_count": grid_count,
            "features": features,
        },
        "summary": {
            "grid_count": grid_count,
            "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
            "avg_density_poi_per_km2": round_float(avg_density, 6),
            "avg_local_entropy": round_float(avg_entropy, 6),
            "global_moran_i_density": global_moran_i,
            "global_moran_z_score": global_moran_z_score,
            "analysis_engine": "arcgis",
            "arcgis_status": arcgis_status,
            "arcgis_image_url": arcgis_image_url,
            "arcgis_image_url_gi": arcgis_image_url_gi,
            "arcgis_image_url_lisa": arcgis_image_url_lisa,
            "gi_render_meta": build_gi_render_meta(),
            "lisa_render_meta": build_lisa_render_meta(lisa_i_stats),
            "gi_z_stats": gi_z_stats,
            "lisa_i_stats": lisa_i_stats,
        },
        "charts": _build_shared_chart_payload(list(poi_metrics.get("category_counts") or []), density_values),
    }
    report(
        "completed",
        "POI 共享栅格分析计算完成",
        total_steps,
        total_steps,
        {
            "grid_count": grid_count,
            "poi_count": int(poi_metrics.get("assigned_poi_count") or 0),
            "arcgis_enabled": bool(_has_density_variance(cells)),
        },
    )
    return result


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
    _compute_shared_neighbor_metrics(cells, 1)
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
