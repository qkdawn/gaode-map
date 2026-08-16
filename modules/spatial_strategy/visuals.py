from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageColor, ImageDraw, ImageFont
from shapely.errors import ShapelyError
from shapely.geometry import shape as shapely_shape
from shapely.ops import unary_union
from sqlalchemy.exc import SQLAlchemyError

from core.config import settings
from modules.nightlight.analysis import build_gradient_layer_cells, build_hotspot_layer_cells
from modules.nightlight.common import RADIANCE_UNIT
from modules.nightlight.render import radiance_domain, radiance_percentile, radiance_style
from modules.nightlight.types import AggregatedNightlightCell

from .project_data import _DATA, _resolve_history_id
from modules.spatial_projects.data_contract import DATASET_SCHEMAS, DATASET_SOURCES


_WIDTH = 1600
_HEIGHT = 1000
_PADDING = 90
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_DEFAULT_COLORS = ("#2563eb", "#e11d48", "#16a34a", "#ea580c", "#7c3aed", "#0891b2")
_DATASET_LABELS = {
    "poi": "城市设施",
    "road_nodes": "路网节点",
    "road_edges": "道路网络",
    "population": "常住人口",
    "nightlight": "夜光辐亮度",
}
_POI_COLORS = {
    "餐饮服务": "#d95d39",
    "购物服务": "#f4a261",
    "科教文化服务": "#2a9d8f",
    "风景名胜": "#16856b",
    "交通设施服务": "#457b9d",
    "医疗保健服务": "#d1495b",
    "政府机构及社会团体": "#6d597a",
    "住宿服务": "#8d6e63",
    "公司企业": "#7b8794",
    "商务住宅": "#9c89b8",
    "其他": "#98a2b3",
}


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = list(_FONT_CANDIDATES)
    if bold:
        candidates.insert(0, "C:/Windows/Fonts/msyhbd.ttc")
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x, y = _number(value[0]), _number(value[1])
    return (x, y) if x is not None and y is not None else None


def _geometry_points(geometry: Any) -> list[tuple[float, float]]:
    if not isinstance(geometry, Mapping):
        return []
    coordinates = geometry.get("coordinates")
    geometry_type = str(geometry.get("type") or "")
    if geometry_type == "Point":
        point = _point(coordinates)
        return [point] if point else []
    if geometry_type == "LineString":
        return [point for point in (_point(value) for value in coordinates or []) if point]
    if geometry_type == "MultiLineString":
        return [point for line in coordinates or [] for point in (_point(value) for value in line) if point]
    if geometry_type == "Polygon":
        ring = (coordinates or [[]])[0] if isinstance(coordinates, list) and coordinates else []
        return [point for point in (_point(value) for value in ring) if point]
    if geometry_type == "MultiPolygon":
        return [
            point
            for polygon in coordinates or []
            for ring in (polygon[:1] if isinstance(polygon, list) else [])
            for point in (_point(value) for value in ring)
            if point
        ]
    return []


def _bounds(groups: Iterable[Iterable[tuple[float, float]]]) -> tuple[float, float, float, float] | None:
    points = [point for group in groups for point in group]
    if not points:
        return None
    xs, ys = zip(*points)
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if min_x == max_x:
        min_x -= 0.005
        max_x += 0.005
    if min_y == max_y:
        min_y -= 0.005
        max_y += 0.005
    return min_x, min_y, max_x, max_y


def _project(
    point: tuple[float, float],
    bounds: tuple[float, float, float, float],
    *,
    right_padding: int = _PADDING,
    canvas_width: int = _WIDTH,
    canvas_height: int = _HEIGHT,
) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    center_latitude = (min_y + max_y) / 2.0
    longitude_scale = max(0.01, math.cos(math.radians(center_latitude)))
    projected_width = (max_x - min_x) * longitude_scale
    projected_height = max_y - min_y
    frame_width = canvas_width - _PADDING - right_padding
    frame_height = canvas_height - 2 * _PADDING
    scale = min(frame_width / projected_width, frame_height / projected_height)
    used_width = projected_width * scale
    used_height = projected_height * scale
    offset_x = _PADDING + (frame_width - used_width) / 2.0
    offset_y = _PADDING + (frame_height - used_height) / 2.0
    x = offset_x + (point[0] - min_x) * longitude_scale * scale
    y = offset_y + (max_y - point[1]) * scale
    return x, y


def _projection_metadata(
    bounds: tuple[float, float, float, float],
    *,
    right_padding: int,
    canvas_width: int = _WIDTH,
    canvas_height: int = _HEIGHT,
) -> dict[str, Any]:
    min_x, min_y, max_x, max_y = bounds
    center_latitude = (min_y + max_y) / 2.0
    longitude_scale = max(0.01, math.cos(math.radians(center_latitude)))
    projected_width = (max_x - min_x) * longitude_scale
    projected_height = max_y - min_y
    frame_width = canvas_width - _PADDING - right_padding
    frame_height = canvas_height - 2 * _PADDING
    scale = min(frame_width / projected_width, frame_height / projected_height)
    used_width = projected_width * scale
    used_height = projected_height * scale
    return {
        "method": "local_equirectangular_wgs84",
        "center_latitude": round(center_latitude, 6),
        "projected_extent_aspect_ratio": round(projected_width / projected_height, 6),
        "map_frame_aspect_ratio": round(
            frame_width / frame_height,
            6,
        ),
        "axis_scale_delta_percent": 0.0,
        "content_occupancy_ratio": round((used_width * used_height) / (frame_width * frame_height), 6),
        "canvas_size_px": {"width": canvas_width, "height": canvas_height},
    }


def _map_canvas_size(
    bounds: tuple[float, float, float, float], *, has_side_panel: bool = False
) -> tuple[int, int]:
    if has_side_panel:
        return _WIDTH, _HEIGHT
    min_x, min_y, max_x, max_y = bounds
    longitude_scale = max(0.01, math.cos(math.radians((min_y + max_y) / 2.0)))
    aspect = ((max_x - min_x) * longitude_scale) / (max_y - min_y)
    if aspect < 0.5:
        return 900, 1400
    if aspect < 0.82:
        return 1200, 1400
    if aspect > 1.45:
        return 1600, 1000
    return 1200, 1200


def _canvas(
    title: str, subtitle: str = "", *, width: int = _WIDTH, height: int = _HEIGHT
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 70), fill="#ffffff")
    draw.text((_PADDING, 18), title, fill="#172033", font=_font(32, bold=True))
    if subtitle:
        draw.text((_PADDING, 58), subtitle, fill="#667085", font=_font(16))
    return image, draw


