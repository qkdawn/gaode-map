from __future__ import annotations

from typing import Any, Dict

import numpy as np

from core.spatial import round_float
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02

from .dataset import require_rasterio
from .registry import age_band_keys, get_age_band_label

PREVIEW_PALETTE = [
    (14, 116, 144),
    (45, 212, 191),
    (250, 204, 21),
    (249, 115, 22),
    (190, 24, 93),
]
DENSITY_UNIT = "人/平方公里"
PERCENT_UNIT = "%"
DOMINANT_AGE_COLORS = {
    "00": "#7dd3fc",
    "01": "#60a5fa",
    "05": "#818cf8",
    "10": "#a78bfa",
    "15": "#c084fc",
    "20": "#e879f9",
    "25": "#f472b6",
    "30": "#fb7185",
    "35": "#f43f5e",
    "40": "#ef4444",
    "45": "#f97316",
    "50": "#f59e0b",
    "55": "#eab308",
    "60": "#84cc16",
    "65": "#22c55e",
    "70": "#10b981",
    "75": "#14b8a6",
    "80": "#06b6d4",
    "85": "#0ea5e9",
    "90": "#0284c7",
}


def require_pillow():
    try:
        from PIL import Image  # type: ignore

        return Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"population analysis pillow import failed: {exc.__class__.__name__}: {exc}"
        ) from exc


