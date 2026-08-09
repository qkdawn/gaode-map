from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02

from .common import PREVIEW_PALETTE, RADIANCE_UNIT, RADIANCE_VIEW, RADIANCE_VIEW_LABEL, round_float, year_label
from .dataset import require_rasterio
from .types import AggregatedNightlightCell


def require_pillow():
    try:
        from PIL import Image  # type: ignore

        return Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"nightlight pillow import failed: {exc.__class__.__name__}: {exc}"
        ) from exc


def default_summary() -> dict[str, Any]:
    return {
        "total_radiance": 0.0,
        "mean_radiance": 0.0,
        "max_radiance": 0.0,
        "lit_pixel_ratio": 0.0,
        "p90_radiance": 0.0,
        "valid_pixel_count": 0,
        "lit_pixel_count": 0,
    }


def _extract_valid_values(masked_array: np.ma.MaskedArray) -> np.ndarray:
    values = np.ma.filled(masked_array, np.nan).astype(np.float64)
    mask = np.ma.getmaskarray(masked_array)
    valid = (~mask) & np.isfinite(values)
    if not np.any(valid):
        return np.asarray([], dtype=np.float64)
    return np.maximum(values[valid], 0.0)


def summarize_masked_values(masked_array: np.ma.MaskedArray | None) -> dict[str, Any]:
    if masked_array is None:
        return default_summary()
    values = _extract_valid_values(masked_array)
    valid_count = int(values.size)
    if valid_count <= 0:
        return default_summary()
    lit_values = values[values > 0]
    lit_count = int(lit_values.size)
    return {
        "total_radiance": round_float(np.sum(values), 3),
        "mean_radiance": round_float(np.mean(values), 3),
        "max_radiance": round_float(np.max(values), 3),
        "lit_pixel_ratio": round_float((lit_count / valid_count), 6),
        "p90_radiance": round_float(np.percentile(values, 90), 3),
        "valid_pixel_count": valid_count,
        "lit_pixel_count": lit_count,
    }


def _palette_color(ratio: float) -> tuple[int, int, int]:
    if ratio <= 0:
        return PREVIEW_PALETTE[0]
    if ratio >= 1:
        return PREVIEW_PALETTE[-1]
    scaled = ratio * (len(PREVIEW_PALETTE) - 1)
    idx = int(np.floor(scaled))
    if idx >= len(PREVIEW_PALETTE) - 1:
        return PREVIEW_PALETTE[-1]
    local = scaled - idx
    left = PREVIEW_PALETTE[idx]
    right = PREVIEW_PALETTE[idx + 1]
    return tuple(
        int(round(left[channel] + (right[channel] - left[channel]) * local))
        for channel in range(3)
    )


def radiance_percentile(values: Iterable[float], percentile: float) -> float:
    materialized: list[float] = []
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(numeric):
            materialized.append(max(0.0, numeric))
    usable = np.asarray(materialized, dtype=np.float64)
    positive = usable[usable > 0]
    return float(np.percentile(positive, percentile)) if positive.size else 0.0


def radiance_domain(values: Iterable[float]) -> tuple[float, float]:
    materialized = list(values)
    min_value = radiance_percentile(materialized, 5)
    max_value = radiance_percentile(materialized, 98)
    if max_value <= min_value:
        positive = []
        for value in materialized:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(numeric) and numeric > 0:
                positive.append(numeric)
        min_value = min(positive, default=0.0)
        max_value = max(positive, default=0.0)
    return min_value, max_value


def radiance_style(value: float, *, min_value: float, max_value: float, has_data: bool = True) -> dict[str, Any]:
    raw_value = max(0.0, float(value))
    if not has_data:
        return {
            "fill_color": "#94a3b8",
            "stroke_color": "#64748b",
            "fill_opacity": 0.16,
            "normalized": 0.0,
        }
    span = max(max_value - min_value, 1e-9)
    normalized = 0.0 if max_value <= min_value else max(0.0, min(1.0, (raw_value - min_value) / span))
    color = _palette_color(normalized if raw_value > 0 else 0.0)
    return {
        "fill_color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
        "stroke_color": "#94a3b8" if raw_value <= 0 else "#ffffff",
        "fill_opacity": round_float(0.28 + (0.40 * normalized), 3),
        "normalized": round_float(normalized, 6),
    }


def build_legend(title: str, min_value: float, max_value: float, unit: str = RADIANCE_UNIT) -> dict[str, Any]:
    stops = []
    for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
        value = min_value + ((max_value - min_value) * ratio)
        color = _palette_color(ratio)
        stops.append(
            {
                "ratio": round_float(ratio, 3),
                "color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                "value": round_float(value, 3),
                "label": None,
            }
        )
    return {
        "title": title,
        "kind": "continuous",
        "unit": unit,
        "min_value": round_float(min_value, 3),
        "max_value": round_float(max_value, 3),
        "stops": stops,
    }


