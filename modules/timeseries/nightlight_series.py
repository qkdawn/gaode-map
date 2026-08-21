from __future__ import annotations

from modules.nightlight.service import get_nightlight_grid, get_nightlight_layer, get_nightlight_overview

from .common import (
    NIGHTLIGHT_STABLE_DELTA,
    NIGHTLIGHT_STABLE_RATE,
    NIGHTLIGHT_VIEWS,
    NIGHTLIGHT_YEARS,
    build_categorical_legend,
    build_cell_map,
    build_continuous_legend,
    build_diverging_cell,
    build_periods,
    build_summary_from_counts,
    calc_rate,
    extract_feature_cell_ids,
    parse_period,
    round_metric,
)


def build_nightlight_series(polygon: list, coord_type: str) -> list[dict[str, float | int]]:
    series = []
    for year in NIGHTLIGHT_YEARS:
        overview = get_nightlight_overview(polygon, coord_type, year)
        summary = overview.get("summary") or {}
        series.append(
            {
                "year": int(year),
                "total_radiance": round_metric(summary.get("total_radiance"), 6),
                "mean_radiance": round_metric(summary.get("mean_radiance"), 6),
                "max_radiance": round_metric(summary.get("max_radiance"), 6),
                "lit_pixel_ratio": round_metric(summary.get("lit_pixel_ratio"), 6),
                "p90_radiance": round_metric(summary.get("p90_radiance"), 6),
            }
        )
    return series


def get_nightlight_timeseries(
    polygon: list,
    coord_type: str = "gcj02",
    period: str = "2023-2025",
    layer_view: str = "radiance_delta",
) -> dict:
    safe_view = layer_view if layer_view in NIGHTLIGHT_VIEWS else "radiance_delta"
    from_year_raw, to_year_raw = parse_period(period, NIGHTLIGHT_YEARS)
    from_year, to_year = int(from_year_raw), int(to_year_raw)
    series = build_nightlight_series(polygon, coord_type)
    grid = get_nightlight_grid(polygon, coord_type, year=to_year)
    features = grid.get("features") or []
    cell_ids = extract_feature_cell_ids(features)
    source_view = "hotspot" if safe_view == "hotspot_shift" else "radiance"
    from_cells = build_cell_map(get_nightlight_layer(polygon, coord_type, year=from_year, view=source_view))
    to_cells = build_cell_map(get_nightlight_layer(polygon, coord_type, year=to_year, view=source_view))
    cells: list[dict] = []
    for cell_id in cell_ids:
        before = from_cells.get(cell_id) or {}
        after = to_cells.get(cell_id) or {}
        from_value = round_metric(before.get("value"), 6)
        to_value = round_metric(after.get("value"), 6)
        delta = round_metric(to_value - from_value, 6)
        rate = round_metric(calc_rate(delta, from_value), 6)
        if safe_view == "hotspot_shift":
            before_hot = bool(str(before.get("class_key") or "").endswith("hotspot"))
            after_hot = bool(str(after.get("class_key") or "").endswith("hotspot"))
            if before_hot and after_hot:
                key, label, color, opacity = "hotspot_stable", "热点持续活跃", "#ef4444", 0.72
            elif (not before_hot) and after_hot:
                key, label, color, opacity = "hotspot_emerging", "新热点出现", "#f59e0b", 0.72
            elif before_hot and not after_hot:
                key, label, color, opacity = "hotspot_faded", "热点消退", "#38bdf8", 0.64
            else:
                key, label, color, opacity = "stable", "整体稳定", "#e5e7eb", 0.32
            value = 1.0 if key != "stable" else 0.0
        elif safe_view == "lit_change":
            stable = abs(delta) < NIGHTLIGHT_STABLE_DELTA or abs(rate) < NIGHTLIGHT_STABLE_RATE
            if stable:
                key, label, color, opacity = "stable", "变化平稳", "#e5e7eb", 0.34
            elif delta > 0:
                key, label, color, opacity = "lit_brightened", "亮度增强", "#f97316", 0.68
            else:
                key, label, color, opacity = "lit_dimmed", "亮度减弱", "#2563eb", 0.64
            value = delta
        else:
            stable = abs(delta) < NIGHTLIGHT_STABLE_DELTA or abs(rate) < NIGHTLIGHT_STABLE_RATE
            key, label, color, opacity = (
                ("stable", "变化平稳", "#e5e7eb", 0.34)
                if stable
                else build_diverging_cell(delta, rate, safe_view)
            )
            value = rate * 100.0 if safe_view == "radiance_rate" else delta
        cells.append(
            {
                "cell_id": cell_id,
                "from_value": from_value,
                "to_value": to_value,
                "delta": delta,
                "rate": rate,
                "value": round_metric(value, 6),
                "class_key": key,
                "class_label": label,
                "fill_color": color,
                "stroke_color": "#64748b",
                "fill_opacity": opacity,
                "label": label,
            }
        )
    view_meta = NIGHTLIGHT_VIEWS[safe_view]
    if safe_view == "hotspot_shift":
        legend = build_categorical_legend("热点迁移", [("hotspot_emerging", "新热点出现", "#f59e0b"), ("hotspot_stable", "热点持续活跃", "#ef4444"), ("hotspot_faded", "热点消退", "#38bdf8"), ("stable", "整体稳定", "#e5e7eb")])
    elif safe_view == "lit_change":
        legend = build_categorical_legend("亮灯强度变化", [("lit_brightened", "亮度增强", "#f97316"), ("lit_dimmed", "亮度减弱", "#2563eb"), ("stable", "变化平稳", "#e5e7eb")])
    else:
        legend = build_continuous_legend(view_meta["label"], view_meta["unit"])
    summary = build_summary_from_counts(cells)
    summary.update({"from_year": from_year, "to_year": to_year, "view": safe_view})
    return {
        "series": series,
        "method": {
            "spatial_aggregation": "intersecting_full_cells",
            "boundary_cell_policy": "include_full_cell_value",
        },
        "periods": build_periods(NIGHTLIGHT_YEARS),
        "layer": {
            "period": f"{from_year}-{to_year}",
            "from_year": from_year,
            "to_year": to_year,
            "view": safe_view,
            "view_label": view_meta["label"],
            "summary": summary,
            "legend": legend,
            "features": features,
            "cells": cells,
        },
        "insights": [
            {"type": "nightlight_delta", "title": "总夜光变化", "value": summary["total_delta"], "unit": view_meta["unit"]},
            {"type": "nightlight_grid", "title": "增强网格数", "value": summary["increase_count"], "unit": "格"},
        ],
    }
