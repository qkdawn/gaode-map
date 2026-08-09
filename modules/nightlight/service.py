from __future__ import annotations

import base64
import copy
import io
from typing import Any

from shapely.geometry import mapping

from core.config import settings

from .analysis import (
    build_gradient_layer_cells,
    build_hotspot_layer_cells,
    enrich_economic_activity_analysis,
)
from .aggregate import aggregate_clip_to_target_cells
from .common import (
    GRADIENT_VIEW,
    GRADIENT_VIEW_LABEL,
    HOTSPOT_VIEW,
    HOTSPOT_VIEW_LABEL,
    RADIANCE_VIEW,
    RADIANCE_VIEW_LABEL,
    build_scope_id,
    to_wgs84_geometry,
)
from .dataset import load_manifest, load_or_compute_clip, resolve_dataset
from .render import (
    bounds_gcj02_from_transform,
    build_layer_cells,
    build_legend,
    colorize_nightlight_array,
    default_summary,
    selected_descriptor,
    summarize_masked_values,
)
from .targets import load_target_cells


def build_nightlight_meta_payload() -> dict[str, Any]:
    manifest = load_manifest()
    return {
        "available_years": [
            {"year": int(item["year"]), "label": str(item["label"])}
            for item in manifest["datasets"]
        ],
        "default_year": int(manifest["default_year"]),
    }


def _resolve_context(
    polygon: list,
    coord_type: str,
    year: int | None = None,
    scope_id: str | None = None,
):
    dataset = resolve_dataset(year)
    geom_wgs84 = to_wgs84_geometry(polygon, coord_type)
    resolved_scope_id = str(scope_id or build_scope_id(geom_wgs84, int(dataset.year)))
    clip = load_or_compute_clip(resolved_scope_id, int(dataset.year), dataset.path, geom_wgs84)
    return dataset, resolved_scope_id, clip


def _empty_grid_payload(scope_id: str, year: int, source: str) -> dict[str, Any]:
    return {
        "scope_id": scope_id,
        "year": int(year),
        "source": str(source),
        "cell_count": 0,
        "features": [],
    }


def _empty_layer_payload(
    scope_id: str,
    year: int,
    unit: str,
    view: str = RADIANCE_VIEW,
    view_label: str = RADIANCE_VIEW_LABEL,
) -> dict[str, Any]:
    if view == HOTSPOT_VIEW:
        _, legend, _ = build_hotspot_layer_cells([], unit)
    elif view == GRADIENT_VIEW:
        _, legend, _ = build_gradient_layer_cells([], unit)
    else:
        legend = build_legend(RADIANCE_VIEW_LABEL, 0.0, 0.0, unit)
    return {
        "scope_id": scope_id,
        "year": int(year),
        "selected": selected_descriptor(int(year), unit, view=view, view_label=view_label),
        "summary": default_summary(),
        "analysis": {},
        "legend": legend,
        "cells": [],
    }


def _polygon_center_gcj02(polygon: list) -> list[float]:
    points: list[list[float]] = []

    def _collect(value: Any) -> None:
        if not isinstance(value, list):
            return
        if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
            points.append([float(value[0]), float(value[1])])
            return
        for item in value:
            _collect(item)

    _collect(polygon)
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    if not points:
        return []
    return [
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    ]


def _empty_raster_payload(scope_id: str, year: int, unit: str) -> dict[str, Any]:
    return {
        "scope_id": scope_id,
        "year": int(year),
        "selected": selected_descriptor(int(year), unit),
        "summary": default_summary(),
        "image_url": None,
        "bounds_gcj02": [],
        "legend": build_legend(RADIANCE_VIEW_LABEL, 0.0, 0.0, unit),
    }


