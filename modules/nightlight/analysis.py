from __future__ import annotations

import math
from typing import Any

import numpy as np

from .common import (
    GRADIENT_VIEW_LABEL,
    HOTSPOT_VIEW_LABEL,
    round_float,
)
from .types import AggregatedNightlightCell

_HOTSPOT_CLASSES = [
    ("core_hotspot", "核心热点", "#fff7bc"),
    ("secondary_hotspot", "高亮热点", "#fde047"),
    ("emerging_hotspot", "次级热点", "#f59e0b"),
    ("transition", "过渡区", "#b45309"),
    ("low_light", "低亮区", "#52525b"),
]

_GRADIENT_CLASSES = [
    ("core_peak", "核心高亮", "#fff7bc"),
    ("inner_spread", "内圈扩散", "#fde047"),
    ("middle_decay", "中圈衰减", "#f59e0b"),
    ("outer_decay", "外圈衰减", "#c2410c"),
    ("fringe_dark", "边缘暗区", "#334155"),
]

_SECTOR_DIRECTIONS = [
    ("north", "北"),
    ("northeast", "东北"),
    ("east", "东"),
    ("southeast", "东南"),
    ("south", "南"),
    ("southwest", "西南"),
    ("west", "西"),
    ("northwest", "西北"),
]


def _categorical_legend(title: str, items: list[tuple[str, str, str]], unit: str) -> dict[str, Any]:
    return {
        "title": title,
        "kind": "categorical",
        "unit": unit,
        "min_value": 0.0,
        "max_value": float(max(0, len(items) - 1)),
        "stops": [
            {
                "ratio": round_float((idx / max(1, len(items) - 1)), 3),
                "color": color,
                "value": float(idx),
                "label": label,
            }
            for idx, (_, label, color) in enumerate(items)
        ],
    }


def _empty_analysis_payload() -> dict[str, Any]:
    return {
        "core_hotspot_count": 0,
        "secondary_hotspot_count": 0,
        "emerging_hotspot_count": 0,
        "transition_count": 0,
        "low_light_count": 0,
        "hotspot_cell_ratio": 0.0,
        "peak_radiance": 0.0,
        "peak_cell_id": None,
        "max_distance_km": 0.0,
        "core_band_count": 0,
        "middle_band_count": 0,
        "fringe_band_count": 0,
        "peak_to_edge_ratio": 0.0,
        "economic_activity_intensity_level": "low",
        "economic_activity_summary_text": "当前缺少可直接利用的夜间经济活动强度证据。",
        "sector_direction_analysis": _empty_sector_direction_analysis(),
    }


def _cell_value(cell: AggregatedNightlightCell) -> float:
    return max(0.0, float(cell.raw_value))


def _valid_cells(aggregated_cells: list[AggregatedNightlightCell]) -> list[AggregatedNightlightCell]:
    return [cell for cell in aggregated_cells if int(cell.valid_pixel_count) > 0]


def _empty_sector_direction_analysis() -> dict[str, Any]:
    return {
        "center_gcj02": [],
        "dominant_direction": "",
        "secondary_direction": "",
        "dominant_share": 0.0,
        "secondary_share": 0.0,
        "sectors": [
            {
                "key": key,
                "label": label,
                "total_radiance": 0.0,
                "mean_radiance": 0.0,
                "cell_count": 0,
                "hotspot_count": 0,
                "radiance_share": 0.0,
            }
            for key, label in _SECTOR_DIRECTIONS
        ],
    }


