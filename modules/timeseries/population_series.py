from __future__ import annotations

from typing import Any

from modules.population.service import get_population_grid, get_population_layer, get_population_overview

from .common import (
    POPULATION_STABLE_DELTA,
    POPULATION_STABLE_RATE,
    POPULATION_VIEWS,
    POPULATION_YEARS,
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


def top_age_label(overview: dict[str, Any]) -> str:
    items = overview.get("age_distribution") or []
    if not items:
        return "-"
    top = max(items, key=lambda item: float(item.get("total") or 0.0))
    return str(top.get("age_band_label") or top.get("age_band") or "-")


def _age_band_start(age_band: str) -> int | None:
    if age_band == "00":
        return 0
    try:
        return int(age_band)
    except (TypeError, ValueError):
        return None


def summarize_age_structure(overview: dict[str, Any]) -> dict[str, Any]:
    items = overview.get("age_distribution") or []
    summary = overview.get("summary") or {}
    total_population = float(summary.get("total_population") or 0.0)
    groups = {"child_0_14": 0.0, "working_15_64": 0.0, "senior_65_plus": 0.0}
    compact_items = []
    for item in items:
        total = float(item.get("total") or 0.0)
        age_band = str(item.get("age_band") or "")
        start = _age_band_start(age_band)
        if start is not None:
            if start < 15:
                groups["child_0_14"] += total
            elif start < 65:
                groups["working_15_64"] += total
            else:
                groups["senior_65_plus"] += total
        compact_items.append(
            {
                "age_band": age_band,
                "age_band_label": item.get("age_band_label") or age_band,
                "total": round_metric(total, 3),
                "male": round_metric(item.get("male"), 3),
                "female": round_metric(item.get("female"), 3),
                "ratio": round_metric(total / total_population, 6) if total_population > 0 else 0.0,
            }
        )
    top = max(compact_items, key=lambda item: float(item.get("total") or 0.0), default={})
    return {
        "age_distribution": compact_items,
        "age_group_totals": {key: round_metric(value, 3) for key, value in groups.items()},
        "age_group_ratios": {
            key: round_metric(value / total_population, 6) if total_population > 0 else 0.0
            for key, value in groups.items()
        },
        "top_age_band": top.get("age_band") or None,
        "top_age_band_label": top.get("age_band_label") or None,
        "top_age_band_ratio": round_metric(top.get("ratio"), 6),
    }


def build_population_series(polygon: list, coord_type: str) -> list[dict[str, Any]]:
    series = []
    for year in POPULATION_YEARS:
        overview = get_population_overview(polygon, coord_type, year)
        density = get_population_layer(polygon, coord_type, year=year, view="density")
        summary = overview.get("summary") or {}
        density_summary = density.get("summary") or {}
        age_structure = summarize_age_structure(overview)
        series.append(
            {
                "year": year,
                "total_population": round_metric(summary.get("total_population"), 3),
                "male_total": round_metric(summary.get("male_total"), 3),
                "female_total": round_metric(summary.get("female_total"), 3),
                "male_ratio": round_metric(summary.get("male_ratio"), 6),
                "female_ratio": round_metric(summary.get("female_ratio"), 6),
                "average_density": round_metric(density_summary.get("average_density_per_km2"), 3),
                "dominant_age_band": age_structure["top_age_band_label"] or top_age_label(overview),
                "age_distribution": age_structure["age_distribution"],
                "age_group_totals": age_structure["age_group_totals"],
                "age_group_ratios": age_structure["age_group_ratios"],
                "top_age_band": age_structure["top_age_band"],
                "top_age_band_label": age_structure["top_age_band_label"],
                "top_age_band_ratio": age_structure["top_age_band_ratio"],
            }
        )
    return series


def get_population_timeseries(
    polygon: list,
    coord_type: str = "gcj02",
    period: str = "2024-2026",
    layer_view: str = "population_delta",
) -> dict[str, Any]:
    safe_view = layer_view if layer_view in POPULATION_VIEWS else "population_delta"
    from_year, to_year = parse_period(period, POPULATION_YEARS)
    series = build_population_series(polygon, coord_type)
    grid = get_population_grid(polygon, coord_type, year=to_year)
    features = grid.get("features") or []
    cell_ids = extract_feature_cell_ids(features)

    if safe_view == "density_delta":
        from_layer = get_population_layer(polygon, coord_type, year=from_year, view="density")
        to_layer = get_population_layer(polygon, coord_type, year=to_year, view="density")
    elif safe_view == "age_shift":
        from_layer = get_population_layer(polygon, coord_type, year=from_year, view="age", age_mode="dominant", age_band="all")
        to_layer = get_population_layer(polygon, coord_type, year=to_year, view="age", age_mode="dominant", age_band="all")
    else:
        from_layer = get_population_layer(polygon, coord_type, year=from_year, view="overview")
        to_layer = get_population_layer(polygon, coord_type, year=to_year, view="overview")

    from_cells = build_cell_map(from_layer)
    to_cells = build_cell_map(to_layer)
    cells: list[dict[str, Any]] = []
    for cell_id in cell_ids:
        before = from_cells.get(cell_id) or {}
        after = to_cells.get(cell_id) or {}
        from_value = round_metric(before.get("value"), 6)
        to_value = round_metric(after.get("value"), 6)
        delta = round_metric(to_value - from_value, 6)
        rate = round_metric(calc_rate(delta, from_value), 6)
        if safe_view == "age_shift":
            before_label = str(before.get("label") or "-")
            after_label = str(after.get("label") or "-")
            changed = before_label != after_label
            key = "age_shift" if changed else "stable"
            label = f"{before_label} -> {after_label}" if changed else "年龄结构稳定"
            color = "#7c3aed" if changed else "#e5e7eb"
            opacity = 0.68 if changed else 0.34
            value = 1.0 if changed else 0.0
        else:
            stable = abs(delta) < POPULATION_STABLE_DELTA or abs(rate) < POPULATION_STABLE_RATE
            key, label, color, opacity = (
                ("stable", "变化平稳", "#e5e7eb", 0.36)
                if stable
                else build_diverging_cell(delta, rate, safe_view)
            )
            value = rate * 100.0 if safe_view == "population_rate" else delta
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
                "label": label if safe_view == "age_shift" else f"{label}: {round_metric(delta, 2)}",
            }
        )
    view_meta = POPULATION_VIEWS[safe_view]
    legend = (
        build_categorical_legend("主导年龄段迁移", [("age_shift", "年龄结构变化", "#7c3aed"), ("stable", "变化平稳", "#e5e7eb")])
        if safe_view == "age_shift"
        else build_continuous_legend(view_meta["label"], view_meta["unit"])
    )
    summary = build_summary_from_counts(cells)
    summary.update({"from_year": from_year, "to_year": to_year, "view": safe_view})
    return {
        "series": series,
        "method": {
            "spatial_aggregation": "intersecting_full_cells",
            "boundary_cell_policy": "include_full_cell_value",
        },
        "periods": build_periods(POPULATION_YEARS),
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
            {"type": "population_delta", "title": "总人口变化", "value": summary["total_delta"], "unit": view_meta["unit"]},
            {"type": "population_grid", "title": "增长网格数", "value": summary["increase_count"], "unit": "格"},
        ],
    }
