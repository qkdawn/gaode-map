from __future__ import annotations

import base64
import io
from typing import Any, Dict

import numpy as np

from core.config import settings
from core.spatial import build_scope_id, round_float, to_wgs84_geometry

from .cache import (
    grid_cache_path,
    layer_cache_json_path,
    overview_cache_path,
    raster_cache_json_path,
    read_json,
    resolve_dir,
    write_json,
)
from .dataset import combine_masked_layers, combine_population_layers, ensure_data_files, masked_stats
from .registry import (
    DEFAULT_AGE_BAND,
    DEFAULT_POPULATION_YEAR,
    DEFAULT_SEX,
    age_band_keys,
    build_meta_payload,
    build_selected_descriptor,
    get_age_band_label,
    get_sex_label,
    normalize_population_year,
    resolve_population_data_dir,
    resolve_population_file_paths,
)
from .render import (
    DENSITY_UNIT,
    DOMINANT_AGE_COLORS,
    PERCENT_UNIT,
    bounds_gcj02_from_transform,
    build_age_ratio_cells,
    build_categorical_legend,
    build_dominant_age_cell_styles,
    build_dominant_age_cells,
    build_discrete_ratio_cell_styles,
    build_legend,
    build_population_layer_cell_styles,
    build_population_layer_summary,
    colorize_population_array,
    iter_population_cells,
)

DEFAULT_ANALYSIS_AGE_BAND = "25"
POPULATION_RECORD_SOURCE = "WorldPop"
POPULATION_RECORD_REQUIRED_FIELDS = (
    "population_total",
    "male_total",
    "female_total",
    "age_total",
    "age_male",
    "age_female",
)


def _population_year(year: str | None = None) -> str:
    return normalize_population_year(year or settings.population_data_year)


def _population_data_dir(year: str | None = None):
    return resolve_population_data_dir(resolve_dir(settings.population_data_dir), _population_year(year))


def _population_scope_id(geom_wgs84, year: str | None = None) -> str:
    data_dir = _population_data_dir(year)
    return build_scope_id(geom_wgs84, "population", str(data_dir))


def _compute_population_overview(scope_id: str, geom_wgs84, year: str | None = None) -> Dict[str, Any]:
    safe_year = _population_year(year)
    data_dir = _population_data_dir(safe_year)
    if not data_dir.exists():
        raise RuntimeError(f"population data directory not found: {data_dir}")

    male_total_data = combine_population_layers(data_dir, "male", "all", geom_wgs84, safe_year)
    female_total_data = combine_population_layers(data_dir, "female", "all", geom_wgs84, safe_year)

    male_total = masked_stats(male_total_data["array"] if male_total_data else None, round_float)["sum"]
    female_total = masked_stats(female_total_data["array"] if female_total_data else None, round_float)["sum"]
    total_population = round_float(float(male_total) + float(female_total), 3)
    male_ratio = round_float(float(male_total) / total_population, 6) if total_population > 0 else 0.0
    female_ratio = round_float(float(female_total) / total_population, 6) if total_population > 0 else 0.0

    age_distribution: list[dict[str, Any]] = []
    for age_band in age_band_keys():
        male_paths = resolve_population_file_paths(data_dir, "male", age_band, safe_year)
        female_paths = resolve_population_file_paths(data_dir, "female", age_band, safe_year)
        ensure_data_files([*male_paths, *female_paths])
        male_data = combine_masked_layers(male_paths, geom_wgs84)
        female_data = combine_masked_layers(female_paths, geom_wgs84)
        male_sum = masked_stats(male_data["array"] if male_data else None, round_float)["sum"]
        female_sum = masked_stats(female_data["array"] if female_data else None, round_float)["sum"]
        total_sum = round_float(float(male_sum) + float(female_sum), 3)
        age_distribution.append(
            {
                "age_band": age_band,
                "age_band_label": get_age_band_label(age_band),
                "total": total_sum,
                "male": round_float(male_sum, 3),
                "female": round_float(female_sum, 3),
            }
        )

    payload = {
        "scope_id": scope_id,
        "summary": {
            "total_population": total_population,
            "male_total": round_float(male_total, 3),
            "female_total": round_float(female_total, 3),
            "male_ratio": male_ratio,
            "female_ratio": female_ratio,
        },
        "sex_totals": {
            "total": total_population,
            "male": round_float(male_total, 3),
            "female": round_float(female_total, 3),
        },
        "age_distribution": age_distribution,
    }
    write_json(overview_cache_path(scope_id), payload)
    return payload