def _sector_key_for_point(point: list[float], center: list[float]) -> str:
    if len(point) < 2 or len(center) < 2:
        return ""
    dx = float(point[0]) - float(center[0])
    dy = float(point[1]) - float(center[1])
    if abs(dx) <= 1e-12 and abs(dy) <= 1e-12:
        return "north"
    # Bearing in degrees clockwise from north.
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    idx = int(((bearing + 22.5) % 360.0) // 45.0)
    return _SECTOR_DIRECTIONS[idx][0]


def build_sector_direction_analysis(
    aggregated_cells: list[AggregatedNightlightCell],
    center_gcj02: list[float] | None = None,
    hotspot_cell_ids: set[str] | None = None,
) -> dict[str, Any]:
    valid_cells = _valid_cells(aggregated_cells)
    if not valid_cells:
        return _empty_sector_direction_analysis()

    center = list(center_gcj02 or [])
    if len(center) < 2:
        center = [
            float(sum(float(cell.centroid_gcj02[0]) for cell in valid_cells) / len(valid_cells)),
            float(sum(float(cell.centroid_gcj02[1]) for cell in valid_cells) / len(valid_cells)),
        ]
    hotspot_ids = {str(item) for item in (hotspot_cell_ids or set())}
    rows = {
        key: {
            "key": key,
            "label": label,
            "total_radiance": 0.0,
            "mean_radiance": 0.0,
            "cell_count": 0,
            "hotspot_count": 0,
            "radiance_share": 0.0,
        }
        for key, label in _SECTOR_DIRECTIONS
    }
    for cell in valid_cells:
        key = _sector_key_for_point(list(cell.centroid_gcj02), center)
        if not key:
            continue
        row = rows[key]
        value = _cell_value(cell)
        row["total_radiance"] += value
        row["cell_count"] += 1
        if str(cell.cell_id) in hotspot_ids:
            row["hotspot_count"] += 1

    total = sum(float(row["total_radiance"]) for row in rows.values())
    for row in rows.values():
        count = int(row["cell_count"])
        row["total_radiance"] = round_float(float(row["total_radiance"]), 3)
        row["mean_radiance"] = round_float(float(row["total_radiance"]) / count, 3) if count > 0 else 0.0
        row["radiance_share"] = round_float(float(row["total_radiance"]) / total, 6) if total > 1e-9 else 0.0

    sectors = list(rows.values())
    ranked = sorted(sectors, key=lambda item: (float(item["total_radiance"]), int(item["cell_count"])), reverse=True)
    dominant = ranked[0] if ranked else {}
    secondary = ranked[1] if len(ranked) > 1 else {}
    return {
        "center_gcj02": [round_float(float(center[0]), 6), round_float(float(center[1]), 6)] if len(center) >= 2 else [],
        "dominant_direction": str(dominant.get("label") or ""),
        "secondary_direction": str(secondary.get("label") or ""),
        "dominant_share": float(dominant.get("radiance_share") or 0.0),
        "secondary_share": float(secondary.get("radiance_share") or 0.0),
        "sectors": sectors,
    }


def classify_economic_activity_intensity(
    summary: dict[str, Any],
    analysis: dict[str, Any],
) -> str:
    mean_radiance = float(summary.get("mean_radiance") or 0.0)
    p90_radiance = float(summary.get("p90_radiance") or 0.0)
    lit_pixel_ratio = float(summary.get("lit_pixel_ratio") or 0.0)
    hotspot_cell_ratio = float(analysis.get("hotspot_cell_ratio") or 0.0)
    peak_to_edge_ratio = float(analysis.get("peak_to_edge_ratio") or 0.0)
    score = 0.0
    if mean_radiance >= 8.0:
        score += 2.0
    elif mean_radiance >= 3.0:
        score += 1.0
    if p90_radiance >= 12.0:
        score += 1.0
    if lit_pixel_ratio >= 0.8:
        score += 1.0
    elif lit_pixel_ratio >= 0.4:
        score += 0.5
    if hotspot_cell_ratio >= 0.3:
        score += 1.0
    if peak_to_edge_ratio >= 2.0:
        score += 1.0
    if score >= 5.0:
        return "high"
    if score >= 3.5:
        return "medium_high"
    if score >= 1.5:
        return "medium"
    return "low"


def economic_activity_level_label(level: str) -> str:
    return {
        "high": "高",
        "medium_high": "中等偏上",
        "medium": "中等",
        "low": "偏低",
    }.get(str(level or ""), "偏低")


def enrich_economic_activity_analysis(
    summary: dict[str, Any],
    analysis: dict[str, Any],
    aggregated_cells: list[AggregatedNightlightCell],
    center_gcj02: list[float] | None = None,
    hotspot_cell_ids: set[str] | None = None,
) -> dict[str, Any]:
    payload = dict(analysis or {})
    sector_analysis = build_sector_direction_analysis(
        aggregated_cells,
        center_gcj02=center_gcj02,
        hotspot_cell_ids=hotspot_cell_ids,
    )
    level = classify_economic_activity_intensity(summary or {}, payload)
    dominant = str(sector_analysis.get("dominant_direction") or "")
    secondary = str(sector_analysis.get("secondary_direction") or "")
    direction_text = f"，亮度高值主要集中在{dominant}" + (f"与{secondary}扇区" if secondary else "扇区") if dominant else ""
    payload.update(
        {
            "economic_activity_intensity_level": level,
            "economic_activity_summary_text": (
                f"基于夜间灯光亮度，等时圈内经济活动强度呈现{economic_activity_level_label(level)}水平{direction_text}。"
            ),
            "sector_direction_analysis": sector_analysis,
        }
    )
    return payload


def _descending_quantiles(values: np.ndarray, quantiles: list[float]) -> list[float]:
    if values.size <= 0:
        return [0.0 for _ in quantiles]
    thresholds = [float(np.percentile(values, q)) for q in quantiles]
    for idx in range(1, len(thresholds)):
        if thresholds[idx] > thresholds[idx - 1]:
            thresholds[idx] = thresholds[idx - 1]
    return thresholds


def build_hotspot_layer_cells(
    aggregated_cells: list[AggregatedNightlightCell],
    unit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    analysis = _empty_analysis_payload()
    legend = _categorical_legend(HOTSPOT_VIEW_LABEL, _HOTSPOT_CLASSES, unit)
    if not aggregated_cells:
        return [], legend, analysis

    valid_cells = _valid_cells(aggregated_cells)
    if not valid_cells:
        return _build_no_data_cells(aggregated_cells), legend, analysis

    values = np.asarray([_cell_value(cell) for cell in valid_cells], dtype=np.float64)
    positive = values[values > 0]
    if positive.size <= 0:
        return _build_low_light_cells(aggregated_cells, unit), legend, analysis

    q90, q75, q55, q25 = _descending_quantiles(positive, [90, 75, 55, 25])
    class_counts = {key: 0 for key, _, _ in _HOTSPOT_CLASSES}
    peak_cell = max(valid_cells, key=_cell_value)
    hotspot_total = 0
    hotspot_cell_ids: set[str] = set()
    cells = []
    for cell in aggregated_cells:
        raw_value = _cell_value(cell)
        valid_pixel_count = int(max(0, int(cell.valid_pixel_count)))
        has_data = valid_pixel_count > 0
        if not has_data:
            cells.append(_no_data_payload(cell, "无有效夜光像素"))
            continue

        if raw_value >= q90:
            key, label, color = _HOTSPOT_CLASSES[0]
        elif raw_value >= q75:
            key, label, color = _HOTSPOT_CLASSES[1]
        elif raw_value >= q55:
            key, label, color = _HOTSPOT_CLASSES[2]
        elif raw_value >= q25:
            key, label, color = _HOTSPOT_CLASSES[3]
        else:
            key, label, color = _HOTSPOT_CLASSES[4]
        class_counts[key] += 1
        if key in {"core_hotspot", "secondary_hotspot", "emerging_hotspot"}:
            hotspot_total += 1
            hotspot_cell_ids.add(str(cell.cell_id))
        cells.append(
            {
                "cell_id": str(cell.cell_id),
                "value": round_float(raw_value, 3),
                "valid_pixel_count": valid_pixel_count,
                "has_data": True,
                "class_key": key,
                "class_label": label,
                "fill_color": color,
                "stroke_color": "#ffffff" if key == "core_hotspot" else "#d6d3d1",
                "fill_opacity": 0.34 if key == "low_light" else 0.58,
                "label": f"{label} | {round_float(raw_value, 2)} {unit}",
            }
        )

    analysis.update(
        {
            "core_hotspot_count": int(class_counts["core_hotspot"]),
            "secondary_hotspot_count": int(class_counts["secondary_hotspot"]),
            "emerging_hotspot_count": int(class_counts["emerging_hotspot"]),
            "transition_count": int(class_counts["transition"]),
            "low_light_count": int(class_counts["low_light"]),
            "hotspot_cell_ratio": round_float(hotspot_total / max(1, len(valid_cells)), 6),
            "peak_radiance": round_float(_cell_value(peak_cell), 3),
            "peak_cell_id": str(peak_cell.cell_id),
            "_hotspot_cell_ids": hotspot_cell_ids,
        }
    )
    return cells, legend, analysis


def _haversine_km(a: list[float], b: list[float]) -> float:
    lng1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lng2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lng = lng2 - lng1
    d_lat = lat2 - lat1
    hav = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * (math.sin(d_lng / 2.0) ** 2)
    )
    return 6371.0 * 2.0 * math.atan2(math.sqrt(hav), math.sqrt(max(1e-12, 1.0 - hav)))


def build_gradient_layer_cells(
    aggregated_cells: list[AggregatedNightlightCell],
    unit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    analysis = _empty_analysis_payload()
    legend = _categorical_legend(GRADIENT_VIEW_LABEL, _GRADIENT_CLASSES, unit)
    if not aggregated_cells:
        return [], legend, analysis

    valid_cells = _valid_cells(aggregated_cells)
    if not valid_cells:
        return _build_no_data_cells(aggregated_cells), legend, analysis

    peak_cell = max(valid_cells, key=_cell_value)
    peak_value = max(_cell_value(peak_cell), 1e-9)
    peak_centroid = list(peak_cell.centroid_gcj02)
    distances = np.asarray(
        [_haversine_km(list(cell.centroid_gcj02), peak_centroid) for cell in valid_cells],
        dtype=np.float64,
    )
    max_distance = float(np.max(distances)) if distances.size else 0.0
    distance_map = {
        str(cell.cell_id): float(distances[idx])
        for idx, cell in enumerate(valid_cells)
    }
    class_counts = {key: 0 for key, _, _ in _GRADIENT_CLASSES}
    edge_values: list[float] = []
    cells = []
    for cell in aggregated_cells:
        raw_value = _cell_value(cell)
        valid_pixel_count = int(max(0, int(cell.valid_pixel_count)))
        has_data = valid_pixel_count > 0
        if not has_data:
            cells.append(_no_data_payload(cell, "无有效夜光像素"))
            continue

        distance_km = float(distance_map.get(str(cell.cell_id), 0.0))
        distance_ratio = 0.0 if max_distance <= 1e-9 else max(0.0, min(1.0, distance_km / max_distance))
        energy_ratio = max(0.0, min(1.0, raw_value / peak_value))
        gradient_score = (0.65 * energy_ratio) + (0.35 * (1.0 - distance_ratio))

        if gradient_score >= 0.82:
            key, label, color = _GRADIENT_CLASSES[0]
        elif gradient_score >= 0.62:
            key, label, color = _GRADIENT_CLASSES[1]
        elif gradient_score >= 0.42:
            key, label, color = _GRADIENT_CLASSES[2]
        elif gradient_score >= 0.22:
            key, label, color = _GRADIENT_CLASSES[3]
        else:
            key, label, color = _GRADIENT_CLASSES[4]
        class_counts[key] += 1
        if key in {"outer_decay", "fringe_dark"}:
            edge_values.append(raw_value)

        cells.append(
            {
                "cell_id": str(cell.cell_id),
                "value": round_float(raw_value, 3),
                "valid_pixel_count": valid_pixel_count,
                "has_data": True,
                "class_key": key,
                "class_label": label,
                "fill_color": color,
                "stroke_color": "#ffffff" if key == "core_peak" else "#cbd5e1",
                "fill_opacity": 0.38 if key == "fringe_dark" else 0.58,
                "label": f"{label} | {round_float(distance_km, 2)} km | {round_float(raw_value, 2)} {unit}",
            }
        )

    edge_mean = float(np.mean(edge_values)) if edge_values else 0.0
    analysis.update(
        {
            "peak_radiance": round_float(_cell_value(peak_cell), 3),
            "peak_cell_id": str(peak_cell.cell_id),
            "max_distance_km": round_float(max_distance, 3),
            "core_band_count": int(class_counts["core_peak"]),
            "middle_band_count": int(class_counts["inner_spread"] + class_counts["middle_decay"]),
            "fringe_band_count": int(class_counts["outer_decay"] + class_counts["fringe_dark"]),
            "peak_to_edge_ratio": round_float((peak_value / edge_mean), 3) if edge_mean > 1e-9 else 0.0,
        }
    )
    return cells, legend, analysis


def _no_data_payload(cell: AggregatedNightlightCell, label: str) -> dict[str, Any]:
    return {
        "cell_id": str(cell.cell_id),
        "value": round_float(_cell_value(cell), 3),
        "valid_pixel_count": int(max(0, int(cell.valid_pixel_count))),
        "has_data": False,
        "class_key": None,
        "class_label": None,
        "fill_color": "#94a3b8",
        "stroke_color": "#64748b",
        "fill_opacity": 0.16,
        "label": label,
    }


def _build_no_data_cells(aggregated_cells: list[AggregatedNightlightCell]) -> list[dict[str, Any]]:
    return [_no_data_payload(cell, "无有效夜光像素") for cell in aggregated_cells]


def _build_low_light_cells(
    aggregated_cells: list[AggregatedNightlightCell],
    unit: str,
) -> list[dict[str, Any]]:
    low_light_color = _HOTSPOT_CLASSES[-1][2]
    cells = []
    for cell in aggregated_cells:
        valid_pixel_count = int(max(0, int(cell.valid_pixel_count)))
        if valid_pixel_count <= 0:
            cells.append(_no_data_payload(cell, "无有效夜光像素"))
            continue
        cells.append(
            {
                "cell_id": str(cell.cell_id),
                "value": round_float(_cell_value(cell), 3),
                "valid_pixel_count": valid_pixel_count,
                "has_data": True,
                "class_key": "low_light",
                "class_label": "低亮区",
                "fill_color": low_light_color,
                "stroke_color": "#d6d3d1",
                "fill_opacity": 0.34,
                "label": f"低亮区 | {round_float(_cell_value(cell), 2)} {unit}",
            }
        )
    return cells