def _save(
    image: Image.Image,
    directory: Path,
    filename: str,
    title: str,
    *,
    source_datasets: list[dict[str, Any]] | None = None,
    design: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    target = directory / filename
    image.save(target, format="PNG", optimize=True)
    return {
        "kind": "image",
        "title": title,
        "caption": str((design or {}).get("caption") or ""),
        "decision_question": str((design or {}).get("decision_question") or ""),
        "filename": filename,
        "path": str(target),
        "relative_path": f"visuals/{filename}",
        "media_type": "image/png",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "source_datasets": source_datasets or [],
        "design": dict(design or {}),
    }


def _road_poi_map(roads: list[dict[str, Any]], pois: list[dict[str, Any]], directory: Path) -> dict[str, Any] | None:
    road_paths = [_geometry_points(record.get("geometry")) for record in roads]
    poi_points = [_point(record.get("location")) for record in pois]
    bounds = _bounds([*road_paths, [point for point in poi_points if point]])
    if bounds is None:
        return None
    image, draw = _canvas("路网与 POI 复合图", f"全量路网 {len(roads):,} 条 · 全量 POI {len(pois):,} 个")
    road_colors = {"高速": "#bfdbfe", "快速": "#93c5fd", "主干": "#60a5fa", "次干": "#94a3b8"}
    for record, path in zip(roads, road_paths):
        if len(path) < 2:
            continue
        road_class = str(record.get("road_class") or "")
        color = next((value for key, value in road_colors.items() if key in road_class), "#cbd5e1")
        draw.line([_project(point, bounds) for point in path], fill=color, width=2)
    category_colors = ("#e11d48", "#7c3aed", "#0891b2", "#16a34a", "#ea580c", "#475569")
    category_index: dict[str, int] = {}
    for record, point in zip(pois, poi_points):
        if point is None:
            continue
        category = str(record.get("category") or "其他")
        if category not in category_index:
            category_index[category] = len(category_index)
        color = category_colors[category_index[category] % len(category_colors)]
        x, y = _project(point, bounds)
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
    for index, category in enumerate(list(category_index)[:6]):
        x = _PADDING + index * 220
        draw.ellipse((x, _HEIGHT - 45, x + 13, _HEIGHT - 32), fill=category_colors[category_index[category] % len(category_colors)])
        draw.text((x + 20, _HEIGHT - 48), category[:14], fill="#344054", font=_font(15))
    return _save(image, directory, "road-poi-composite.png", "路网与 POI 复合图")


def _poi_category_chart(pois: list[dict[str, Any]], directory: Path) -> dict[str, Any] | None:
    counts = Counter(str(item.get("category") or "其他") for item in pois)
    rows = counts.most_common(12)
    if not rows:
        return None
    image, draw = _canvas("POI 分类结构", f"全量 POI {len(pois):,} 个，展示数量最多的 12 类")
    baseline, top, left, right = 840, 160, 130, 1520
    max_value = max(value for _, value in rows)
    width = (right - left) / len(rows)
    for index, (label, value) in enumerate(rows):
        bar_height = (baseline - top) * value / max_value
        x0 = left + index * width + 18
        x1 = left + (index + 1) * width - 18
        draw.rectangle((x0, baseline - bar_height, x1, baseline), fill="#2563eb")
        draw.text((x0, baseline - bar_height - 30), f"{value:,}", fill="#172033", font=_font(16))
        draw.text((x0, baseline + 14), label[:10], fill="#344054", font=_font(15))
    draw.line((left, baseline, right, baseline), fill="#98a2b3", width=2)
    return _save(image, directory, "poi-category-structure.png", "POI 分类结构")


def _population_nightlight_grid(
    population: list[dict[str, Any]], nightlight: list[dict[str, Any]], directory: Path
) -> dict[str, Any] | None:
    population_paths = [_geometry_points(record.get("geometry")) for record in population]
    nightlight_paths = [_geometry_points(record.get("geometry")) for record in nightlight]
    bounds = _bounds([*population_paths, *nightlight_paths])
    if bounds is None:
        return None
    image, draw = _canvas("人口与夜光格网", f"人口格网 {len(population):,} 个 · 夜光格网 {len(nightlight):,} 个")
    population_max = max((_number(item.get("population_total")) or 0 for item in population), default=0) or 1
    for record, path in zip(population, population_paths):
        if len(path) < 3:
            continue
        ratio = min(1.0, (_number(record.get("population_total")) or 0) / population_max)
        color = (52, 109, 219, int(45 + 165 * ratio))
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon([_project(point, bounds) for point in path], fill=color)
        image.paste(layer, (0, 0), layer)
    nightlight_max = max((_number(item.get("radiance")) or 0 for item in nightlight), default=0) or 1
    for record, path in zip(nightlight, nightlight_paths):
        if len(path) < 3:
            continue
        ratio = min(1.0, (_number(record.get("radiance")) or 0) / nightlight_max)
        draw.line([_project(point, bounds) for point in [*path, path[0]]], fill=(234, 88, 12, int(70 + 185 * ratio)), width=2)
    draw.rectangle((_PADDING, _HEIGHT - 50, _PADDING + 18, _HEIGHT - 32), fill="#346ddb")
    draw.text((_PADDING + 26, _HEIGHT - 53), "人口填色", fill="#344054", font=_font(15))
    draw.line((_PADDING + 160, _HEIGHT - 40, _PADDING + 178, _HEIGHT - 40), fill="#ea580c", width=3)
    draw.text((_PADDING + 188, _HEIGHT - 53), "夜光边界", fill="#344054", font=_font(15))
    return _save(image, directory, "population-nightlight-grid.png", "人口与夜光格网")


def _markdown_table(pois: list[dict[str, Any]], roads: list[dict[str, Any]], population: list[dict[str, Any]], nightlight: list[dict[str, Any]]) -> str:
    categories = Counter(str(item.get("category") or "其他") for item in pois).most_common(8)
    lines = ["| 数据集 | 全量记录数 | 主要汇总 |", "|---|---:|---|"]
    lines.extend(
        [
            f"| POI | {len(pois):,} | " + "、".join(f"{name} {count:,}" for name, count in categories) + " |",
            f"| 路网边 | {len(roads):,} | 总长度 {sum((_number(item.get('length_m')) or 0 for item in roads)) / 1000:.1f} km |",
            f"| 人口格网 | {len(population):,} | 总人口 {sum((_number(item.get('population_total')) or 0 for item in population)):,.0f} |",
            f"| 夜光格网 | {len(nightlight):,} | 平均辐亮度 {(sum((_number(item.get('radiance')) or 0 for item in nightlight)) / len(nightlight)) if nightlight else 0:.2f} |",
        ]
    )
    return "\n".join(lines)


def _safe_color(value: Any, index: int) -> str:
    candidate = str(value or "").strip()
    return candidate if re.fullmatch(r"#[0-9a-fA-F]{6}", candidate) else _DEFAULT_COLORS[index % len(_DEFAULT_COLORS)]


def _record_point(record: Mapping[str, Any]) -> tuple[float, float] | None:
    return _point(record.get("location")) or next(iter(_geometry_points(record.get("geometry"))), None)


def _role_for_record(record: Mapping[str, Any]) -> str:
    geometry_type = str((record.get("geometry") or {}).get("type") or "")
    if "Line" in geometry_type:
        return "line"
    if "Polygon" in geometry_type:
        return "polygon"
    return "point"


def _source_manifest(data: Mapping[str, list[dict[str, Any]]], dataset_ids: Iterable[str]) -> list[dict[str, Any]]:
    return [
        {"dataset_id": dataset_id, "record_count": len(data[dataset_id]), "complete": True}
        for dataset_id in dict.fromkeys(dataset_ids)
        if dataset_id in data
    ]


def _filename(index: int, visual_format: str, title: str) -> str:
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]
    return f"visual-{index:02d}-{visual_format}-{digest}.png"


def _nightlight_map_style(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        _number(record.get("radiance")) or 0.0
        for record in records
        if record.get("has_data") is not False
    ]
    min_value, max_value = radiance_domain(values)
    aggregated_cells = []
    for index, record in enumerate(records):
        try:
            geometry = shapely_shape(record.get("geometry") or {})
        except (KeyError, TypeError, ValueError, ShapelyError):
            continue
        if geometry.is_empty:
            continue
        centroid = geometry.centroid
        aggregated_cells.append(
            AggregatedNightlightCell(
                cell_id=str(record.get("cell_id") or f"nightlight-{index}"),
                row=0,
                col=index,
                raw_value=_number(record.get("radiance")) or 0.0,
                valid_pixel_count=0 if record.get("has_data") is False else 1,
                centroid_gcj02=[float(centroid.x), float(centroid.y)],
                geometry_gcj02=[],
            )
        )
    hotspot_cells, _, hotspot_analysis = build_hotspot_layer_cells(aggregated_cells, RADIANCE_UNIT)
    gradient_cells, gradient_legend, gradient_analysis = build_gradient_layer_cells(aggregated_cells, RADIANCE_UNIT)
    hotspot_analysis = dict(hotspot_analysis)
    hotspot_analysis.pop("_hotspot_cell_ids", None)
    return {
        "min_value": min_value,
        "max_value": max_value,
        "p75": radiance_percentile(values, 75),
        "p90": radiance_percentile(values, 90),
        "valid_count": len(values),
        "total_count": len(records),
        "hotspot_cells": {str(item["cell_id"]): item for item in hotspot_cells},
        "hotspot_analysis": hotspot_analysis,
        "gradient_cells": {str(item["cell_id"]): item for item in gradient_cells},
        "gradient_legend": gradient_legend,
        "gradient_analysis": gradient_analysis,
    }