def _load_or_compute_population_overview(scope_id: str, geom_wgs84, year: str | None = None) -> Dict[str, Any]:
    cached = read_json(overview_cache_path(scope_id))
    if cached:
        return cached
    return _compute_population_overview(scope_id, geom_wgs84, year)


def _compute_population_grid(scope_id: str, geom_wgs84, year: str | None = None) -> Dict[str, Any]:
    safe_year = _population_year(year)
    data_dir = _population_data_dir(safe_year)
    if not data_dir.exists():
        raise RuntimeError(f"population data directory not found: {data_dir}")

    base_data = combine_population_layers(data_dir, "total", "all", geom_wgs84, safe_year)
    if base_data is None:
        payload = {"scope_id": scope_id, "year": safe_year, "source": POPULATION_RECORD_SOURCE, "cell_count": 0, "features": []}
        write_json(grid_cache_path(scope_id), payload)
        return payload

    def aligned_array(sex: str, age_band: str):
        layer = combine_population_layers(data_dir, sex, age_band, geom_wgs84, safe_year)
        if layer is None:
            return None
        if base_data["shape"] != layer["shape"] or base_data["transform"] != layer["transform"]:
            raise RuntimeError("population artifact raster alignment mismatch")
        return np.ma.filled(layer["array"], 0.0)

    male_values = aligned_array("male", "all")
    female_values = aligned_array("female", "all")
    age_male_values = {band: aligned_array("male", band) for band in age_band_keys()}
    age_female_values = {band: aligned_array("female", band) for band in age_band_keys()}

    features: list[dict[str, Any]] = []
    for cell in iter_population_cells(base_data["array"], base_data["transform"]):
        row = int(cell["row"])
        col = int(cell["col"])
        male_total = max(0.0, float(male_values[row, col])) if male_values is not None else 0.0
        female_total = max(0.0, float(female_values[row, col])) if female_values is not None else 0.0
        population_total = male_total + female_total
        age_male = {
            band: round_float(max(0.0, float(values[row, col])), 6) if values is not None else 0.0
            for band, values in age_male_values.items()
        }
        age_female = {
            band: round_float(max(0.0, float(values[row, col])), 6) if values is not None else 0.0
            for band, values in age_female_values.items()
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": cell["geometry_gcj02"]},
                "geometry_wgs84": {"type": "Polygon", "coordinates": cell["geometry_wgs84"]},
                "properties": {
                    "cell_id": cell["cell_id"],
                    "h3_id": cell["cell_id"],
                    "row": cell["row"],
                    "col": cell["col"],
                    "centroid_gcj02": cell["centroid_gcj02"],
                    "year": safe_year,
                    "population_total": round_float(population_total, 6),
                    "male_total": round_float(male_total, 6),
                    "female_total": round_float(female_total, 6),
                    "age_total": {
                        band: round_float(age_male[band] + age_female[band], 6)
                        for band in age_band_keys()
                    },
                    "age_male": age_male,
                    "age_female": age_female,
                    "source": POPULATION_RECORD_SOURCE,
                },
            }
        )

    payload = {
        "scope_id": scope_id,
        "year": safe_year,
        "source": POPULATION_RECORD_SOURCE,
        "cell_count": len(features),
        "features": features,
    }
    write_json(grid_cache_path(scope_id), payload)
    return payload


def _load_or_compute_population_grid(scope_id: str, geom_wgs84, year: str | None = None) -> Dict[str, Any]:
    cached = read_json(grid_cache_path(scope_id))
    features = cached.get("features") if isinstance(cached, dict) else None
    if (
        cached
        and cached.get("year") == _population_year(year)
        and cached.get("source") == POPULATION_RECORD_SOURCE
        and isinstance(features, list)
        and all(
            isinstance(feature, dict)
            and isinstance(feature.get("geometry_wgs84"), dict)
            and all(key in (feature.get("properties") or {}) for key in POPULATION_RECORD_REQUIRED_FIELDS)
            for feature in features
        )
    ):
        return cached
    return _compute_population_grid(scope_id, geom_wgs84, year)