def build_layer_cells(
    aggregated_cells: list[AggregatedNightlightCell],
    unit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not aggregated_cells:
        return [], build_legend(RADIANCE_VIEW_LABEL, 0.0, 0.0, unit)
    data_cells = [cell for cell in aggregated_cells if int(cell.valid_pixel_count) > 0]
    values = [max(0.0, float(cell.raw_value)) for cell in data_cells]
    min_value, max_value = radiance_domain(values)
    cells = []
    for cell in aggregated_cells:
        valid_pixel_count = int(max(0, int(cell.valid_pixel_count)))
        has_data = valid_pixel_count > 0
        raw_value = max(0.0, float(cell.raw_value))
        if has_data:
            style = radiance_style(raw_value, min_value=min_value, max_value=max_value)
            fill_color = str(style["fill_color"])
            stroke_color = str(style["stroke_color"])
            opacity = float(style["fill_opacity"])
            label = f"{RADIANCE_VIEW_LABEL} {round_float(raw_value, 2)} {unit}"
        else:
            fill_color = "#94a3b8"
            stroke_color = "#64748b"
            opacity = 0.16
            label = "无有效夜光像素"
        cells.append(
            {
                "cell_id": str(cell.cell_id),
                "value": round_float(raw_value, 3),
                "valid_pixel_count": valid_pixel_count,
                "has_data": has_data,
                "fill_color": fill_color,
                "stroke_color": stroke_color,
                "fill_opacity": round_float(opacity, 3),
                "label": label,
            }
        )
    return cells, build_legend(RADIANCE_VIEW_LABEL, min_value, max_value, unit)


def selected_descriptor(year: int, unit: str, view: str = RADIANCE_VIEW, view_label: str = RADIANCE_VIEW_LABEL) -> dict[str, Any]:
    return {
        "year": int(year),
        "year_label": year_label(year),
        "view": str(view),
        "view_label": str(view_label),
        "unit": unit,
    }


def colorize_nightlight_array(masked_array: np.ma.MaskedArray, max_size: int):
    Image = require_pillow()

    values = np.ma.filled(masked_array, np.nan).astype(np.float64)
    mask = np.ma.getmaskarray(masked_array)
    valid = (~mask) & np.isfinite(values)
    safe = np.where(valid, np.maximum(values, 0.0), 0.0)
    height, width = safe.shape
    if height <= 0 or width <= 0:
        raise RuntimeError("empty nightlight raster preview")

    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    positive = safe[safe > 0]
    if positive.size:
        min_value = float(np.percentile(positive, 5))
        max_value = float(np.percentile(positive, 98))
        if max_value <= min_value:
            min_value = float(np.min(positive))
            max_value = float(np.max(positive))
        log_valid = np.log1p(safe)
        log_min = np.log1p(max(min_value, 0.0))
        log_max = np.log1p(max(max_value, min_value + 1e-9))
        span = max(log_max - log_min, 1e-9)
        normalized = np.clip((log_valid - log_min) / span, 0.0, 1.0)
        normalized = np.where(safe > 0, normalized, 0.0)
        scaled = normalized * (len(PREVIEW_PALETTE) - 1)
        left_idx = np.floor(scaled).astype(np.int64)
        left_idx = np.clip(left_idx, 0, len(PREVIEW_PALETTE) - 1)
        right_idx = np.clip(left_idx + 1, 0, len(PREVIEW_PALETTE) - 1)
        local_ratio = (scaled - left_idx).astype(np.float64)
        palette = np.asarray(PREVIEW_PALETTE, dtype=np.float64)
        left_colors = palette[left_idx]
        right_colors = palette[right_idx]
        rgb = left_colors + ((right_colors - left_colors) * local_ratio[..., None])
        rgba[..., 0] = np.where(safe > 0, rgb[..., 0], 0).astype(np.uint8)
        rgba[..., 1] = np.where(safe > 0, rgb[..., 1], 0).astype(np.uint8)
        rgba[..., 2] = np.where(safe > 0, rgb[..., 2], 0).astype(np.uint8)
        alpha = np.where(
            normalized > 0.025,
            18 + (210 * np.power(normalized, 0.8)),
            0,
        )
        rgba[..., 3] = alpha.astype(np.uint8)
    else:
        min_value = 0.0
        max_value = 0.0

    image = Image.fromarray(rgba, mode="RGBA")
    longest = max(width, height)
    if longest > max_size:
        scale = max_size / float(longest)
        target_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        image = image.resize(target_size, Image.Resampling.NEAREST)
    return image, min_value, max_value


def bounds_gcj02_from_transform(masked_transform, width: int, height: int) -> list[list[float]]:
    _, _, array_bounds = require_rasterio()
    west, south, east, north = array_bounds(height, width, masked_transform)
    sw = wgs84_to_gcj02(west, south)
    ne = wgs84_to_gcj02(east, north)
    return [
        [float(sw[0]), float(sw[1])],
        [float(ne[0]), float(ne[1])],
    ]