def _draw_nightlight_legend(draw: ImageDraw.ImageDraw, style: Mapping[str, Any]) -> None:
    left, top, right, bottom = 1060, 145, 1510, 610
    draw.rounded_rectangle((left, top, right, bottom), radius=7, fill="#ffffff", outline="#d0d5dd", width=1)
    draw.text((left + 24, top + 20), "夜光辐亮度", fill="#172033", font=_font(21, bold=True))
    draw.text(
        (left + 24, top + 52),
        f"有效网格 {int(style['valid_count']):,} / {int(style['total_count']):,}",
        fill="#667085",
        font=_font(14),
    )
    bar_left, bar_top, bar_width, bar_height = left + 24, top + 91, 398, 28
    segments = 100
    for segment in range(segments):
        ratio = segment / max(1, segments - 1)
        value = float(style["min_value"]) + ratio * (float(style["max_value"]) - float(style["min_value"]))
        color = str(
            radiance_style(
                value,
                min_value=float(style["min_value"]),
                max_value=float(style["max_value"]),
            )["fill_color"]
        )
        x0 = bar_left + (bar_width * segment / segments)
        x1 = bar_left + (bar_width * (segment + 1) / segments) + 1
        draw.rectangle((x0, bar_top, x1, bar_top + bar_height), fill=color)
    draw.rectangle((bar_left, bar_top, bar_left + bar_width, bar_top + bar_height), outline="#98a2b3", width=1)
    draw.text((bar_left, bar_top + 36), f"P5 {float(style['min_value']):.1f}", fill="#475467", font=_font(13))
    max_label = f"P98 {float(style['max_value']):.1f} {RADIANCE_UNIT}"
    label_width = draw.textbbox((0, 0), max_label, font=_font(13))[2]
    draw.text((bar_left + bar_width - label_width, bar_top + 36), max_label, fill="#475467", font=_font(13))

    hotspot = style["hotspot_analysis"]
    draw.text((left + 24, top + 188), "热点分级边界", fill="#172033", font=_font(16, bold=True))
    hotspot_rows = [
        ("#fff7bc", "核心", int(hotspot.get("core_hotspot_count") or 0)),
        ("#fde047", "高亮", int(hotspot.get("secondary_hotspot_count") or 0)),
        ("#f59e0b", "次级", int(hotspot.get("emerging_hotspot_count") or 0)),
    ]
    for index, (color, label, count) in enumerate(hotspot_rows):
        x = left + 24 + index * 132
        draw.line((x, top + 230, x + 30, top + 230), fill="#ffffff", width=7)
        draw.line((x, top + 230, x + 30, top + 230), fill=color, width=max(2, 5 - index))
        draw.text((x + 38, top + 220), f"{label} {count}", fill="#344054", font=_font(13))

    draw.text((left + 24, top + 270), "梯度衰减边界", fill="#172033", font=_font(16, bold=True))
    gradient_stops = list((style.get("gradient_legend") or {}).get("stops") or [])
    gradient_labels = ["核心", "内圈", "中圈", "外圈", "边缘"]
    swatch_width = 76
    for index, stop in enumerate(gradient_stops[:5]):
        x = left + 24 + index * swatch_width
        color = str(stop.get("color") or "#94a3b8")
        draw.rectangle((x, top + 307, x + swatch_width - 5, top + 326), fill=color)
        draw.text((x, top + 334), gradient_labels[index], fill="#475467", font=_font(12))
    gradient = style["gradient_analysis"]
    draw.text(
        (left + 24, top + 370),
        f"峰值—边缘比 {float(gradient.get('peak_to_edge_ratio') or 0):.2f} · 最远 {float(gradient.get('max_distance_km') or 0):.2f} km",
        fill="#475467",
        font=_font(13),
    )
    draw.line((left + 24, top + 413, left + 64, top + 413), fill="#465362", width=2)
    draw.text((left + 78, top + 403), "路网骨架", fill="#344054", font=_font(14))
    draw.text((left + 24, bottom - 34), "亮度为活动背景代理，不等同客流或营收", fill="#667085", font=_font(13))


def _boundary_rings(
    records: list[dict[str, Any]],
    classified_cells: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[list[tuple[float, float]]]]:
    grouped: dict[str, list[Any]] = {}
    for index, record in enumerate(records):
        cell_id = str(record.get("cell_id") or f"nightlight-{index}")
        class_key = str((classified_cells.get(cell_id) or {}).get("class_key") or "")
        if not class_key:
            continue
        try:
            geometry = shapely_shape(record.get("geometry") or {})
        except (KeyError, TypeError, ValueError, ShapelyError):
            continue
        if not geometry.is_empty:
            grouped.setdefault(class_key, []).append(geometry)

    boundaries: dict[str, list[list[tuple[float, float]]]] = {}
    for class_key, geometries in grouped.items():
        merged = unary_union(geometries)
        polygons = [merged] if merged.geom_type == "Polygon" else list(getattr(merged, "geoms", []))
        boundaries[class_key] = [
            [(float(x), float(y)) for x, y in polygon.exterior.coords]
            for polygon in polygons
            if polygon.geom_type == "Polygon" and not polygon.is_empty
        ]
    return boundaries


def _draw_nightlight_boundaries(
    draw: ImageDraw.ImageDraw,
    records: list[dict[str, Any]],
    style: Mapping[str, Any],
    project: Any,
) -> None:
    gradient_styles = {
        "core_peak": ("#fff7bc", 4),
        "inner_spread": ("#fde047", 3),
        "middle_decay": ("#f59e0b", 3),
        "outer_decay": ("#c2410c", 2),
        "fringe_dark": ("#475569", 2),
    }
    hotspot_styles = {
        "core_hotspot": ("#fff7bc", 6),
        "secondary_hotspot": ("#fde047", 5),
        "emerging_hotspot": ("#f59e0b", 4),
    }
    gradient_rings = _boundary_rings(records, style["gradient_cells"])
    hotspot_rings = _boundary_rings(records, style["hotspot_cells"])
    for class_key, (color, width) in gradient_styles.items():
        for ring in gradient_rings.get(class_key, []):
            points = [project(point) for point in ring]
            draw.line(points, fill="#ffffff", width=width + 2, joint="curve")
            draw.line(points, fill=color, width=width, joint="curve")
    for class_key, (color, width) in hotspot_styles.items():
        for ring in hotspot_rings.get(class_key, []):
            points = [project(point) for point in ring]
            draw.line(points, fill="#ffffff", width=width + 4, joint="curve")
            draw.line(points, fill=color, width=width, joint="curve")


def _wrap_text(value: Any, width: int = 24) -> list[str]:
    text = str(value or "").strip()
    lines = [text[index : index + width] for index in range(0, len(text), width)] or [""]
    leading_punctuation = "，。；：！？、）】》”’"
    for index in range(1, len(lines)):
        while lines[index] and lines[index][0] in leading_punctuation:
            lines[index - 1] += lines[index][0]
            lines[index] = lines[index][1:]
    return [line for line in lines if line] or [""]


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    *,
    title: str,
    lines: list[tuple[str, str]],
    note: str,
    top: int = 135,
    bottom: int = 875,
) -> None:
    left, right = 1050, 1510
    draw.rounded_rectangle((left, top, right, bottom), radius=7, fill="#ffffff", outline="#d0d5dd", width=1)
    draw.text((left + 25, top + 22), title, fill="#172033", font=_font(22, bold=True))
    note_lines = _wrap_text(note, 29)
    note_y = bottom - 30 - len(note_lines) * 19
    blocks = [(label, _wrap_text(value, 26)) for label, value in lines]
    block_heights = [43 + len(value_lines) * 21 for _, value_lines in blocks]
    available_height = max(0, note_y - 25 - (top + 70) - sum(block_heights))
    gap = available_height / max(1, len(blocks) - 1)
    y = float(top + 70)
    for label, value_lines in blocks:
        draw.text((left + 25, y), label, fill="#667085", font=_font(13))
        for value_line in value_lines:
            draw.text((left + 25, y + 22), value_line, fill="#172033", font=_font(16, bold=True))
            y += 21
        y += 43 + gap
    draw.line((left + 25, note_y - 14, right - 25, note_y - 14), fill="#e4e7ec", width=1)
    for line in note_lines:
        draw.text((left + 25, note_y), line, fill="#667085", font=_font(13))
        note_y += 19


def _draw_context_panel(
    draw: ImageDraw.ImageDraw,
    *,
    road_count: int,
    poi_count: int,
    poi_counts: Counter[str],
    named: list[dict[str, Any]],
) -> None:
    left, right = 1035, 1600
    draw.rectangle((left, 70, right, 1000), fill="#f1efe9")
    draw.text((1080, 118), "区域证据摘要", fill="#172033", font=_font(24, bold=True))
    draw.text((1080, 153), "完整记录 · 不是客流热力图", fill="#667085", font=_font(14))

    draw.text((1080, 212), f"{road_count:,}", fill="#1f4e5f", font=_font(39, bold=True))
    draw.text((1080, 258), "路网边", fill="#667085", font=_font(13))
    draw.text((1315, 212), f"{poi_count:,}", fill="#b54d2e", font=_font(39, bold=True))
    draw.text((1315, 258), "2024 POI", fill="#667085", font=_font(13))
    draw.line((1080, 294, 1545, 294), fill="#d0cdc5", width=1)

    draw.text((1080, 322), "主要供给结构", fill="#344054", font=_font(15, bold=True))
    top_rows = poi_counts.most_common(4)
    maximum = max((count for _, count in top_rows), default=1)
    for index, (label, count) in enumerate(top_rows):
        y = 360 + index * 52
        draw.text((1080, y), label.replace("服务", "")[:10], fill="#475467", font=_font(13))
        bar_width = 245 * count / maximum
        color = _mix_color(_POI_COLORS.get(label, _POI_COLORS["其他"]), "#ffffff", 0.18)
        draw.rounded_rectangle((1235, y + 2, 1235 + bar_width, y + 17), radius=3, fill=color)
        draw.text((1490, y - 1), f"{count:,}", fill="#475467", font=_font(12))

    draw.text((1080, 578), "重点核验节点", fill="#344054", font=_font(15, bold=True))
    for index, record in enumerate(named[:5], start=1):
        y = 615 + (index - 1) * 50
        draw.ellipse((1080, y, 1102, y + 22), fill="#ffffff", outline="#c44b2f", width=2)
        draw.text((1087, y + 2), str(index), fill="#c44b2f", font=_font(12, bold=True))
        draw.text((1118, y - 2), str(record.get("name") or "")[:18], fill="#172033", font=_font(14, bold=True))
        draw.text((1118, y + 21), str(record.get("category") or "")[:18], fill="#667085", font=_font(11))

    decision_top = 868
    draw.rectangle((1080, decision_top, 1085, 944), fill="#c44b2f")
    draw.text((1102, decision_top), "决策含义", fill="#667085", font=_font(12))
    decision = "以连接、识别和公共文化协作为重点，不复制普通商业供给。"
    for line_index, line in enumerate(_wrap_text(decision, 24)):
        draw.text((1102, decision_top + 22 + line_index * 20), line, fill="#172033", font=_font(14, bold=True))
    draw.text((1080, 968), "道路结构与 POI 供给均不等同实测客流。", fill="#667085", font=_font(11))


