from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Optional, Tuple

from .geometry import haversine_m, safe_round


def select_metric_columns(fieldnames: List[str], metric_key: str, radius_label_from_header) -> Dict[str, str]:
    chosen: Dict[str, str] = {}
    best_len: Dict[str, int] = {}
    for name in fieldnames:
        lower = (name or "").strip().lower()
        if metric_key not in lower:
            continue
        if "wgt" in lower or "route weight" in lower or "[slw]" in lower:
            continue
        label = radius_label_from_header(name)
        length = len(name)
        prev = best_len.get(label)
        if prev is None or length < prev:
            chosen[label] = name
            best_len[label] = length
    return chosen


def extract_finite_column_values(rows: List[Dict[str, Any]], column_name: str) -> List[float]:
    values: List[float] = []
    if not column_name:
        return values
    for row in rows:
        try:
            value = float(row.get(column_name, ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def column_numeric_stats(rows: List[Dict[str, Any]], column_name: str) -> Tuple[int, float, int]:
    values = extract_finite_column_values(rows, column_name)
    if not values:
        return 0, 0.0, 0
    spread = float(max(values) - min(values))
    distinct_count = len({round(v, 10) for v in values})
    return len(values), spread, distinct_count


def select_single_metric_column(
    fieldnames: List[str],
    include_patterns: List[Tuple[str, ...]],
    rows: Optional[List[Dict[str, Any]]] = None,
    preferred_tokens: Optional[Tuple[str, ...]] = None,
) -> Optional[str]:
    excluded_tokens = (
        "wgt",
        "route weight",
        "[slw]",
        "segment id",
        "line id",
        "point id",
        "entity id",
        "p-value",
        "pvalue",
        "zscore",
        "z-score",
        "quantile",
        "percentile",
        "rank",
    )
    best_name: Optional[str] = None
    best_rank: Optional[Tuple[int, int, int, float, int, int, int, int]] = None
    for name in fieldnames:
        lower = (name or "").strip().lower()
        if not lower:
            continue
        if any(token in lower for token in excluded_tokens):
            continue
        matched_rank: Optional[int] = None
        for idx, pattern in enumerate(include_patterns):
            if pattern and all((token or "").lower() in lower for token in pattern):
                matched_rank = idx
                break
        if matched_rank is None:
            continue
        valid_count = 0
        spread = 0.0
        distinct_count = 0
        if rows is not None and rows:
            valid_count, spread, distinct_count = column_numeric_stats(rows, name)
        preferred_hit = 0
        if preferred_tokens:
            preferred_hit = 1 if any((token or "").lower() in lower for token in preferred_tokens) else 0
        rank = (
            1 if valid_count > 0 else 0,
            valid_count,
            1 if spread > 1e-12 else 0,
            spread,
            distinct_count,
            preferred_hit,
            -matched_rank,
            -len(name),
        )
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_name = name
    return best_name


def metric_bounds(values_by_label: Dict[str, List[float]]) -> Dict[str, Tuple[float, float]]:
    bounds: Dict[str, Tuple[float, float]] = {}
    for label, values in values_by_label.items():
        finite = [float(v) for v in values if math.isfinite(float(v))]
        if not finite:
            continue
        bounds[label] = (min(finite), max(finite))
    return bounds


def norm(value: Optional[float], bounds: Optional[Tuple[float, float]]) -> float:
    if value is None or bounds is None:
        return 0.0
    low, high = bounds
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (float(value) - low) / (high - low)))


