from __future__ import annotations

import asyncio
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

from fastapi import HTTPException

from core.config import settings
from modules.history.service import get_history_pois_payload


_TYPE_MAP_PATH = Path(__file__).resolve().parents[2] / "share" / "type_map.json"
_TYPE_CONFIG: Dict[str, Any] = json.loads(_TYPE_MAP_PATH.read_text(encoding="utf-8"))
_HEATMAP_VIEW_WIDTH = 100.0
_HEATMAP_BOUNDS_PADDING_RATIO = 0.08
_STATICMAP_WIDTH = 640
_STATICMAP_MIN_HEIGHT = 320
_STATICMAP_MAX_HEIGHT = 860
_STATICMAP_PADDING_PX = 28
_POI_ITERATION_AI_TIMEOUT_S = 2.0


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _compact_h3_evidence(value: Any, cell_limit: int = 40, row_limit: int = 20) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cells = value.get("cells") if isinstance(value.get("cells"), list) else []
    compact_cells: List[Dict[str, Any]] = []
    for cell in cells[:cell_limit]:
        if not isinstance(cell, dict):
            continue
        props = cell.get("properties") if isinstance(cell.get("properties"), dict) else cell
        h3_id = _as_text(props.get("h3_id"))
        if not h3_id:
            continue
        compact_cells.append({
            "h3_id": h3_id,
            "poi_count": props.get("poi_count"),
            "density_poi_per_km2": props.get("density_poi_per_km2"),
            "local_entropy": props.get("local_entropy"),
            "neighbor_mean_density": props.get("neighbor_mean_density"),
            "neighbor_mean_entropy": props.get("neighbor_mean_entropy"),
            "neighbor_count": props.get("neighbor_count"),
            "category_counts": props.get("category_counts") or {},
            "gi_star_z_score": props.get("gi_star_z_score"),
            "gi_star_value": props.get("gi_star_value"),
            "lisa_i": props.get("lisa_i"),
            "lisa_z_score": props.get("lisa_z_score"),
        })

    derived = value.get("derived_stats") if isinstance(value.get("derived_stats"), dict) else {}

    def rows_from(compact_key: str) -> List[Dict[str, Any]]:
        rows = derived.get(compact_key)
        return rows[:row_limit] if isinstance(rows, list) else []

    return {
        "evidence_version": value.get("evidence_version") or "poi_h3_evidence_v1",
        "grid_type": value.get("grid_type") or "h3",
        "usage": value.get("usage") or "POI-only spatial structure evidence; do not use it for population or nightlight coupling.",
        "params": value.get("params") or {},
        "counts": {
            **(value.get("counts") if isinstance(value.get("counts"), dict) else {}),
            "cell_count": ((value.get("counts") or {}).get("cell_count") if isinstance(value.get("counts"), dict) else len(cells)),
            "included_cell_count": len(compact_cells),
        },
        "metrics": value.get("metrics") or {},
        "summary": value.get("summary") or {},
        "charts": value.get("charts") or {},
        "cells": compact_cells,
        "derived_stats": {
            "structure_rows": rows_from("structure_rows"),
            "typing_rows": rows_from("typing_rows"),
            "lq_rows": rows_from("lq_rows"),
            "gap_rows": rows_from("gap_rows"),
        },
        "omitted": {
            "cells_total": ((value.get("omitted") or {}).get("cells_total") if isinstance(value.get("omitted"), dict) else len(cells)),
            "cells_included": len(compact_cells),
            "geometry_removed": True,
        },
        "constraints": {
            "poi_only": True,
            "do_not_use_for_population_nightlight_coupling": True,
        },
    }


def _compact_yearly_grid_evidence(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "evidence_version": value.get("evidence_version") or "poi_iteration_yearly_grid_evidence_v1",
        "years": value.get("years") if isinstance(value.get("years"), list) else [],
        "grid_scope": value.get("grid_scope") or "poi_iteration_h3_per_year",
        "grid_type": value.get("grid_type") or "h3",
        "latest_year": value.get("latest_year"),
        "latest_h3_evidence": _compact_h3_evidence(value.get("latest_h3_evidence"), cell_limit=20, row_limit=12),
        "items": [
            {
                "year": item.get("year"),
                "status": item.get("status") or "ready",
                "error": item.get("error") or "",
                "grid_scope": item.get("grid_scope") or value.get("grid_scope") or "poi_iteration_h3_per_year",
                "h3_evidence": _compact_h3_evidence(item.get("h3_evidence"), cell_limit=20, row_limit=12),
            }
            for item in (value.get("items") if isinstance(value.get("items"), list) else [])
            if isinstance(item, dict)
        ],
    }


def _to_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _valid_lng_lat(point: Dict[str, Any]) -> Optional[tuple[float, float]]:
    lng = _to_number(point.get("lng"))
    lat = _to_number(point.get("lat"))
    if lng is None or lat is None:
        location = point.get("location")
        if isinstance(location, (list, tuple)) and len(location) >= 2:
            lng = _to_number(location[0])
            lat = _to_number(location[1])
    if lng is None or lat is None:
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return lng, lat


def _mercator_unit(lng: float, lat: float) -> tuple[float, float]:
    clamped_lat = max(-85.05112878, min(85.05112878, float(lat)))
    sin_lat = math.sin(math.radians(clamped_lat))
    x = (float(lng) + 180.0) / 360.0
    y = 0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)
    return x, y