def _build_complete_layer_analysis(
    summary: dict[str, Any],
    aggregated_cells: list,
    unit: str,
    center_gcj02: list[float] | None = None,
    base_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _, _, hotspot_analysis = build_hotspot_layer_cells(aggregated_cells, unit)
    _, _, gradient_analysis = build_gradient_layer_cells(aggregated_cells, unit)
    hotspot_cell_ids = set()
    raw_hotspot_ids = hotspot_analysis.pop("_hotspot_cell_ids", set()) if isinstance(hotspot_analysis, dict) else set()
    if isinstance(raw_hotspot_ids, set):
        hotspot_cell_ids = {str(item) for item in raw_hotspot_ids}
    analysis = dict(base_analysis or {})

    def _merge_payload(payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            if key == "_hotspot_cell_ids":
                continue
            current = analysis.get(key)
            if current in (None, "", [], {}, 0, 0.0):
                if value not in (None, "", [], {}, 0, 0.0):
                    analysis[key] = value

    _merge_payload(gradient_analysis if isinstance(gradient_analysis, dict) else {})
    _merge_payload(hotspot_analysis if isinstance(hotspot_analysis, dict) else {})
    return enrich_economic_activity_analysis(
        summary,
        analysis,
        aggregated_cells,
        center_gcj02=center_gcj02,
        hotspot_cell_ids=hotspot_cell_ids,
    )


def get_nightlight_overview(
    polygon: list,
    coord_type: str = "gcj02",
    year: int | None = None,
) -> dict[str, Any]:
    dataset, resolved_scope_id, clip = _resolve_context(polygon, coord_type, year)
    return {
        "scope_id": resolved_scope_id,
        "year": int(dataset.year),
        "summary": summarize_masked_values(None if clip.empty else clip.array),
    }


def get_nightlight_grid(
    polygon: list,
    coord_type: str = "gcj02",
    year: int | None = None,
) -> dict[str, Any]:
    dataset, resolved_scope_id, clip = _resolve_context(polygon, coord_type, year)
    if clip.empty:
        return _empty_grid_payload(resolved_scope_id, int(dataset.year), str(dataset.label or dataset.file))
    target_cells = load_target_cells(polygon, coord_type)
    features = [copy.deepcopy(cell.feature) for cell in target_cells if cell.feature is not None]
    for feature, cell in zip(features, (cell for cell in target_cells if cell.feature is not None)):
        feature["geometry_wgs84"] = mapping(cell.geometry_wgs84)
    return {
        "scope_id": resolved_scope_id,
        "year": int(dataset.year),
        "source": str(dataset.label or dataset.file),
        "cell_count": len(features),
        "features": features,
    }


def get_nightlight_layer(
    polygon: list,
    coord_type: str = "gcj02",
    scope_id: str | None = None,
    year: int | None = None,
    view: str = RADIANCE_VIEW,
) -> dict[str, Any]:
    safe_view = str(view or RADIANCE_VIEW).strip().lower()
    if safe_view not in {RADIANCE_VIEW, HOTSPOT_VIEW, GRADIENT_VIEW}:
        raise ValueError(f"unsupported nightlight view: {view}")
    dataset, resolved_scope_id, clip = _resolve_context(polygon, coord_type, year, scope_id=scope_id)
    if safe_view == HOTSPOT_VIEW:
        view_label = HOTSPOT_VIEW_LABEL
    elif safe_view == GRADIENT_VIEW:
        view_label = GRADIENT_VIEW_LABEL
    else:
        view_label = RADIANCE_VIEW_LABEL
    if clip.empty:
        return _empty_layer_payload(
            resolved_scope_id,
            int(dataset.year),
            str(dataset.unit),
            view=safe_view,
            view_label=view_label,
        )

    target_cells = load_target_cells(polygon, coord_type)
    aggregated_cells = aggregate_clip_to_target_cells(clip, target_cells)
    if safe_view == HOTSPOT_VIEW:
        cells, legend, view_analysis = build_hotspot_layer_cells(aggregated_cells, str(dataset.unit))
    elif safe_view == GRADIENT_VIEW:
        cells, legend, view_analysis = build_gradient_layer_cells(aggregated_cells, str(dataset.unit))
    else:
        cells, legend = build_layer_cells(aggregated_cells, str(dataset.unit))
        view_analysis = {}
    summary = summarize_masked_values(clip.array)
    analysis = _build_complete_layer_analysis(
        summary,
        aggregated_cells,
        str(dataset.unit),
        center_gcj02=_polygon_center_gcj02(polygon),
        base_analysis=view_analysis,
    )
    return {
        "scope_id": resolved_scope_id,
        "year": int(dataset.year),
        "selected": selected_descriptor(
            int(dataset.year),
            str(dataset.unit),
            view=safe_view,
            view_label=view_label,
        ),
        "summary": summary,
        "analysis": analysis,
        "legend": legend,
        "cells": cells,
    }


def get_nightlight_raster_preview(
    polygon: list,
    coord_type: str = "gcj02",
    scope_id: str | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    dataset, resolved_scope_id, clip = _resolve_context(polygon, coord_type, year, scope_id=scope_id)
    if clip.empty or clip.array is None or clip.transform is None:
        return _empty_raster_payload(resolved_scope_id, int(dataset.year), str(dataset.unit))

    image, min_value, max_value = colorize_nightlight_array(
        clip.array,
        int(settings.nightlight_preview_max_size or 2048),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        "scope_id": resolved_scope_id,
        "year": int(dataset.year),
        "selected": selected_descriptor(int(dataset.year), str(dataset.unit)),
        "summary": summarize_masked_values(clip.array),
        "image_url": image_url,
        "bounds_gcj02": bounds_gcj02_from_transform(clip.transform, int(clip.width), int(clip.height)),
        "legend": build_legend(RADIANCE_VIEW_LABEL, min_value, max_value, str(dataset.unit)),
    }