def _resolve_population_layer_source(view: str, sex_mode: str, age_mode: str, age_band: str) -> Dict[str, str]:
    safe_view = str(view or "density").strip().lower()
    safe_sex_mode = str(sex_mode or "male").strip().lower()
    safe_age_mode = str(age_mode or "ratio").strip().lower()
    safe_age_band = str(age_band or DEFAULT_ANALYSIS_AGE_BAND).strip().lower()

    if safe_view == "sex":
        resolved_sex = safe_sex_mode if safe_sex_mode in {"male", "female"} else "male"
        return {
            "view": "sex",
            "sex": resolved_sex,
            "age_band": "all",
            "view_label": f"{get_sex_label(resolved_sex)}密度",
            "unit": DENSITY_UNIT,
        }
    if safe_view == "age":
        target_age_band = safe_age_band if safe_age_band in set(age_band_keys()) else DEFAULT_ANALYSIS_AGE_BAND
        resolved_age_mode = safe_age_mode if safe_age_mode in {"ratio", "dominant"} else "ratio"
        return {
            "view": "age",
            "sex": "total",
            "age_band": target_age_band,
            "age_mode": resolved_age_mode,
            "view_label": "主导年龄图" if resolved_age_mode == "dominant" else f"{get_age_band_label(target_age_band)}占比",
            "unit": PERCENT_UNIT,
        }
    if safe_view == "overview":
        return {
            "view": "overview",
            "sex": "total",
            "age_band": "all",
            "view_label": "总人口",
            "unit": "人口",
        }
    return {
        "view": "density",
        "sex": "total",
        "age_band": "all",
        "age_mode": "ratio",
        "view_label": "人口密度",
        "unit": DENSITY_UNIT,
    }


def _build_population_layer_selected(view_config: Dict[str, str], sex_mode: str, age_mode: str, age_band: str) -> Dict[str, Any]:
    safe_view = str(view_config.get("view") or "density")
    safe_sex_mode = str(sex_mode or "male")
    safe_age_mode = str(age_mode or "ratio")
    safe_age_band = str(age_band or DEFAULT_ANALYSIS_AGE_BAND)
    return {
        "view": safe_view,
        "view_label": str(view_config.get("view_label") or ""),
        "sex_mode": safe_sex_mode if safe_view == "sex" else None,
        "sex_mode_label": get_sex_label(safe_sex_mode) if safe_view == "sex" else None,
        "age_mode": safe_age_mode if safe_view == "age" else None,
        "age_mode_label": "主导年龄图" if (safe_view == "age" and safe_age_mode == "dominant") else ("年龄占比图" if safe_view == "age" else None),
        "age_band": safe_age_band if safe_view == "age" else "all",
        "age_band_label": get_age_band_label(safe_age_band) if safe_view == "age" else get_age_band_label("all"),
        "unit": str(view_config.get("unit") or "人口"),
    }


def build_population_meta_payload() -> Dict[str, Any]:
    return build_meta_payload()


def get_population_overview(
    polygon: list,
    coord_type: str = "gcj02",
    year: str = DEFAULT_POPULATION_YEAR,
) -> Dict[str, Any]:
    geom_wgs84 = to_wgs84_geometry(polygon, coord_type)
    safe_year = _population_year(year)
    scope_id = _population_scope_id(geom_wgs84, safe_year)
    return _load_or_compute_population_overview(scope_id, geom_wgs84, safe_year)


def get_population_grid(
    polygon: list,
    coord_type: str = "gcj02",
    year: str = DEFAULT_POPULATION_YEAR,
) -> Dict[str, Any]:
    geom_wgs84 = to_wgs84_geometry(polygon, coord_type)
    safe_year = _population_year(year)
    scope_id = _population_scope_id(geom_wgs84, safe_year)
    return _load_or_compute_population_grid(scope_id, geom_wgs84, safe_year)