def _road_style(record: Mapping[str, Any]) -> tuple[str, int]:
    road_class = str(record.get("road_class") or "")
    if "高速" in road_class or "快速" in road_class:
        return "#344054", 3
    if "主干" in road_class:
        return "#475467", 3
    if "次干" in road_class:
        return "#667085", 2
    return "#98a2b3", 1


def _poi_category_palette(records: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    categories = sorted({str(record.get("category") or "其他") for record in records})
    palette: dict[str, str] = {}
    fallback_index = 0
    for category in categories:
        if category in _POI_COLORS:
            palette[category] = _POI_COLORS[category]
            continue
        palette[category] = _DEFAULT_COLORS[fallback_index % len(_DEFAULT_COLORS)]
        fallback_index += 1
    return palette


def _poi_color(record: Mapping[str, Any], palette: Mapping[str, str] | None = None) -> str:
    category = str(record.get("category") or "其他")
    return (palette or _POI_COLORS).get(category, _POI_COLORS["其他"])


def _named_pois(
    pois: list[dict[str, Any]],
    bounds: tuple[float, float, float, float],
    *,
    limit: int = 7,
) -> list[dict[str, Any]]:
    center_x = (bounds[0] + bounds[2]) / 2.0
    center_y = (bounds[1] + bounds[3]) / 2.0
    longitude_scale = max(0.01, math.cos(math.radians(center_y)))
    preferred = {"科教文化服务", "风景名胜", "医疗保健服务", "政府机构及社会团体", "交通设施服务"}
    strategic_terms = ("文化馆", "博物馆", "文物", "考古", "古开福寺", "开福寺文化", "文化长廊", "文化服务中心", "综合文化")
    public_terms = ("公园", "广场", "社区", "公共服务中心", "医院", "地铁站", "公交站", "研究所", "图书馆")
    excluded_terms = (
        "停车", "车场", "出入口", "入口", "出口", "充电", "卫生间", "酒店", "植发", "医美", "美容",
        "口腔", "自习室", "钢琴", "培训", "早教", "餐厅", "饭", "咖啡", "火锅", "寿司",
    )
    ranked = []
    for record in pois:
        point = _record_point(record)
        name = str(record.get("name") or "").strip()
        category = str(record.get("category") or "")
        if point is None or not name or category not in preferred or any(term in name for term in excluded_terms):
            continue
        distance = ((point[0] - center_x) * longitude_scale) ** 2 + (point[1] - center_y) ** 2
        priority = 0 if any(term in name for term in strategic_terms) else (1 if any(term in name for term in public_terms) else 2)
        ranked.append((priority, distance, name, record))
    seen = set()
    selected = []
    selected_points: list[tuple[float, float]] = []
    minimum_separation = 0.00055
    for _, _, name, record in sorted(ranked, key=lambda item: (item[0], item[1], item[2])):
        if name in seen:
            continue
        point = _record_point(record)
        if point is None:
            continue
        if any(
            ((point[0] - other[0]) * longitude_scale) ** 2 + (point[1] - other[1]) ** 2
            < minimum_separation**2
            for other in selected_points
        ):
            continue
        seen.add(name)
        selected.append(record)
        selected_points.append(point)
        if len(selected) >= limit:
            break
    return selected


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * max(0.0, min(100.0, percentile)) / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * ratio


def _mix_color(left: str, right: str, ratio: float) -> str:
    left_rgb = ImageColor.getrgb(left)
    right_rgb = ImageColor.getrgb(right)
    bounded = max(0.0, min(1.0, ratio))
    color = tuple(round(a + (b - a) * bounded) for a, b in zip(left_rgb, right_rgb))
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _evidence_map_asset(
    spec: Mapping[str, Any],
    data: Mapping[str, list[dict[str, Any]]],
    directory: Path,
    index: int,
) -> dict[str, Any] | None:
    variant = str(spec.get("map_variant") or "")
    layers = list(spec["layers"])
    groups = []
    for layer in layers:
        for record in data[layer["dataset_id"]]:
            points = _geometry_points(record.get("geometry"))
            point = _record_point(record)
            groups.append(points or ([point] if point else []))
    bounds = _bounds(groups)
    if bounds is None:
        return None

    roads = data.get("road_edges", [])
    pois = data.get("poi", [])
    poi_palette = _poi_category_palette(pois)
    population = data.get("population", [])
    total = sum(len(data[layer["dataset_id"]]) for layer in layers)
    image, draw = _canvas(str(spec["title"]), f"基于完整项目记录 · 共 {total:,} 条 · WGS84 局部等距投影")
    right_padding = 590
    project = lambda point: _project(point, bounds, right_padding=right_padding)

    population_values = [
        _number(record.get("population_total")) or 0.0
        for record in population
        if (_number(record.get("population_total")) or 0.0) > 0
    ]
    population_low = _percentile(population_values, 5)
    population_high = _percentile(population_values, 95)
    population_span = max(population_high - population_low, 1e-9)
    if variant == "regional_role":
        for record in population:
            path = _geometry_points(record.get("geometry"))
            if len(path) < 3:
                continue
            value = _number(record.get("population_total")) or 0.0
            ratio = max(0.0, min(1.0, (value - population_low) / population_span))
            color = _mix_color("#edf4f7", "#277da1", ratio)
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).polygon(
                [project(point) for point in path],
                fill=(*ImageColor.getrgb(color), 188),
                outline=(*ImageColor.getrgb("#ffffff"), 150),
            )
            image.paste(overlay, (0, 0), overlay)

    for record in roads:
        path = _geometry_points(record.get("geometry"))
        if len(path) < 2:
            continue
        color, width = _road_style(record)
        draw.line([project(point) for point in path], fill=color, width=width)

    emphasized = {"科教文化服务", "风景名胜", "交通设施服务", "政府机构及社会团体"}
    for record in pois:
        point = _record_point(record)
        if point is None:
            continue
        category = str(record.get("category") or "")
        if variant == "regional_role" and category not in emphasized:
            continue
        x, y = project(point)
        radius = 3 if category in emphasized else 2
        color = _poi_color(record, poi_palette)
        if variant == "context_full":
            radius = 2 if category in emphasized else 1
            color = _mix_color(color, "#ffffff", 0.25)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="#ffffff" if radius == 3 else color)

    named = _named_pois(pois, bounds)
    poi_counts = Counter(str(record.get("category") or "其他") for record in pois)
    if variant == "context_full":
        for node_index, record in enumerate(named[:5], start=1):
            point = _record_point(record)
            if point is None:
                continue
            x, y = project(point)
            draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill="#ffffff", outline="#c44b2f", width=3)
            draw.text((x - 4, y - 8), str(node_index), fill="#c44b2f", font=_font(13, bold=True))
    if variant in {"poi_access", "context_full"}:
        lines = [
            ("道路与设施", f"路网 {len(roads):,} 条 · POI {len(pois):,} 个"),
            ("主要供给", " · ".join(f"{name.replace('服务', '')} {count}" for name, count in poi_counts.most_common(3))),
            ("近中心具名节点", " / ".join(str(item.get("name") or "")[:12] for item in named[:4])),
            ("决策含义", "完整路网用于判断连接关系；项目应改善连接与识别，而非复制普通商业。"),
        ]
        note = "使用完整项目记录；节点为真实POI，道路结构不等同实测客流，入口与步行连续性仍需现场核验。"
    else:
        population_total = sum(_number(record.get("population_total")) or 0.0 for record in population)
        cultural_count = poi_counts.get("科教文化服务", 0) + poi_counts.get("风景名胜", 0)
        lines = [
            ("人口底盘", f"常住人口代理 {population_total:,.0f} · 格网 {len(population):,}"),
            ("文化与公共节点", f"科教文化/风景名胜 {cultural_count:,} 个"),
            ("近中心具名节点", " / ".join(str(item.get("name") or "")[:12] for item in named[:4])),
            ("决策含义", "区域角色应以社区高频使用为底盘，以文化节点协作为增量。"),
        ]
        note = "人口是常住人口代理，POI是设施供给；二者均不能直接换算项目到访率或收入。"
    if variant == "context_full":
        _draw_context_panel(
            draw,
            road_count=len(roads),
            poi_count=len(pois),
            poi_counts=poi_counts,
            named=named,
        )
    else:
        _draw_panel(draw, title="证据读法", lines=lines, note=note)

    legend_y = 925
    legend_items = [
        ("#475467", "主次路网"),
        (_POI_COLORS["科教文化服务"], "科教文化"),
        (_POI_COLORS["风景名胜"], "风景名胜"),
        (_POI_COLORS["交通设施服务"], "交通节点"),
    ]
    if variant == "regional_role":
        legend_items.insert(0, ("#277da1", "人口高值格网"))
    for legend_index, (color, label) in enumerate(legend_items):
        x = _PADDING + legend_index * 170
        draw.rectangle((x, legend_y, x + 16, legend_y + 16), fill=color)
        draw.text((x + 23, legend_y - 3), label, fill="#344054", font=_font(14))

    if variant == "context_full":
        image = image.resize((2400, 1500), Image.Resampling.LANCZOS)
    saved_design = dict(spec)
    saved_design["legend_labels"] = [label for _, label in legend_items]
    if variant == "context_full":
        saved_design["data_scope"] = "full_project_records"
        saved_design["output_size_px"] = {"width": 2400, "height": 1500}
    saved_design["projection"] = _projection_metadata(bounds, right_padding=right_padding)
    saved_design["named_pois"] = [
        {"name": item.get("name"), "category": item.get("category")}
        for item in named
    ]
    if pois:
        displayed_categories = [category for category, _ in poi_counts.most_common(4)]
        saved_design["poi_style"] = {
            "palette": "facility_category_v1",
            "category_colors": {
                category: poi_palette[category] for category in displayed_categories
            },
            "available_category_count": len(poi_palette),
            "named_label_count": len(named),
        }
    if variant == "regional_role":
        saved_design["population_style"] = {
            "field": "population_total",
            "domain": "positive_p5_p95",
            "palette": "population_blue_v1",
            "min_value": population_low,
            "max_value": population_high,
            "unit": "person",
        }
    return _save(
        image,
        directory,
        _filename(index, "map", str(spec["title"])),
        str(spec["title"]),
        source_datasets=_source_manifest(data, (layer["dataset_id"] for layer in layers)),
        design=saved_design,
    )