def _mercator_pixel(lng: float, lat: float, zoom: int) -> tuple[float, float]:
    unit_x, unit_y = _mercator_unit(lng, lat)
    world_size = 256 * (2 ** int(zoom))
    return unit_x * world_size, unit_y * world_size


def _lng_lat_from_mercator_unit(x: float, y: float) -> tuple[float, float]:
    lng = float(x) * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * float(y))))
    return lng, math.degrees(lat_rad)


def _mercator_bounds_from_pairs(pairs: List[tuple[float, float]]) -> Optional[Dict[str, float]]:
    units = [_mercator_unit(lng, lat) for lng, lat in pairs if lng is not None and lat is not None]
    if not units:
        return None
    xs = [item[0] for item in units]
    ys = [item[1] for item in units]
    return {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)}


def _round_float(value: Any, digits: int = 6) -> float:
    number = _to_number(value)
    return round(float(number or 0), digits)


def _build_heatmap_view_bounds(pairs: List[tuple[float, float]]) -> Optional[Dict[str, Any]]:
    clean_pairs = [pair for pair in pairs if pair is not None]
    if not clean_pairs:
        return None

    unit_bounds = _mercator_bounds_from_pairs(clean_pairs)
    if not unit_bounds:
        return None

    raw_span_x = max(unit_bounds["max_x"] - unit_bounds["min_x"], 1e-9)
    raw_span_y = max(unit_bounds["max_y"] - unit_bounds["min_y"], 1e-9)
    pad_x = max(raw_span_x * _HEATMAP_BOUNDS_PADDING_RATIO, 1e-7)
    pad_y = max(raw_span_y * _HEATMAP_BOUNDS_PADDING_RATIO, 1e-7)
    min_x = max(0.0, unit_bounds["min_x"] - pad_x)
    max_x = min(1.0, unit_bounds["max_x"] + pad_x)
    min_y = max(0.0, unit_bounds["min_y"] - pad_y)
    max_y = min(1.0, unit_bounds["max_y"] + pad_y)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    static_height = int(round(_STATICMAP_WIDTH * span_y / span_x))
    static_height = max(_STATICMAP_MIN_HEIGHT, min(_STATICMAP_MAX_HEIGHT, static_height))
    view_width = _HEATMAP_VIEW_WIDTH
    view_height = max(1.0, view_width * static_height / _STATICMAP_WIDTH)

    center_unit_x = (min_x + max_x) / 2
    center_unit_y = (min_y + max_y) / 2
    center_lng, center_lat = _lng_lat_from_mercator_unit(center_unit_x, center_unit_y)
    available_width = max(1, _STATICMAP_WIDTH - _STATICMAP_PADDING_PX * 2)
    available_height = max(1, static_height - _STATICMAP_PADDING_PX * 2)
    zoom_x = math.log2(available_width / (256 * span_x))
    zoom_y = math.log2(available_height / (256 * span_y))
    zoom = max(3, min(17, int(math.floor(min(zoom_x, zoom_y)))))
    center_px, center_py = _mercator_pixel(center_lng, center_lat, zoom)
    left_px = center_px - (_STATICMAP_WIDTH / 2)
    top_px = center_py - (static_height / 2)

    min_lng, max_lat = _lng_lat_from_mercator_unit(min_x, min_y)
    max_lng, min_lat = _lng_lat_from_mercator_unit(max_x, max_y)
    svg_view = {"width": view_width, "height": view_height}
    return {
        "min_lng": min_lng,
        "min_lat": min_lat,
        "max_lng": max_lng,
        "max_lat": max_lat,
        "ref_lat": center_lat,
        "mercator_bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
        "view": svg_view,
        "view_box": f"0 0 {_round_float(svg_view['width'], 3):g} {_round_float(svg_view['height'], 3):g}",
        "aspect_ratio": f"{_round_float(svg_view['width'], 3):g} / {_round_float(svg_view['height'], 3):g}",
        "svg_viewport": {
            "min_lng": min_lng,
            "min_lat": min_lat,
            "max_lng": max_lng,
            "max_lat": max_lat,
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "width": svg_view["width"],
            "height": svg_view["height"],
        },
        "staticmap_viewport": {
            "left_px": left_px,
            "top_px": top_px,
            "width": float(_STATICMAP_WIDTH),
            "height": float(static_height),
            "zoom": zoom,
        },
        "staticmap_size": {"width": _STATICMAP_WIDTH, "height": static_height},
        "staticmap_center": [round(center_lng, 6), round(center_lat, 6)],
        "staticmap_zoom": zoom,
        "center": [round(center_lng, 6), round(center_lat, 6)],
        "size": {"width": _round_float(svg_view["width"], 3), "height": _round_float(svg_view["height"], 3)},
    }


