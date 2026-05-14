from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from shapely.geometry import Point, shape
from shapely.prepared import prep

from modules.population.service import get_population_grid
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02


DEFAULT_POI_YEARS = [2020, 2022, 2024]


def normalize_years(years: Any) -> List[int]:
    normalized: List[int] = []
    for item in years or []:
        try:
            year = int(item)
        except (TypeError, ValueError):
            continue
        if year not in (2020, 2022, 2024, 2026):
            continue
        normalized.append(year)
    unique = sorted(set(normalized))
    return unique or DEFAULT_POI_YEARS[:]


def normalize_type_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def build_category_matchers(categories: List[Any]) -> Dict[str, Dict[str, Any]]:
    matchers: Dict[str, Dict[str, Any]] = {}
    for category in categories or []:
        cat_id = str(getattr(category, "id", "") or "").strip()
        if not cat_id:
            continue
        codes: List[str] = []
        for raw in str(getattr(category, "types", "") or "").split("|"):
            code = normalize_type_code(raw)
            if code and code not in codes:
                codes.append(code)
        matchers[cat_id] = {
            "id": cat_id,
            "name": str(getattr(category, "name", "") or cat_id),
            "codes": codes,
        }
    return matchers


def resolve_category_id(type_text: Any, matchers: Dict[str, Dict[str, Any]]) -> str:
    code = normalize_type_code(type_text)
    if not code:
        return ""
    for cat_id, matcher in matchers.items():
        for candidate in matcher.get("codes") or []:
            if code == candidate or code.startswith(candidate) or code[:2] == candidate[:2]:
                return cat_id
    return ""


def poi_exact_key(poi: Dict[str, Any]) -> str:
    poi_id = str((poi or {}).get("id") or "").strip()
    if poi_id:
        return f"id:{poi_id}"
    name = str((poi or {}).get("name") or "").strip()
    location = (poi or {}).get("location")
    if isinstance(location, (list, tuple)) and len(location) >= 2:
        try:
            return f"name_loc:{name}|{float(location[0]):.6f},{float(location[1]):.6f}"
        except (TypeError, ValueError):
            pass
    return f"name:{name}"