def _validate_rendered_assets(plan: list[dict[str, Any]], assets: list[dict[str, Any]]) -> None:
    if len(assets) != len(plan):
        raise ValueError("visual_render_incomplete")
    for asset in assets:
        design = dict(asset.get("design") or {})
        if len(str(design.get("caption") or "").strip()) < 12:
            raise ValueError("visual_render_missing_caption")
        if asset.get("kind") != "image" or design.get("format") != "map":
            continue
        projection = dict(design.get("projection") or {})
        occupancy = _number(projection.get("content_occupancy_ratio"))
        if occupancy is not None and occupancy < 0.25:
            raise ValueError("visual_render_excessive_empty_space")
        legend_labels = [str(label).strip() for label in design.get("legend_labels") or [] if str(label).strip()]
        if not legend_labels and not design.get("nightlight_style"):
            raise ValueError("visual_render_missing_legend")
        if any(label in DATASET_SOURCES for label in legend_labels):
            raise ValueError("visual_render_exposes_internal_dataset_label")
        layer_ids = {
            str(layer.get("dataset_id") or "")
            for layer in design.get("layers") or []
            if isinstance(layer, Mapping)
        }
        if "poi" in layer_ids:
            poi_style = dict(design.get("poi_style") or {})
            category_colors = dict(poi_style.get("category_colors") or {})
            available_category_count = int(_number(poi_style.get("available_category_count")) or 0)
            required_distinct_colors = min(2, available_category_count)
            if (
                poi_style.get("palette") != "facility_category_v1"
                or required_distinct_colors < 1
                or len(set(category_colors.values())) < required_distinct_colors
            ):
                raise ValueError("visual_render_missing_poi_category_palette")
        if "population" in layer_ids:
            population_style = dict(design.get("population_style") or {})
            if (
                population_style.get("domain") != "positive_p5_p95"
                or population_style.get("palette") != "population_blue_v1"
                or _number(population_style.get("min_value")) is None
                or _number(population_style.get("max_value")) is None
            ):
                raise ValueError("visual_render_missing_population_color_scale")
        if "nightlight" in layer_ids:
            nightlight_style = dict(design.get("nightlight_style") or {})
            if (
                nightlight_style.get("palette") != "platform_radiance_v1"
                or nightlight_style.get("domain") != "positive_p5_p98"
                or nightlight_style.get("boundary_modes") != ["hotspot", "gradient"]
            ):
                raise ValueError("visual_render_missing_nightlight_color_scale")