def get_population_layer(
    polygon: list,
    coord_type: str = "gcj02",
    year: str = DEFAULT_POPULATION_YEAR,
    scope_id: str | None = None,
    view: str = "density",
    sex_mode: str = "male",
    age_mode: str = "ratio",
    age_band: str = DEFAULT_ANALYSIS_AGE_BAND,
) -> Dict[str, Any]:
    geom_wgs84 = to_wgs84_geometry(polygon, coord_type)
    safe_year = _population_year(year)
    resolved_scope_id = scope_id or _population_scope_id(geom_wgs84, safe_year)
    overview = _load_or_compute_population_overview(resolved_scope_id, geom_wgs84, safe_year)
    _load_or_compute_population_grid(resolved_scope_id, geom_wgs84, safe_year)

    view_config = _resolve_population_layer_source(view, sex_mode, age_mode, age_band)
    selected = _build_population_layer_selected(view_config, sex_mode, age_mode, age_band)

    cache_path = layer_cache_json_path(
        resolved_scope_id,
        str(view_config.get("view") or "density"),
        str(selected.get("sex_mode") or "male"),
        str(selected.get("age_mode") or "ratio"),
        str(selected.get("age_band") or DEFAULT_ANALYSIS_AGE_BAND),
    )
    cached = read_json(cache_path)
    if cached:
        cached["scope_id"] = resolved_scope_id
        cached["selected"] = selected
        return cached

    data_dir = _population_data_dir(safe_year)
    if not data_dir.exists():
        raise RuntimeError(f"population data directory not found: {data_dir}")

    combined = None
    legend = None
    raw_cells: list[dict[str, Any]] = []
    display_values: list[float] = []
    raw_sum = 0.0

    if str(view_config.get("view")) == "age" and str(view_config.get("age_mode")) == "ratio":
        total_layer = combine_population_layers(data_dir, "total", "all", geom_wgs84, safe_year)
        age_layer = combine_population_layers(data_dir, "total", str(view_config["age_band"]), geom_wgs84, safe_year)
        if total_layer is not None and age_layer is not None:
            raw_cells, raw_sum = build_age_ratio_cells(total_layer, age_layer)
            display_values = [float(cell["display_value"]) for cell in raw_cells]
            discrete = build_discrete_ratio_cell_styles(raw_cells, "display_value", str(view_config["view_label"]))
            if discrete is not None:
                styled_cells, legend, _ = discrete
            else:
                styled_cells, min_value, max_value = build_population_layer_cell_styles(
                    raw_cells,
                    "display_value",
                    PERCENT_UNIT,
                    str(view_config["view_label"]),
                )
                legend = build_legend(str(view_config["view_label"]), min_value, max_value, PERCENT_UNIT)
        else:
            combined = None
    elif str(view_config.get("view")) == "age" and str(view_config.get("age_mode")) == "dominant":
        total_layer = combine_population_layers(data_dir, "total", "all", geom_wgs84, safe_year)
        age_layers = {
            age_key: combine_population_layers(data_dir, "total", age_key, geom_wgs84, safe_year)
            for age_key in age_band_keys()
        }
        if total_layer is not None and all(layer is not None for layer in age_layers.values()):
            raw_cells, _ = build_dominant_age_cells(total_layer, age_layers)
            display_values = [float(cell["display_value"]) for cell in raw_cells]
            styled_cells, category_counts = build_dominant_age_cell_styles(raw_cells)
            legend_items = [
                {
                    "label": get_age_band_label(age_key),
                    "color": DOMINANT_AGE_COLORS.get(age_key, "#d1d5db"),
                    "value": float(category_counts.get(age_key) or 0),
                }
                for age_key in age_band_keys()
                if int(category_counts.get(age_key) or 0) > 0
            ]
            legend = build_categorical_legend("主导年龄图", legend_items, "主导格子数")
        else:
            combined = None
    else:
        combined = combine_population_layers(
            data_dir,
            str(view_config["sex"]),
            str(view_config["age_band"]),
            geom_wgs84,
            safe_year,
        )

    if combined is None and not raw_cells:
        payload = {
            "scope_id": resolved_scope_id,
            "selected": selected,
            "summary": {},
            "legend": build_legend(str(view_config["view_label"]), 0.0, 0.0, str(view_config["unit"])),
            "cells": [],
        }
        write_json(cache_path, payload)
        return payload

    if combined is not None:
        raw_cells = list(iter_population_cells(combined["array"], combined["transform"]))
        display_values = []
        for cell in raw_cells:
            raw_value = float(cell["raw_value"])
            display_value = raw_value * 100.0 if view_config["unit"] == DENSITY_UNIT else raw_value
            cell["display_value"] = round_float(display_value, 6)
            display_values.append(display_value)

        styled_cells, min_value, max_value = build_population_layer_cell_styles(
            raw_cells,
            "display_value",
            str(view_config["unit"]),
            str(view_config["view_label"]),
        )
        raw_sum = float(sum(float(cell["raw_value"]) for cell in raw_cells))
        legend = build_legend(str(view_config["view_label"]), min_value, max_value, str(view_config["unit"]))

    summary = build_population_layer_summary(
        str(view_config["view"]),
        selected,
        overview,
        raw_cells,
        display_values,
        raw_sum,
        str(view_config["age_band"]),
    )
    if (
        str(view_config.get("view")) == "age"
        and str(view_config.get("age_mode")) == "ratio"
        and isinstance(legend, dict)
        and str(legend.get("kind") or "") == "categorical"
    ):
        summary["value_bucket_count"] = len((legend.get("stops") or []))

    payload = {
        "scope_id": resolved_scope_id,
        "selected": selected,
        "summary": summary,
        "legend": legend,
        "cells": styled_cells,
    }
    write_json(cache_path, payload)
    return payload


