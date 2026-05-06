from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


_DIRECTIONS = [
    ("north", "北"),
    ("northeast", "东北"),
    ("east", "东"),
    ("southeast", "东南"),
    ("south", "南"),
    ("southwest", "西南"),
    ("west", "西"),
    ("northwest", "西北"),
]


def safe_round(value: float, digits: int = 6) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6371008.8
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return 2.0 * radius * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_point(raw: Any, subject_key: Optional[str] = None, value_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    lng = _to_float(raw.get("lng"))
    lat = _to_float(raw.get("lat"))
    if lng is None or lat is None:
        location = raw.get("location")
        if isinstance(location, (list, tuple)) and len(location) >= 2:
            lng = _to_float(location[0])
            lat = _to_float(location[1])
    if lng is None or lat is None:
        return None
    subject = _as_text(raw.get(subject_key or "subcategory") or raw.get("subcategory") or raw.get("category"))
    value = _to_float(raw.get(value_key)) if value_key else None
    return {
        "lng": lng,
        "lat": lat,
        "subject": subject or "未分类",
        "category": _as_text(raw.get("category")),
        "subcategory": _as_text(raw.get("subcategory")) or subject or "未分类小类",
        "area": _as_text(raw.get("area") or raw.get("adname") or raw.get("region")),
        "value": value if value is not None else 1.0,
    }


def _normalize_points(points: Iterable[Any], subject_key: Optional[str] = None, value_key: Optional[str] = None) -> List[Dict[str, Any]]:
    return [
        point
        for point in (_normalize_point(item, subject_key=subject_key, value_key=value_key) for item in points or [])
        if point is not None
    ]


def _resolve_center(points: List[Dict[str, Any]], center: Optional[List[float]] = None) -> List[float]:
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        lng = _to_float(center[0])
        lat = _to_float(center[1])
        if lng is not None and lat is not None:
            return [safe_round(lng, 6), safe_round(lat, 6)]
    if not points:
        return []
    return [
        safe_round(sum(float(item["lng"]) for item in points) / len(points), 6),
        safe_round(sum(float(item["lat"]) for item in points) / len(points), 6),
    ]


def _direction_key_for_point(lng: float, lat: float, center: List[float]) -> str:
    if len(center) < 2:
        return ""
    dx = float(lng) - float(center[0])
    dy = float(lat) - float(center[1])
    if abs(dx) <= 1e-12 and abs(dy) <= 1e-12:
        return "north"
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    idx = int(((bearing + 22.5) % 360.0) // 45.0)
    return _DIRECTIONS[idx][0]


def _direction_label(key: str) -> str:
    return dict(_DIRECTIONS).get(key, "")


def _centroid(points: List[Dict[str, Any]]) -> List[float]:
    if not points:
        return []
    weight_sum = sum(max(0.0, float(item.get("value") or 1.0)) for item in points)
    if weight_sum <= 1e-9:
        weight_sum = float(len(points))
        return [
            safe_round(sum(float(item["lng"]) for item in points) / weight_sum, 6),
            safe_round(sum(float(item["lat"]) for item in points) / weight_sum, 6),
        ]
    return [
        safe_round(sum(float(item["lng"]) * max(0.0, float(item.get("value") or 1.0)) for item in points) / weight_sum, 6),
        safe_round(sum(float(item["lat"]) * max(0.0, float(item.get("value") or 1.0)) for item in points) / weight_sum, 6),
    ]


def _direction_factor(points: List[Dict[str, Any]], center: List[float]) -> Dict[str, Any]:
    rows = {
        key: {"key": key, "label": label, "count": 0, "value": 0.0, "share": 0.0}
        for key, label in _DIRECTIONS
    }
    for point in points:
        key = _direction_key_for_point(float(point["lng"]), float(point["lat"]), center)
        if not key:
            continue
        rows[key]["count"] += 1
        rows[key]["value"] += max(0.0, float(point.get("value") or 1.0))
    total_value = sum(float(item["value"]) for item in rows.values())
    total_count = sum(int(item["count"]) for item in rows.values())
    for item in rows.values():
        item["value"] = safe_round(float(item["value"]), 6)
        item["share"] = safe_round(float(item["value"]) / total_value, 6) if total_value > 1e-9 else 0.0
    ranked = sorted(rows.values(), key=lambda item: (float(item["value"]), int(item["count"])), reverse=True)
    dominant = ranked[0] if ranked and (ranked[0]["count"] or ranked[0]["value"]) else {}
    secondary = ranked[1] if len(ranked) > 1 and (ranked[1]["count"] or ranked[1]["value"]) else {}
    return {
        "dominant_direction": str(dominant.get("label") or ""),
        "secondary_direction": str(secondary.get("label") or ""),
        "dominant_share": float(dominant.get("share") or 0.0),
        "secondary_share": float(secondary.get("share") or 0.0),
        "direction_rows": list(rows.values()),
        "point_count": total_count,
    }


def _ring_factor(points: List[Dict[str, Any]], center: List[float]) -> Dict[str, Any]:
    buckets = {
        "core": {"key": "core", "label": "核心圈层", "count": 0, "share": 0.0, "max_distance_m": 0.0},
        "middle": {"key": "middle", "label": "中圈层", "count": 0, "share": 0.0, "max_distance_m": 0.0},
        "outer": {"key": "outer", "label": "外围圈层", "count": 0, "share": 0.0, "max_distance_m": 0.0},
    }
    if len(center) < 2 or not points:
        return {"dominant_ring": "", "dominant_share": 0.0, "ring_rows": list(buckets.values()), "max_distance_m": 0.0}
    distances = [haversine_m(center[0], center[1], float(item["lng"]), float(item["lat"])) for item in points]
    max_distance = max(distances) if distances else 0.0
    core_threshold = max_distance / 3.0
    middle_threshold = max_distance * 2.0 / 3.0
    for distance in distances:
        if max_distance <= 1e-9 or distance <= core_threshold:
            key = "core"
        elif distance <= middle_threshold:
            key = "middle"
        else:
            key = "outer"
        buckets[key]["count"] += 1
        buckets[key]["max_distance_m"] = max(float(buckets[key]["max_distance_m"]), distance)
    total = max(1, len(points))
    for item in buckets.values():
        item["share"] = safe_round(int(item["count"]) / total, 6)
        item["max_distance_m"] = safe_round(float(item["max_distance_m"]), 2)
    ranked = sorted(buckets.values(), key=lambda item: (int(item["count"]), float(item["share"])), reverse=True)
    dominant = ranked[0] if ranked and int(ranked[0]["count"]) > 0 else {}
    return {
        "dominant_ring": str(dominant.get("label") or ""),
        "dominant_share": float(dominant.get("share") or 0.0),
        "ring_rows": list(buckets.values()),
        "max_distance_m": safe_round(max_distance, 2),
    }


def _hotspot_factor(points: List[Dict[str, Any]], center: List[float], grid_size: int = 4) -> Dict[str, Any]:
    if not points:
        return {"hotspot_grid_count": 0, "dominant_hotspot_direction": "", "hotspot_pattern": "none", "grid_rows": []}
    lngs = [float(item["lng"]) for item in points]
    lats = [float(item["lat"]) for item in points]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    span_lng = max(max_lng - min_lng, 1e-9)
    span_lat = max(max_lat - min_lat, 1e-9)
    grid_counts: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for point in points:
        gx = min(grid_size - 1, max(0, int(((float(point["lng"]) - min_lng) / span_lng) * grid_size)))
        gy = min(grid_size - 1, max(0, int(((float(point["lat"]) - min_lat) / span_lat) * grid_size)))
        cell = grid_counts.setdefault((gx, gy), {"gx": gx, "gy": gy, "count": 0, "points": []})
        cell["count"] += 1
        cell["points"].append(point)
    counts = sorted([int(item["count"]) for item in grid_counts.values()], reverse=True)
    threshold = max(2, counts[0] if len(points) < 8 else counts[max(0, min(len(counts) - 1, len(counts) // 4))])
    hotspots = [item for item in grid_counts.values() if int(item["count"]) >= threshold]
    if not hotspots and counts:
        threshold = counts[0]
        hotspots = [item for item in grid_counts.values() if int(item["count"]) >= threshold]
    rows = []
    direction_counter: Counter[str] = Counter()
    for item in hotspots:
        centroid = _centroid(item["points"])
        direction_key = _direction_key_for_point(centroid[0], centroid[1], center) if len(centroid) >= 2 else ""
        direction_counter[direction_key] += int(item["count"])
        rows.append(
            {
                "grid_key": f"{item['gx']},{item['gy']}",
                "count": int(item["count"]),
                "centroid": centroid,
                "direction": _direction_label(direction_key),
            }
        )
    dominant_key = direction_counter.most_common(1)[0][0] if direction_counter else ""
    if not hotspots:
        pattern = "none"
    elif len(hotspots) == 1:
        pattern = "single_core"
    elif len(hotspots) <= 3:
        pattern = "multi_core"
    else:
        pattern = "dispersed_hotspots"
    return {
        "hotspot_grid_count": len(hotspots),
        "dominant_hotspot_direction": _direction_label(dominant_key),
        "hotspot_pattern": pattern,
        "grid_rows": sorted(rows, key=lambda item: int(item["count"]), reverse=True)[:8],
    }


def build_point_spatial_factors(
    points: Iterable[Any],
    center: Optional[List[float]] = None,
    subject_key: Optional[str] = None,
    value_key: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = _normalize_points(points, subject_key=subject_key, value_key=value_key)
    resolved_center = _resolve_center(normalized, center)
    centroid = _centroid(normalized)
    return {
        "geometry_mode": "point",
        "center": resolved_center,
        "point_count": len(normalized),
        "centroid": centroid,
        "direction_factor": _direction_factor(normalized, resolved_center),
        "ring_factor": _ring_factor(normalized, resolved_center),
        "hotspot_factor": _hotspot_factor(normalized, resolved_center),
    }


def _shift_factor(first_points: List[Dict[str, Any]], last_points: List[Dict[str, Any]]) -> Dict[str, Any]:
    first_centroid = _centroid(first_points)
    last_centroid = _centroid(last_points)
    if len(first_centroid) < 2 or len(last_centroid) < 2:
        return {"from_centroid": first_centroid, "to_centroid": last_centroid, "direction": "", "distance_m": 0.0}
    direction_key = _direction_key_for_point(last_centroid[0], last_centroid[1], first_centroid)
    return {
        "from_centroid": first_centroid,
        "to_centroid": last_centroid,
        "direction": _direction_label(direction_key),
        "distance_m": safe_round(haversine_m(first_centroid[0], first_centroid[1], last_centroid[0], last_centroid[1]), 2),
    }


def build_subcategory_spatial_trends(
    year_summaries: Iterable[Dict[str, Any]],
    center: Optional[List[float]] = None,
    top_n: int = 6,
) -> Dict[str, Any]:
    summaries = sorted(
        [item for item in year_summaries or [] if isinstance(item, dict)],
        key=lambda item: float(item.get("year") or 0),
    )
    all_points = _normalize_points(point for summary in summaries for point in (summary.get("points") or []))
    resolved_center = _resolve_center(all_points, center)
    overall = build_point_spatial_factors(all_points, center=resolved_center)
    if len(summaries) < 2:
        return {"spatial_factors": overall, "subcategory_spatial_trend_rows": [], "subcategory_spatial_summary": []}

    first, last = summaries[0], summaries[-1]
    first_counts = dict(first.get("subcategory_counts") or {})
    last_counts = dict(last.get("subcategory_counts") or {})
    names = sorted(set(first_counts) | set(last_counts))
    parent_by_name: Dict[str, str] = {}
    for summary in summaries:
        for row in summary.get("top_subcategories") or []:
            if isinstance(row, dict) and row.get("name") and not parent_by_name.get(str(row.get("name"))):
                parent_by_name[str(row.get("name"))] = _as_text(row.get("parent"))

    ranked = sorted(
        [
            {
                "name": name,
                "parent": parent_by_name.get(name, ""),
                "start_count": int(first_counts.get(name) or 0),
                "end_count": int(last_counts.get(name) or 0),
                "delta": int(last_counts.get(name) or 0) - int(first_counts.get(name) or 0),
            }
            for name in names
        ],
        key=lambda item: (abs(int(item["delta"])), int(item["end_count"])),
        reverse=True,
    )[: max(1, int(top_n or 6))]

    first_points_by_subcategory: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    last_points_by_subcategory: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for point in _normalize_points(first.get("points") or []):
        first_points_by_subcategory[point["subcategory"]].append(point)
    for point in _normalize_points(last.get("points") or []):
        last_points_by_subcategory[point["subcategory"]].append(point)

    rows: List[Dict[str, Any]] = []
    for item in ranked:
        name = item["name"]
        first_points = first_points_by_subcategory.get(name, [])
        last_points = last_points_by_subcategory.get(name, [])
        if int(item.get("delta") or 0) == 0 or (not first_points and not last_points):
            continue
        factors = build_point_spatial_factors(last_points, center=resolved_center)
        before_hotspots = build_point_spatial_factors(first_points, center=resolved_center).get("hotspot_factor") or {}
        hotspot = factors.get("hotspot_factor") or {}
        direction = factors.get("direction_factor") or {}
        ring = factors.get("ring_factor") or {}
        shift = _shift_factor(first_points, last_points)
        area_counts = Counter(point.get("area") or "未知区域" for point in last_points)
        top_area = area_counts.most_common(1)[0][0] if area_counts else ""
        rows.append(
            {
                **item,
                "dominant_direction": direction.get("dominant_direction") or "",
                "secondary_direction": direction.get("secondary_direction") or "",
                "dominant_ring": ring.get("dominant_ring") or "",
                "dominant_ring_share": ring.get("dominant_share") or 0.0,
                "centroid_shift_direction": shift.get("direction") or "",
                "centroid_shift_m": shift.get("distance_m") or 0.0,
                "hotspot_grid_count": hotspot.get("hotspot_grid_count") or 0,
                "hotspot_grid_count_delta": int(hotspot.get("hotspot_grid_count") or 0) - int(before_hotspots.get("hotspot_grid_count") or 0),
                "hotspot_pattern": hotspot.get("hotspot_pattern") or "none",
                "dominant_hotspot_direction": hotspot.get("dominant_hotspot_direction") or "",
                "top_area": top_area,
            }
        )

    summary = []
    for row in rows[:3]:
        direction = row.get("dominant_direction") or "方向不明显"
        ring = row.get("dominant_ring") or "圈层不明显"
        delta = int(row.get("delta") or 0)
        summary.append(
            f"{row.get('name')}较首年{'增加' if delta >= 0 else '减少'}{abs(delta)}个，末年主要位于{direction}方向、{ring}。"
        )
    return {
        "spatial_factors": overall,
        "subcategory_spatial_trend_rows": rows,
        "subcategory_spatial_summary": summary,
    }