def deduplicate_pois(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for poi in pois or []:
        key = poi_exact_key(poi)
        if key in seen:
            continue
        seen.add(key)
        result.append(poi)
    return result


def select_display_year(results_by_year: List[Dict[str, Any]]) -> Optional[int]:
    successful = [
        int(item["year"])
        for item in results_by_year or []
        if int(item.get("count") or 0) > 0
    ]
    return max(successful) if successful else None


def build_summary_by_year(
    results_by_year: List[Dict[str, Any]],
    categories: List[Any],
) -> List[Dict[str, Any]]:
    matchers = build_category_matchers(categories)
    summaries: List[Dict[str, Any]] = []
    for item in results_by_year or []:
        counts = {cat_id: 0 for cat_id in matchers.keys()}
        for poi in item.get("pois") or []:
            cat_id = resolve_category_id((poi or {}).get("type"), matchers)
            if cat_id:
                counts[cat_id] = counts.get(cat_id, 0) + 1
        summaries.append(
            {
                "year": int(item.get("year")),
                "source": item.get("source") or "local",
                "count": int(item.get("count") or 0),
                "category_counts": counts,
            }
        )
    return summaries


def build_category_summary(
    pois: List[Dict[str, Any]],
    categories: List[Any],
) -> List[Dict[str, Any]]:
    matchers = build_category_matchers(categories)
    counts = {cat_id: 0 for cat_id in matchers.keys()}
    for poi in pois or []:
        cat_id = resolve_category_id((poi or {}).get("type"), matchers)
        if cat_id:
            counts[cat_id] = counts.get(cat_id, 0) + 1
    return [
        {
            "id": cat_id,
            "name": str(matcher.get("name") or cat_id),
            "count": int(counts.get(cat_id, 0)),
        }
        for cat_id, matcher in matchers.items()
    ]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        pass
    return default


def _safe_round(value: Any, digits: int = 6) -> float:
    return round(_safe_float(value), digits)


def _feature_area_km2(feature: Dict[str, Any]) -> float:
    geometry = (feature or {}).get("geometry") or {}
    try:
        geom_gcj02 = shape(geometry)
    except Exception:
        return 0.0
    if geom_gcj02.is_empty:
        return 0.0
    try:
        centroid = geom_gcj02.centroid
        lat = float(centroid.y)
        km_per_degree_lat = 110.574
        km_per_degree_lng = 111.320 * math.cos(math.radians(lat))
        return abs(float(geom_gcj02.area) * km_per_degree_lat * km_per_degree_lng)
    except Exception:
        return 0.0


def _poi_point(poi: Dict[str, Any], poi_coord_type: str) -> Optional[Point]:
    location = (poi or {}).get("location")
    if not isinstance(location, (list, tuple)) or len(location) < 2:
        return None
    try:
        lng = float(location[0])
        lat = float(location[1])
    except (TypeError, ValueError):
        return None
    if poi_coord_type == "wgs84":
        lng, lat = wgs84_to_gcj02(lng, lat)
    return Point(lng, lat)


def _resolve_category_name(cat_id: str, category_counts: Dict[str, Dict[str, Any]]) -> str:
    row = category_counts.get(cat_id) or {}
    return str(row.get("name") or cat_id)


def build_poi_shared_grid(
    *,
    polygon: list,
    coord_type: str = "gcj02",
    pois: List[Dict[str, Any]] | None = None,
    poi_coord_type: str = "gcj02",
    categories: List[Any] | None = None,
    year: int | None = None,
) -> Dict[str, Any]:
    grid = get_population_grid(polygon, coord_type)
    features = list(grid.get("features") or [])
    matchers = build_category_matchers(categories or [])
    category_counts = {
        cat_id: {"id": cat_id, "name": str(matcher.get("name") or cat_id), "count": 0}
        for cat_id, matcher in matchers.items()
    }

    cell_rows: Dict[str, Dict[str, Any]] = {}
    prepared_cells = []
    for feature in features:
        props = (feature or {}).get("properties") or {}
        cell_id = str(props.get("cell_id") or props.get("h3_id") or "").strip()
        if not cell_id:
            continue
        try:
            geom = shape((feature or {}).get("geometry") or {})
        except Exception:
            continue
        if geom.is_empty:
            continue
        area_km2 = _feature_area_km2(feature)
        row = {
            "cell_id": cell_id,
            "poi_count": 0,
            "category_counts": {},
            "area_km2": area_km2,
            "density_poi_per_km2": 0.0,
        }
        cell_rows[cell_id] = row
        prepared_cells.append((cell_id, geom, prep(geom)))

    assigned_poi_count = 0
    for poi in pois or []:
        point = _poi_point(poi, poi_coord_type)
        if point is None:
            continue
        matched_cell_id = ""
        for cell_id, geom, prepared in prepared_cells:
            if prepared.contains(point) or geom.touches(point):
                matched_cell_id = cell_id
                break
        if not matched_cell_id:
            continue
        assigned_poi_count += 1
        row = cell_rows[matched_cell_id]
        row["poi_count"] += 1
        cat_id = resolve_category_id((poi or {}).get("type"), matchers)
        if cat_id:
            row["category_counts"][cat_id] = int(row["category_counts"].get(cat_id, 0)) + 1
            if cat_id not in category_counts:
                category_counts[cat_id] = {"id": cat_id, "name": cat_id, "count": 0}
            category_counts[cat_id]["count"] = int(category_counts[cat_id].get("count") or 0) + 1

    density_values: List[float] = []
    max_poi_count = 0
    for row in cell_rows.values():
        area_km2 = _safe_float(row.get("area_km2"))
        poi_count = int(row.get("poi_count") or 0)
        max_poi_count = max(max_poi_count, poi_count)
        density = (poi_count / area_km2) if area_km2 > 0 else 0.0
        row["density_poi_per_km2"] = _safe_round(density, 6)
        density_values.append(row["density_poi_per_km2"])

    styled_features: List[Dict[str, Any]] = []
    for feature in features:
        props = dict((feature or {}).get("properties") or {})
        cell_id = str(props.get("cell_id") or props.get("h3_id") or "").strip()
        row = cell_rows.get(cell_id) or {}
        counts = dict(row.get("category_counts") or {})
        dominant_category = ""
        dominant_category_name = ""
        if counts:
            dominant_category = max(counts.items(), key=lambda item: int(item[1] or 0))[0]
            dominant_category_name = _resolve_category_name(dominant_category, category_counts)
        props.update(
            {
                "cell_id": cell_id,
                "h3_id": cell_id,
                "poi_count": int(row.get("poi_count") or 0),
                "density_poi_per_km2": _safe_round(row.get("density_poi_per_km2"), 6),
                "area_km2": _safe_round(row.get("area_km2"), 6),
                "category_counts": counts,
                "dominant_category": dominant_category,
                "dominant_category_name": dominant_category_name,
                "grid_type": "raster",
            }
        )
        styled_features.append(
            {
                "type": (feature or {}).get("type") or "Feature",
                "geometry": (feature or {}).get("geometry"),
                "properties": props,
            }
        )

    active_rows = [
        {
            "cell_id": cell_id,
            "poi_count": int(row.get("poi_count") or 0),
            "density_poi_per_km2": _safe_round(row.get("density_poi_per_km2"), 6),
            "dominant_category": (
                max((row.get("category_counts") or {}).items(), key=lambda item: int(item[1] or 0))[0]
                if row.get("category_counts") else ""
            ),
        }
        for cell_id, row in cell_rows.items()
        if int(row.get("poi_count") or 0) > 0
    ]
    for row in active_rows:
        row["dominant_category_name"] = _resolve_category_name(str(row.get("dominant_category") or ""), category_counts)
    active_rows.sort(key=lambda item: (int(item.get("poi_count") or 0), _safe_float(item.get("density_poi_per_km2"))), reverse=True)

    summary = {
        "grid_count": len(styled_features),
        "active_cell_count": len(active_rows),
        "poi_count": len(pois or []),
        "assigned_poi_count": assigned_poi_count,
        "max_poi_count": max_poi_count,
        "avg_density_poi_per_km2": _safe_round(sum(density_values) / len(density_values) if density_values else 0.0, 6),
        "top_cells": active_rows[:12],
        "category_counts": sorted(category_counts.values(), key=lambda item: int(item.get("count") or 0), reverse=True),
        "year": year,
    }
    return {
        "type": "FeatureCollection",
        "grid_type": "raster",
        "count": len(styled_features),
        "cell_count": len(styled_features),
        "features": styled_features,
        "summary": summary,
    }