def get_population_raster_preview(
    polygon: list,
    coord_type: str = "gcj02",
    year: str = DEFAULT_POPULATION_YEAR,
    sex: str = DEFAULT_SEX,
    age_band: str = DEFAULT_AGE_BAND,
    scope_id: str | None = None,
) -> Dict[str, Any]:
    geom_wgs84 = to_wgs84_geometry(polygon, coord_type)
    safe_year = _population_year(year)
    resolved_scope_id = scope_id or _population_scope_id(geom_wgs84, safe_year)
    overview = _load_or_compute_population_overview(resolved_scope_id, geom_wgs84, safe_year)
    selected = build_selected_descriptor(sex, age_band)

    cache_json_path = raster_cache_json_path(resolved_scope_id, sex, age_band)
    cached = read_json(cache_json_path)
    if cached:
        cached["scope_id"] = resolved_scope_id
        cached["selected"] = selected
        return cached

    data_dir = _population_data_dir(safe_year)
    if not data_dir.exists():
        raise RuntimeError(f"population data directory not found: {data_dir}")
    combined = combine_population_layers(data_dir, sex, age_band, geom_wgs84, safe_year)
    if combined is None:
        payload = {
            "scope_id": resolved_scope_id,
            "selected": selected,
            "summary": {
                "selected_population": 0.0,
                "selected_ratio_of_total": 0.0,
                "nonzero_pixel_count": 0,
                "max_pixel_value": 0.0,
            },
            "image_url": None,
            "bounds_gcj02": [],
            "legend": build_legend(f"{selected['sex_label']} {selected['age_band_label']}", 0.0, 0.0),
        }
        write_json(cache_json_path, payload)
        return payload

    masked_array = combined["array"]
    stats = masked_stats(masked_array, round_float)
    total_population = float(((overview.get("summary") or {}).get("total_population") or 0.0))
    image, min_value, max_value = colorize_population_array(masked_array, int(settings.population_preview_max_size or 2048))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    image_url = f"data:image/png;base64,{png_base64}"

    height, width = masked_array.shape
    bounds_gcj02 = bounds_gcj02_from_transform(combined["transform"], width, height)
    payload = {
        "scope_id": resolved_scope_id,
        "selected": selected,
        "summary": {
            "selected_population": round_float(stats["sum"], 3),
            "selected_ratio_of_total": round_float((float(stats["sum"]) / total_population), 6) if total_population > 0 else 0.0,
            "nonzero_pixel_count": int(stats["nonzero_pixel_count"]),
            "max_pixel_value": round_float(stats["max_pixel_value"], 3),
        },
        "image_url": image_url,
        "bounds_gcj02": bounds_gcj02,
        "legend": build_legend(f"{selected['sex_label']} {selected['age_band_label']}", min_value, max_value),
    }
    write_json(cache_json_path, payload)
    return payload