def _project_lng_lat(lng: float, lat: float, bounds: Dict[str, float]) -> Dict[str, float]:
    viewport = bounds.get("staticmap_viewport") if isinstance(bounds, dict) else None
    view = bounds.get("view") if isinstance(bounds, dict) else None
    if isinstance(viewport, dict):
        zoom = int(viewport.get("zoom") or 0)
        width = max(1.0, float(viewport.get("width") or 1))
        height = max(1.0, float(viewport.get("height") or 1))
        left = float(viewport.get("left_px") or 0)
        top = float(viewport.get("top_px") or 0)
        view_width = float((view or {}).get("width") or _HEATMAP_VIEW_WIDTH)
        view_height = float((view or {}).get("height") or _HEATMAP_VIEW_WIDTH)
        px, py = _mercator_pixel(float(lng), float(lat), zoom)
        return {
            "x": max(0, min(view_width, ((px - left) / width) * view_width)),
            "y": max(0, min(view_height, ((py - top) / height) * view_height)),
        }

    svg_viewport = bounds.get("svg_viewport") if isinstance(bounds, dict) else None
    if isinstance(svg_viewport, dict):
        min_lng = float(svg_viewport.get("min_lng") or bounds.get("min_lng") or 0)
        max_lng = float(svg_viewport.get("max_lng") or bounds.get("max_lng") or min_lng)
        min_lat = float(svg_viewport.get("min_lat") or bounds.get("min_lat") or 0)
        max_lat = float(svg_viewport.get("max_lat") or bounds.get("max_lat") or min_lat)
        view_width = max(1.0, float(svg_viewport.get("width") or _HEATMAP_VIEW_WIDTH))
        view_height = max(1.0, float(svg_viewport.get("height") or _HEATMAP_VIEW_WIDTH))
        span_lng = max(max_lng - min_lng, 1e-12)
        span_lat = max(max_lat - min_lat, 1e-12)
        return {
            "x": max(0, min(view_width, ((float(lng) - min_lng) / span_lng) * view_width)),
            "y": max(0, min(view_height, ((max_lat - float(lat)) / span_lat) * view_height)),
        }

    mercator_bounds = _mercator_bounds_from_pairs(
        [
            (float(bounds["min_lng"]), float(bounds["min_lat"])),
            (float(bounds["max_lng"]), float(bounds["max_lat"])),
        ]
    )
    if not mercator_bounds:
        return {"x": 0.0, "y": 0.0}
    min_x = mercator_bounds["min_x"]
    max_x = mercator_bounds["max_x"]
    min_y = mercator_bounds["min_y"]
    max_y = mercator_bounds["max_y"]
    x, y = _mercator_unit(float(lng), float(lat))
    span_x = max(max_x - min_x, 1e-12)
    span_y = max(max_y - min_y, 1e-12)
    scale_span = max(span_x, span_y)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    return {
        "x": max(0, min(100, 50 + ((x - center_x) / scale_span) * 100)),
        "y": max(0, min(100, 50 + ((y - center_y) / scale_span) * 100)),
    }


def _pad_bounds(min_lng: float, min_lat: float, max_lng: float, max_lat: float) -> Dict[str, float]:
    pad_lng = max((max_lng - min_lng) * 0.12, 0.003)
    pad_lat = max((max_lat - min_lat) * 0.12, 0.003)
    ref_lat = (min_lat + max_lat) / 2
    return {
        "min_lng": min_lng - pad_lng,
        "min_lat": min_lat - pad_lat,
        "max_lng": max_lng + pad_lng,
        "max_lat": max_lat + pad_lat,
        "ref_lat": ref_lat,
    }


def _bounds_from_pairs(pairs: List[tuple[float, float]]) -> Optional[Dict[str, Any]]:
    pairs = [pair for pair in pairs if pair is not None]
    if not pairs:
        return None
    return _build_heatmap_view_bounds(pairs)