def pearson_corr(xs: List[float], ys: List[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    total = float(len(xs))
    mean_x = sum(xs) / total
    mean_y = sum(ys) / total
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for x, y in zip(xs, ys):
        dx = float(x) - mean_x
        dy = float(y) - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    if var_x <= 0.0 or var_y <= 0.0:
        return 0.0
    return cov / math.sqrt(var_x * var_y)


def linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0, 0.0
    total = float(len(xs))
    mean_x = sum(xs) / total
    mean_y = sum(ys) / total
    var_x = 0.0
    cov_xy = 0.0
    for x, y in zip(xs, ys):
        dx = float(x) - mean_x
        dy = float(y) - mean_y
        var_x += dx * dx
        cov_xy += dx * dy
    if var_x <= 0.0:
        return 0.0, mean_y
    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x
    return float(slope), float(intercept)


def percentile_rank(sorted_values: List[float], value: float) -> float:
    if not sorted_values:
        return 0.0
    idx = bisect.bisect_right(sorted_values, float(value))
    return max(0.0, min(1.0, idx / float(len(sorted_values))))


def quantile_value(sorted_values: List[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    qq = max(0.0, min(1.0, float(q)))
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = qq * (len(sorted_values) - 1)
    low = int(math.floor(pos))
    high = min(len(sorted_values) - 1, low + 1)
    t = pos - low
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * t)


def sample_scatter_points(
    points: List[Tuple[float, float]],
    max_points: int = 3000,
    bins: int = 20,
) -> List[Tuple[float, float]]:
    if len(points) <= max_points:
        return list(points)
    if max_points <= 0:
        return []

    clean = [
        (float(x), float(y))
        for x, y in points
        if math.isfinite(float(x)) and math.isfinite(float(y))
    ]
    if len(clean) <= max_points:
        return clean
    if not clean:
        return []
    clean.sort(key=lambda point: (point[0], point[1]))
    bucket_count = max(1, int(bins))
    buckets: List[List[Tuple[float, float]]] = [[] for _ in range(bucket_count)]
    total_len = len(clean)
    for idx, point in enumerate(clean):
        bucket_id = int((idx * bucket_count) / float(total_len))
        bucket_id = max(0, min(bucket_count - 1, bucket_id))
        buckets[bucket_id].append(point)

    total_n = float(len(clean))
    quotas: List[int] = [0 for _ in range(bucket_count)]
    frac_parts: List[Tuple[float, int]] = []
    used = 0
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        exact = (len(bucket) / total_n) * max_points
        base = int(math.floor(exact))
        base = max(1, min(base, len(bucket)))
        quotas[idx] = base
        used += base
        frac_parts.append((exact - math.floor(exact), idx))

    if used > max_points:
        over = used - max_points
        reducible = sorted(
            [(quotas[idx], idx) for idx in range(bucket_count) if quotas[idx] > 1],
            reverse=True,
        )
        reduce_idx = 0
        while over > 0 and reducible:
            _, bucket_id = reducible[reduce_idx % len(reducible)]
            if quotas[bucket_id] > 1:
                quotas[bucket_id] -= 1
                over -= 1
            reduce_idx += 1
            reducible = [(quotas[idx], idx) for _, idx in reducible if quotas[idx] > 1]
        used = sum(quotas)

    if used < max_points:
        remain = max_points - used
        for _, bucket_id in sorted(frac_parts, reverse=True):
            if remain <= 0:
                break
            cap = len(buckets[bucket_id]) - quotas[bucket_id]
            if cap <= 0:
                continue
            take = min(cap, remain)
            quotas[bucket_id] += take
            remain -= take

    sampled: List[Tuple[float, float]] = []
    for idx, bucket in enumerate(buckets):
        quota = quotas[idx]
        if quota <= 0 or not bucket:
            continue
        ordered = sorted(bucket, key=lambda point: (point[1], point[0]))
        if quota >= len(ordered):
            sampled.extend(ordered)
            continue
        if quota == 1:
            sampled.append(ordered[len(ordered) // 2])
            continue
        step = (len(ordered) - 1) / float(quota - 1)
        for pick_idx in range(quota):
            row_idx = int(round(pick_idx * step))
            row_idx = max(0, min(len(ordered) - 1, row_idx))
            sampled.append(ordered[row_idx])

    if len(sampled) > max_points:
        sampled = sampled[:max_points]
    return sampled


_ORIENTATION_LABELS = {
    "east_west": "东西向",
    "north_south": "南北向",
    "northeast_southwest": "东北-西南向",
    "northwest_southeast": "西北-东南向",
}


def classify_axis_orientation(lon1: float, lat1: float, lon2: float, lat2: float) -> str:
    dx = float(lon2) - float(lon1)
    dy = float(lat2) - float(lat1)
    if abs(dx) <= 1e-12 and abs(dy) <= 1e-12:
        return ""
    angle = (math.degrees(math.atan2(dy, dx)) + 180.0) % 180.0
    if angle < 22.5 or angle >= 157.5:
        return "east_west"
    if angle < 67.5:
        return "northeast_southwest"
    if angle < 112.5:
        return "north_south"
    return "northwest_southeast"


def build_road_orientation_analysis(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets = {
        key: {
            "key": key,
            "label": label,
            "length_km": 0.0,
            "length_share": 0.0,
            "edge_count": 0,
        }
        for key, label in _ORIENTATION_LABELS.items()
    }
    for feature in features or []:
        geometry = (feature or {}).get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        coords = geometry.get("coordinates") or []
        clean: List[List[float]] = []
        for point in coords:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                try:
                    clean.append([float(point[0]), float(point[1])])
                except (TypeError, ValueError):
                    continue
        for a, b in zip(clean, clean[1:]):
            key = classify_axis_orientation(a[0], a[1], b[0], b[1])
            if not key:
                continue
            length_km = haversine_m(a[0], a[1], b[0], b[1]) / 1000.0
            buckets[key]["length_km"] += max(0.0, float(length_km))
            buckets[key]["edge_count"] += 1

    total_length = sum(float(item["length_km"]) for item in buckets.values())
    for item in buckets.values():
        item["length_km"] = safe_round(float(item["length_km"]), 4)
        item["length_share"] = safe_round(float(item["length_km"]) / total_length, 6) if total_length > 1e-9 else 0.0
    rows = list(buckets.values())
    ranked = sorted(rows, key=lambda item: (float(item["length_km"]), int(item["edge_count"])), reverse=True)
    dominant = ranked[0] if ranked and float(ranked[0]["length_km"]) > 0 else {}
    secondary = ranked[1] if len(ranked) > 1 and float(ranked[1]["length_km"]) > 0 else {}
    return {
        "dominant_orientation": str(dominant.get("label") or ""),
        "secondary_orientation": str(secondary.get("label") or ""),
        "dominant_share": float(dominant.get("length_share") or 0.0),
        "secondary_share": float(secondary.get("length_share") or 0.0),
        "orientation_rows": rows,
    }
