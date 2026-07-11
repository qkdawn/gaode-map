from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from .schemas import AnalysisSnapshot


_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _position_is_valid(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and isfinite(float(item))
            for item in value[:2]
        )
    )


def _line_is_valid(value: Any, *, closed: bool = False) -> bool:
    minimum = 4 if closed else 2
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(_position_is_valid(item) for item in value)
        and (not closed or value[0][:2] == value[-1][:2])
    )


def _coordinates_are_valid(geometry_type: str, value: Any) -> bool:
    if geometry_type == "Point":
        return _position_is_valid(value)
    if geometry_type == "MultiPoint":
        return isinstance(value, list) and bool(value) and all(
            _position_is_valid(item) for item in value
        )
    if geometry_type == "LineString":
        return _line_is_valid(value)
    if geometry_type == "MultiLineString":
        return isinstance(value, list) and bool(value) and all(
            _line_is_valid(item) for item in value
        )
    if geometry_type == "Polygon":
        return isinstance(value, list) and bool(value) and all(
            _line_is_valid(item, closed=True) for item in value
        )
    if geometry_type == "MultiPolygon":
        return isinstance(value, list) and bool(value) and all(
            _coordinates_are_valid("Polygon", item) for item in value
        )
    return False


def _normalized_feature(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    geometry = value.get("geometry") if value.get("type") == "Feature" else value
    if not isinstance(geometry, dict):
        return None
    geometry_type = _text(geometry.get("type"))
    if geometry_type not in _GEOMETRY_TYPES or not _coordinates_are_valid(
        geometry_type, geometry.get("coordinates")
    ):
        return None
    return {
        "type": "Feature",
        "id": value.get("id") if value.get("type") == "Feature" else None,
        "properties": deepcopy(value.get("properties") or {})
        if value.get("type") == "Feature"
        else {},
        "geometry": {
            "type": geometry_type,
            "coordinates": deepcopy(geometry.get("coordinates")),
        },
    }


def is_valid_spatial_feature(value: Any) -> bool:
    return _normalized_feature(value) is not None


def build_spatial_object_registry(
    snapshot: AnalysisSnapshot,
) -> dict[str, dict[str, Any]]:
    """Keep only frontend-supplied, stable objects with valid authoritative geometry."""

    registry: dict[str, dict[str, Any]] = {}
    for item in snapshot.spatial_objects:
        if not isinstance(item, dict):
            continue
        object_id = _text(item.get("spatial_object_id"))
        object_type = _text(item.get("object_type"))
        source_ref = _text(item.get("source_ref"))
        source_locator = _text(item.get("source_locator"))
        feature = _normalized_feature(item.get("feature"))
        if (
            not object_id
            or object_id in registry
            or not object_type
            or not source_ref
            or not source_locator
            or feature is None
        ):
            continue
        registry[object_id] = {
            "spatial_object_id": object_id,
            "object_type": object_type,
            "title": _text(item.get("title")) or object_id,
            "source_ref": source_ref,
            "source_locator": source_locator,
            "feature": feature,
        }
    return registry


def spatial_object_catalog(
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    """Expose only selection metadata to the model; geometry remains server-owned."""

    return [
        {
            "spatial_object_id": object_id,
            "object_type": _text(item.get("object_type")),
            "title": _text(item.get("title")),
            "source_ref": _text(item.get("source_ref")),
            "source_locator": _text(item.get("source_locator")),
        }
        for object_id, item in registry.items()
    ]


def bind_spatial_matrix_to_objects(
    matrix: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve model selections against the authoritative registry and attach geometry."""

    result = deepcopy(matrix) if isinstance(matrix, dict) else {}
    decisions = result.get("space_decisions")
    if not isinstance(decisions, list):
        decisions = []
        result["space_decisions"] = decisions

    bound_count = 0
    unavailable_count = 0
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        requested = (
            decision.get("map_binding")
            if isinstance(decision.get("map_binding"), dict)
            else {}
        )
        requested_status = _text(requested.get("status"))
        requested_id = _text(requested.get("spatial_object_id"))
        authoritative = registry.get(requested_id)
        if requested_status == "bound" and authoritative is not None:
            decision["map_binding"] = {
                "status": "bound",
                **deepcopy(authoritative),
                "reason": "",
            }
            bound_count += 1
            continue

        reason = _text(requested.get("reason"))
        if requested_status == "bound" and requested_id:
            reason = "模型引用的空间对象不在本轮权威对象清单中，已拒绝地图绑定。"
        elif requested_status == "bound":
            reason = "模型声明地图绑定但未选择权威空间对象 ID，已拒绝地图绑定。"
        elif requested_status not in {"unavailable", "bound"}:
            reason = "模型未返回有效地图绑定状态，已按未绑定处理。"
        elif not reason and not registry:
            reason = "本轮输入未提供带稳定 ID 和几何的权威空间对象。"
        elif not reason:
            reason = "没有能够与该决策精确对应的权威地图对象。"
        decision["map_binding"] = {
            "status": "unavailable",
            "spatial_object_id": "",
            "object_type": "",
            "title": "",
            "source_ref": "",
            "source_locator": "",
            "feature": None,
            "reason": reason,
        }
        unavailable_count += 1

    result["map_binding_summary"] = {
        "registry_count": len(registry),
        "decision_count": len([item for item in decisions if isinstance(item, dict)]),
        "bound_count": bound_count,
        "unavailable_count": unavailable_count,
        "status": (
            "complete"
            if decisions and unavailable_count == 0
            else "partial"
            if bound_count
            else "unavailable"
        ),
    }
    return result
