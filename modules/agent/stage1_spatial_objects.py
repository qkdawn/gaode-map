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


def _registry_entry(
    value: Any,
    *,
    seen_ids: set[str],
) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(value, dict):
        return None, "空间对象不是可解析的对象记录。"
    object_id = _text(value.get("spatial_object_id"))
    object_type = _text(value.get("object_type"))
    source_ref = _text(value.get("source_ref"))
    source_locator = _text(value.get("source_locator"))
    feature = _normalized_feature(value.get("feature"))
    if not object_id:
        return None, "缺少稳定 spatial_object_id，不能作为权威地图对象。"
    if object_id in seen_ids:
        return None, f"spatial_object_id '{object_id}' 重复，已拒绝歧义对象。"
    if not object_type:
        return None, f"空间对象 '{object_id}' 缺少 object_type。"
    if not source_ref or not source_locator:
        return None, f"空间对象 '{object_id}' 缺少来源或来源定位，不能作为权威对象。"
    if feature is None:
        return None, f"空间对象 '{object_id}' 缺少有效 GeoJSON 几何。"
    return {
        "spatial_object_id": object_id,
        "object_type": object_type,
        "title": _text(value.get("title")) or object_id,
        "source_ref": source_ref,
        "source_locator": source_locator,
        "feature": feature,
    }, ""


def assess_spatial_object_registry(snapshot: AnalysisSnapshot) -> dict[str, Any]:
    """Compile the authoritative map-object catalog and expose every rejected input.

    Geometry remains server-owned.  The returned assessment is deliberately about
    catalog readiness rather than pretending that a generic project must contain a
    fixed set of buildings or courtyards.
    """

    registry: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, str | int]] = []
    seen_ids: set[str] = set()
    raw_items = list(snapshot.spatial_objects or [])
    for index, item in enumerate(raw_items):
        entry, reason = _registry_entry(item, seen_ids=seen_ids)
        if entry is None:
            diagnostics.append(
                {
                    "index": index,
                    "code": "invalid_spatial_object",
                    "message": reason,
                }
            )
            continue
        object_id = str(entry["spatial_object_id"])
        seen_ids.add(object_id)
        registry[object_id] = entry

    type_counts: dict[str, int] = {}
    geometry_counts: dict[str, int] = {}
    for entry in registry.values():
        object_type = _text(entry.get("object_type"))
        geometry_type = _text(
            ((entry.get("feature") or {}).get("geometry") or {}).get("type")
        )
        type_counts[object_type] = type_counts.get(object_type, 0) + 1
        geometry_counts[geometry_type] = geometry_counts.get(geometry_type, 0) + 1

    has_routes = any(
        _text(((entry.get("feature") or {}).get("geometry") or {}).get("type"))
        in {"LineString", "MultiLineString"}
        for entry in registry.values()
    )
    if not registry:
        status = "unavailable"
        availability_message = "未提供带稳定 ID、可定位来源和有效几何的权威空间对象；地图绑定将保持不可用。"
    elif diagnostics or not has_routes:
        status = "partial"
        gaps = []
        if diagnostics:
            gaps.append("存在被拒绝的对象记录")
        if not has_routes:
            gaps.append("尚无可用于动线绑定的线要素")
        availability_message = f"已建立部分权威对象目录；{'；'.join(gaps)}。"
    else:
        status = "ready"
        availability_message = "权威空间对象目录已就绪，可用于空间决策和动线地图绑定。"

    return {
        "status": status,
        "input_count": len(raw_items),
        "accepted_count": len(registry),
        "rejected_count": len(diagnostics),
        "object_type_counts": dict(sorted(type_counts.items())),
        "geometry_type_counts": dict(sorted(geometry_counts.items())),
        "binding_capabilities": {
            "space_decisions": bool(registry),
            "movement_routes": has_routes,
        },
        "availability_message": availability_message,
        "diagnostics": diagnostics,
        "catalog": spatial_object_catalog(registry),
        "registry": registry,
    }


def build_spatial_object_registry(
    snapshot: AnalysisSnapshot,
) -> dict[str, dict[str, Any]]:
    """Keep only frontend-supplied, stable objects with valid authoritative geometry."""

    return assess_spatial_object_registry(snapshot)["registry"]


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


def _unavailable_binding(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "spatial_object_id": "",
        "object_type": "",
        "title": "",
        "source_ref": "",
        "source_locator": "",
        "feature": None,
        "reason": reason,
    }


def _resolve_authoritative_binding(
    requested: Any,
    registry: dict[str, dict[str, Any]],
    *,
    required_geometry_types: set[str] | None = None,
    object_label: str = "空间对象",
) -> dict[str, Any]:
    """Resolve one model-selected ID without exposing geometry choices to the model."""

    selection = requested if isinstance(requested, dict) else {}
    requested_status = _text(selection.get("status"))
    requested_id = _text(selection.get("spatial_object_id"))
    authoritative = registry.get(requested_id)
    if requested_status == "bound" and authoritative is not None:
        geometry_type = _text(
            ((authoritative.get("feature") or {}).get("geometry") or {}).get("type")
        )
        if required_geometry_types and geometry_type not in required_geometry_types:
            expected = "、".join(sorted(required_geometry_types))
            return _unavailable_binding(
                f"模型引用的权威对象不是可用的{object_label}，其几何类型为 {geometry_type or '未知'}；"
                f"要求 {expected}。"
            )
        return {
            "status": "bound",
            **deepcopy(authoritative),
            "reason": "",
        }

    reason = _text(selection.get("reason"))
    if requested_status == "bound" and requested_id:
        reason = f"模型引用的{object_label}不在本轮权威对象清单中，已拒绝地图绑定。"
    elif requested_status == "bound":
        reason = f"模型声明地图绑定但未选择权威{object_label} ID，已拒绝地图绑定。"
    elif requested_status not in {"unavailable", "bound"}:
        reason = "模型未返回有效地图绑定状态，已按未绑定处理。"
    elif not reason and not registry:
        reason = "本轮输入未提供带稳定 ID 和几何的权威空间对象。"
    elif not reason:
        reason = f"没有能够精确对应的权威{object_label}。"
    return _unavailable_binding(reason)


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
        decision["map_binding"] = _resolve_authoritative_binding(
            decision.get("map_binding"), registry
        )
        if decision["map_binding"]["status"] == "bound":
            bound_count += 1
        else:
            unavailable_count += 1

    movement_routes = result.get("movement_routes")
    if not isinstance(movement_routes, list):
        movement_routes = []
        result["movement_routes"] = movement_routes
    movement_bound_count = 0
    movement_unavailable_count = 0
    for route in movement_routes:
        if not isinstance(route, dict):
            continue
        route["map_binding"] = _resolve_authoritative_binding(
            route.get("map_binding"),
            registry,
            required_geometry_types={"LineString", "MultiLineString"},
            object_label="路径对象",
        )
        if route["map_binding"]["status"] == "bound":
            movement_bound_count += 1
        else:
            movement_unavailable_count += 1

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
    result["movement_binding_summary"] = {
        "registry_count": len(registry),
        "route_count": len(
            [item for item in movement_routes if isinstance(item, dict)]
        ),
        "bound_count": movement_bound_count,
        "unavailable_count": movement_unavailable_count,
        "status": (
            "complete"
            if movement_routes and movement_unavailable_count == 0
            else "partial"
            if movement_bound_count
            else "unavailable"
        ),
    }
    return result