def _bounds_from_points(points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    pairs = [_valid_lng_lat(point) for point in points]
    return _bounds_from_pairs([pair for pair in pairs if pair is not None])


def _normalize_polygon_rings(polygon: Any) -> List[List[tuple[float, float]]]:
    if not isinstance(polygon, list) or not polygon:
        return []

    def as_pair(value: Any) -> Optional[tuple[float, float]]:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return None
        lng = _to_number(value[0])
        lat = _to_number(value[1])
        if lng is None or lat is None:
            return None
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            return None
        return lng, lat

    def as_ring(value: Any) -> List[tuple[float, float]]:
        if not isinstance(value, list):
            return []
        ring = [pair for pair in (as_pair(point) for point in value) if pair is not None]
        return ring if len(ring) >= 3 else []

    if as_pair(polygon[0]):
        ring = as_ring(polygon)
        return [ring] if ring else []

    rings: List[List[tuple[float, float]]] = []
    for item in polygon:
        if not isinstance(item, list) or not item:
            continue
        if as_pair(item[0]):
            ring = as_ring(item)
            if ring:
                rings.append(ring)
        elif isinstance(item[0], list):
            for nested in item:
                ring = as_ring(nested)
                if ring:
                    rings.append(ring)
    return rings


def _bounds_from_polygon(polygon: Any) -> Optional[Dict[str, Any]]:
    pairs = [point for ring in _normalize_polygon_rings(polygon) for point in ring]
    return _bounds_from_pairs(pairs)


def _point_in_ring(lng: float, lat: float, ring: List[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        xi, yi = point
        xj, yj = ring[j]
        if (abs((yi - lat) * (xj - lng) - (xi - lng) * (yj - lat)) < 1e-10
                and min(xi, xj) - 1e-10 <= lng <= max(xi, xj) + 1e-10
                and min(yi, yj) - 1e-10 <= lat <= max(yi, yj) + 1e-10):
            return True
        intersects = ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lng: float, lat: float, polygon: Any) -> bool:
    rings = _normalize_polygon_rings(polygon)
    if not rings:
        return True
    return any(_point_in_ring(lng, lat, ring) for ring in rings)


def _public_heatmap_bounds(bounds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not bounds:
        return {}
    result: Dict[str, Any] = {}
    for key, value in bounds.items():
        if key in {
            "svg_viewport",
            "staticmap_viewport",
            "staticmap_size",
            "staticmap_center",
            "staticmap_zoom",
            "view",
            "size",
            "center",
            "view_box",
            "aspect_ratio",
        }:
            continue
        if isinstance(value, dict):
            result[key] = {nested_key: _round_float(nested_value, 8) for nested_key, nested_value in value.items()}
        elif isinstance(value, (int, float)):
            result[key] = _round_float(value, 8)
        else:
            result[key] = value
    return result


def _heatmap_view_meta(bounds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    view = dict((bounds or {}).get("view") or {"width": _HEATMAP_VIEW_WIDTH, "height": _HEATMAP_VIEW_WIDTH})
    view_width = max(1.0, float(view.get("width") or _HEATMAP_VIEW_WIDTH))
    view_height = max(1.0, float(view.get("height") or _HEATMAP_VIEW_WIDTH))
    return {
        "view": {"width": _round_float(view_width, 3), "height": _round_float(view_height, 3)},
        "view_box": (bounds or {}).get("view_box") or f"0 0 {_round_float(view_width, 3):g} {_round_float(view_height, 3):g}",
        "aspect_ratio": (bounds or {}).get("aspect_ratio") or f"{_round_float(view_width, 3):g} / {_round_float(view_height, 3):g}",
    }


def build_area_heatmap_basemap(bounds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    view_size = dict((bounds or {}).get("size") or {"width": _HEATMAP_VIEW_WIDTH, "height": _HEATMAP_VIEW_WIDTH})
    meta = _heatmap_view_meta(bounds)
    empty = {
        "url": "",
        "bounds": _public_heatmap_bounds(bounds),
        "center": list((bounds or {}).get("staticmap_center") or (bounds or {}).get("center") or []),
        "zoom": None,
        "size": view_size,
        "source": "none",
        **meta,
    }
    key = _as_text(settings.amap_web_service_key).split(",", 1)[0].strip()
    if not key or not bounds:
        return empty
    center = list(bounds.get("staticmap_center") or bounds.get("center") or [])
    zoom = int(bounds.get("staticmap_zoom") or 0)
    if not center or not zoom:
        return empty
    static_size = dict(bounds.get("staticmap_size") or view_size)
    params = {
        "location": f"{center[0]:.6f},{center[1]:.6f}",
        "zoom": zoom,
        "size": f"{int(static_size['width'])}*{int(static_size['height'])}",
        "scale": 2,
        "key": key,
    }
    return {
        **empty,
        "url": f"https://restapi.amap.com/v3/staticmap?{urlencode(params)}",
        "zoom": zoom,
        "size": static_size,
        "source": "amap_static_url",
    }


def build_area_heatmap_boundary(polygon: Any, bounds: Optional[Dict[str, float]]) -> List[Dict[str, float]]:
    if not bounds:
        return []
    rings = _normalize_polygon_rings(polygon)
    if not rings:
        return []
    ring = rings[0]
    result = []
    for lng, lat in ring:
        result.append(_project_lng_lat(lng, lat, bounds))
    return result


def _normalize_type_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _build_type_indexes() -> Dict[str, Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_label: Dict[str, Dict[str, Any]] = {}
    by_typecode: Dict[str, Dict[str, Any]] = {}
    for group in _TYPE_CONFIG.get("groups") or []:
        group_title = _as_text(group.get("title")) or _as_text(group.get("id")) or "未分类"
        for item in group.get("items") or []:
            row = {
                "id": _as_text(item.get("id")),
                "label": _as_text(item.get("label")),
                "parent": group_title,
            }
            if row["id"]:
                by_id[row["id"]] = row
            if row["label"]:
                by_label[row["label"]] = row
            for raw_code in _as_text(item.get("types")).split("|"):
                code = _normalize_type_code(raw_code)
                if code:
                    by_typecode[code] = row
    return {"by_id": by_id, "by_label": by_label, "by_typecode": by_typecode}


_TYPE_INDEXES = _build_type_indexes()


def _resolve_poi_type(poi: Dict[str, Any]) -> Dict[str, str]:
    raw_type = _as_text(poi.get("type") or poi.get("typecode") or poi.get("type_code"))
    typecode = _normalize_type_code(poi.get("typecode") or poi.get("type_code") or raw_type)
    item = (
        _TYPE_INDEXES["by_id"].get(raw_type)
        or _TYPE_INDEXES["by_label"].get(raw_type)
        or _TYPE_INDEXES["by_typecode"].get(typecode)
    )
    if item:
        return {
            "category": item["parent"] or "未分类",
            "subcategory": item["label"] or "未分类小类",
            "subcategory_id": item["id"],
            "raw_type": raw_type,
        }
    labels = [part.strip() for part in raw_type.replace("，", ";").replace(",", ";").replace("/", ";").split(";") if part.strip()]
    return {
        "category": labels[0] if labels else "未分类",
        "subcategory": (labels[1] if len(labels) > 1 else (labels[0] if labels else "未分类小类")),
        "subcategory_id": "",
        "raw_type": raw_type,
    }


def _sort_count_rows(counter: Counter, total: int, extra=None) -> List[Dict[str, Any]]:
    total = max(1, int(total or 0))
    extra = extra or (lambda _name, _count: {})
    rows = [
        {"name": name, "count": int(count), "ratio": int(count) / total, **extra(name, int(count))}
        for name, count in counter.items()
    ]
    return sorted(rows, key=lambda item: (-int(item["count"]), _as_text(item["name"])))


def summarize_iteration_pois(pois: Iterable[Dict[str, Any]], year: Optional[int] = None) -> Dict[str, Any]:
    poi_list = [item for item in pois or [] if isinstance(item, dict)]
    category_counts: Counter[str] = Counter()
    subcategory_counts: Counter[str] = Counter()
    subcategory_parent: Dict[str, str] = {}
    category_to_subcategory: Dict[str, Counter[str]] = defaultdict(Counter)
    area_counts: Counter[str] = Counter()
    points: List[Dict[str, Any]] = []

    for poi in poi_list:
        type_info = _resolve_poi_type(poi)
        category = type_info["category"] or "未分类"
        subcategory = type_info["subcategory"] or "未分类小类"
        category_counts[category] += 1
        subcategory_counts[subcategory] += 1
        subcategory_parent.setdefault(subcategory, category)
        category_to_subcategory[category][subcategory] += 1
        area = _as_text(poi.get("adname") or poi.get("cityname") or poi.get("pname") or poi.get("area")) or "未知区域"
        area_counts[area] += 1
        location = poi.get("location")
        if isinstance(location, (list, tuple)) and len(location) >= 2:
            lng = _to_number(location[0])
            lat = _to_number(location[1])
            if lng is not None and lat is not None:
                points.append({"lng": lng, "lat": lat, "category": category, "subcategory": subcategory, "area": area})

    total = len(poi_list)
    category_to_subcategory_mix = {}
    for category, child_counter in category_to_subcategory.items():
        category_total = max(1, int(category_counts.get(category) or 0))
        category_to_subcategory_mix[category] = sorted(
            [
                {"name": name, "parent": category, "count": int(count), "ratio": int(count) / category_total}
                for name, count in child_counter.items()
            ],
            key=lambda item: (-int(item["count"]), _as_text(item["name"])),
        )

    return {
        "year": int(year) if year is not None else None,
        "count": total,
        "category_count": len(category_counts),
        "subcategory_count": len(subcategory_counts),
        "top_categories": _sort_count_rows(category_counts, total)[:5],
        "top_subcategories": _sort_count_rows(
            subcategory_counts,
            total,
            lambda name, _count: {"parent": subcategory_parent.get(name) or "未分类"},
        ),
        "top_areas": _sort_count_rows(area_counts, total)[:5],
        "category_counts": dict(category_counts),
        "subcategory_counts": dict(subcategory_counts),
        "category_to_subcategory_mix": category_to_subcategory_mix,
        "area_counts": dict(area_counts),
        "points": points,
    }


def build_category_stack(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if item.get("category_counts")], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    totals: Counter[str] = Counter()
    for summary in sorted_summaries:
        totals.update({name: int(count or 0) for name, count in (summary.get("category_counts") or {}).items()})
    top_names = [name for name, _count in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:5]]
    rows = []
    for summary in sorted_summaries:
        counts = summary.get("category_counts") or {}
        total = max(1, int(summary.get("count") or 0))
        segments = [{"name": name, "count": int(counts.get(name) or 0), "ratio": int(counts.get(name) or 0) / total} for name in top_names]
        known = sum(int(item["count"]) for item in segments)
        other = max(0, int(summary.get("count") or 0) - known)
        if other:
            segments.append({"name": "其他", "count": other, "ratio": other / total})
        rows.append({"year": summary.get("year"), "total": int(summary.get("count") or 0), "segments": segments})
    return rows


def build_subcategory_stack(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if item.get("subcategory_counts")], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    totals: Counter[str] = Counter()
    parent_by_name: Dict[str, str] = {}
    for summary in sorted_summaries:
        for item in summary.get("top_subcategories") or []:
            if isinstance(item, dict) and item.get("name"):
                parent_by_name.setdefault(_as_text(item.get("name")), _as_text(item.get("parent")))
        totals.update({name: int(count or 0) for name, count in (summary.get("subcategory_counts") or {}).items()})
    top_names = [name for name, _count in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:6]]
    rows = []
    for summary in sorted_summaries:
        counts = summary.get("subcategory_counts") or {}
        total = max(1, int(summary.get("count") or 0))
        segments = [
            {
                "name": name,
                "parent": parent_by_name.get(name, ""),
                "count": int(counts.get(name) or 0),
                "ratio": int(counts.get(name) or 0) / total,
            }
            for name in top_names
        ]
        known = sum(int(item["count"]) for item in segments)
        other = max(0, int(summary.get("count") or 0) - known)
        if other:
            segments.append({"name": "其他小类", "parent": "", "count": other, "ratio": other / total})
        rows.append({"year": summary.get("year"), "total": int(summary.get("count") or 0), "segments": segments})
    return rows


def build_area_heatmaps(
    summaries: List[Dict[str, Any]],
    bounds: Optional[Dict[str, float]] = None,
    polygon: Any = None,
) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if item.get("points")], key=lambda item: int(item.get("year") or 0))
    if not bounds:
        all_points = [point for summary in sorted_summaries for point in (summary.get("points") or [])]
        bounds = _bounds_from_points(all_points)
    if not bounds:
        return []
    view = dict(bounds.get("view") or {})
    view_width = max(1.0, float(view.get("width") or _HEATMAP_VIEW_WIDTH))
    view_height = max(1.0, float(view.get("height") or _HEATMAP_VIEW_WIDTH))
    rows = []
    for summary in sorted_summaries:
        points = []
        for point in summary.get("points") or []:
            pair = _valid_lng_lat(point)
            if pair is None:
                continue
            lng, lat = pair
            if polygon and not _point_in_polygon(lng, lat, polygon):
                continue
            projected = _project_lng_lat(lng, lat, bounds)
            points.append(
                {
                    "x": projected["x"],
                    "y": projected["y"],
                    "area": _as_text(point.get("area")),
                    "category": _as_text(point.get("category")),
                    "subcategory": _as_text(point.get("subcategory")),
                }
            )
        cell_counts: Counter[tuple[int, int]] = Counter()
        grid_size = 12
        cell_width = view_width / grid_size
        cell_height = view_height / grid_size
        for point in points:
            col = max(0, min(grid_size - 1, int(float(point["x"]) / cell_width)))
            row = max(0, min(grid_size - 1, int(float(point["y"]) / cell_height)))
            cell_counts[(col, row)] += 1
        max_cell_count = max(cell_counts.values(), default=1)
        cells = [
            {
                "x": round(col * cell_width, 3),
                "y": round(row * cell_height, 3),
                "width": round(cell_width, 3),
                "height": round(cell_height, 3),
                "count": count,
                "intensity": round(count / max_cell_count, 4),
            }
            for (col, row), count in sorted(cell_counts.items(), key=lambda item: (item[0][1], item[0][0]))
        ]
        rows.append(
            {
                "year": summary.get("year"),
                "points": points[:260],
                "cells": cells,
                "point_count": len(points),
                "top_area": ((summary.get("top_areas") or [{}])[0] or {}).get("name") or "",
            }
        )
    return rows


def build_trend_rows(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if "count" in item], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    first, last = sorted_summaries[0], sorted_summaries[-1]
    first_counts = first.get("category_counts") or {}
    last_counts = last.get("category_counts") or {}
    names = sorted(set(first_counts) | set(last_counts))
    deltas = sorted(
        [{"name": name, "delta": int(last_counts.get(name) or 0) - int(first_counts.get(name) or 0)} for name in names],
        key=lambda item: (-abs(int(item["delta"])), item["name"]),
    )
    top_increase = next((item for item in deltas if item["delta"] > 0), None)
    top_decrease = next((item for item in deltas if item["delta"] < 0), None)
    total_delta = int(last.get("count") or 0) - int(first.get("count") or 0)
    return [
        {"key": "years", "label": "覆盖年份", "value": f"{first.get('year') or '-'}-{last.get('year') or '-'}"},
        {"key": "total_delta", "label": "POI 首尾变化", "value": f"{'+' if total_delta >= 0 else ''}{total_delta}"},
        {"key": "category_delta", "label": "业态类型变化", "value": f"{'+' if int(last.get('category_count') or 0) - int(first.get('category_count') or 0) >= 0 else ''}{int(last.get('category_count') or 0) - int(first.get('category_count') or 0)}"},
        {"key": "top_increase", "label": "增长最明显业态", "value": f"{top_increase['name']} +{top_increase['delta']}" if top_increase else "-"},
        {"key": "top_decrease", "label": "减少最明显业态", "value": f"{top_decrease['name']} {top_decrease['delta']}" if top_decrease else "-"},
        {"key": "latest_top", "label": "末年第一业态", "value": ((last.get("top_categories") or [{}])[0] or {}).get("name") or "-"},
    ]


def build_subcategory_trend_rows(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if "count" in item], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    first, last = sorted_summaries[0], sorted_summaries[-1]
    first_counts = first.get("subcategory_counts") or {}
    last_counts = last.get("subcategory_counts") or {}
    parent_by_name: Dict[str, str] = {}
    for item in list(first.get("top_subcategories") or []) + list(last.get("top_subcategories") or []):
        if isinstance(item, dict) and item.get("name"):
            parent_by_name.setdefault(_as_text(item.get("name")), _as_text(item.get("parent")))
    deltas = sorted(
        [
            {
                "name": name,
                "parent": parent_by_name.get(name, ""),
                "delta": int(last_counts.get(name) or 0) - int(first_counts.get(name) or 0),
            }
            for name in sorted(set(first_counts) | set(last_counts))
        ],
        key=lambda item: (-abs(int(item["delta"])), item["name"]),
    )
    top_increase = next((item for item in deltas if item["delta"] > 0), None)
    top_decrease = next((item for item in deltas if item["delta"] < 0), None)
    latest_top = (last.get("top_subcategories") or [{}])[0] or {}
    subcategory_delta = int(last.get("subcategory_count") or 0) - int(first.get("subcategory_count") or 0)
    increase_parent = f"（{top_increase['parent']}）" if top_increase and top_increase.get("parent") else ""
    decrease_parent = f"（{top_decrease['parent']}）" if top_decrease and top_decrease.get("parent") else ""
    latest_parent = f"（{latest_top.get('parent')}）" if latest_top.get("parent") else ""
    return [
        {"key": "subcategory_delta", "label": "小类类型变化", "value": f"{'+' if subcategory_delta >= 0 else ''}{subcategory_delta}"},
        {"key": "top_subcategory_increase", "label": "增长最明显小类", "value": f"{top_increase['name']}{increase_parent} +{top_increase['delta']}" if top_increase else "-"},
        {"key": "top_subcategory_decrease", "label": "减少最明显小类", "value": f"{top_decrease['name']}{decrease_parent} {top_decrease['delta']}" if top_decrease else "-"},
        {"key": "latest_top_subcategory", "label": "末年第一小类", "value": f"{latest_top.get('name')}{latest_parent}" if latest_top.get("name") else "-"},
    ]


def _format_metric(value: Any, digits: int = 0) -> str:
    number = _to_number(value)
    if number is None:
        return "0"
    return f"{number:.{digits}f}" if digits > 0 else str(int(round(number)))


def build_rule_insights(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    sorted_summaries = sorted([item for item in summaries if "count" in item], key=lambda item: int(item.get("year") or 0))
    latest = sorted_summaries[-1] if sorted_summaries else {}
    top_category = (latest.get("top_categories") or [{}])[0] or {}
    top_subcategory = (latest.get("top_subcategories") or [{}])[0] or {}
    top_area = (latest.get("top_areas") or [{}])[0] or {}
    top_subcategory_parts = []
    for item in (latest.get("top_subcategories") or [])[:3]:
        if item.get("name"):
            parent = f"（{item.get('parent')}）" if item.get("parent") else ""
            top_subcategory_parts.append(f"{item.get('name')}{parent}")
    top_subcategory_text = "、".join(top_subcategory_parts)
    single_structure_detail = f"，内部小类以{top_subcategory.get('name')}较突出" if top_subcategory.get("name") else ""
    structure_detail = f"，其下小类{top_subcategory.get('name')}表现突出" if top_subcategory.get("name") else ""
    if len(sorted_summaries) < 2:
        return {
            "summary": [
                f"当前POI规模为 {_format_metric(latest.get('count'), 0)}，一级主导业态为{top_category.get('name') or '未分类'}。",
                f"关键小类集中在{top_subcategory_text}。" if top_subcategory_text else "当前小类结构信号有限。",
                f"{top_area.get('name') or '主要区域'}为核心聚集区，呈现当前POI的主要空间承载。",
            ],
            "insights": {
                "fastest_growth": "当前只有一个年份，暂无法判断增长最快行业。",
                "declining_category": "当前只有一个年份，暂无法判断衰退行业。",
                "emerging_area": f"当前核心承载片区：{top_area.get('name')}" if top_area.get("name") else "当前缺少可识别的增长片区信号。",
                "structure_judgement": f"一级业态以{top_category.get('name')}为主{single_structure_detail}。" if top_category.get("name") else "业态结构信号有限。",
            },
        }

    first, last = sorted_summaries[0], sorted_summaries[-1]
    total_delta = int(last.get("count") or 0) - int(first.get("count") or 0)
    top_ratio = (int(top_category.get("count") or 0) / int(last.get("count") or 1)) if int(last.get("count") or 0) > 0 else 0
    category_changes = _change_rows(first.get("category_counts") or {}, last.get("category_counts") or {})
    subcategory_changes = _change_rows(first.get("subcategory_counts") or {}, last.get("subcategory_counts") or {})
    fastest = next((item for item in sorted(category_changes, key=lambda item: (-item["rate"], -item["delta"])) if item["delta"] > 0), None)
    declining = next((item for item in sorted(category_changes, key=lambda item: (item["rate"], item["delta"])) if item["delta"] < 0), None)
    fastest_sub = next((item for item in sorted(subcategory_changes, key=lambda item: (-item["rate"], -item["delta"])) if item["delta"] > 0), None)
    declining_sub = next((item for item in sorted(subcategory_changes, key=lambda item: (item["rate"], item["delta"])) if item["delta"] < 0), None)
    growth_sub_detail = f"; fastest_subcategory={fastest_sub['name']}; delta={fastest_sub['delta']}" if fastest_sub else ""
    decline_sub_detail = f"; declining_subcategory={declining_sub['name']}; delta={declining_sub['delta']}" if declining_sub else ""
    growth_area = next(
        (
            item
            for item in sorted(_change_rows(first.get("area_counts") or {}, last.get("area_counts") or {}), key=lambda item: -item["delta"])
            if item["delta"] > 0
        ),
        None,
    )
    growth_area_text = (
        f"growth_area={growth_area['name']}; delta={growth_area['delta']}."
        if growth_area
        else "growth_area=-."
    )
    return {
        "summary": [
            f"当前POI规模为 {_format_metric(last.get('count'), 0)}，较{first.get('year') or '首年'}{'增加' if total_delta >= 0 else '减少'} {_format_metric(abs(total_delta), 0)}。",
            f"top_category={top_category.get('name') or '-'}; top_category_ratio={top_ratio * 100:.1f}%.",
            f"top_subcategories={top_subcategory_text}." if top_subcategory_text else "top_subcategories=-.",
            f"top_area={top_area.get('name') or '-'}.",
            f"top_category_ratio_signal={'ge_0_25' if top_ratio >= 0.25 else 'lt_0_25'}.",
        ],
        "insights": {
            "fastest_growth": f"category={fastest['name']}; delta={fastest['delta']}; rate={fastest['rate'] * 100:.1f}%{growth_sub_detail}" if fastest else "fastest_growth=-.",
            "declining_category": f"category={declining['name']}; delta={declining['delta']}; rate={declining['rate'] * 100:.1f}%{decline_sub_detail}" if declining else "declining_category=-.",
            "emerging_area": growth_area_text,
            "structure_judgement": f"top_category={top_category.get('name')}; detail={structure_detail or '-'}." if top_category.get("name") else "top_category=-.",
        },
    }


def _change_rows(first_counts: Dict[str, Any], last_counts: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for name in sorted(set(first_counts) | set(last_counts)):
        before = int(first_counts.get(name) or 0)
        after = int(last_counts.get(name) or 0)
        delta = after - before
        rows.append({"name": name, "before": before, "after": after, "delta": delta, "rate": (delta / before) if before > 0 else (1 if after > 0 else 0)})
    return rows


def _normalize_years(years: Iterable[Any]) -> List[int]:
    result = []
    for item in years or []:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


def _get_payload_value(payload: Any, key: str, default: Any = None) -> Any:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


async def _generate_poi_iteration_analysis(evidence: Dict[str, Any]) -> Dict[str, Any]:
    from modules.agent.iteration_change_service import generate_poi_iteration_analysis

    return await generate_poi_iteration_analysis(evidence)


async def _generate_poi_iteration_analysis_with_timeout(evidence: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return await asyncio.wait_for(
            _generate_poi_iteration_analysis(evidence),
            timeout=max(0.1, float(_POI_ITERATION_AI_TIMEOUT_S)),
        )
    except asyncio.TimeoutError:
        return {"status": "failed", "report_title": "", "report_sections": [], "report_content": "", "error": "ai_timeout"}


async def build_agent_poi_iteration_payload(payload: Any, repo) -> Dict[str, Any]:
    history_id = _as_text(_get_payload_value(payload, "history_id", ""))
    years = _normalize_years(_get_payload_value(payload, "years", None))
    center = _get_payload_value(payload, "center", None)
    h3_evidence = _get_payload_value(payload, "h3_evidence", {}) or {}
    if not isinstance(h3_evidence, dict):
        h3_evidence = {}
    h3_evidence = _compact_h3_evidence(h3_evidence)
    yearly_grid_evidence = _get_payload_value(payload, "yearly_grid_evidence", {}) or {}
    if not isinstance(yearly_grid_evidence, dict):
        yearly_grid_evidence = {}
    yearly_grid_evidence = _compact_yearly_grid_evidence(yearly_grid_evidence)
    if not history_id:
        raise HTTPException(status_code=400, detail="history_id is required")
    if len(years) < 2:
        raise HTTPException(status_code=400, detail="at least two years are required")

    summaries: List[Dict[str, Any]] = []
    polygon = []
    for year in years:
        history_payload = get_history_pois_payload(history_id, repo, year=year)
        if not polygon and isinstance(history_payload.get("polygon"), list):
            polygon = history_payload.get("polygon") or []
        summaries.append(summarize_iteration_pois(history_payload.get("pois") or [], year))

    if not any(int(summary.get("count") or 0) > 0 for summary in summaries):
        raise HTTPException(status_code=404, detail="no POI data for requested years")

    all_points = [point for summary in summaries for point in (summary.get("points") or [])]
    area_heatmap_bounds = _bounds_from_polygon(polygon) or _bounds_from_points(all_points)
    area_heatmap_basemap = build_area_heatmap_basemap(area_heatmap_bounds)
    area_heatmap_boundary = build_area_heatmap_boundary(polygon, area_heatmap_bounds)
    rule = build_rule_insights(summaries)
    base_payload: Dict[str, Any] = {
        "status": "ready",
        "source": "history",
        "historyId": history_id,
        "years": years,
        "center": center,
        "summaries": summaries,
        "trend_rows": build_trend_rows(summaries),
        "total_series": [{"year": summary.get("year"), "value": int(summary.get("count") or 0)} for summary in summaries],
        "category_stack": build_category_stack(summaries),
        "subcategory_stack": build_subcategory_stack(summaries),
        "subcategory_trend_rows": build_subcategory_trend_rows(summaries),
        "area_heatmaps": build_area_heatmaps(summaries, area_heatmap_bounds, polygon),
        "area_heatmap_basemap": area_heatmap_basemap,
        "area_heatmap_boundary": area_heatmap_boundary,
        "area_heatmap_polygon": polygon,
        "spatial_factors": {},
        "subcategory_spatial_trend_rows": [],
        "subcategory_spatial_summary": [],
        "h3_evidence": h3_evidence,
        "yearly_grid_evidence": yearly_grid_evidence,
        "rule_summary": rule["summary"],
        "rule_insights": rule["insights"],
        "ai_summary": [],
        "ai_insights": {},
        "driver_analysis": [],
        "planning_implications": [],
        "report_title": "",
        "report_sections": [],
        "report_content": "",
        "ai_status": "pending",
        "ai_error": "",
        "error": "",
    }
    return base_payload
