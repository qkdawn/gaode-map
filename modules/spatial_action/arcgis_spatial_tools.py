"""Deep V4 boundary for safely turning archived results into ArcGIS SVG assets."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shapely.geometry import (
    GeometryCollection,
    LineString,
    box,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
    shape,
)
from shapely.validation import make_valid

from core.config import settings
from core.spatial import to_wgs84_geometry
from core.svg_safety import validate_safe_svg
from modules.spatial_projects.query_snapshot_store import MAX_SNAPSHOT_FEATURES, SpatialQuerySnapshotStore

VISUAL_TEMPLATES = {
    "bar": ("report_chart", "chart.bar.v1", "report.decision_visual"),
    "line": ("report_chart", "chart.line.v1", "report.decision_visual"),
    "scatter": ("report_chart", "chart.scatter.v1", "report.decision_visual"),
    "timeline": ("report_chart", "chart.timeline.v1", "report.decision_visual"),
    "diagram": ("report_chart", "chart.relationship.v1", "report.decision_visual"),
    "thematic_map": ("thematic_map", "map.thematic.v1", "spatial.thematic_visual"),
}



_MAX_SERIES = 6
_MAX_POINTS_PER_SERIES = 24
_MAX_SCATTER_POINTS = 250
_MAX_TIMELINE_ITEMS = 8
_MAX_DIAGRAM_NODES = 8
_MAX_DIAGRAM_LINKS = 12
_MAX_THEMATIC_FEATURES = 10_256
_DECISION_MAP_LAYOUT_VERSION = "decision-map-v1"


def _text(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    normalized = value.replace("\x00", " ").strip()
    if not normalized or len(normalized) > limit:
        raise ValueError(f"{field} is required and exceeds its approved limit")
    return normalized


def _number(value: Any, *, field: str) -> float:
    from math import isfinite

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _identifier(value: Any, *, field: str) -> str:
    normalized = _text(value, field=field, limit=96)
    if any(token in normalized for token in ("/", "\\", "://")):
        raise ValueError(f"{field} must be a stable public identifier")
    return normalized


def _exact_keys(value: Any, *, allowed: set[str], required: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
        raise ValueError(f"{field} has unsupported or missing fields")
    return value


def _normalize_series(data: dict[str, Any], *, scatter: bool) -> dict[str, Any]:
    _exact_keys(data, allowed={"series"}, required={"series"}, field="chart data")
    series = data["series"]
    if not isinstance(series, list) or not series or len(series) > _MAX_SERIES:
        raise ValueError("chart series count is outside the approved limit")
    total = 0
    output = []
    for series_index, item in enumerate(series, 1):
        _exact_keys(item, allowed={"name", "points"}, required={"name", "points"}, field=f"series {series_index}")
        points = item["points"]
        if not isinstance(points, list) or not points or len(points) > _MAX_POINTS_PER_SERIES:
            raise ValueError("chart point count is outside the approved limit")
        normalized_points = []
        for point_index, point in enumerate(points, 1):
            if scatter:
                _exact_keys(point, allowed={"x", "y", "label"}, required={"x", "y", "label"}, field=f"scatter point {point_index}")
                normalized_points.append({
                    "x": _number(point["x"], field="scatter x"),
                    "y": _number(point["y"], field="scatter y"),
                    "label": _text(point["label"], field="scatter label", limit=80),
                })
            else:
                _exact_keys(point, allowed={"label", "value"}, required={"label", "value"}, field=f"chart point {point_index}")
                normalized_points.append({
                    "label": _text(point["label"], field="chart label", limit=80),
                    "value": _number(point["value"], field="chart value"),
                })
        total += len(normalized_points)
        output.append({"name": _text(item["name"], field="series name", limit=80), "points": normalized_points})
    if scatter and total > _MAX_SCATTER_POINTS:
        raise ValueError("scatter point count is outside the approved limit")
    return {"series": output}


def _normalize_timeline(data: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(data, allowed={"items"}, required={"items"}, field="timeline data")
    items = data["items"]
    if not isinstance(items, list) or not items or len(items) > _MAX_TIMELINE_ITEMS:
        raise ValueError("timeline item count is outside the approved limit")
    seen = set()
    output = []
    for item in items:
        _exact_keys(item, allowed={"label", "detail", "order"}, required={"label", "detail", "order"}, field="timeline item")
        order = item["order"]
        if isinstance(order, bool) or not isinstance(order, int) or order in seen:
            raise ValueError("timeline order must be a unique integer")
        seen.add(order)
        output.append({
            "label": _text(item["label"], field="timeline label", limit=80),
            "detail": _text(item["detail"], field="timeline detail", limit=160),
            "order": order,
        })
    return {"items": sorted(output, key=lambda item: item["order"])}


def _normalize_diagram(data: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(data, allowed={"nodes", "links"}, required={"nodes", "links"}, field="relationship data")
    nodes, links = data["nodes"], data["links"]
    if not isinstance(nodes, list) or not nodes or len(nodes) > _MAX_DIAGRAM_NODES or not isinstance(links, list) or len(links) > _MAX_DIAGRAM_LINKS:
        raise ValueError("relationship graph exceeds the approved limit")
    ids, normalized_nodes = set(), []
    for node in nodes:
        _exact_keys(node, allowed={"id", "label"}, required={"id", "label"}, field="relationship node")
        node_id = _identifier(node["id"], field="relationship node id")
        if node_id in ids:
            raise ValueError("relationship node ids must be unique")
        ids.add(node_id)
        normalized_nodes.append({"id": node_id, "label": _text(node["label"], field="relationship label", limit=80)})
    normalized_links = []
    for link in links:
        _exact_keys(link, allowed={"source", "target", "label"}, required={"source", "target", "label"}, field="relationship link")
        source = _identifier(link["source"], field="relationship source")
        target = _identifier(link["target"], field="relationship target")
        if source not in ids or target not in ids or source == target:
            raise ValueError("relationship link must connect distinct declared nodes")
        normalized_links.append({"source": source, "target": target, "label": _text(link["label"], field="relationship link label", limit=80)})
    return {"nodes": normalized_nodes, "links": normalized_links}


def _normalize_position(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("GeoJSON position must contain longitude and latitude")
    return [_number(value[0], field="longitude"), _number(value[1], field="latitude")]


def _polygon_parts(geometry: Any) -> list[Polygon]:
    """Repair private source geometry and return deterministic Polygon parts for Bridge input."""
    if not isinstance(geometry, dict):
        raise ValueError("source geometry must be GeoJSON")
    try:
        candidate = shape(geometry)
    except Exception as exc:
        raise ValueError("source geometry is invalid") from exc
    try:
        repaired = candidate if candidate.is_valid else make_valid(candidate)
    except Exception as exc:
        raise ValueError("source geometry cannot be repaired") from exc
    polygons: list[Polygon] = []
    def visit(item: Any) -> None:
        if isinstance(item, Polygon):
            if not item.is_empty and item.area > 0:
                cleaned = item if item.is_valid else item.buffer(0)
                if isinstance(cleaned, Polygon) and not cleaned.is_empty and cleaned.area > 0:
                    polygons.append(cleaned)
                elif isinstance(cleaned, MultiPolygon):
                    polygons.extend(part for part in cleaned.geoms if not part.is_empty and part.area > 0)
        elif isinstance(item, (MultiPolygon, GeometryCollection)):
            for child in item.geoms:
                visit(child)
    visit(repaired)
    return sorted(polygons, key=lambda part: (round(part.centroid.x, 9), round(part.centroid.y, 9), round(part.area, 12), part.wkb_hex))


def _polygon_feature_parts(*, geometry: Any, role: str, upstream_id: str, label: str, value: float | None = None) -> list[dict[str, Any]]:
    parts = _polygon_parts(geometry)
    if not parts:
        raise ValueError("no valid polygon remains after geometry repair")
    normalized: list[dict[str, Any]] = []
    for index, part in enumerate(parts, 1):
        exterior = [[float(x), float(y)] for x, y in part.exterior.coords]
        interiors = [[[float(x), float(y)] for x, y in ring.coords] for ring in part.interiors]
        digest = hashlib.sha256((upstream_id + "|" + part.wkb_hex).encode("utf-8")).hexdigest()[:12]
        # The Bridge deliberately accepts a narrow identifier alphabet.  Keep the
        # public upstream result/scope id private to this deep module and derive a
        # deterministic transport-only feature id without separators such as `:`.
        safe_upstream = "-".join(part for part in __import__("re").split(r"[^A-Za-z0-9_.-]+", upstream_id) if part).strip(".-")
        safe_upstream = (safe_upstream or "geometry")[:72]
        item: dict[str, Any] = {
            "id": f"{safe_upstream}-polygon-{index}-{digest}",
            "label": label,
            "role": role,
            "geometry": {"type": "Polygon", "coordinates": [exterior, *interiors]},
        }
        if value is not None:
            item["value"] = value
        normalized.append(item)
    return normalized


def _line_parts(geometry: Any) -> list[LineString]:
    if not isinstance(geometry, dict):
        raise ValueError("source geometry must be GeoJSON")
    try:
        candidate = shape(geometry)
        repaired = candidate if candidate.is_valid else make_valid(candidate)
    except Exception as exc:
        raise ValueError("source geometry is invalid") from exc
    parts: list[LineString] = []
    def visit(item: Any) -> None:
        if isinstance(item, LineString):
            if not item.is_empty and len(item.coords) >= 2:
                parts.append(item)
        elif isinstance(item, (MultiLineString, GeometryCollection)):
            for child in item.geoms:
                visit(child)
    visit(repaired)
    return sorted(parts, key=lambda part: (round(part.centroid.x, 9), round(part.centroid.y, 9), part.wkb_hex))


def _point_parts(geometry: Any) -> list[Point]:
    if not isinstance(geometry, dict):
        raise ValueError("source geometry must be GeoJSON")
    try:
        candidate = shape(geometry)
    except Exception as exc:
        raise ValueError("source geometry is invalid") from exc
    points: list[Point] = []
    if isinstance(candidate, Point):
        points = [candidate] if not candidate.is_empty else []
    elif isinstance(candidate, GeometryCollection):
        points = [item for item in candidate.geoms if isinstance(item, Point) and not item.is_empty]
    return sorted(points, key=lambda point: (round(point.x, 9), round(point.y, 9), point.wkb_hex))


def _feature_id(upstream_id: str, kind: str, index: int, geometry: Any) -> str:
    digest = hashlib.sha256((upstream_id + "|" + geometry.wkb_hex).encode("utf-8")).hexdigest()[:12]
    safe_upstream = "-".join(part for part in __import__("re").split(r"[^A-Za-z0-9_.-]+", upstream_id) if part).strip(".-")
    safe_upstream = (safe_upstream or "geometry")[:72]
    return f"{safe_upstream}-{kind}-{index}-{digest}"


def _line_feature_parts(*, geometry: Any, role: str, upstream_id: str, label: str, value: float | None = None) -> list[dict[str, Any]]:
    parts = _line_parts(geometry)
    if not parts:
        raise ValueError("no valid line remains after geometry repair")
    output = []
    for index, part in enumerate(parts, 1):
        item: dict[str, Any] = {
            "id": _feature_id(upstream_id, "line", index, part),
            "label": label,
            "role": role,
            "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in part.coords]},
        }
        if value is not None:
            item["value"] = value
        output.append(item)
    return output


def _point_feature_parts(*, geometry: Any, role: str, upstream_id: str, label: str, value: float | None = None) -> list[dict[str, Any]]:
    parts = _point_parts(geometry)
    if not parts:
        raise ValueError("no valid point remains after geometry repair")
    output = []
    for index, point in enumerate(parts, 1):
        item: dict[str, Any] = {
            "id": _feature_id(upstream_id, "point", index, point),
            "label": label,
            "role": role,
            "geometry": {"type": "Point", "coordinates": [float(point.x), float(point.y)]},
        }
        if value is not None:
            item["value"] = value
        output.append(item)
    return output


def _normalize_geometry(geometry: Any) -> dict[str, Any]:
    _exact_keys(geometry, allowed={"type", "coordinates"}, required={"type", "coordinates"}, field="thematic geometry")
    geometry_type = _text(geometry["type"], field="thematic geometry type", limit=32)
    coordinates = geometry["coordinates"]
    if geometry_type == "Point":
        normalized = _normalize_position(coordinates)
    elif geometry_type == "LineString":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError("LineString needs at least two positions")
        normalized = [_normalize_position(point) for point in coordinates]
    elif geometry_type == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("Polygon needs at least one ring")
        normalized = []
        for ring in coordinates:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("Polygon ring needs at least four positions")
            normalized_ring = [_normalize_position(point) for point in ring]
            if normalized_ring[0] != normalized_ring[-1]:
                raise ValueError("Polygon ring must be closed")
            normalized.append(normalized_ring)
    else:
        raise ValueError("only Point, LineString, and Polygon are approved thematic geometries")
    return {"type": geometry_type, "coordinates": normalized}


def _normalize_thematic(data: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(data, allowed={"features", "style"}, required={"features"}, field="thematic data")
    features = data["features"]
    if not isinstance(features, list) or not features or len(features) > _MAX_THEMATIC_FEATURES:
        raise ValueError("thematic feature count is outside the approved limit")
    style = str(data.get("style") or "single").strip()
    if style not in {"single", "graduated", "categorical"}:
        raise ValueError("thematic style is not approved")
    ids, output = set(), []
    for feature in features:
        _exact_keys(feature, allowed={"id", "layer_id", "label", "role", "geometry", "value", "category"}, required={"id", "layer_id", "label", "geometry"}, field="thematic feature")
        feature_id = _identifier(feature["id"], field="thematic feature id")
        if feature_id in ids:
            raise ValueError("thematic feature ids must be unique")
        ids.add(feature_id)
        normalized = {
            "id": feature_id,
            "layer_id": _identifier(feature["layer_id"], field="thematic layer id"),
            "label": _text(feature["label"], field="thematic label", limit=120),
            "role": _text(feature.get("role") or "proxy_high_value_zone", field="thematic role", limit=48),
            "geometry": _normalize_geometry(feature["geometry"]),
        }
        if normalized["role"] not in {
            "study_scope", "grid_metric", "poi_point", "road_context",
            "direction_sector", "distance_band", "spatial_unit",
            "proxy_high_value_zone", "context_corridor", "context_point",
        }:
            raise ValueError("thematic role is not approved")
        if feature.get("value") is not None:
            normalized["value"] = _number(feature["value"], field="thematic value")
        if feature.get("category") is not None:
            normalized["category"] = _text(feature["category"], field="thematic category", limit=80)
        if style == "graduated" and normalized["role"] != "study_scope" and "value" not in normalized:
            raise ValueError("graduated thematic maps require a value for every non-scope feature")
        if style == "categorical" and "category" not in normalized:
            raise ValueError("categorical thematic maps require a category for every feature")
        output.append(normalized)
    return {"features": output, "style": style}


def _normalize_report_visual_data(visual_type: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("report visual data is required")
    if visual_type == "bar":
        return _normalize_series(data, scatter=False)
    if visual_type == "line":
        return _normalize_series(data, scatter=False)
    if visual_type == "scatter":
        return _normalize_series(data, scatter=True)
    if visual_type == "timeline":
        return _normalize_timeline(data)
    if visual_type == "diagram":
        return _normalize_diagram(data)
    if visual_type == "thematic_map":
        return _normalize_thematic(data)
    raise ValueError(f"unsupported ArcGIS report visual type: {visual_type}")


class ArcGISBridgeClient(Protocol):
    def capabilities(self) -> dict[str, Any]: ...

    def execute_report_operation(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class _HttpArcGISBridgeClient:
    """Private client: bridge protocol details never escape the V4 tool boundary."""

    def __init__(self, *, base_url: str | None = None, token: str | None = None, status_timeout_sec: int = 5) -> None:
        # Settings are the single application configuration boundary. Explicit
        # arguments remain useful for isolated tests, but production callers do
        # not need to know about environment variable names.
        configured_url = str(getattr(settings, "arcgis_bridge_base_url", "") or "").strip()
        if not configured_url:
            configured_url = f"http://127.0.0.1:{int(getattr(settings, 'arcgis_bridge_port', 18081) or 18081)}"
        self._base_url = str(base_url or configured_url).rstrip("/")
        self._token = str(token if token is not None else getattr(settings, "arcgis_bridge_token", "") or "").strip()
        self._enabled = bool(getattr(settings, "arcgis_bridge_enabled", True))
        self._status_timeout_sec = max(1, int(status_timeout_sec or 5))

    def _request(self, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._enabled:
            return {"status": "unavailable", "summary": "ArcGIS 报告视觉服务已被配置为不可用。", "limitations": ["本机受控视觉服务开关处于关闭状态。"]}
        if not self._token:
            return {"status": "unavailable", "summary": "ArcGIS 报告视觉服务尚未配置。", "limitations": ["本机受控视觉服务凭据不可用。"]}
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers={"X-ArcGIS-Token": self._token, "Accept": "application/json", **({"Content-Type": "application/json"} if data else {})},
            method="POST" if data else "GET",
        )
        try:
            # Report-map rendering is a long-running server-side export. Do
            # not impose a client socket deadline; the bridge owns its job
            # lifecycle and returns a terminal response when rendering ends.
            response_stream = urlopen(request) if payload is not None else urlopen(request, timeout=self._status_timeout_sec)
            with response_stream as response:
                parsed = json.loads(response.read().decode("utf-8"))
                return parsed if isinstance(parsed, dict) else {}
        except HTTPError as exc:
            if exc.code in {401, 403}:
                return {"status": "unauthorized", "summary": "ArcGIS 报告视觉服务未授权。", "limitations": ["受控视觉服务凭据无效或权限不足。"]}
            if exc.code == 404:
                return {"status": "template_unavailable", "summary": "ArcGIS 报告视觉模板不可用。", "limitations": ["受控视觉服务未提供所需操作。"]}
            if exc.code == 503:
                return {"status": "unavailable", "summary": "ArcGIS 报告视觉服务当前不可用。", "limitations": ["受控视觉服务尚未就绪。"]}
            return {"status": "failed", "summary": "ArcGIS 报告视觉服务未能响应。", "limitations": ["受控视觉服务请求失败。"]}
        except (URLError, ConnectionError):
            return {"status": "unavailable", "summary": "ArcGIS 报告视觉服务当前不可连接。", "limitations": ["可在服务恢复后重新生成该视觉资产。"]}
        except TimeoutError:
            return {"status": "timeout", "summary": "ArcGIS 报告视觉作业超时。", "limitations": ["未生成替代图片；可在服务恢复后重试。"]}
        except (ValueError, OSError):
            return {"status": "failed", "summary": "ArcGIS 报告视觉服务返回了无法读取的响应。", "limitations": ["未生成替代图片。"]}

    def capabilities(self) -> dict[str, Any]:
        return self._request("/v1/arcgis/capabilities")

    def execute_report_operation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("/v1/arcgis/report-operations", payload=payload)


@dataclass(frozen=True)
class _BridgeAvailability:
    available_templates: frozenset[str]
    checked_at: float
    template_versions: dict[str, str]
    bridge_status: str = "available"
    render_manifest_version: str = ""
    pixel_qa_version: str = ""
    max_thematic_features: int = 0


class ArcGISSpatialToolModule:
    """Owns template choice, asset signatures, reuse, failures, and SVG safety."""

    _availability_ttl_sec = 20.0

    def __init__(
        self, *, client: ArcGISBridgeClient | None = None, clock=time.monotonic,
        query_snapshot_store: SpatialQuerySnapshotStore | None = None,
    ) -> None:
        self._client = client or _HttpArcGISBridgeClient()
        self._clock = clock
        self._query_snapshots = query_snapshot_store or SpatialQuerySnapshotStore()
        self._availability: _BridgeAvailability | None = None

    def is_tool_available(self, tool_id: str) -> bool:
        expected = {
            "spatial.thematic_visual": {"map.thematic.v1"},
            "report.decision_visual": {
                "chart.bar.v1", "chart.line.v1", "chart.scatter.v1", "chart.timeline.v1", "chart.relationship.v1",
            },
        }.get(str(tool_id or ""))
        return bool(expected and expected.issubset(self._available_templates()))

    def report_status(self) -> dict[str, Any]:
        """Check the authenticated Bridge and every approved report template."""

        availability = self._load_availability(force_refresh=True)
        available = availability.available_templates
        map_templates = {"map.thematic.v1"}
        chart_templates = {
            "chart.bar.v1", "chart.line.v1", "chart.scatter.v1",
            "chart.timeline.v1", "chart.relationship.v1",
        }
        bridge_reachable = availability.bridge_status in {
            "available", "unauthorized", "template_unavailable",
        }
        credentials_valid = availability.bridge_status == "available"
        missing_map = sorted(map_templates - available)
        missing_charts = sorted(chart_templates - available)
        contract_ready = (
            availability.render_manifest_version == "1.0"
            and availability.pixel_qa_version == "1.0"
            and availability.max_thematic_features == MAX_SNAPSHOT_FEATURES
        )
        ready = credentials_valid and not missing_map and not missing_charts and contract_ready
        return {
            "status": "available" if ready else availability.bridge_status,
            "ready": ready,
            "summary": "ArcGIS 报告视觉服务已就绪。" if ready else "ArcGIS 报告视觉服务尚未完全就绪。",
            "checks": {
                "service_connection": {
                    "ready": bridge_reachable,
                    "status": "reachable" if bridge_reachable else availability.bridge_status,
                },
                "credentials": {
                    "ready": credentials_valid,
                    "status": "valid" if credentials_valid else (
                        "invalid" if availability.bridge_status == "unauthorized" else "unverified"
                    ),
                },
                "thematic_map_templates": {
                    "ready": not missing_map,
                    "available": sorted(map_templates & available),
                    "missing": missing_map,
                },
                "report_chart_templates": {
                    "ready": not missing_charts,
                    "available": sorted(chart_templates & available),
                    "missing": missing_charts,
                },
                "render_quality_contract": {
                    "ready": contract_ready,
                    "render_manifest_version": availability.render_manifest_version,
                    "pixel_qa_version": availability.pixel_qa_version,
                    "max_thematic_features": availability.max_thematic_features,
                },
            },
            "limitations": [] if ready else self._status_limitations(
                availability=availability,
                missing_map=missing_map,
                missing_charts=missing_charts,
            ),
        }

    def create_report_visual_asset(
        self, *, result: Any, visual: dict[str, Any], source_index: Any,
        dependency_ids: list[str] | None = None, study_scope: dict[str, Any] | None = None,
        input_manifest: dict[str, Any] | None = None,
    ) -> Any:
        """Create or reuse one V4 asset record; never synthesize an SVG locally.

        The optional dependencies and scope are accepted only from V4 orchestration,
        not chapter authors.  They keep the public input semantic while this deep
        module owns geometry normalization and the Bridge request.
        """
        visual_type, operation, template_id, semantic_tool = self._normalize_visual(visual)
        normalized_visual = {
            "visual_type": visual_type,
            "visual_id": _text(str(visual.get("visual_id") or ""), field="visual_id", limit=120) if str(visual.get("visual_id") or "").strip() else "",
            "title": _text(visual["title"], field="report visual title", limit=240),
            "purpose": _text(visual["purpose"], field="report visual purpose", limit=500),
            "data": _normalize_report_visual_data(visual_type, visual["data"]),
            "layout_version": _identifier(str(visual.get("layout_version") or "v1"), field="layout version"),
            "source_note": _text(str(visual.get("source_note") or "来源：已归档 V4 结果或项目材料。"), field="source note", limit=300),
            "limitation_note": _text(str(visual.get("limitation_note") or "限制：仅解释已有结果，不产生新的分析结论。"), field="limitation note", limit=300),
            **{key: _text(str(visual[key]), field=key, limit=500) for key in (
                "decision_question", "what_it_shows", "how_to_read", "supports_judgment",
                "does_not_prove", "next_validation",
            ) if str(visual.get(key) or "").strip()},
        }
        if visual_type == "thematic_map":
            if input_manifest is None:
                raise ValueError("thematic maps require an immutable input manifest")
            requirements = visual.get("cartographic_requirements") or {
                "title": True,
                "legend": True,
                "orientation": True,
                "distance_reference": True,
                "geographic_context": True,
                "analysis_locator": True,
                "data_period": True,
                "limitation_note": True,
            }
            if not isinstance(requirements, dict) or not all(bool(requirements.get(key)) for key in (
                "title", "legend", "orientation", "distance_reference", "geographic_context",
                "analysis_locator", "data_period", "limitation_note",
            )):
                raise ValueError("public thematic maps require complete cartographic_requirements")
            normalized_visual["cartographic_requirements"] = {key: True for key in requirements}
            map_layout = visual.get("map_layout")
            if map_layout is not None:
                normalized_visual["map_layout"] = self._normalize_map_layout(map_layout)
        resolved_dependency_ids = sorted(set(str(item) for item in (dependency_ids or [result.result_id]) if str(item).strip()))
        resolved_scope = deepcopy(study_scope if study_scope is not None else getattr(result, "spatial_scope", {})) if isinstance(study_scope if study_scope is not None else getattr(result, "spatial_scope", {}), dict) else {}
        asset_id = self._asset_id(
            result=result, normalized_visual=normalized_visual, template_id=template_id,
            template_version=self._template_version(template_id), dependency_ids=resolved_dependency_ids, study_scope=resolved_scope,
        )
        existing = next((item for item in source_index.items if item.resource_id == asset_id), None)
        if existing is not None:
            if existing.status == "available" and asset_id not in result.asset_ids:
                result.asset_ids.append(asset_id)
            return existing

        if result.status != "available":
            return self._record_asset(
                source_index=source_index, result=result, asset_id=asset_id, visual=normalized_visual,
                dependency_ids=resolved_dependency_ids, study_scope=resolved_scope, status="unavailable",
                bridge_status="upstream_unavailable",
                summary="上游分析结果不可用，未生成报告视觉。",
                limitations=["报告视觉只能表达已归档且可用的分析结果。"],
            )
        available_templates = self._available_templates()
        if template_id not in available_templates:
            bridge_status = (self._availability.bridge_status if self._availability else "template_unavailable")
            if bridge_status not in {"unavailable", "unauthorized", "template_unavailable", "timeout", "failed"}:
                bridge_status = "template_unavailable"
            return self._record_asset(
                source_index=source_index, result=result, asset_id=asset_id, visual=normalized_visual,
                dependency_ids=resolved_dependency_ids, study_scope=resolved_scope, status="unavailable",
                bridge_status=bridge_status,
                summary="ArcGIS 报告视觉模板当前不可用。",
                limitations=["受控 ArcGIS 模板或服务未就绪；未调用本地 SVG 替代实现。"],
            )

        payload = {
            "operation": operation,
            "template_id": template_id,
            "resource_refs": resolved_dependency_ids,
            "data_view": normalized_visual["data"],
            "study_scope": resolved_scope,
            "time_scope": self._public_scope(getattr(result, "time_scope", {})),
            "visual_semantics": {
                key: normalized_visual[key]
                for key in (
                    "visual_id", "visual_type", "title", "purpose", "source_note", "limitation_note",
                    "decision_question", "what_it_shows", "how_to_read", "supports_judgment",
                    "does_not_prove", "next_validation",
                )
                if key in normalized_visual
            },
            "cartographic_requirements": normalized_visual.get("cartographic_requirements", {}),
            "map_layout": normalized_visual.get("map_layout", {}),
            "layout_version": normalized_visual["layout_version"],
        }
        if input_manifest is not None:
            payload["input_manifest"] = deepcopy(input_manifest)
        response = self._client.execute_report_operation(payload)
        status = str(response.get("status") or "failed")
        summary = str(response.get("summary") or "ArcGIS 报告视觉未完成。")
        limitations = [str(item) for item in response.get("limitations") or [] if str(item).strip()]
        if status != "available":
            public_status = status if status in {"unavailable", "unauthorized", "template_unavailable", "timeout", "failed"} else "failed"
            asset_status = "unavailable" if public_status in {"unavailable", "unauthorized", "template_unavailable", "timeout"} else "failed"
            return self._record_asset(
                source_index=source_index, result=result, asset_id=asset_id, visual=normalized_visual,
                dependency_ids=resolved_dependency_ids, study_scope=resolved_scope, status=asset_status,
                bridge_status=public_status, summary=summary, limitations=limitations or ["未生成替代图表。"],
            )
        svg = response.get("svg")
        visual_manifest = response.get("visual_manifest")
        try:
            validate_safe_svg(svg)
            if visual_type == "thematic_map":
                if input_manifest is None:
                    raise ValueError("thematic map input manifest is required")
                visual_manifest = self._validate_visual_manifest(
                    input_manifest=input_manifest,
                    visual_manifest=visual_manifest,
                )
        except ValueError:
            return self._record_asset(
                source_index=source_index, result=result, asset_id=asset_id, visual=normalized_visual,
                dependency_ids=resolved_dependency_ids, study_scope=resolved_scope, status="failed",
                bridge_status="map_quality_rejected", summary="ArcGIS 返回的专题地图未通过安全或可读性校验。",
                limitations=["地图缺少必需图层、制图要素或可读版式，未写入报告资产。"],
            )
        return self._record_asset(
            source_index=source_index, result=result, asset_id=asset_id, visual=normalized_visual,
            dependency_ids=resolved_dependency_ids, study_scope=resolved_scope, status="available",
            summary=summary, limitations=limitations, svg=svg, semantic_tool=semantic_tool,
            visual_manifest=visual_manifest if isinstance(visual_manifest, dict) else None,
        )

    @staticmethod
    def _validate_visual_manifest(
        *, input_manifest: dict[str, Any], visual_manifest: Any,
    ) -> dict[str, Any]:
        """Verify ArcGIS rendered exactly the immutable server-side inputs."""
        required = {
            "schema_version", "input_result_ids", "input_layer_manifest",
            "input_feature_count", "rendered_feature_count", "geometry_types",
            "bbox", "crs", "basemap_status", "road_context_status",
            "legend_items", "warnings", "quality_status", "pixel_quality",
        }
        if not isinstance(visual_manifest, dict) or not required.issubset(visual_manifest):
            raise ValueError("render manifest is incomplete")
        if visual_manifest.get("schema_version") != "1.0":
            raise ValueError("render manifest version mismatch")
        if sorted(visual_manifest.get("input_result_ids") or []) != sorted(input_manifest.get("input_result_ids") or []):
            raise ValueError("render manifest result ids mismatch")
        expected_total = int(input_manifest.get("input_feature_count") or 0)
        if int(visual_manifest.get("input_feature_count") or -1) != expected_total:
            raise ValueError("render manifest input count mismatch")
        if int(visual_manifest.get("rendered_feature_count") or -1) != expected_total:
            raise ValueError("ArcGIS rendered feature count mismatch")
        if str(visual_manifest.get("crs") or "").upper() != "EPSG:4326":
            raise ValueError("ArcGIS render CRS mismatch")
        if sorted(visual_manifest.get("geometry_types") or []) != sorted(input_manifest.get("geometry_types") or []):
            raise ValueError("ArcGIS render geometry types mismatch")

        expected_layer_rows = input_manifest.get("input_layer_manifest") or []
        rendered_layer_rows = visual_manifest.get("input_layer_manifest") or []
        expected_layers = {
            str(item.get("layer_id")): item
            for item in expected_layer_rows
            if isinstance(item, dict) and item.get("layer_id")
        }
        rendered_layers = {
            str(item.get("layer_id")): item
            for item in rendered_layer_rows
            if isinstance(item, dict) and item.get("layer_id")
        }
        if len(expected_layers) != len(expected_layer_rows) or len(rendered_layers) != len(rendered_layer_rows) or set(rendered_layers) != set(expected_layers):
            raise ValueError("ArcGIS render layer set mismatch")
        for layer_id, expected in expected_layers.items():
            rendered = rendered_layers[layer_id]
            expected_count = int(expected.get("normalized_feature_count") or 0)
            if bool(expected.get("required", True)) and expected_count <= 0:
                raise ValueError("required input layer is empty")
            if int(rendered.get("rendered_feature_count") or -1) != expected_count:
                raise ValueError(f"ArcGIS render layer count mismatch:{layer_id}")
            if sorted(rendered.get("geometry_types") or []) != sorted(expected.get("geometry_types") or []):
                raise ValueError(f"ArcGIS render layer geometry mismatch:{layer_id}")

        bbox = visual_manifest.get("bbox")
        locator = input_manifest.get("analysis_locator")
        if (
            not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
            or not isinstance(locator, list) or len(locator) != 2
            or not (bbox[0] <= locator[0] <= bbox[2] and bbox[1] <= locator[1] <= bbox[3])
        ):
            raise ValueError("ArcGIS map extent excludes project locator")
        road_expected = sum(
            int(item.get("normalized_feature_count") or 0)
            for item in expected_layers.values() if item.get("role") == "road_context"
        )
        if road_expected:
            if str(visual_manifest.get("road_context_status") or "") != "rendered":
                raise ValueError("ArcGIS road context was not rendered")
        elif str(visual_manifest.get("basemap_status") or "") not in {"approved", "rendered"}:
            raise ValueError("ArcGIS map lacks geographic context")
        if not isinstance(visual_manifest.get("legend_items"), list) or not visual_manifest["legend_items"]:
            raise ValueError("ArcGIS map legend is empty")
        pixel_quality = visual_manifest.get("pixel_quality")
        if not isinstance(pixel_quality, dict) or pixel_quality.get("status") != "passed":
            raise ValueError("ArcGIS map pixel QA failed")
        if visual_manifest.get("quality_status") != "passed":
            raise ValueError("ArcGIS map quality status failed")
        return {
            key: deepcopy(visual_manifest[key])
            for key in (
                "schema_version", "input_result_ids", "input_layer_manifest",
                "input_feature_count", "rendered_feature_count", "geometry_types",
                "bbox", "crs", "basemap_status", "road_context_status",
                "legend_items", "warnings", "quality_status", "pixel_quality",
            )
        }

    @staticmethod
    def _normalize_map_layout(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("thematic map layout must be an object")
        required_layers = value.get("required_layers")
        if not isinstance(required_layers, list) or not required_layers:
            raise ValueError("thematic map layout requires visible layers")
        allowed_layers = {
            "road_basemap", "road_corridor", "grid_theme", "analysis_reference",
            "study_scope", "direction_context",
        }
        layers = [str(item).strip() for item in required_layers]
        if any(item not in allowed_layers for item in layers) or len(layers) != len(set(layers)):
            raise ValueError("thematic map layout contains an unsupported layer")
        view = str(value.get("view") or "regional").strip()
        if view not in {"regional", "vicinity"}:
            raise ValueError("thematic map layout view must be regional or vicinity")
        return {
            "quality_profile": _DECISION_MAP_LAYOUT_VERSION,
            "view": view,
            "required_layers": layers,
            "analysis_locator_status": "reference_only",
            "scale_mode": "computed_from_projected_extent",
            "required_labels": ["图例", "N", "比例尺", "限制"],
        }

    def _available_templates(self) -> frozenset[str]:
        return self._load_availability().available_templates

    def _load_availability(self, *, force_refresh: bool = False) -> _BridgeAvailability:
        now = self._clock()
        if not force_refresh and self._availability and now - self._availability.checked_at < self._availability_ttl_sec:
            return self._availability
        payload = self._client.capabilities()
        templates = payload.get("templates") if isinstance(payload, dict) else []
        available = {
            str(item.get("template_id"))
            for item in templates or []
            if isinstance(item, dict) and item.get("implementation_status") == "implemented"
        }
        versions = {
            str(item.get("template_id")): str(item.get("version") or "v1")
            for item in templates or []
            if isinstance(item, dict) and item.get("implementation_status") == "implemented"
        }
        bridge_status = str(payload.get("status") or "available") if isinstance(payload, dict) else "failed"
        if bridge_status not in {"available", "unavailable", "unauthorized", "template_unavailable", "timeout", "failed"}:
            bridge_status = "failed"
        self._availability = _BridgeAvailability(
            frozenset(available), now, versions, bridge_status,
            str(payload.get("render_manifest_version") or "") if isinstance(payload, dict) else "",
            str(payload.get("pixel_qa_version") or "") if isinstance(payload, dict) else "",
            int(payload.get("max_thematic_features") or 0) if isinstance(payload, dict) else 0,
        )
        return self._availability

    @staticmethod
    def _status_limitations(
        *, availability: _BridgeAvailability, missing_map: list[str], missing_charts: list[str],
    ) -> list[str]:
        limitations: list[str] = []
        if availability.bridge_status == "unauthorized":
            limitations.append("ArcGIS Bridge 可连接，但凭据无效或权限不足。")
        elif availability.bridge_status != "available":
            limitations.append("ArcGIS Bridge 当前不可完成认证后的能力检查。")
        if missing_map:
            limitations.append("ArcGIS 专题地图模板不可用。")
        if missing_charts:
            limitations.append("ArcGIS 报告图表模板不完整。")
        if (
            availability.render_manifest_version != "1.0"
            or availability.pixel_qa_version != "1.0"
            or availability.max_thematic_features != MAX_SNAPSHOT_FEATURES
        ):
            limitations.append("ArcGIS Bridge 未声明 1.0 渲染 manifest、像素 QA 与 10,000 要素质量能力。")
        return limitations

    def _template_version(self, template_id: str) -> str:
        self._available_templates()
        return str((self._availability.template_versions if self._availability else {}).get(template_id) or "v1")

    @staticmethod
    def _normalize_visual(visual: dict[str, Any]) -> tuple[str, str, str, str]:
        if not isinstance(visual, dict):
            raise ValueError("report visual must be an object")
        visual_type = str(visual.get("visual_type") or "").strip()
        mapping = VISUAL_TEMPLATES.get(visual_type)
        if mapping is None:
            raise ValueError(f"unsupported ArcGIS report visual type: {visual_type}")
        for key in ("title", "purpose"):
            if not str(visual.get(key) or "").strip():
                raise ValueError(f"report visual {key} is required")
        operation, template_id, semantic_tool = mapping
        return visual_type, operation, template_id, semantic_tool

    @staticmethod
    def _public_scope(value: Any) -> dict[str, Any]:
        """Keep scope metadata in V4 artifacts but never publish raw geometry."""
        private = {"geometry", "coordinates", "polygon", "polygon_wgs84", "features"}
        def scrub(item: Any) -> Any:
            if isinstance(item, dict):
                return {str(key): scrub(child) for key, child in item.items() if str(key).lower() not in private}
            if isinstance(item, list):
                return [scrub(child) for child in item]
            return deepcopy(item)
        return scrub(value) if isinstance(value, dict) else {}

    @staticmethod
    def normalize_polygon_features(*, geometry: dict[str, Any], role: str, upstream_id: str, label: str, value: float | None = None) -> list[dict[str, Any]]:
        """Publicly testable deep operation: repair/split polygons before the narrow Bridge boundary."""
        if role not in {
            "study_scope", "grid_metric", "poi_point", "road_context",
            "direction_sector", "distance_band", "spatial_unit",
            "proxy_high_value_zone", "context_corridor", "context_point",
        }:
            raise ValueError("thematic role is not approved")
        return _polygon_feature_parts(geometry=geometry, role=role, upstream_id=_identifier(upstream_id, field="upstream id"), label=_text(label, field="label", limit=120), value=value)

    @staticmethod
    def _history_id(*, history_detail: dict[str, Any], source_index: Any, result_items: list[Any]) -> str:
        candidates: list[Any] = [history_detail.get("history_id")]
        for item in result_items:
            scope = getattr(item, "spatial_scope", {})
            if isinstance(scope, dict):
                candidates.append(scope.get("history_id"))
            payload = getattr(item, "payload", {})
            if isinstance(payload, dict):
                candidates.append(payload.get("spatial_scope", {}).get("history_id") if isinstance(payload.get("spatial_scope"), dict) else None)
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _dependency_matches(expected: str, source_index: Any) -> list[Any]:
        prefix = expected[:-1] if expected.endswith("*") else expected
        return [
            item for item in getattr(source_index, "items", [])
            if item.resource_type == "analysis_result" and item.resource_id.startswith(prefix)
        ]

    @staticmethod
    def _combined_time_scope(result_items: list[Any]) -> dict[str, Any]:
        """Publish the time basis for every dataset actually drawn on a map.

        A thematic map can combine results with different vintages (for example
        2024 POI, 2025 nightlight, and a saved road snapshot).  Keeping only the
        first result's ``year`` makes the map's provenance misleading, so this
        helper folds explicit public scopes and dataset source labels into a
        compact, reader-facing mapping.  It never publishes geometry or private
        provider metadata.
        """
        if not result_items:
            return {}

        def semantic_key(item: Any) -> str | None:
            haystack = " ".join([
                str(getattr(item, "title", "")),
                *[str(value) for value in getattr(item, "source_ids", []) or []],
                str(getattr(item, "tool_id", "")),
            ]).lower()
            for key, tokens in (
                ("poi", ("poi", "设施")),
                ("population", ("population", "人口")),
                ("nightlight", ("nightlight", "夜光", "亮度")),
                ("road", ("road", "路网", "syntax")),
            ):
                if any(token.lower() in haystack for token in tokens):
                    return key
            return None

        combined: dict[str, Any] = {}
        inferred: dict[str, Any] = {}
        for item in result_items:
            scope = getattr(item, "time_scope", {})
            if isinstance(scope, dict):
                for key in ("poi", "population", "nightlight", "road"):
                    if scope.get(key) not in (None, ""):
                        combined[key] = scope[key]
                if scope.get("year") not in (None, ""):
                    key = semantic_key(item)
                    if key:
                        inferred[key] = scope["year"]
                    elif len(result_items) == 1:
                        combined["year"] = scope["year"]

            for source_id in getattr(item, "source_ids", []) or []:
                source = str(source_id).lower()
                for key, prefix in (("poi", "dataset:poi-"), ("population", "dataset:population-"), ("nightlight", "dataset:nightlight-")):
                    if source.startswith(prefix):
                        value = source[len(prefix):].strip()
                        if value:
                            inferred[key] = int(value) if value.isdigit() else value
                if source == "dataset:road-network-saved":
                    inferred["road"] = "saved snapshot"

        if len(result_items) == 1 and combined:
            return ArcGISSpatialToolModule._public_scope(combined)
        combined.update(inferred)
        return ArcGISSpatialToolModule._public_scope(combined)

    @staticmethod
    def _analysis_reference_features(*, history_detail: dict[str, Any]) -> list[dict[str, Any]]:
        """Render the explicitly saved analysis reference point."""
        point = history_detail.get("analysis_reference_point")
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return []
        try:
            longitude, latitude = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return []
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            return []
        return _point_feature_parts(
            geometry={"type": "Point", "coordinates": [longitude, latitude]},
            role="context_point",
            upstream_id="project:historical-reference",
            label="分析参考点",
        )

    def create_approved_visual_asset(self, *, visual_plan: Any, source_index: Any, history_detail: dict[str, Any]) -> Any:
        """Render a thematic map exclusively from immutable geometry snapshots."""
        if getattr(visual_plan, "status", "") != "approved":
            raise ValueError("only chief-analyst-approved visual plans may create assets")
        visual_id = str(getattr(visual_plan, "visual_id", "visual"))
        purpose = str(getattr(visual_plan, "purpose", "解释已保存空间结果"))
        title = str(getattr(visual_plan, "title", "") or purpose or visual_id)
        requested_results = list(getattr(visual_plan, "required_result_ids", []) or [])
        snapshot_ids = list(getattr(visual_plan, "input_snapshot_ids", []) or [])
        result_items: list[Any] = []
        missing_results: list[str] = []
        for expected in requested_results:
            available = [item for item in self._dependency_matches(expected, source_index) if item.status == "available"]
            if not available:
                missing_results.append(expected)
            result_items.extend(available)
        input_result_ids = sorted({item.resource_id for item in result_items})
        dependency_ids = sorted(set([*input_result_ids, *snapshot_ids, *(getattr(visual_plan, "required_source_ids", []) or [])]))
        result_proxy = SimpleNamespace(
            result_id=f"result:visual:{visual_id}",
            status="available" if not missing_results else "unavailable",
            asset_ids=[], input_sources=dependency_ids, spatial_scope={},
            time_scope=self._combined_time_scope(result_items),
        )
        visual_base = {
            "visual_id": visual_id, "visual_type": "thematic_map", "title": title, "purpose": purpose,
            "decision_question": str(getattr(visual_plan, "decision_question", "")),
            "what_it_shows": str(getattr(visual_plan, "what_it_shows", "")),
            "how_to_read": str(getattr(visual_plan, "how_to_read", "")),
            "supports_judgment": str(getattr(visual_plan, "supports_judgment", "")),
            "does_not_prove": str(getattr(visual_plan, "does_not_prove", "")),
            "next_validation": str(getattr(visual_plan, "next_validation", "")),
        }
        if getattr(visual_plan, "visual_semantics", "") != "thematic_map":
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="not_approved_spatial_map", summary="该视觉不是专题地图，未生成地图资产。",
                limitations=["该能力只接受真实几何专题地图。"],
            )
        if missing_results:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="upstream_unavailable", summary="视觉依赖的已执行空间结果不可用，未生成地图。",
                limitations=[f"缺少或不可用的分析结果：{'、'.join(missing_results)}"],
            )
        if not snapshot_ids:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="geometry_snapshot_required", summary="地图缺少可追溯的几何查询快照。",
                limitations=["聚合数量或分类总数不能单独作为地图输入。"],
            )

        history_id = self._history_id(history_detail=history_detail, source_index=source_index, result_items=result_items)
        role_by_source = {
            "current:dataset:poi": ("poi_point", "设施记录点位"),
            "current:dataset:h3": ("grid_metric", "设施 H3 网格"),
            "current:dataset:poi_grid": ("grid_metric", "设施共享网格"),
            "current:dataset:population": ("grid_metric", "人口空间单元"),
            "current:dataset:nightlight": ("grid_metric", "夜间亮度空间单元"),
            "current:dataset:road_edges": ("road_context", "真实道路线段"),
            "current:dataset:road_grid": ("grid_metric", "路网共享网格"),
        }
        geometry_by_source = {
            "current:dataset:poi": {"Point"},
            "current:dataset:h3": {"Polygon"},
            "current:dataset:poi_grid": {"Polygon"},
            "current:dataset:population": {"Polygon"},
            "current:dataset:nightlight": {"Polygon"},
            "current:dataset:road_edges": {"LineString"},
            "current:dataset:road_grid": {"Polygon"},
        }
        snapshots: list[dict[str, Any]] = []
        try:
            for snapshot_id in snapshot_ids:
                snapshot = self._query_snapshots.read(history_id=history_id, snapshot_id=snapshot_id)
                if snapshot.get("source_id") not in role_by_source:
                    raise ValueError(f"unsupported_snapshot_source:{snapshot.get('source_id')}")
                if not set(snapshot.get("geometry_types") or []).issubset(geometry_by_source[str(snapshot["source_id"])]):
                    raise ValueError(f"snapshot_geometry_type_mismatch:{snapshot_id}")
                snapshots.append(snapshot)
        except (LookupError, ValueError) as exc:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="geometry_snapshot_unavailable", summary="地图引用的几何查询快照不可用。",
                limitations=[str(exc)],
            )
        thematic_count = sum(int(item.get("normalized_feature_count") or 0) for item in snapshots)
        empty_snapshots = [str(item.get("snapshot_id")) for item in snapshots if int(item.get("normalized_feature_count") or 0) <= 0]
        if empty_snapshots:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="required_layer_empty", summary="地图必需的真实数据图层为空。",
                limitations=[f"空查询快照：{'、'.join(empty_snapshots)}"],
            )
        if thematic_count > MAX_SNAPSHOT_FEATURES:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="feature_limit_exceeded", summary="地图真实数据要素超过受控上限。",
                limitations=[f"标准化专题要素总数不得超过 {MAX_SNAPSHOT_FEATURES}。"],
            )

        try:
            scope_geometry = self._study_scope_geometry(history_detail)
            scope_features = self.normalize_polygon_features(
                geometry=scope_geometry, role="study_scope", upstream_id="scope:analysis", label="分析范围",
            )
            locator_features = self._analysis_reference_features(history_detail=history_detail)
            if not locator_features:
                raise ValueError("analysis_locator_unavailable")
            if len(scope_features) + len(locator_features) > 256:
                raise ValueError("project_context_feature_limit_exceeded")
        except ValueError as exc:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="project_context_incomplete", summary="研究范围或项目定位不可用，未生成地图。",
                limitations=[str(exc)],
            )

        features: list[dict[str, Any]] = []
        layer_manifest: list[dict[str, Any]] = []
        scope_layer_id = "layer:study-scope"
        locator_layer_id = "layer:project-locator"
        for item in scope_features:
            item["layer_id"] = scope_layer_id
            features.append(item)
        for item in locator_features:
            item["layer_id"] = locator_layer_id
            features.append(item)
        scope_bbox = list(shape(scope_geometry).bounds)
        locator = list(locator_features[0]["geometry"]["coordinates"])
        layer_manifest.extend([
            {
                "layer_id": scope_layer_id, "snapshot_id": "", "source_id": "history:study_scope",
                "role": "study_scope", "required": True, "source_record_count": 1,
                "normalized_feature_count": len(scope_features), "geometry_types": ["Polygon"], "bbox": scope_bbox,
            },
            {
                "layer_id": locator_layer_id, "snapshot_id": "", "source_id": "history:analysis_locator",
                "role": "context_point", "required": True, "source_record_count": 1,
                "normalized_feature_count": 1, "geometry_types": ["Point"], "bbox": [locator[0], locator[1], locator[0], locator[1]],
            },
        ])
        for index, snapshot in enumerate(snapshots, 1):
            source_id = str(snapshot["source_id"])
            role, label = role_by_source[source_id]
            layer_id = f"layer:snapshot:{index}"
            private_features = snapshot.get("features") if isinstance(snapshot.get("features"), list) else []
            for feature in private_features:
                geometry = _normalize_geometry(feature.get("geometry"))
                feature_hash = hashlib.sha256(
                    f"{snapshot['snapshot_id']}:{feature.get('id')}".encode("utf-8")
                ).hexdigest()[:24]
                features.append({
                    "id": f"feature:{feature_hash}", "layer_id": layer_id, "label": label,
                    "role": role, "geometry": geometry,
                })
            layer_manifest.append({
                "layer_id": layer_id, "snapshot_id": snapshot["snapshot_id"], "source_id": source_id,
                "role": role, "required": True,
                "source_record_count": int(snapshot.get("record_count") or 0),
                "normalized_feature_count": int(snapshot.get("normalized_feature_count") or 0),
                "geometry_types": list(snapshot.get("geometry_types") or []),
                "bbox": list(snapshot.get("bbox") or []),
            })
        theme_roles = {item["role"] for item in layer_manifest} - {"study_scope", "context_point", "road_context"}
        if not theme_roles:
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="thematic_layer_required", summary="地图没有非空主题数据图层。",
                limitations=["道路、范围和定位不能代替主题数据图层。"],
            )
        corpus = " ".join([visual_id, title, purpose, *requested_results]).lower()
        if any(token in corpus for token in ("poi", "设施")) and not any(
            item["source_id"] in {"current:dataset:poi", "current:dataset:h3", "current:dataset:poi_grid"}
            for item in layer_manifest
        ):
            return self._record_asset(
                source_index=source_index, result=result_proxy, asset_id=f"asset:visual:{visual_id}:unavailable",
                visual=visual_base, dependency_ids=dependency_ids, status="unavailable",
                bridge_status="poi_geometry_required", summary="POI 地图缺少真实点位或网格快照。",
                limitations=["POI 分类总数不能代替带几何的查询快照。"],
            )

        geometry_types = sorted({kind for item in layer_manifest for kind in item["geometry_types"]})
        input_manifest = {
            "schema_version": "1.0", "input_result_ids": input_result_ids,
            "input_layer_manifest": layer_manifest,
            "input_feature_count": len(features), "geometry_types": geometry_types,
            "bbox": scope_bbox, "crs": "EPSG:4326", "analysis_locator": locator,
            "warnings": sorted({warning for item in snapshots for warning in item.get("warnings") or []}),
        }
        visual = {
            **visual_base, "data": {"features": features, "style": "single"}, "layout_version": "v4",
            "source_note": "来源：分析范围、分析参考点与不可变空间查询快照。",
            "limitation_note": "限制：地图表达真实空间分布，不等同于客流、消费、营收或 ROI。",
            "cartographic_requirements": {
                "title": True, "legend": True, "orientation": True, "distance_reference": True,
                "geographic_context": True, "analysis_locator": True, "data_period": True, "limitation_note": True,
            },
        }
        return self.create_report_visual_asset(
            result=result_proxy, visual=visual, source_index=source_index,
            dependency_ids=dependency_ids,
            study_scope={"scope_id": "scope:analysis", "bbox": scope_bbox, "crs": "EPSG:4326"},
            input_manifest=input_manifest,
        )

    @staticmethod
    def _study_scope_geometry(history_detail: dict[str, Any]) -> dict[str, Any]:
        candidates: list[Any] = [history_detail.get("polygon_wgs84")]
        scope = history_detail.get("scope") if isinstance(history_detail.get("scope"), dict) else {}
        candidates.extend([scope.get("polygon_wgs84"), scope.get("geometry"), scope])
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("type") in {"Polygon", "MultiPolygon", "GeometryCollection"}:
                return mapping(shape(candidate))
        raw_polygon = scope.get("polygon") or history_detail.get("polygon")
        if isinstance(raw_polygon, list) and raw_polygon:
            coord_type = str(scope.get("coord_type") or history_detail.get("coord_type") or "wgs84").lower()
            return mapping(to_wgs84_geometry(raw_polygon, coord_type))
        raise ValueError("未找到可用的 WGS84 分析范围")

    @staticmethod
    def _asset_id(*, result: Any, normalized_visual: dict[str, Any], template_id: str, template_version: str, dependency_ids: list[str] | None = None, study_scope: dict[str, Any] | None = None) -> str:
        from store.artifact_identity import content_digest
        signature = content_digest({
            "result_id": str(result.result_id),
            "input_sources": sorted(str(item) for item in getattr(result, "input_sources", []) or []),
            "dependencies": sorted(dependency_ids or [str(result.result_id)]),
            "study_scope": study_scope or {},
            "visual": normalized_visual,
            "template_id": template_id,
            "template_version": template_version,
            "layout_version": normalized_visual["layout_version"],
            "render_version": "arcgis-report-v2",
        })[7:23]
        return f"asset:{result.result_id}:{signature}"

    @staticmethod
    def _record_asset(
        *, source_index: Any, result: Any, asset_id: str, visual: dict[str, Any],
        dependency_ids: list[str] | None = None, study_scope: dict[str, Any] | None = None,
        status: str, summary: str, limitations: list[str], svg: str | None = None,
        semantic_tool: str | None = None, bridge_status: str | None = None,
        visual_manifest: dict[str, Any] | None = None,
    ) -> Any:
        from modules.spatial_action.source_index import SourceIndexItem

        visual_semantics = {
            "visual_id": visual.get("visual_id", ""),
            "visual_type": visual["visual_type"],
            "title": visual["title"],
            "purpose": visual["purpose"],
        }
        for key in ("decision_question", "what_it_shows", "how_to_read", "supports_judgment", "does_not_prove", "next_validation"):
            value = visual.get(key)
            if isinstance(value, str) and value.strip():
                visual_semantics[key] = value.strip()
        payload: dict[str, Any] = {
            "asset_category": "thematic_map" if visual["visual_type"] == "thematic_map" else "report_chart",
            "visual_id": visual.get("visual_id", ""),
            "visual_semantics": visual_semantics,
        }
        if visual["visual_type"] == "thematic_map":
            payload["cartographic_requirements"] = deepcopy(visual.get("cartographic_requirements") or {})
        if semantic_tool:
            payload["semantic_tool"] = semantic_tool
        if bridge_status:
            # This is a public operational state, never the raw bridge response.
            payload["bridge_status"] = bridge_status
        if visual_manifest is not None:
            payload["visual_manifest"] = deepcopy(visual_manifest)
        if svg is not None:
            payload.update({"filename": f"{asset_id.replace(':', '-')}.svg", "svg": svg})
        asset = SourceIndexItem(
            resource_id=asset_id,
            resource_type="asset",
            title=visual["title"],
            status=status,
            summary=summary,
            source_ids=sorted(dependency_ids or [str(result.result_id)]),
            spatial_scope=ArcGISSpatialToolModule._public_scope(study_scope if study_scope is not None else getattr(result, "spatial_scope", {})),
            time_scope=ArcGISSpatialToolModule._public_scope(getattr(result, "time_scope", {})),
            limitations=limitations,
            payload=payload,
        )
        source_index.upsert(asset)
        if status == "available" and asset_id not in result.asset_ids:
            result.asset_ids.append(asset_id)
        return asset