def format_number_label(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        num = 0.0
    if num >= 100000000:
        return f"{num / 100000000:.2f}亿"
    if num >= 10000:
        return f"{num / 10000:.1f}万"
    if abs(num) >= 100:
        return f"{round(num):.0f}"
    if abs(num) >= 10:
        return f"{num:.1f}"
    return f"{num:.2f}"


def build_cell_id(row: int, col: int) -> str:
    return f"r{int(row)}_c{int(col)}"


def cell_bounds_from_transform(masked_transform, row: int, col: int) -> tuple[float, float, float, float]:
    left_top = masked_transform * (col, row)
    right_bottom = masked_transform * (col + 1, row + 1)
    west = min(float(left_top[0]), float(right_bottom[0]))
    east = max(float(left_top[0]), float(right_bottom[0]))
    south = min(float(left_top[1]), float(right_bottom[1]))
    north = max(float(left_top[1]), float(right_bottom[1]))
    return west, south, east, north


def cell_polygon_gcj02(masked_transform, row: int, col: int) -> list[list[list[float]]]:
    west, south, east, north = cell_bounds_from_transform(masked_transform, row, col)
    ring_wgs84 = [
        (west, north),
        (east, north),
        (east, south),
        (west, south),
        (west, north),
    ]
    ring_gcj02 = [
        [round_float(pair[0], 6), round_float(pair[1], 6)]
        for pair in (wgs84_to_gcj02(lng, lat) for lng, lat in ring_wgs84)
    ]
    return [ring_gcj02]


def cell_polygon_wgs84(masked_transform, row: int, col: int) -> list[list[list[float]]]:
    west, south, east, north = cell_bounds_from_transform(masked_transform, row, col)
    return [[
        [round_float(west, 6), round_float(north, 6)],
        [round_float(east, 6), round_float(north, 6)],
        [round_float(east, 6), round_float(south, 6)],
        [round_float(west, 6), round_float(south, 6)],
        [round_float(west, 6), round_float(north, 6)],
    ]]


def cell_centroid_gcj02(masked_transform, row: int, col: int) -> list[float]:
    center = masked_transform * (col + 0.5, row + 0.5)
    lng, lat = wgs84_to_gcj02(float(center[0]), float(center[1]))
    return [round_float(lng, 6), round_float(lat, 6)]


def iter_population_cells(masked_array: np.ma.MaskedArray, masked_transform):
    values = np.ma.filled(masked_array, 0.0).astype(np.float64)
    mask = np.ma.getmaskarray(masked_array)
    height, width = values.shape
    for row in range(height):
        for col in range(width):
            if bool(mask[row, col]):
                continue
            raw_value = max(0.0, float(values[row, col]))
            yield {
                "cell_id": build_cell_id(row, col),
                "row": int(row),
                "col": int(col),
                "raw_value": round_float(raw_value, 6),
                "centroid_gcj02": cell_centroid_gcj02(masked_transform, row, col),
                "geometry_gcj02": cell_polygon_gcj02(masked_transform, row, col),
                "geometry_wgs84": cell_polygon_wgs84(masked_transform, row, col),
            }


def color_to_hex(color: tuple[int, int, int]) -> str:
    return f"#{int(color[0]):02x}{int(color[1]):02x}{int(color[2]):02x}"


def palette_color(ratio: float) -> tuple[int, int, int]:
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
    return tuple(int(round(left[channel] + (right[channel] - left[channel]) * local)) for channel in range(3))


def colorize_population_array(masked_array: np.ma.MaskedArray, max_size: int):
    Image = require_pillow()

    valid = np.ma.filled(masked_array, 0.0).astype(np.float64)
    positive = valid[valid > 0]
    height, width = valid.shape
    if height <= 0 or width <= 0:
        raise RuntimeError("empty raster preview")

    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    if positive.size:
        min_value = float(np.percentile(positive, 8))
        max_value = float(np.percentile(positive, 98.5))
        if max_value <= min_value:
            min_value = float(np.min(positive))
            max_value = float(np.max(positive))
        log_valid = np.log1p(np.maximum(valid, 0.0))
        log_min = np.log1p(max(min_value, 0.0))
        log_max = np.log1p(max(max_value, min_value + 1e-9))
        span = max(log_max - log_min, 1e-9)
        normalized = np.clip((log_valid - log_min) / span, 0.0, 1.0)
        normalized = np.where(valid > 0, normalized, 0.0)
        scaled = normalized * (len(PREVIEW_PALETTE) - 1)
        left_idx = np.floor(scaled).astype(np.int64)
        left_idx = np.clip(left_idx, 0, len(PREVIEW_PALETTE) - 1)
        right_idx = np.clip(left_idx + 1, 0, len(PREVIEW_PALETTE) - 1)
        local_ratio = (scaled - left_idx).astype(np.float64)
        palette = np.asarray(PREVIEW_PALETTE, dtype=np.float64)
        left_colors = palette[left_idx]
        right_colors = palette[right_idx]
        rgb = left_colors + ((right_colors - left_colors) * local_ratio[..., None])
        rgba[..., 0] = np.where(valid > 0, rgb[..., 0], 0).astype(np.uint8)
        rgba[..., 1] = np.where(valid > 0, rgb[..., 1], 0).astype(np.uint8)
        rgba[..., 2] = np.where(valid > 0, rgb[..., 2], 0).astype(np.uint8)
        alpha = np.where(normalized > 0.025, 12 + (188 * np.power(normalized, 0.92)), 0)
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
    return [[float(sw[0]), float(sw[1])], [float(ne[0]), float(ne[1])]]


def build_legend(title: str, min_value: float, max_value: float, unit: str = "人口") -> Dict[str, Any]:
    stops = []
    for idx, ratio in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
        value = min_value + (max_value - min_value) * ratio
        color = palette_color(ratio)
        stops.append(
            {
                "ratio": ratio,
                "color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                "value": round_float(value, 3),
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


def build_categorical_legend(title: str, items: list[dict[str, Any]], unit: str = "") -> Dict[str, Any]:
    stops = []
    total = max(len(items) - 1, 1)
    for idx, item in enumerate(items):
        stops.append(
            {
                "ratio": round_float(idx / total, 3),
                "color": str(item.get("color") or "#d1d5db"),
                "value": float(item.get("value") or 0.0),
                "label": str(item.get("label") or ""),
            }
        )
    return {
        "title": title,
        "kind": "categorical",
        "unit": unit,
        "min_value": 0.0,
        "max_value": float(len(items)),
        "stops": stops,
    }


def filled_values(masked_array: np.ma.MaskedArray) -> tuple[np.ndarray, np.ndarray]:
    values = np.ma.filled(masked_array, 0.0).astype(np.float64)
    mask = np.ma.getmaskarray(masked_array)
    return values, mask


def ensure_layer_alignment(base_layer: Dict[str, Any], other_layer: Dict[str, Any]) -> None:
    if base_layer.get("shape") != other_layer.get("shape") or base_layer.get("transform") != other_layer.get("transform"):
        raise RuntimeError("population raster alignment mismatch")


def build_age_ratio_cells(total_layer: Dict[str, Any], age_layer: Dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    ensure_layer_alignment(total_layer, age_layer)
    total_values, total_mask = filled_values(total_layer["array"])
    age_values, age_mask = filled_values(age_layer["array"])
    height, width = total_values.shape
    cells: list[dict[str, Any]] = []
    age_sum = 0.0
    for row in range(height):
        for col in range(width):
            if bool(total_mask[row, col]):
                continue
            total_value = max(0.0, float(total_values[row, col]))
            age_value = 0.0 if bool(age_mask[row, col]) else max(0.0, float(age_values[row, col]))
            ratio_value = (age_value / total_value) if total_value > 0 else 0.0
            age_sum += age_value
            cells.append(
                {
                    "cell_id": build_cell_id(row, col),
                    "row": int(row),
                    "col": int(col),
                    "raw_value": round_float(age_value, 6),
                    "ratio_value": round_float(ratio_value, 6),
                    "display_value": round_float(ratio_value * 100.0, 6),
                    "centroid_gcj02": cell_centroid_gcj02(total_layer["transform"], row, col),
                    "geometry_gcj02": cell_polygon_gcj02(total_layer["transform"], row, col),
                }
            )
    return cells, age_sum


def build_dominant_age_cells(
    total_layer: Dict[str, Any],
    age_layers: Dict[str, Dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    total_values, total_mask = filled_values(total_layer["array"])
    prepared_layers: Dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for age_band, layer in age_layers.items():
        ensure_layer_alignment(total_layer, layer)
        prepared_layers[age_band] = filled_values(layer["array"])
    height, width = total_values.shape
    cells: list[dict[str, Any]] = []
    dominant_counts = {age_band: 0 for age_band in age_band_keys()}
    for row in range(height):
        for col in range(width):
            if bool(total_mask[row, col]):
                continue
            total_value = max(0.0, float(total_values[row, col]))
            dominant_age_band = None
            dominant_age_value = 0.0
            for age_band in age_band_keys():
                values, mask = prepared_layers[age_band]
                age_value = 0.0 if bool(mask[row, col]) else max(0.0, float(values[row, col]))
                if dominant_age_band is None or age_value > dominant_age_value:
                    dominant_age_band = age_band
                    dominant_age_value = age_value
            dominant_ratio = (dominant_age_value / total_value) if total_value > 0 else 0.0
            if dominant_age_band:
                dominant_counts[dominant_age_band] += 1
            cells.append(
                {
                    "cell_id": build_cell_id(row, col),
                    "row": int(row),
                    "col": int(col),
                    "raw_value": round_float(dominant_age_value, 6),
                    "dominant_age_band": dominant_age_band,
                    "dominant_age_band_label": get_age_band_label(dominant_age_band or "all"),
                    "ratio_value": round_float(dominant_ratio, 6),
                    "display_value": round_float(dominant_ratio * 100.0, 6),
                    "centroid_gcj02": cell_centroid_gcj02(total_layer["transform"], row, col),
                    "geometry_gcj02": cell_polygon_gcj02(total_layer["transform"], row, col),
                }
            )
    return cells, dominant_counts


def build_population_layer_cell_styles(
    cells: list[dict[str, Any]],
    value_key: str,
    unit: str,
    value_label: str,
) -> tuple[list[dict[str, Any]], float, float]:
    positive_values = [float(cell.get(value_key) or 0.0) for cell in cells if float(cell.get(value_key) or 0.0) > 0]
    if positive_values:
        min_value = float(np.percentile(np.asarray(positive_values, dtype=np.float64), 8))
        max_value = float(np.percentile(np.asarray(positive_values, dtype=np.float64), 98.5))
        if max_value <= min_value:
            min_value = float(min(positive_values))
            max_value = float(max(positive_values))
    else:
        min_value = 0.0
        max_value = 0.0

    span = max(max_value - min_value, 1e-9)
    styled_cells: list[dict[str, Any]] = []
    for cell in cells:
        value = max(0.0, float(cell.get(value_key) or 0.0))
        if value > 0 and max_value > 0:
            ratio = np.clip((value - min_value) / span, 0.0, 1.0)
            fill_color = color_to_hex(palette_color(float(ratio)))
            fill_opacity = 0.28 + (0.52 * float(np.power(ratio, 0.72)))
            stroke_color = "#ffffff"
        else:
            fill_color = "#f4f5f7"
            fill_opacity = 0.12
            stroke_color = "#d7dde7"
        styled_cells.append(
            {
                "cell_id": cell["cell_id"],
                "value": round_float(value, 3),
                "fill_color": fill_color,
                "stroke_color": stroke_color,
                "fill_opacity": round_float(fill_opacity, 3),
                "label": f"{value_label} {format_number_label(value)} {unit}",
            }
        )
    return styled_cells, min_value, max_value


def build_discrete_ratio_cell_styles(
    cells: list[dict[str, Any]],
    value_key: str,
    value_label: str,
    max_buckets: int = 12,
) -> tuple[list[dict[str, Any]], Dict[str, Any], int] | None:
    rounded_values = sorted(
        {
            round_float(max(0.0, float(cell.get(value_key) or 0.0)), 3)
            for cell in cells
            if float(cell.get(value_key) or 0.0) > 0
        }
    )
    if not rounded_values or len(rounded_values) > max_buckets:
        return None

    total = max(len(rounded_values) - 1, 1)
    value_to_index = {value: idx for idx, value in enumerate(rounded_values)}
    styled_cells: list[dict[str, Any]] = []
    for cell in cells:
        value = max(0.0, float(cell.get(value_key) or 0.0))
        if value > 0:
            rounded = round_float(value, 3)
            idx = value_to_index.get(rounded, 0)
            ratio = idx / total
            fill_color = color_to_hex(palette_color(float(ratio)))
            fill_opacity = 0.34 + (0.46 * float(np.power(ratio, 0.72)))
            stroke_color = "#ffffff"
        else:
            fill_color = "#f4f5f7"
            fill_opacity = 0.12
            stroke_color = "#d7dde7"
        styled_cells.append(
            {
                "cell_id": cell["cell_id"],
                "value": round_float(value, 3),
                "fill_color": fill_color,
                "stroke_color": stroke_color,
                "fill_opacity": round_float(fill_opacity, 3),
                "label": f"{value_label} {round_float(value, 3)}%",
            }
        )

    legend_items = []
    for idx, value in enumerate(rounded_values):
        ratio = idx / total
        color = color_to_hex(palette_color(float(ratio)))
        legend_items.append({"label": f"{round_float(value, 3)}%", "color": color, "value": round_float(value, 3)})
    legend = build_categorical_legend(value_label, legend_items, PERCENT_UNIT)
    return styled_cells, legend, len(rounded_values)


def build_dominant_age_cell_styles(cells: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Dict[str, int]]:
    styled_cells: list[dict[str, Any]] = []
    category_counts = {age_band: 0 for age_band in age_band_keys()}
    for cell in cells:
        age_band = str(cell.get("dominant_age_band") or "")
        ratio_percent = max(0.0, float(cell.get("display_value") or 0.0))
        if age_band in category_counts:
            category_counts[age_band] += 1
        fill_color = DOMINANT_AGE_COLORS.get(age_band, "#d1d5db")
        fill_opacity = 0.26 + (0.54 * float(np.power(np.clip(ratio_percent / 100.0, 0.0, 1.0), 0.72)))
        styled_cells.append(
            {
                "cell_id": cell["cell_id"],
                "value": round_float(ratio_percent, 3),
                "fill_color": fill_color,
                "stroke_color": "#ffffff",
                "fill_opacity": round_float(fill_opacity, 3),
                "label": f"主导年龄 {get_age_band_label(age_band)}，占比 {round_float(ratio_percent, 2)}%",
            }
        )
    return styled_cells, category_counts


def build_population_layer_summary(
    view: str,
    selected: Dict[str, Any],
    overview: Dict[str, Any],
    cells: list[dict[str, Any]],
    display_values: list[float],
    raw_sum: float,
    age_band: str,
) -> Dict[str, Any]:
    overview_summary = overview.get("summary") or {}
    total_population = float(overview_summary.get("total_population") or 0.0)
    nonzero_cell_count = int(sum(1 for value in display_values if value > 0))
    cell_count = len(cells)
    peak_value = float(max(display_values)) if display_values else 0.0
    average_value = float(sum(display_values) / cell_count) if cell_count else 0.0

    if view == "sex":
        selected_population = raw_sum
        return {
            "male_total": round_float(float(overview_summary.get("male_total") or 0.0), 3),
            "female_total": round_float(float(overview_summary.get("female_total") or 0.0), 3),
            "male_ratio": round_float(float(overview_summary.get("male_ratio") or 0.0), 6),
            "female_ratio": round_float(float(overview_summary.get("female_ratio") or 0.0), 6),
            "selected_population": round_float(selected_population, 3),
            "ratio_of_total_population": round_float((selected_population / total_population), 6) if total_population > 0 else 0.0,
            "peak_density_per_km2": round_float(peak_value, 3),
            "average_density_per_km2": round_float(average_value, 3),
            "nonzero_cell_count": nonzero_cell_count,
            "sex_mode": selected.get("sex_mode"),
            "sex_mode_label": selected.get("sex_mode_label"),
        }
    if view == "age":
        age_mode = str(selected.get("age_mode") or "ratio")
        if age_mode == "dominant":
            dominant_counter: Dict[str, int] = {}
            for cell in cells:
                key = str(cell.get("dominant_age_band") or "")
                if not key:
                    continue
                dominant_counter[key] = int(dominant_counter.get(key) or 0) + 1
            top_age_band = max(dominant_counter, key=dominant_counter.get, default="")
            dominant_cell_count = int(dominant_counter.get(top_age_band) or 0)
            dominant_cell_ratio = (float(dominant_cell_count) / float(cell_count)) if cell_count > 0 else 0.0
            return {
                "top_dominant_age_band": top_age_band or None,
                "top_dominant_age_band_label": get_age_band_label(top_age_band) if top_age_band else None,
                "dominant_cell_count": dominant_cell_count,
                "dominant_cell_ratio": round_float(dominant_cell_ratio, 6),
                "average_dominant_ratio_percent": round_float(average_value, 3),
                "peak_dominant_ratio_percent": round_float(peak_value, 3),
                "nonzero_cell_count": nonzero_cell_count,
                "age_mode": age_mode,
            }
        return {
            "selected_population": round_float(raw_sum, 3),
            "ratio_of_total_population": round_float((raw_sum / total_population), 6) if total_population > 0 else 0.0,
            "peak_ratio_percent": round_float(peak_value, 3),
            "nonzero_cell_count": nonzero_cell_count,
            "value_bucket_count": len(
                {
                    round_float(max(0.0, float(cell.get("display_value") or 0.0)), 6)
                    for cell in cells
                    if float(cell.get("display_value") or 0.0) > 0
                }
            ),
            "age_band": age_band,
            "age_band_label": get_age_band_label(age_band),
            "age_mode": age_mode,
        }
    if view == "overview":
        age_rows = overview.get("age_distribution") or []
        dominant_age_row = max(age_rows, key=lambda item: float(item.get("total") or 0.0), default=None)
        return {
            "total_population": round_float(total_population, 3),
            "male_total": round_float(float(overview_summary.get("male_total") or 0.0), 3),
            "female_total": round_float(float(overview_summary.get("female_total") or 0.0), 3),
            "male_ratio": round_float(float(overview_summary.get("male_ratio") or 0.0), 6),
            "female_ratio": round_float(float(overview_summary.get("female_ratio") or 0.0), 6),
            "selected_population": round_float(total_population, 3),
            "ratio_of_total_population": 1.0 if total_population > 0 else 0.0,
            "peak_density_per_km2": round_float(peak_value, 3),
            "nonzero_cell_count": nonzero_cell_count,
            "dominant_age_band": dominant_age_row.get("age_band") if dominant_age_row else None,
            "dominant_age_band_label": dominant_age_row.get("age_band_label") if dominant_age_row else None,
            "dominant_age_population": round_float(float((dominant_age_row or {}).get("total") or 0.0), 3),
        }
    return {
        "total_population": round_float(total_population, 3),
        "selected_population": round_float(total_population, 3),
        "ratio_of_total_population": 1.0 if total_population > 0 else 0.0,
        "average_density_per_km2": round_float(average_value, 3),
        "peak_density_per_km2": round_float(peak_value, 3),
        "nonzero_cell_count": nonzero_cell_count,
        "cell_count": cell_count,
    }
