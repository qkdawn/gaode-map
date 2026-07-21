#!/usr/bin/env python3
"""Deterministic direction/distance fusion for a shared spatial grid.

This is a data-plane helper. It computes comparable spatial summaries only; it
never invents business conclusions, traffic, revenue, or ROI.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRECTION_LABELS = {"N": "北", "NE": "东北", "E": "东", "SE": "东南", "S": "南", "SW": "西南", "W": "西", "NW": "西北"}
DEFAULT_BANDS = ((0.0, 500.0), (500.0, 1000.0), (1000.0, 1600.0))
CATEGORY_LABELS = {
    "050000": "餐饮", "060000": "购物", "080000": "体育休闲", "090000": "医疗",
    "100000": "住宿", "110000": "风景名胜", "120000": "商务住宅", "130000": "政府机构",
    "140000": "科教文化", "150000": "交通", "170000": "公司",
}


def _unwrap_grid(raw: Any) -> list[dict[str, Any]]:
    payload = raw.get("payload", raw) if isinstance(raw, dict) else raw
    if isinstance(payload, dict) and "grid" in payload:
        grid = payload["grid"]
    else:
        grid = payload
    if isinstance(grid, dict) and grid.get("type") == "FeatureCollection":
        features = grid.get("features", [])
    elif isinstance(grid, dict):
        features = grid.get("features", grid.get("rows", []))
    else:
        features = grid
    if not isinstance(features, list):
        raise ValueError("shared grid must contain a feature list")
    rows: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", feature)
        if not isinstance(props, dict):
            continue
        centroid = props.get("centroid_gcj02") or props.get("centroid")
        if not isinstance(centroid, (list, tuple)) or len(centroid) < 2:
            geometry = feature.get("geometry") or {}
            coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
            centroid = _polygon_centroid(coords)
        if not isinstance(centroid, (list, tuple)) or len(centroid) < 2:
            raise ValueError(f"cell {props.get('cell_id', '<unknown>')} has no centroid")
        row = dict(props)
        row["centroid_gcj02"] = [float(centroid[0]), float(centroid[1])]
        rows.append(row)
    if not rows:
        raise ValueError("shared grid is empty")
    return rows


def _polygon_centroid(coords: Any) -> list[float] | None:
    try:
        ring = coords[0] if coords and isinstance(coords[0], list) else coords
        points = [(float(p[0]), float(p[1])) for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(points) < 3:
            return None
        return [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]
    except (TypeError, ValueError, IndexError):
        return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in {"true", "1", "yes"}:
            return True
        if value.lower() in {"false", "0", "no"}:
            return False
    return bool(value)


def _distance_and_direction(center: tuple[float, float], point: tuple[float, float]) -> tuple[float, str]:
    lon0, lat0 = center
    lon, lat = point
    lat_mid = math.radians((lat0 + lat) / 2.0)
    dx = (lon - lon0) * 111.32 * math.cos(lat_mid)
    dy = (lat - lat0) * 111.32
    distance = math.hypot(dx, dy) * 1000.0
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    index = int((bearing + 22.5) // 45.0) % 8
    return distance, DIRECTIONS[index]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    pos = (len(values) - 1) * q
    lower, upper = math.floor(pos), math.ceil(pos)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (pos - lower)


def _band_label(start: float, end: float) -> str:
    return f"{int(start)}-{int(end)}m"


def _weighted_mean(rows: list[dict[str, Any]], key: str) -> float:
    total_area = sum(_num(r.get("area_km2"), 1.0) for r in rows)
    if not total_area:
        return 0.0
    return sum(_num(r.get(key)) * _num(r.get("area_km2"), 1.0) for r in rows) / total_area


def _summary(rows: list[dict[str, Any]], *, baseline: dict[str, float], category_labels: dict[str, str]) -> dict[str, Any]:
    area = sum(_num(r.get("area_km2"), 1.0) for r in rows)
    poi_count = sum(int(round(_num(r.get("poi_count")))) for r in rows)
    covered = [r for r in rows if r["road_covered"]]
    category_counts: dict[str, int] = {}
    for row in rows:
        counts = row.get("category_counts") or {}
        if isinstance(counts, dict):
            for category, count in counts.items():
                category_counts[str(category)] = category_counts.get(str(category), 0) + int(round(_num(count)))
    top_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    result = {
        "cells": len(rows),
        "area_km2": round(area, 4),
        "poi_count": poi_count,
        "poi_density": round(poi_count / area, 1) if area else 0.0,
        "population_density": round(_weighted_mean(rows, "population_density"), 1),
        "nightlight_mean": round(_weighted_mean(rows, "nightlight_radiance"), 1),
        "road_covered_cells": len(covered),
        "road_coverage_ratio": round(len(covered) / len(rows), 3) if rows else 0.0,
        "road_density_covered_mean": round(_weighted_mean(covered, "road_length_km_per_km2"), 1) if covered else None,
        "road_integration_covered_mean": round(_weighted_mean(covered, "road_integration"), 3) if covered else None,
        "top_categories": [[category_labels.get(k, k), v] for k, v in top_categories],
    }
    result["relative_to_overall"] = {
        "poi_density": round(result["poi_density"] / baseline["poi_density"], 2) if baseline["poi_density"] else None,
        "population_density": round(result["population_density"] / baseline["population_density"], 2) if baseline["population_density"] else None,
        "nightlight_mean": round(result["nightlight_mean"] / baseline["nightlight_mean"], 2) if baseline["nightlight_mean"] else None,
        "road_integration_covered_mean": round(result["road_integration_covered_mean"] / baseline["road_integration_covered_mean"], 2) if result["road_integration_covered_mean"] is not None and baseline["road_integration_covered_mean"] else None,
    }
    result["signals"] = {
        "poi_above_overall": result["poi_density"] > baseline["poi_density"],
        "population_above_overall": result["population_density"] > baseline["population_density"],
        "nightlight_above_overall": result["nightlight_mean"] > baseline["nightlight_mean"],
        "road_coverage_available": bool(covered),
        "road_integration_above_overall": result["road_integration_covered_mean"] is not None and baseline["road_integration_covered_mean"] is not None and result["road_integration_covered_mean"] > baseline["road_integration_covered_mean"],
    }
    return result


def analyze(rows: list[dict[str, Any]], center: tuple[float, float], bands: tuple[tuple[float, float], ...]) -> dict[str, Any]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        point = row["centroid_gcj02"]
        distance, direction = _distance_and_direction(center, (point[0], point[1]))
        road_covered = _bool(row.get("road_covered"))
        if road_covered is None:
            road_covered = _num(row.get("road_length_km_per_km2")) > 0.0
        item = dict(row)
        item.update({"distance_m": round(distance, 1), "sector": direction, "road_covered": road_covered})
        prepared.append(item)
    area = sum(_num(r.get("area_km2"), 1.0) for r in prepared)
    baseline = {
        "poi_density": sum(int(round(_num(r.get("poi_count")))) for r in prepared) / area if area else 0.0,
        "population_density": _weighted_mean(prepared, "population_density"),
        "nightlight_mean": _weighted_mean(prepared, "nightlight_radiance"),
        "road_integration_covered_mean": _weighted_mean([r for r in prepared if r["road_covered"]], "road_integration") if any(r["road_covered"] for r in prepared) else 0.0,
    }
    sectors = []
    for direction in DIRECTIONS:
        group = [r for r in prepared if r["sector"] == direction]
        summary = _summary(group, baseline=baseline, category_labels=CATEGORY_LABELS)
        summary.update({"sector": direction, "label": DIRECTION_LABELS[direction], "distance_band": "0-1600m"})
        sectors.append(summary)
    bands_out = []
    for start, end in bands:
        for direction in DIRECTIONS:
            group = [r for r in prepared if r["sector"] == direction and start <= r["distance_m"] < end]
            summary = _summary(group, baseline=baseline, category_labels=CATEGORY_LABELS)
            summary.update({"sector": direction, "label": DIRECTION_LABELS[direction], "distance_band": _band_label(start, end), "distance_start_m": start, "distance_end_m": end})
            bands_out.append(summary)
    threshold_source = {"poi_density_p75": _percentile([_num(r.get("density_poi_per_km2")) for r in prepared], .75), "population_density_p75": _percentile([_num(r.get("population_density")) for r in prepared], .75), "nightlight_p75": _percentile([_num(r.get("nightlight_radiance")) for r in prepared], .75), "road_integration_p75_covered": _percentile([_num(r.get("road_integration")) for r in prepared if r["road_covered"]], .75), "road_connectivity_p25_covered": _percentile([_num(r.get("road_connectivity")) for r in prepared if r["road_covered"]], .25)}
    all_summary = _summary(prepared, baseline=baseline, category_labels=CATEGORY_LABELS)
    return {
        "schema_version": "directional-fusion.v1",
        "center_gcj02": list(center),
        "scope_definition": {"grid_type": "shared_grid", "cell_count": len(prepared), "direction_method": "栅格中心点相对项目中心，按八方位划分", "distance_bands": [_band_label(a, b) for a, b in bands]},
        "comparison_baseline": {"type": "all_shared_cells", "summary": all_summary},
        "thresholds": {key: round(value, 3) for key, value in threshold_source.items()},
        "all_summary": all_summary,
        "sectors": sectors,
        "distance_bands": bands_out,
        "rows": [{"cell_id": r.get("cell_id"), "sector": r["sector"], "distance_m": r["distance_m"], "poi_count": int(round(_num(r.get("poi_count")))), "poi_density": round(_num(r.get("density_poi_per_km2")), 1), "population_density": round(_num(r.get("population_density")), 1), "nightlight": round(_num(r.get("nightlight_radiance")), 1), "road_covered": r["road_covered"], "road_density_km_per_km2": round(_num(r.get("road_length_km_per_km2")), 1), "road_integration": round(_num(r.get("road_integration")), 3), "road_connectivity": round(_num(r.get("road_connectivity")), 3)} for r in sorted(prepared, key=lambda r: (r["distance_m"], DIRECTIONS.index(r["sector"]), str(r.get("cell_id"))))],
        "limitations": ["同一共享栅格用于对齐来源；POI、人口、夜光和路网描述空间条件，不代表客流、消费、营收或投资回报。", "来源年份和采集口径可能不同，报告必须标注各来源年份；方向结果只用于空间比较和现场核验优先级。"],
    }


def _svg(result: dict[str, Any]) -> str:
    sectors = result["sectors"]
    width, height = 1080, 720
    x0, y0, row_h = 260, 112, 56
    colors = {"poi_density": "#1769aa", "population_density": "#2f855a", "nightlight_mean": "#d69e2e", "road_integration_covered_mean": "#805ad5"}
    labels = {"poi_density": "POI密度", "population_density": "人口密度", "nightlight_mean": "夜光均值", "road_integration_covered_mean": "路网整合度"}
    maxes = {key: max(float(s[key] or 0) for s in sectors) or 1 for key in colors}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#f8fafc"/>', '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#243047}.title{font-size:26px;font-weight:700}.sub{font-size:14px;fill:#526174}.label{font-size:16px;font-weight:700}.legend{font-size:13px}</style>', '<text x="48" y="48" class="title">项目周边八方向空间条件矩阵</text>', '<text x="48" y="75" class="sub">同一共享栅格；数值为相对空间条件，不是客流、消费或营收预测</text>']
    for i, (key, label) in enumerate(labels.items()):
        x = 48 + i * 235
        parts += [f'<rect x="{x}" y="88" width="14" height="14" rx="3" fill="{colors[key]}"/>', f'<text x="{x+22}" y="101" class="legend">{label}</text>']
    for index, sector in enumerate(sectors):
        y = y0 + index * row_h
        parts.append(f'<text x="{48}" y="{y+20}" class="label">{sector["label"]}</text>')
        for col, key in enumerate(colors):
            x = x0 + col * 195
            value = float(sector[key] or 0)
            bar_w = max(2, 150 * value / maxes[key])
            parts += [f'<rect x="{x}" y="{y+5}" width="150" height="24" rx="5" fill="#e2e8f0"/>', f'<rect x="{x}" y="{y+5}" width="{bar_w:.1f}" height="24" rx="5" fill="{colors[key]}"/>', f'<text x="{x+158}" y="{y+22}" class="legend">{value:.1f}</text>']
    parts += ['<text x="48" y="668" class="sub">读法：先看方向，再看多指标是否同向；路网只在有覆盖的栅格中比较，冲突处安排现场核验。</text>', "</svg>"]
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--center", nargs=2, type=float, default=(112.98634414425665, 28.220763114598597), metavar=("LON", "LAT"))
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    result = analyze(_unwrap_grid(raw), (args.center[0], args.center[1]), DEFAULT_BANDS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if args.svg:
        args.svg.parent.mkdir(parents=True, exist_ok=True)
        args.svg.write_text(_svg(result), encoding="utf-8", newline="\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
