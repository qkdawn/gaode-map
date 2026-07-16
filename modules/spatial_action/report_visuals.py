"""Deterministic SVG rendering for validated report visual candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
import json
from math import ceil, isfinite, sqrt
import re
from typing import Any
from xml.etree import ElementTree

WIDTH = 960
HEIGHT = 540
PALETTE = ("#2563eb", "#0f766e", "#d97706", "#7c3aed", "#dc2626", "#0891b2")
GRID = "#dbe3ee"
INK = "#172033"
MUTED = "#61708a"
SURFACE = "#ffffff"
PROVENANCE_FIELDS = (
    "visual_id",
    "metric_attempt_ids",
    "evidence_ids",
    "source_artifact",
    "transform",
    "coordinate_system",
    "extent",
    "geometry_sources",
    "spec_hash",
)
URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


def render_report_visual(candidate: Any) -> str:
    """Render one validated VisualCandidate-compatible object as an SVG string."""
    payload = _mapping(candidate, "VisualCandidate")
    visual_type = _text(payload.get("visual_type"), "VisualCandidate.visual_type")
    title = _text(payload.get("title"), "VisualCandidate.title")
    purpose = _text(payload.get("purpose"), "VisualCandidate.purpose")
    data = _mapping(payload.get("data"), f"{visual_type}.data")
    renderers = {
        "bar": _render_bar,
        "line": _render_line,
        "scatter": _render_scatter,
        "simple_map": _render_simple_map,
        "diagram": _render_diagram,
        "timeline": _render_timeline,
    }
    renderer = renderers.get(visual_type)
    if renderer is None:
        raise ValueError(f"unsupported report visual type: {visual_type}")
    provenance = {field: payload[field] for field in PROVENANCE_FIELDS if field in payload}
    return renderer(title, purpose, data, provenance)


def validate_safe_svg(svg: str) -> None:
    """Reject active content and external references in an SVG string."""
    if not isinstance(svg, str) or not svg.strip():
        raise ValueError("report visual SVG must be a non-empty string")
    lowered = svg.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("report visual SVG must not contain document type or entity declarations")
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("report visual SVG is not well-formed XML") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError("report visual SVG root element must be svg")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script", "foreignobject"}:
            raise ValueError(f"report visual SVG contains forbidden element: {tag}")
        if tag == "style":
            _validate_reference_text(element.text or "")
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].lower()
            value = str(raw_value or "").strip()
            if name.startswith("on"):
                raise ValueError(f"report visual SVG contains forbidden event handler: {name}")
            if name in {"href", "src"} and value and not value.startswith("#"):
                raise ValueError(f"report visual SVG contains external reference: {name}")
            _validate_reference_text(value)


def _validate_reference_text(value: str) -> None:
    lowered = value.lower()
    if "@import" in lowered:
        raise ValueError("report visual SVG contains an external style import")
    if re.search(r"(^|[\s:'\"(])(?:https?:|file:|data:|//)", lowered):
        raise ValueError("report visual SVG contains an external resource reference")
    for match in URL_PATTERN.finditer(value):
        if not match.group(2).strip().startswith("#"):
            raise ValueError("report visual SVG contains an external URL reference")


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _sequence(value: Any, field: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be an array")
    items = list(value)
    if not allow_empty and not items:
        raise ValueError(f"{field} must not be empty")
    return items


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _optional_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _fmt(value: float) -> str:
    if abs(value) < 1e-9:
        value = 0.0
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _short(value: str, limit: int = 22) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _svg_start(title: str, purpose: str, provenance: dict[str, Any], *, height: int = HEIGHT, definitions: str = "") -> list[str]:
    title_text = escape(title)
    purpose_text = escape(purpose)
    provenance_text = escape(json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="visual-title visual-description">',
        f'<title id="visual-title">{title_text}</title>',
        f'<desc id="visual-description">{purpose_text}</desc>',
        f'<metadata id="report-visual-provenance">{provenance_text}</metadata>',
        definitions,
        f'<rect width="{WIDTH}" height="{height}" rx="18" fill="{SURFACE}"/>',
        f'<text x="48" y="42" fill="{INK}" font-family="Segoe UI,Arial,sans-serif" font-size="24" font-weight="700">{title_text}</text>',
        f'<text x="48" y="70" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="13">{escape(_short(purpose, 112))}</text>',
    ]


def _finish(parts: list[str]) -> str:
    parts.append("</svg>")
    svg = "\n".join(item for item in parts if item) + "\n"
    validate_safe_svg(svg)
    return svg


def _domain(values: list[float], *, include_zero: bool = False) -> tuple[float, float]:
    low, high = min(values), max(values)
    if include_zero:
        low, high = min(low, 0.0), max(high, 0.0)
    if low == high:
        padding = abs(low) * 0.1 or 1.0
        low, high = low - padding, high + padding
        if include_zero:
            low, high = min(low, 0.0), max(high, 0.0)
    return low, high


def _scale(value: float, low: float, high: float, start: float, end: float) -> float:
    return start + (value - low) * (end - start) / (high - low)


def _axes(parts: list[str], *, left: float, top: float, right: float, bottom: float, low: float, high: float, x_label: str, y_label: str) -> None:
    for index in range(5):
        ratio = index / 4
        y = bottom - ratio * (bottom - top)
        value = low + ratio * (high - low)
        parts.append(f'<line x1="{_fmt(left)}" y1="{_fmt(y)}" x2="{_fmt(right)}" y2="{_fmt(y)}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{_fmt(left - 12)}" y="{_fmt(y + 4)}" text-anchor="end" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">{escape(_fmt(value))}</text>')
    parts.append(f'<line x1="{_fmt(left)}" y1="{_fmt(bottom)}" x2="{_fmt(right)}" y2="{_fmt(bottom)}" stroke="{INK}" stroke-width="1.4"/>')
    parts.append(f'<line x1="{_fmt(left)}" y1="{_fmt(top)}" x2="{_fmt(left)}" y2="{_fmt(bottom)}" stroke="{INK}" stroke-width="1.4"/>')
    if x_label:
        parts.append(f'<text x="{_fmt((left + right) / 2)}" y="{_fmt(bottom + 58)}" text-anchor="middle" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="12">{escape(x_label)}</text>')
    if y_label:
        parts.append(f'<text x="24" y="{_fmt((top + bottom) / 2)}" text-anchor="middle" transform="rotate(-90 24 {_fmt((top + bottom) / 2)})" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="12">{escape(y_label)}</text>')


def _legend(parts: list[str], names: list[str]) -> None:
    x = 48
    for index, name in enumerate(names):
        color = PALETTE[index % len(PALETTE)]
        parts.append(f'<rect x="{x}" y="88" width="12" height="12" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + 18}" y="99" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">{escape(_short(name, 18))}</text>')
        x += 36 + min(len(name), 18) * 7


def _categorical_series(data: dict[str, Any], visual_type: str) -> tuple[list[dict[str, Any]], list[str], list[float]]:
    raw_series = _sequence(data.get("series"), f"{visual_type}.data.series")
    series: list[dict[str, Any]] = []
    labels: list[str] | None = None
    values: list[float] = []
    for series_index, raw in enumerate(raw_series):
        item = _mapping(raw, f"{visual_type}.data.series[{series_index}]")
        name = _text(item.get("name"), f"{visual_type}.data.series[{series_index}].name")
        points = _sequence(item.get("points"), f"{visual_type}.data.series[{series_index}].points")
        parsed_points = []
        point_labels = []
        for point_index, raw_point in enumerate(points):
            point = _mapping(raw_point, f"{visual_type}.data.series[{series_index}].points[{point_index}]")
            label = _text(point.get("label"), f"{visual_type}.data.series[{series_index}].points[{point_index}].label")
            value = _number(point.get("value"), f"{visual_type}.data.series[{series_index}].points[{point_index}].value")
            point_labels.append(label)
            parsed_points.append((label, value))
            values.append(value)
        if labels is None:
            labels = point_labels
        elif labels != point_labels:
            raise ValueError(f"{visual_type}.data.series point labels must align")
        series.append({"name": name, "points": parsed_points})
    return series, labels or [], values


def _render_bar(title: str, purpose: str, data: dict[str, Any], provenance: dict[str, Any]) -> str:
    series, labels, values = _categorical_series(data, "bar")
    low, high = _domain(values, include_zero=True)
    left, top, right, bottom = 88.0, 124.0, 922.0, 448.0
    parts = _svg_start(title, purpose, provenance)
    _legend(parts, [item["name"] for item in series])
    _axes(parts, left=left, top=top, right=right, bottom=bottom, low=low, high=high, x_label=_optional_text(data.get("x_label")), y_label=_optional_text(data.get("y_label")))
    category_width = (right - left) / len(labels)
    group_width = category_width * 0.72
    bar_width = group_width / len(series)
    zero_y = _scale(0.0, low, high, bottom, top)
    for category_index, label in enumerate(labels):
        group_left = left + category_index * category_width + (category_width - group_width) / 2
        for series_index, item in enumerate(series):
            value = item["points"][category_index][1]
            value_y = _scale(value, low, high, bottom, top)
            y = min(zero_y, value_y)
            height = max(abs(value_y - zero_y), 1.0)
            x = group_left + series_index * bar_width
            parts.append(f'<rect x="{_fmt(x + 1)}" y="{_fmt(y)}" width="{_fmt(max(bar_width - 2, 1))}" height="{_fmt(height)}" rx="3" fill="{PALETTE[series_index % len(PALETTE)]}"/>')
        center = left + (category_index + 0.5) * category_width
        parts.append(f'<text x="{_fmt(center)}" y="{_fmt(bottom + 22)}" text-anchor="middle" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">{escape(_short(label, 12))}</text>')
    return _finish(parts)


def _render_line(title: str, purpose: str, data: dict[str, Any], provenance: dict[str, Any]) -> str:
    series, labels, values = _categorical_series(data, "line")
    low, high = _domain(values)
    left, top, right, bottom = 88.0, 124.0, 922.0, 448.0
    parts = _svg_start(title, purpose, provenance)
    _legend(parts, [item["name"] for item in series])
    _axes(parts, left=left, top=top, right=right, bottom=bottom, low=low, high=high, x_label=_optional_text(data.get("x_label")), y_label=_optional_text(data.get("y_label")))
    x_positions = [((left + right) / 2 if len(labels) == 1 else left + index * (right - left) / (len(labels) - 1)) for index in range(len(labels))]
    for index, label in enumerate(labels):
        parts.append(f'<text x="{_fmt(x_positions[index])}" y="{_fmt(bottom + 22)}" text-anchor="middle" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">{escape(_short(label, 12))}</text>')
    for series_index, item in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        points = [(x_positions[index], _scale(point[1], low, high, bottom, top)) for index, point in enumerate(item["points"])]
        coordinates = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points)
        parts.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y in points:
            parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="4" fill="{SURFACE}" stroke="{color}" stroke-width="2.5"/>')
    return _finish(parts)


def _render_scatter(title: str, purpose: str, data: dict[str, Any], provenance: dict[str, Any]) -> str:
    raw_series = _sequence(data.get("series"), "scatter.data.series")
    series = []
    all_x: list[float] = []
    all_y: list[float] = []
    for series_index, raw in enumerate(raw_series):
        item = _mapping(raw, f"scatter.data.series[{series_index}]")
        name = _text(item.get("name"), f"scatter.data.series[{series_index}].name")
        points = []
        for point_index, raw_point in enumerate(_sequence(item.get("points"), f"scatter.data.series[{series_index}].points")):
            point = _mapping(raw_point, f"scatter.data.series[{series_index}].points[{point_index}]")
            x = _number(point.get("x"), f"scatter.data.series[{series_index}].points[{point_index}].x")
            y = _number(point.get("y"), f"scatter.data.series[{series_index}].points[{point_index}].y")
            points.append((x, y, _optional_text(point.get("label"))))
            all_x.append(x)
            all_y.append(y)
        series.append({"name": name, "points": points})
    x_low, x_high = _domain(all_x)
    y_low, y_high = _domain(all_y)
    left, top, right, bottom = 88.0, 124.0, 922.0, 448.0
    parts = _svg_start(title, purpose, provenance)
    _legend(parts, [item["name"] for item in series])
    _axes(parts, left=left, top=top, right=right, bottom=bottom, low=y_low, high=y_high, x_label=_optional_text(data.get("x_label")), y_label=_optional_text(data.get("y_label")))
    for index in range(5):
        ratio = index / 4
        x = left + ratio * (right - left)
        value = x_low + ratio * (x_high - x_low)
        parts.append(f'<line x1="{_fmt(x)}" y1="{_fmt(top)}" x2="{_fmt(x)}" y2="{_fmt(bottom)}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{_fmt(x)}" y="{_fmt(bottom + 22)}" text-anchor="middle" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">{escape(_fmt(value))}</text>')
    for series_index, item in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        for x_value, y_value, label in item["points"]:
            x = _scale(x_value, x_low, x_high, left, right)
            y = _scale(y_value, y_low, y_high, bottom, top)
            parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="5" fill="{color}" fill-opacity="0.82" stroke="{SURFACE}" stroke-width="1.5"/>')
            if label:
                parts.append(f'<text x="{_fmt(x + 8)}" y="{_fmt(y - 7)}" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="10">{escape(_short(label, 18))}</text>')
    return _finish(parts)


def _coordinate(value: Any, field: str) -> tuple[float, float]:
    pair = _sequence(value, field)
    if len(pair) < 2:
        raise ValueError(f"{field} must contain x and y")
    return _number(pair[0], f"{field}[0]"), _number(pair[1], f"{field}[1]")


def _geometry(value: Any, field: str) -> tuple[str, Any, list[tuple[float, float]]]:
    geometry = _mapping(value, field)
    geometry_type = _text(geometry.get("type"), f"{field}.type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        point = _coordinate(coordinates, f"{field}.coordinates")
        return "point", [point], [point]
    if geometry_type == "MultiPoint":
        points = [_coordinate(item, f"{field}.coordinates[{index}]") for index, item in enumerate(_sequence(coordinates, f"{field}.coordinates"))]
        return "point", points, points
    if geometry_type == "LineString":
        line = [_coordinate(item, f"{field}.coordinates[{index}]") for index, item in enumerate(_sequence(coordinates, f"{field}.coordinates"))]
        return "line", [line], line
    if geometry_type == "MultiLineString":
        lines = [[_coordinate(point, f"{field}.coordinates[{line_index}][{point_index}]") for point_index, point in enumerate(_sequence(line, f"{field}.coordinates[{line_index}]"))] for line_index, line in enumerate(_sequence(coordinates, f"{field}.coordinates"))]
        return "line", lines, [point for line in lines for point in line]
    if geometry_type == "Polygon":
        rings = [[_coordinate(point, f"{field}.coordinates[{ring_index}][{point_index}]") for point_index, point in enumerate(_sequence(ring, f"{field}.coordinates[{ring_index}]"))] for ring_index, ring in enumerate(_sequence(coordinates, f"{field}.coordinates"))]
        return "polygon", [rings], [point for ring in rings for point in ring]
    if geometry_type == "MultiPolygon":
        polygons = []
        for polygon_index, polygon in enumerate(_sequence(coordinates, f"{field}.coordinates")):
            rings = [[_coordinate(point, f"{field}.coordinates[{polygon_index}][{ring_index}][{point_index}]") for point_index, point in enumerate(_sequence(ring, f"{field}.coordinates[{polygon_index}][{ring_index}]"))] for ring_index, ring in enumerate(_sequence(polygon, f"{field}.coordinates[{polygon_index}]"))]
            polygons.append(rings)
        return "polygon", polygons, [point for polygon in polygons for ring in polygon for point in ring]
    raise ValueError(f"{field}.type is unsupported: {geometry_type}")


def _render_simple_map(title: str, purpose: str, data: dict[str, Any], provenance: dict[str, Any]) -> str:
    raw_features = _sequence(data.get("features"), "simple_map.data.features")
    features = []
    all_points: list[tuple[float, float]] = []
    for index, raw in enumerate(raw_features):
        feature = _mapping(raw, f"simple_map.data.features[{index}]")
        feature_id = _text(feature.get("id"), f"simple_map.data.features[{index}].id")
        kind, geometry, points = _geometry(feature.get("geometry"), f"simple_map.data.features[{index}].geometry")
        label = _optional_text(feature.get("label"))
        value = None if feature.get("value") is None else _number(feature.get("value"), f"simple_map.data.features[{index}].value")
        features.append({"id": feature_id, "label": label, "value": value, "kind": kind, "geometry": geometry, "points": points})
        all_points.extend(points)
    x_low, x_high = _domain([point[0] for point in all_points])
    y_low, y_high = _domain([point[1] for point in all_points])
    left, top, right, bottom = 48.0, 108.0, 912.0, 492.0
    project = lambda point: (_scale(point[0], x_low, x_high, left, right), _scale(point[1], y_low, y_high, bottom, top))
    parts = _svg_start(title, purpose, provenance)
    parts.append(f'<rect x="{_fmt(left)}" y="{_fmt(top)}" width="{_fmt(right - left)}" height="{_fmt(bottom - top)}" rx="12" fill="#f4f7fb" stroke="{GRID}"/>')
    for index, feature in enumerate(features):
        color = PALETTE[index % len(PALETTE)]
        if feature["kind"] == "point":
            for point in feature["geometry"]:
                x, y = project(point)
                parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="7" fill="{color}" stroke="{SURFACE}" stroke-width="2"/>')
        elif feature["kind"] == "line":
            for line in feature["geometry"]:
                coordinates = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in (project(point) for point in line))
                parts.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            for polygon in feature["geometry"]:
                path_commands = []
                for ring in polygon:
                    projected = [project(point) for point in ring]
                    path_commands.append("M " + " L ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in projected) + " Z")
                parts.append(f'<path d="{" ".join(path_commands)}" fill="{color}" fill-opacity="0.24" fill-rule="evenodd" stroke="{color}" stroke-width="2"/>')
        if feature["label"]:
            projected_points = [project(point) for point in feature["points"]]
            x = sum(point[0] for point in projected_points) / len(projected_points)
            y = sum(point[1] for point in projected_points) / len(projected_points)
            suffix = "" if feature["value"] is None else f" · {_fmt(feature['value'])}"
            parts.append(f'<text x="{_fmt(x)}" y="{_fmt(y - 10)}" text-anchor="middle" fill="{INK}" font-family="Segoe UI,Arial,sans-serif" font-size="11" font-weight="600">{escape(_short(feature["label"] + suffix, 28))}</text>')
    return _finish(parts)


def _render_diagram(title: str, purpose: str, data: dict[str, Any], provenance: dict[str, Any]) -> str:
    raw_nodes = _sequence(data.get("nodes"), "diagram.data.nodes")
    raw_links = _sequence(data.get("links"), "diagram.data.links", allow_empty=True)
    nodes = []
    node_ids = set()
    for index, raw in enumerate(raw_nodes):
        node = _mapping(raw, f"diagram.data.nodes[{index}]")
        node_id = _text(node.get("id"), f"diagram.data.nodes[{index}].id")
        if node_id in node_ids:
            raise ValueError(f"diagram.data.nodes id must be unique: {node_id}")
        node_ids.add(node_id)
        nodes.append({"id": node_id, "label": _text(node.get("label"), f"diagram.data.nodes[{index}].label"), "group": _optional_text(node.get("group"))})
    links = []
    for index, raw in enumerate(raw_links):
        link = _mapping(raw, f"diagram.data.links[{index}]")
        source = _text(link.get("source"), f"diagram.data.links[{index}].source")
        target = _text(link.get("target"), f"diagram.data.links[{index}].target")
        if source not in node_ids or target not in node_ids:
            raise ValueError(f"diagram.data.links[{index}] references an unknown node")
        links.append({"source": source, "target": target, "label": _optional_text(link.get("label"))})
    columns = min(4, max(1, ceil(sqrt(len(nodes)))))
    rows = ceil(len(nodes) / columns)
    height = max(HEIGHT, 180 + rows * 112)
    definitions = '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#61708a"/></marker></defs>'
    parts = _svg_start(title, purpose, provenance, height=height, definitions=definitions)
    positions = {}
    for index, node in enumerate(nodes):
        row, column = divmod(index, columns)
        x = (column + 1) * WIDTH / (columns + 1)
        y = 150 + row * 112
        positions[node["id"]] = (x, y)
    for link in links:
        x1, y1 = positions[link["source"]]
        x2, y2 = positions[link["target"]]
        parts.append(f'<line x1="{_fmt(x1)}" y1="{_fmt(y1 + 32)}" x2="{_fmt(x2)}" y2="{_fmt(y2 - 32)}" stroke="{MUTED}" stroke-width="2" marker-end="url(#arrow)"/>')
        if link["label"]:
            parts.append(f'<text x="{_fmt((x1 + x2) / 2 + 8)}" y="{_fmt((y1 + y2) / 2 - 6)}" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="10">{escape(_short(link["label"], 20))}</text>')
    group_colors: dict[str, str] = {}
    for index, node in enumerate(nodes):
        x, y = positions[node["id"]]
        group = node["group"] or node["id"]
        group_colors.setdefault(group, PALETTE[len(group_colors) % len(PALETTE)])
        color = group_colors[group]
        parts.append(f'<rect x="{_fmt(x - 90)}" y="{_fmt(y - 32)}" width="180" height="64" rx="12" fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<text x="{_fmt(x)}" y="{_fmt(y + 5)}" text-anchor="middle" fill="{INK}" font-family="Segoe UI,Arial,sans-serif" font-size="13" font-weight="600">{escape(_short(node["label"], 24))}</text>')
    return _finish(parts)


def _render_timeline(title: str, purpose: str, data: dict[str, Any], provenance: dict[str, Any]) -> str:
    raw_items = _sequence(data.get("items"), "timeline.data.items")
    items = []
    for index, raw in enumerate(raw_items):
        item = _mapping(raw, f"timeline.data.items[{index}]")
        items.append({"label": _text(item.get("label"), f"timeline.data.items[{index}].label"), "detail": _optional_text(item.get("detail")), "order": _number(item.get("order"), f"timeline.data.items[{index}].order"), "index": index})
    items.sort(key=lambda item: (item["order"], item["index"]))
    height = max(HEIGHT, 150 + len(items) * 92)
    parts = _svg_start(title, purpose, provenance, height=height)
    line_x = 116
    first_y, last_y = 132, 132 + (len(items) - 1) * 92
    parts.append(f'<line x1="{line_x}" y1="{first_y}" x2="{line_x}" y2="{last_y}" stroke="{GRID}" stroke-width="5" stroke-linecap="round"/>')
    for index, item in enumerate(items):
        y = first_y + index * 92
        color = PALETTE[index % len(PALETTE)]
        parts.append(f'<circle cx="{line_x}" cy="{y}" r="11" fill="{color}" stroke="{SURFACE}" stroke-width="4"/>')
        parts.append(f'<text x="78" y="{y + 5}" text-anchor="end" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="11">{escape(_fmt(item["order"]))}</text>')
        parts.append(f'<text x="148" y="{y - 4}" fill="{INK}" font-family="Segoe UI,Arial,sans-serif" font-size="15" font-weight="700">{escape(_short(item["label"], 54))}</text>')
        if item["detail"]:
            parts.append(f'<text x="148" y="{y + 20}" fill="{MUTED}" font-family="Segoe UI,Arial,sans-serif" font-size="12">{escape(_short(item["detail"], 96))}</text>')
    return _finish(parts)