def _plan_defaults(data: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    if data.get("road_edges") and data.get("poi"):
        plans.append({
            "format": "map", "map_variant": "context_full", "title": "区域道路与设施关系",
            "rationale": "识别项目与区域道路、公共文化和交通节点的关系",
            "decision_question": "项目应承担什么区域角色并改善哪些连接",
            "caption": "道路与具名设施共同说明项目应补充文化连接和识别，而不是复制普通商业。",
            "layers": [{"dataset_id": "road_edges", "role": "line"}, {"dataset_id": "poi", "role": "point"}],
        })
    if data.get("poi"):
        plans.append({
            "format": "chart", "chart_variant": "poi_supply", "title": "周边设施供给结构",
            "rationale": "比较常规消费与文化公共设施的供给结构",
            "decision_question": "项目应补哪类供给而不是重复已有商业",
            "caption": "POI 分类数量用于识别供给结构，支持文化公共服务补位而非普通商业扩张。",
            "dataset_id": "poi",
        })
    if data.get("population"):
        plans.append({
            "format": "chart", "chart_variant": "population_profile", "title": "重点年龄人口结构",
            "rationale": "比较研学、家庭和社区日常使用的人口基础",
            "decision_question": "首期公共产品应优先服务哪些日常客群",
            "caption": "重点年龄段人口支持多时段公共使用测试，但不能直接换算项目客流。",
            "dataset_id": "population",
        })
    if data.get("nightlight") and len(plans) < 5:
        layers = [{"dataset_id": "nightlight", "role": "polygon", "metric_field": "radiance"}]
        if data.get("road_edges"):
            layers.insert(0, {"dataset_id": "road_edges", "role": "line"})
        plans.append({
            "format": "map", "title": "夜间活动背景与道路骨架",
            "rationale": "识别夜光热点、衰减边界和道路关系",
            "decision_question": "项目是否具备延时开放条件以及夜间产品边界",
            "caption": "夜光只能支持适度延时开放的背景判断，不能证明夜间消费或营业收入。",
            "layers": layers,
        })
    if data.get("road_edges") and len(plans) < 3:
        plans.append({
            "format": "map", "title": "道路层级与连接骨架",
            "rationale": "识别主要道路层级与内部连接关系",
            "decision_question": "步行接驳和入口识别应优先改善哪些连接",
            "caption": "道路层级用于判断连接骨架，不等同实测客流或正式入口条件。",
            "layers": [{"dataset_id": "road_edges", "role": "line"}],
        })
    return plans[:5]


def _validate_plan_quality(plan: list[dict[str, Any]], data: Mapping[str, list[dict[str, Any]]]) -> None:
    if not 3 <= len(plan) <= 5:
        raise ValueError("visual_plan_requires_three_to_five_items")
    titles: set[str] = set()
    signatures: set[tuple[Any, ...]] = set()
    chart_count = 0
    population_map_count = 0
    specialized_context_count = 0
    for item in plan:
        title = str(item.get("title") or "").strip()
        rationale = str(item.get("rationale") or "").strip()
        decision_question = str(item.get("decision_question") or "").strip()
        caption = str(item.get("caption") or "").strip()
        if len(title) < 4 or len(rationale) < 8 or len(decision_question) < 8 or len(caption) < 12:
            raise ValueError("visual_plan_lacks_decision_context")
        if title in titles:
            raise ValueError("visual_plan_duplicate_title")
        titles.add(title)
        layer_ids = tuple(sorted(str(layer.get("dataset_id") or "") for layer in item.get("layers") or []))
        if "road_nodes" in layer_ids:
            raise ValueError("visual_plan_must_not_render_all_road_nodes")
        signature = (
            item.get("format"), item.get("map_variant"), item.get("chart_variant"), item.get("dataset_id"),
            layer_ids, item.get("group_by"), item.get("metric_field"),
        )
        if signature in signatures:
            raise ValueError("visual_plan_duplicate_evidence_view")
        signatures.add(signature)
        if item["format"] == "chart":
            chart_count += 1
        if item["format"] == "map":
            has_poi = "poi" in layer_ids
            has_roads = "road_edges" in layer_ids
            if has_poi and not has_roads:
                raise ValueError("visual_plan_poi_map_requires_road_context")
            if has_poi and not item.get("map_variant"):
                raise ValueError("visual_plan_poi_map_requires_variant")
            if "population" in layer_ids:
                population_map_count += 1
            if item.get("map_variant") in {"poi_access", "context_full", "regional_role"}:
                specialized_context_count += 1
    if population_map_count > 1:
        raise ValueError("visual_plan_duplicate_population_maps")
    if (data.get("poi") or data.get("population")) and chart_count < 1:
        raise ValueError("visual_plan_requires_explanatory_chart")
    if data.get("poi") and data.get("road_edges") and specialized_context_count < 1:
        raise ValueError("visual_plan_requires_specialized_context_map")


def _normalize_plan(
    visual_plan: Iterable[Mapping[str, Any]] | None, data: Mapping[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    supplied = list(visual_plan or ())
    source_plan = supplied or _plan_defaults(data)
    for raw in source_plan:
        if not isinstance(raw, Mapping):
            raise ValueError("visual_plan_item_must_be_object")
        visual_format = str(raw.get("format") or "").strip().lower()
        if visual_format not in {"map", "chart", "table"}:
            raise ValueError(f"visual_format_invalid:{visual_format or 'empty'}")
        title = str(raw.get("title") or "").strip() or f"项目数据{visual_format}"
        dataset_id = str(raw.get("dataset_id") or "").strip()
        if dataset_id and dataset_id not in data:
            raise ValueError(f"visual_dataset_not_available:{dataset_id}")
        if visual_format == "chart" and not dataset_id:
            raise ValueError("visual_chart_requires_dataset")
        layers = []
        for index, layer in enumerate(raw.get("layers") or []):
            if not isinstance(layer, Mapping):
                raise ValueError("visual_layer_must_be_object")
            layer_dataset_id = str(layer.get("dataset_id") or "").strip()
            if layer_dataset_id not in data:
                raise ValueError(f"visual_layer_dataset_not_available:{layer_dataset_id}")
            role = str(layer.get("role") or "").strip().lower()
            if role not in {"line", "point", "polygon"}:
                raise ValueError(f"visual_layer_role_invalid:{role or 'empty'}")
            expected_role = {
                "Point": "point",
                "LineString": "line",
                "Polygon": "polygon",
            }.get(str(DATASET_SCHEMAS[layer_dataset_id].get("geometry_type") or ""))
            if expected_role and role != expected_role:
                raise ValueError(f"visual_layer_role_mismatch:{layer_dataset_id}:{role}")
            layer_metric_field = str(layer.get("metric_field") or "").strip()
            if layer_metric_field and layer_metric_field not in DATASET_SCHEMAS[layer_dataset_id]["fields"]:
                raise ValueError(f"visual_metric_field_invalid:{layer_dataset_id}:{layer_metric_field}")
            layers.append(
                {
                    "dataset_id": layer_dataset_id,
                    "role": role,
                    "color": _safe_color(layer.get("color"), index),
                    "metric_field": layer_metric_field,
                }
            )
        if visual_format == "map" and not layers:
            raise ValueError("visual_map_requires_layers")
        metric_op = str(raw.get("metric_op") or "count").strip().lower()
        if metric_op not in {"count", "sum", "avg"}:
            raise ValueError(f"visual_metric_operation_invalid:{metric_op}")
        group_by = str(raw.get("group_by") or "").strip()
        metric_field = str(raw.get("metric_field") or "").strip()
        if dataset_id:
            allowed_fields = set(DATASET_SCHEMAS[dataset_id]["fields"])
            if group_by and group_by not in allowed_fields:
                raise ValueError(f"visual_group_by_invalid:{dataset_id}:{group_by}")
            if metric_field and metric_field not in allowed_fields:
                raise ValueError(f"visual_metric_field_invalid:{dataset_id}:{metric_field}")
        if metric_op in {"sum", "avg"} and not metric_field:
            raise ValueError(f"visual_metric_field_required:{metric_op}")
        map_variant = str(raw.get("map_variant") or "").strip()
        chart_variant = str(raw.get("chart_variant") or "").strip()
        if map_variant not in {"", "poi_access", "context_full", "regional_role"}:
            raise ValueError(f"visual_map_variant_invalid:{map_variant}")
        if chart_variant not in {"", "poi_supply", "population_profile"}:
            raise ValueError(f"visual_chart_variant_invalid:{chart_variant}")
        normalized.append(
            {
                "format": visual_format,
                "title": title,
                "rationale": str(raw.get("rationale") or "").strip(),
                "decision_question": str(raw.get("decision_question") or "").strip(),
                "caption": str(raw.get("caption") or "").strip(),
                "map_variant": map_variant,
                "chart_variant": chart_variant,
                "dataset_id": dataset_id,
                "layers": layers,
                "group_by": group_by,
                "metric_op": metric_op,
                "metric_field": metric_field,
            }
        )
    _validate_plan_quality(normalized, data)
    return normalized


def _drop_empty_visual_placeholders(
    visual_plan: Iterable[Mapping[str, Any]] | None,
) -> tuple[list[Mapping[str, Any]], int]:
    """Ignore model-generated empty slots while retaining actionable validation errors."""
    supplied = list(visual_plan or ())
    filtered: list[Mapping[str, Any]] = []
    dropped = 0
    for item in supplied:
        if (
            isinstance(item, Mapping)
            and not str(item.get("format") or "").strip()
            and not str(item.get("title") or "").strip()
            and not str(item.get("decision_question") or "").strip()
            and not str(item.get("caption") or "").strip()
        ):
            dropped += 1
            continue
        filtered.append(item)
    return filtered, dropped


def _map_asset(
    spec: Mapping[str, Any], data: Mapping[str, list[dict[str, Any]]], directory: Path, index: int
) -> dict[str, Any] | None:
    if str(spec.get("map_variant") or "") in {"poi_access", "context_full", "regional_role"}:
        return _evidence_map_asset(spec, data, directory, index)
    layers = list(spec["layers"])
    groups = []
    for layer in layers:
        for record in data[layer["dataset_id"]]:
            points = _geometry_points(record.get("geometry"))
            point = _record_point(record)
            groups.append(points or ([point] if point else []))
    bounds = _bounds(groups)
    if bounds is None:
        return None
    total = sum(len(data[layer["dataset_id"]]) for layer in layers)
    nightlight_layer = next(
        (
            layer
            for layer in layers
            if layer["dataset_id"] == "nightlight" and layer["role"] == "polygon" and layer["metric_field"] == "radiance"
        ),
        None,
    )
    nightlight_style = _nightlight_map_style(data["nightlight"]) if nightlight_layer else None
    subtitle = f"基于全量数据渲染 · 共 {total:,} 条记录"
    if nightlight_style:
        subtitle = (
            f"夜光网格 {int(nightlight_style['total_count']):,} · "
            f"P5-P98 稳健色阶 · 热点分级/梯度衰减边界 · 叠加路网"
        )
    canvas_width, canvas_height = _map_canvas_size(bounds, has_side_panel=bool(nightlight_style))
    image, draw = _canvas(
        str(spec["title"]), subtitle, width=canvas_width, height=canvas_height
    )
    if nightlight_style:
        draw.rectangle((0, 82, canvas_width, canvas_height), fill="#111827")
    right_padding = 590 if nightlight_style else _PADDING
    project = lambda point: _project(
        point,
        bounds,
        right_padding=right_padding,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )
    legend_labels: list[str] = []
    population_domains: dict[str, tuple[float, float]] = {}
    poi_palette = _poi_category_palette(data.get("poi", []))
    for layer in layers:
        dataset_id = layer["dataset_id"]
        records = data[dataset_id]
        role = layer["role"]
        color = layer["color"]
        metric_field = layer["metric_field"]
        effective_metric = metric_field or ("population_total" if dataset_id == "population" else "")
        metric_values = [
            value
            for value in (_number(item.get(effective_metric)) for item in records)
            if value is not None and value >= 0
        ]
        metric_low = _percentile(metric_values, 5)
        metric_high = _percentile(metric_values, 95)
        metric_span = max(metric_high - metric_low, 1e-9)
        if dataset_id == "population":
            population_domains[effective_metric] = (metric_low, metric_high)
        for record in records:
            points = _geometry_points(record.get("geometry"))
            if role == "line" and len(points) >= 2:
                if dataset_id == "road_edges":
                    line_color, line_width = _road_style(record)
                else:
                    line_color, line_width = color, 2
                if nightlight_style and dataset_id == "road_edges":
                    line_color, line_width = "#cbd5e1", 1
                draw.line([project(point) for point in points], fill=line_color, width=line_width)
            elif role == "polygon" and len(points) >= 3:
                polygon_color = color
                alpha = 105
                outline_color = "#ffffff"
                outline_width = 1
                if dataset_id == "nightlight" and metric_field == "radiance" and nightlight_style:
                    value = _number(record.get("radiance")) or 0.0
                    style = radiance_style(
                        value,
                        min_value=float(nightlight_style["min_value"]),
                        max_value=float(nightlight_style["max_value"]),
                        has_data=record.get("has_data") is not False,
                    )
                    polygon_color = str(style["fill_color"])
                    alpha = int(255 * min(0.82, max(0.44, float(style["fill_opacity"]) + 0.16)))
                    outline_color = str(style["stroke_color"])
                elif dataset_id == "population":
                    value = _number(record.get(effective_metric)) or 0.0
                    ratio = max(0.0, min(1.0, (value - metric_low) / metric_span))
                    polygon_color = _mix_color("#edf4f7", "#277da1", ratio)
                    alpha = 220
                elif effective_metric:
                    value = _number(record.get(effective_metric)) or 0.0
                    ratio = max(0.0, min(1.0, (value - metric_low) / metric_span))
                    alpha = int(70 + 155 * ratio)
                overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                projected = [project(point) for point in points]
                overlay_draw.polygon(projected, fill=(*ImageColor.getrgb(polygon_color), alpha))
                if outline_color:
                    overlay_draw.line([*projected, projected[0]], fill=(*ImageColor.getrgb(outline_color), 235), width=outline_width)
                image.paste(overlay, (0, 0), overlay)
            else:
                point = _record_point(record)
                if point is not None:
                    x, y = project(point)
                    point_color = _poi_color(record, poi_palette) if dataset_id == "poi" else color
                    radius = 2 if dataset_id == "poi" else 3
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=point_color)
    if not nightlight_style:
        legend_x = _PADDING
        legend_y = canvas_height - 54
        layer_ids = [layer["dataset_id"] for layer in layers]
        if "population" in layer_ids:
            metric = next(
                (layer["metric_field"] or "population_total" for layer in layers if layer["dataset_id"] == "population"),
                "population_total",
            )
            low, high = population_domains.get(metric, (0.0, 0.0))
            for step in range(5):
                draw.rectangle(
                    (legend_x + step * 34, legend_y, legend_x + (step + 1) * 34, legend_y + 16),
                    fill=_mix_color("#edf4f7", "#277da1", step / 4),
                )
            population_label = f"常住人口 {low:,.0f}–{high:,.0f} 人/格"
            draw.text((legend_x + 182, legend_y - 3), population_label, fill="#344054", font=_font(14))
            legend_labels.append(population_label)
            legend_x += 455
        if "road_edges" in layer_ids:
            draw.line((legend_x, legend_y + 8, legend_x + 34, legend_y + 8), fill="#475467", width=3)
            draw.text((legend_x + 44, legend_y - 3), "道路层级", fill="#344054", font=_font(14))
            legend_labels.append("道路层级")
            legend_x += 155
        if "poi" in layer_ids:
            poi_counts = Counter(str(item.get("category") or "其他") for item in data.get("poi", []))
            for category, _ in poi_counts.most_common(4):
                draw.rectangle((legend_x, legend_y, legend_x + 16, legend_y + 16), fill=poi_palette[category])
                label = category.replace("服务", "")
                draw.text((legend_x + 23, legend_y - 3), label, fill="#344054", font=_font(14))
                legend_labels.append(label)
                legend_x += 145
        if not legend_labels:
            for layer in layers:
                label = _DATASET_LABELS.get(layer["dataset_id"], layer["dataset_id"])
                draw.rectangle((legend_x, legend_y, legend_x + 16, legend_y + 16), fill=layer["color"])
                draw.text((legend_x + 23, legend_y - 3), label, fill="#344054", font=_font(14))
                legend_labels.append(label)
                legend_x += 180
    if nightlight_style:
        _draw_nightlight_boundaries(draw, data["nightlight"], nightlight_style, project)
        _draw_nightlight_legend(draw, nightlight_style)
    saved_design = dict(spec)
    saved_design["projection"] = _projection_metadata(
        bounds,
        right_padding=right_padding,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )
    saved_design["legend_labels"] = legend_labels
    source_layer_ids = {str(layer["dataset_id"]) for layer in layers}
    if "poi" in source_layer_ids:
        poi_counts = Counter(str(item.get("category") or "其他") for item in data.get("poi", []))
        displayed_categories = [category for category, _ in poi_counts.most_common(4)]
        saved_design["poi_style"] = {
            "palette": "facility_category_v1",
            "category_colors": {
                category: poi_palette[category] for category in displayed_categories
            },
            "available_category_count": len(poi_palette),
            "named_label_count": 0,
        }
    if "population" in source_layer_ids:
        population_metric = next(
            (
                layer["metric_field"] or "population_total"
                for layer in layers
                if layer["dataset_id"] == "population"
            ),
            "population_total",
        )
        population_low, population_high = population_domains.get(population_metric, (0.0, 0.0))
        saved_design["population_style"] = {
            "field": population_metric,
            "domain": "positive_p5_p95",
            "palette": "population_blue_v1",
            "min_value": population_low,
            "max_value": population_high,
            "unit": "person",
        }
    if nightlight_style:
        saved_design["nightlight_style"] = {
            "palette": "platform_radiance_v1",
            "domain": "positive_p5_p98",
            "boundary_modes": ["hotspot", "gradient"],
            "min_value": nightlight_style["min_value"],
            "max_value": nightlight_style["max_value"],
            "p75": nightlight_style["p75"],
            "p90": nightlight_style["p90"],
            "valid_count": nightlight_style["valid_count"],
            "total_count": nightlight_style["total_count"],
            "hotspot_analysis": nightlight_style["hotspot_analysis"],
            "gradient_analysis": nightlight_style["gradient_analysis"],
        }
    return _save(
        image,
        directory,
        _filename(index, "map", str(spec["title"])),
        str(spec["title"]),
        source_datasets=_source_manifest(data, (layer["dataset_id"] for layer in layers)),
        design=saved_design,
    )


def _aggregate_rows(
    records: list[dict[str, Any]], group_by: str, metric_op: str, metric_field: str
) -> list[tuple[str, float]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = str(record.get(group_by) or "未分类") if group_by else "全部记录"
        groups.setdefault(key, []).append(record)
    rows = []
    for label, values in groups.items():
        if metric_op == "count":
            value = float(len(values))
        else:
            numbers = [_number(item.get(metric_field)) for item in values]
            usable = [number for number in numbers if number is not None]
            value = sum(usable) if metric_op == "sum" else (sum(usable) / len(usable) if usable else 0.0)
        rows.append((label, value))
    return sorted(rows, key=lambda item: (-item[1], item[0]))


def _poi_supply_chart_asset(
    spec: Mapping[str, Any],
    data: Mapping[str, list[dict[str, Any]]],
    directory: Path,
    index: int,
) -> dict[str, Any] | None:
    records = data.get("poi", [])
    rows = Counter(str(item.get("category") or "其他") for item in records).most_common(11)
    if not rows:
        return None
    total = len(records)
    image, draw = _canvas(
        str(spec["title"]),
        f"完整 POI {total:,} 条 · 展示全部 {len(rows)} 个一级分类 · 数量与占比",
        height=900,
    )
    left, right, top, row_height = 330, 920, 125, 61
    maximum = max(value for _, value in rows)
    for row_index, (label, value) in enumerate(rows):
        y = top + row_index * row_height
        color = _POI_COLORS.get(label, _POI_COLORS["其他"])
        width = (right - left) * value / maximum
        draw.text((_PADDING, y + 8), label, fill="#344054", font=_font(16))
        draw.rounded_rectangle((left, y, left + width, y + 31), radius=3, fill=color)
        draw.text((left + width + 10, y + 5), f"{value:,} · {value / total:.1%}", fill="#172033", font=_font(14))

    cultural = sum(value for label, value in rows if label in {"科教文化服务", "风景名胜"})
    daily = sum(value for label, value in rows if label in {"餐饮服务", "购物服务"})
    lines = [
        ("日常消费供给", f"餐饮+购物 {daily:,} 个，占全部 {daily / total:.1%}"),
        ("文化与游憩供给", f"科教文化+风景名胜 {cultural:,} 个，占全部 {cultural / total:.1%}"),
        ("结构判断", "周边是成熟混合城区，不是商业或公共服务空白。"),
        ("产品影响", "项目应补历史内容、公共活动和社区复访，而非复制普通餐饮街。"),
    ]
    _draw_panel(
        draw,
        title="供给结构如何改变决策",
        lines=lines,
        note="POI数量表示设施供给，不代表营业质量、市场容量、消费额或项目可截获客流。",
        top=125,
        bottom=820,
    )
    return _save(
        image,
        directory,
        _filename(index, "chart", str(spec["title"])),
        str(spec["title"]),
        source_datasets=_source_manifest(data, ["poi"]),
        design={**dict(spec), "display": "count_and_share", "categories_complete": True},
    )


def _population_profile_chart_asset(
    spec: Mapping[str, Any],
    data: Mapping[str, list[dict[str, Any]]],
    directory: Path,
    index: int,
) -> dict[str, Any] | None:
    records = data.get("population", [])
    if not records:
        return None
    totals = {
        "总人口": sum(_number(item.get("population_total")) or 0.0 for item in records),
        "5–19岁": sum(_number(item.get("age_5_19")) or 0.0 for item in records),
        "30–39岁": sum(_number(item.get("age_30_39")) or 0.0 for item in records),
        "50–64岁": sum(_number(item.get("age_50_64")) or 0.0 for item in records),
    }
    total = totals["总人口"]
    share_total = total or 1.0
    image, draw = _canvas(
        str(spec["title"]),
        f"2026 年人口格网 {len(records):,} 个 · 常住人口代理 · 重点年龄段汇总",
        height=900,
    )
    draw.text((_PADDING, 128), f"{total:,.0f}", fill="#172033", font=_font(64, bold=True))
    draw.text((_PADDING, 204), "范围内常住人口代理", fill="#667085", font=_font(17))
    age_rows = [(label, value) for label, value in totals.items() if label != "总人口"]
    colors = ["#2a9d8f", "#457b9d", "#6d597a"]
    maximum = max(value for _, value in age_rows) or 1.0
    for row_index, ((label, value), color) in enumerate(zip(age_rows, colors)):
        y = 310 + row_index * 145
        draw.text((_PADDING, y), label, fill="#344054", font=_font(20, bold=True))
        draw.text((_PADDING, y + 35), f"{value:,.0f} 人 · 占总人口 {value / share_total:.1%}", fill="#667085", font=_font(15))
        width = 760 * value / maximum
        draw.rounded_rectangle((_PADDING, y + 72, _PADDING + width, y + 112), radius=4, fill=color)

    lines = [
        ("青少年使用", "5–19岁支持研学、亲子学习与学校合作测试。"),
        ("成年复访", "30–39岁支持公共课程、家庭活动和内容消费测试。"),
        ("社区日常", "50–64岁支持社区课程、银龄活动与志愿参与测试。"),
        ("决策含义", "首期产品应覆盖多时段公共使用，而非押注单一游客客群。"),
    ]
    _draw_panel(
        draw,
        title="人口底盘如何改变产品",
        lines=lines,
        note="年龄人口是常住人口代理，不等同项目客群、实际到访、付费意愿或收入。",
        top=125,
        bottom=820,
    )
    return _save(
        image,
        directory,
        _filename(index, "chart", str(spec["title"])),
        str(spec["title"]),
        source_datasets=_source_manifest(data, ["population"]),
        design={**dict(spec), "values": totals, "unit": "person", "interpretation": "resident_population_proxy"},
    )


def _chart_asset(
    spec: Mapping[str, Any], data: Mapping[str, list[dict[str, Any]]], directory: Path, index: int
) -> dict[str, Any] | None:
    if str(spec.get("chart_variant") or "") == "poi_supply":
        return _poi_supply_chart_asset(spec, data, directory, index)
    if str(spec.get("chart_variant") or "") == "population_profile":
        return _population_profile_chart_asset(spec, data, directory, index)
    dataset_id = str(spec["dataset_id"])
    if not dataset_id or not data.get(dataset_id):
        return None
    rows = _aggregate_rows(data[dataset_id], str(spec["group_by"]), str(spec["metric_op"]), str(spec["metric_field"]))
    if not rows:
        return None
    height = max(_HEIGHT, 180 + len(rows) * 48)
    image = Image.new("RGB", (_WIDTH, height), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, _WIDTH, 82), fill="#ffffff")
    draw.text((_PADDING, 18), str(spec["title"]), fill="#172033", font=_font(32, bold=True))
    draw.text((_PADDING, 58), f"基于 {dataset_id} 的全量 {len(data[dataset_id]):,} 条记录，完整展示 {len(rows):,} 个分组", fill="#667085", font=_font(16))
    max_value = max(value for _, value in rows) or 1
    left, right = 360, 1480
    for row_index, (label, value) in enumerate(rows):
        y = 122 + row_index * 48
        width = (right - left) * value / max_value
        draw.text((_PADDING, y + 8), label[:28], fill="#344054", font=_font(16))
        draw.rectangle((left, y, left + width, y + 28), fill=_safe_color("", row_index))
        draw.text((left + width + 10, y + 5), f"{value:,.2f}" if value % 1 else f"{value:,.0f}", fill="#172033", font=_font(15))
    return _save(
        image,
        directory,
        _filename(index, "chart", str(spec["title"])),
        str(spec["title"]),
        source_datasets=_source_manifest(data, [dataset_id]),
        design=spec,
    )


def _table_asset(spec: Mapping[str, Any], data: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    dataset_id = str(spec["dataset_id"])
    if dataset_id:
        rows = _aggregate_rows(data.get(dataset_id, []), str(spec["group_by"]), str(spec["metric_op"]), str(spec["metric_field"]))
        metric_label = "记录数" if spec["metric_op"] == "count" else f"{spec['metric_op']}({spec['metric_field']})"
        lines = [f"| {spec['group_by'] or '范围'} | {metric_label} |", "|---|---:|"]
        lines.extend(
            f"| {label} | {value:,.2f} |" if value % 1 else f"| {label} | {value:,.0f} |"
            for label, value in rows
        )
        sources = [dataset_id]
    else:
        lines = ["| 数据集 | 全量记录数 |", "|---|---:|"]
        lines.extend(f"| {name} | {len(records):,} |" for name, records in data.items())
        sources = list(data)
    return {
        "kind": "table",
        "title": str(spec["title"]),
        "markdown": "\n".join(lines),
        "source_datasets": _source_manifest(data, sources),
        "design": dict(spec),
    }


def _available_dataset_ids(project_context: Mapping[str, Any] | None) -> list[str]:
    declared = [
        str(item.get("dataset_id") or "")
        for item in (project_context or {}).get("datasets") or []
        if isinstance(item, Mapping)
    ]
    return [dataset_id for dataset_id in declared if dataset_id in DATASET_SOURCES] or list(DATASET_SOURCES)


def build_spatial_strategy_visuals(
    *,
    run_id: str,
    history_id: str = "",
    project_context: Mapping[str, Any] | None = None,
    visual_plan: Iterable[Mapping[str, Any]] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    resolved_history_id = _resolve_history_id(history_id)
    directory = (root or Path(settings.spatial_strategy_report_dir)) / str(run_id) / "visuals"
    directory.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    for dataset_id in _available_dataset_ids(project_context):
        try:
            # Rendering reads the project's complete stored record set; it never uses paged API results.
            data[dataset_id] = _DATA._all_spatial_records(resolved_history_id, dataset_id)
        except (LookupError, ValueError, SQLAlchemyError) as exc:
            warnings.append(f"{dataset_id}:{exc}")

    filtered_plan, dropped_count = _drop_empty_visual_placeholders(visual_plan)
    if dropped_count:
        warnings.append(f"visual_plan_items_dropped:{dropped_count}")
    if not data:
        # A report can still be delivered with chapter evidence when the optional
        # full-record rendering source is temporarily unavailable.
        warnings.append("visual_render_skipped:no_dataset_records_available")
        plan = []
    else:
        try:
            plan = _normalize_plan(filtered_plan, data)
        except ValueError as exc:
            # A malformed model plan is recoverable: retain the report and use
            # deterministic plans derived from the datasets actually available.
            warnings.append(f"visual_plan_replaced:{exc}")
            plan = _normalize_plan(_plan_defaults(data), data)
    assets = []
    for index, spec in enumerate(plan, start=1):
        visual_format = spec["format"]
        if visual_format == "map":
            asset = _map_asset(spec, data, directory, index)
        elif visual_format == "chart":
            asset = _chart_asset(spec, data, directory, index)
        else:
            asset = _table_asset(spec, data)
        if asset is None:
            warnings.append(f"{spec['title']}:source_data_unavailable")
        else:
            assets.append(asset)
    _validate_rendered_assets(plan, assets)
    descriptors = {
        str(item.get("dataset_id") or ""): item
        for item in (project_context or {}).get("datasets") or []
        if isinstance(item, Mapping)
    }
    for asset in assets:
        for source in asset.get("source_datasets") or []:
            descriptor = descriptors.get(str(source.get("dataset_id") or ""))
            if not isinstance(descriptor, Mapping):
                continue
            source.update(
                {
                    "year": descriptor.get("year"),
                    "coord_type": descriptor.get("coord_type"),
                    "dataset_checksum": descriptor.get("dataset_checksum"),
                    "units": descriptor.get("units") or {},
                }
            )
    return {
        "status": "ready",
        "run_id": str(run_id),
        "history_id": resolved_history_id,
        "visual_plan": plan,
        "assets": assets,
        "warnings": warnings,
    }
