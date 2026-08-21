from __future__ import annotations

from modules.nightlight.service import get_nightlight_layer, get_nightlight_overview
from modules.population.service import get_population_grid, get_population_layer, get_population_overview

from .common import (
    COMMON_YEARS,
    NIGHTLIGHT_STABLE_DELTA,
    NIGHTLIGHT_STABLE_RATE,
    POPULATION_STABLE_DELTA,
    POPULATION_STABLE_RATE,
    build_categorical_legend,
    build_cell_map,
    build_periods,
    build_summary_from_counts,
    calc_rate,
    extract_feature_cell_ids,
    parse_period,
    round_metric,
)
from .nightlight_series import get_nightlight_timeseries
from .population_series import get_population_timeseries


def get_timeseries_meta() -> dict[str, object]:
    return {
        "population_years": ["2024", "2025", "2026"],
        "nightlight_years": [2023, 2024, 2025],
        "common_years": [2024, 2025],
        "population_periods": build_periods(["2024", "2025", "2026"]),
        "nightlight_periods": build_periods([2023, 2024, 2025]),
        "joint_periods": [{"value": "2024-2025", "label": "2024 -> 2025", "from_year": "2024", "to_year": "2025"}],
        "default_population_period": "2024-2026",
        "default_nightlight_period": "2023-2025",
        "default_joint_period": "2024-2025",
    }


def get_timeseries_population(polygon: list, coord_type: str = "gcj02", period: str = "2024-2026", layer_view: str = "population_delta") -> dict:
    return get_population_timeseries(polygon=polygon, coord_type=coord_type, period=period, layer_view=layer_view)


def get_timeseries_nightlight(polygon: list, coord_type: str = "gcj02", period: str = "2023-2025", layer_view: str = "radiance_delta") -> dict:
    return get_nightlight_timeseries(polygon=polygon, coord_type=coord_type, period=period, layer_view=layer_view)


def get_timeseries_joint(polygon: list, coord_type: str = "gcj02", period: str = "2024-2025") -> dict:
    from_year, to_year = parse_period(period, COMMON_YEARS)
    if f"{from_year}-{to_year}" != "2024-2025":
        raise ValueError("joint timeseries currently supports 2024-2025 only")

    pop_grid = get_population_grid(polygon, coord_type, year=to_year)
    features = pop_grid.get("features") or []
    cell_ids = extract_feature_cell_ids(features)
    pop_from = build_cell_map(get_population_layer(polygon, coord_type, year=from_year, view="overview"))
    pop_to = build_cell_map(get_population_layer(polygon, coord_type, year=to_year, view="overview"))
    nl_from = build_cell_map(get_nightlight_layer(polygon, coord_type, year=int(from_year), view="radiance"))
    nl_to = build_cell_map(get_nightlight_layer(polygon, coord_type, year=int(to_year), view="radiance"))

    classes = {
        "pop_up_light_up": ("人口增长且夜光增强", "#b91c1c", 0.76),
        "pop_up_light_down": ("人口增长但夜光减弱", "#f59e0b", 0.70),
        "pop_down_light_up": ("人口下降但夜光增强", "#7c3aed", 0.70),
        "pop_down_light_down": ("人口下降且夜光减弱", "#2563eb", 0.68),
        "joint_stable": ("变化平稳", "#e5e7eb", 0.34),
    }

    cells: list[dict[str, object]] = []
    for cell_id in cell_ids:
        pop_before = round_metric((pop_from.get(cell_id) or {}).get("value"), 6)
        pop_after = round_metric((pop_to.get(cell_id) or {}).get("value"), 6)
        nl_before = round_metric((nl_from.get(cell_id) or {}).get("value"), 6)
        nl_after = round_metric((nl_to.get(cell_id) or {}).get("value"), 6)
        pop_delta = round_metric(pop_after - pop_before, 6)
        nl_delta = round_metric(nl_after - nl_before, 6)
        pop_rate = round_metric(calc_rate(pop_delta, pop_before), 6)
        nl_rate = round_metric(calc_rate(nl_delta, nl_before), 6)
        pop_stable = abs(pop_delta) < POPULATION_STABLE_DELTA or abs(pop_rate) < POPULATION_STABLE_RATE
        nl_stable = abs(nl_delta) < NIGHTLIGHT_STABLE_DELTA or abs(nl_rate) < NIGHTLIGHT_STABLE_RATE

        if pop_stable or nl_stable:
            key = "joint_stable"
        elif pop_delta > 0 and nl_delta > 0:
            key = "pop_up_light_up"
        elif pop_delta > 0 and nl_delta < 0:
            key = "pop_up_light_down"
        elif pop_delta < 0 and nl_delta > 0:
            key = "pop_down_light_up"
        else:
            key = "pop_down_light_down"

        label, color, opacity = classes[key]
        cells.append(
            {
                "cell_id": cell_id,
                "from_value": pop_before,
                "to_value": pop_after,
                "delta": pop_delta,
                "rate": pop_rate,
                "nightlight_from_value": nl_before,
                "nightlight_to_value": nl_after,
                "nightlight_delta": nl_delta,
                "nightlight_rate": nl_rate,
                "value": pop_delta,
                "class_key": key,
                "class_label": label,
                "fill_color": color,
                "stroke_color": "#64748b",
                "fill_opacity": opacity,
                "label": label,
            }
        )

    summary = build_summary_from_counts(cells)
    summary.update({"from_year": from_year, "to_year": to_year, "view": "joint_quadrant"})
    return {
        "method": {
            "spatial_aggregation": "intersecting_full_cells",
            "boundary_cell_policy": "include_full_cell_value",
        },
        "series": [
            {
                "year": int(year),
                "population": round_metric((get_population_overview(polygon, coord_type, str(year)).get("summary") or {}).get("total_population"), 3),
                "total_radiance": round_metric((get_nightlight_overview(polygon, coord_type, int(year)).get("summary") or {}).get("total_radiance"), 6),
            }
            for year in COMMON_YEARS
        ],
        "periods": [{"value": "2024-2025", "label": "2024 -> 2025", "from_year": "2024", "to_year": "2025"}],
        "layer": {
            "period": "2024-2025",
            "from_year": "2024",
            "to_year": "2025",
            "view": "joint_quadrant",
            "view_label": "人口-夜光四象限",
            "summary": summary,
            "legend": build_categorical_legend("人口-夜光变化分类", [(key, value[0], value[1]) for key, value in classes.items()]),
            "features": features,
            "cells": cells,
        },
        "insights": [
            {"type": "joint_quadrant", "title": "人口与夜光同步增长", "value": summary["class_counts"].get("pop_up_light_up", 0), "unit": "格"},
            {"type": "joint_stable", "title": "整体变化平稳", "value": summary["class_counts"].get("joint_stable", 0), "unit": "格"},
        ],
    }
