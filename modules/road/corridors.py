from __future__ import annotations

import hashlib
import math
from collections import defaultdict, deque
from typing import Any, Iterable

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from .geometry import safe_round


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _endpoint_key(coordinate: Iterable[Any]) -> str:
    values = list(coordinate)
    return f"xy:{float(values[0]):.7f},{float(values[1]):.7f}"


def _edge_nodes(feature: dict[str, Any]) -> tuple[str, str] | None:
    properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    left = str(properties.get("from_node") or "").strip()
    right = str(properties.get("to_node") or "").strip()
    if left and right:
        return left, right
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coordinates = geometry.get("coordinates") if geometry.get("type") == "LineString" else None
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    return _endpoint_key(coordinates[0]), _endpoint_key(coordinates[-1])


def _connected_components(features: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    nodes_by_index: dict[int, tuple[str, str]] = {}
    indices_by_node: dict[str, list[int]] = defaultdict(list)
    for index, feature in enumerate(features):
        nodes = _edge_nodes(feature)
        if nodes is None:
            continue
        nodes_by_index[index] = nodes
        for node in set(nodes):
            indices_by_node[node].append(index)

    remaining = set(nodes_by_index)
    components: list[list[dict[str, Any]]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        component_indices: list[int] = []
        while queue:
            index = queue.popleft()
            component_indices.append(index)
            for node in nodes_by_index[index]:
                for neighbor in indices_by_node[node]:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
        components.append([features[index] for index in sorted(component_indices)])
    return components


def build_road_corridors(
    road_edges: list[dict[str, Any]],
    *,
    quantile: float = 0.75,
    minimum_edge_count: int = 2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build persisted, topologically continuous NAIN/NACH corridor records."""

    profiles: set[tuple[str, str]] = set()
    for feature in road_edges:
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        for key in properties:
            if key in {"nain_global", "nach_global"}:
                profiles.add((key.split("_", 1)[0], "global"))
            elif key.startswith("nain_r") or key.startswith("nach_r"):
                metric, radius = key.split("_", 1)
                if radius[1:].isdigit():
                    profiles.add((metric, radius))

    corridors: list[dict[str, Any]] = []
    thresholds: dict[str, float] = {}
    for metric, radius in sorted(profiles, key=lambda item: (item[0], item[1] != "global", item[1])):
        field = f"{metric}_{radius}"
        valued = [
            (feature, value)
            for feature in road_edges
            if (value := _finite((feature.get("properties") or {}).get(field))) is not None
        ]
        threshold = _quantile([value for _, value in valued], quantile)
        if threshold is None:
            continue
        thresholds[field] = safe_round(threshold, 8)
        selected = [feature for feature, value in valued if value >= threshold]
        for component in _connected_components(selected):
            if len(component) < max(1, int(minimum_edge_count)):
                continue
            properties_list = [feature.get("properties") or {} for feature in component]
            edge_ids = sorted(str(props.get("edge_id") or props.get("record_id") or "") for props in properties_list)
            edge_ids = [value for value in edge_ids if value]
            values = [_finite(props.get(field)) for props in properties_list]
            finite_values = [value for value in values if value is not None]
            geometries = []
            for feature in component:
                try:
                    geometry = shape(feature.get("geometry") or {})
                except (TypeError, ValueError):
                    continue
                if not geometry.is_empty:
                    geometries.append(geometry)
            if not geometries:
                continue
            digest = hashlib.sha256(f"{field}:{','.join(edge_ids)}".encode("utf-8")).hexdigest()[:20]
            corridor_id = f"corridor:{digest}"
            names = sorted({str(props.get("road_name") or "").strip() for props in properties_list} - {""})
            length_m = sum(_finite(props.get("length_m")) or 0.0 for props in properties_list)
            corridor_properties = {
                "corridor_id": corridor_id,
                "record_id": corridor_id,
                "metric": metric,
                "metric_field": field,
                "radius": radius.removeprefix("r") if radius != "global" else "global",
                "threshold": safe_round(threshold, 8),
                "mean_value": safe_round(sum(finite_values) / len(finite_values), 8),
                "max_value": safe_round(max(finite_values), 8),
                "edge_count": len(component),
                "length_m": safe_round(length_m, 2),
                "road_names": names[:20],
                "member_edge_ids": edge_ids,
                field: safe_round(sum(finite_values) / len(finite_values), 8),
            }
            corridors.append({
                "type": "Feature",
                "geometry": mapping(unary_union(geometries)),
                "properties": corridor_properties,
            })

    corridors.sort(key=lambda feature: (
        str((feature.get("properties") or {}).get("metric") or ""),
        str((feature.get("properties") or {}).get("radius") or ""),
        -float((feature.get("properties") or {}).get("mean_value") or 0.0),
        str((feature.get("properties") or {}).get("corridor_id") or ""),
    ))
    collection = {"type": "FeatureCollection", "features": corridors, "count": len(corridors)}
    summary = {
        "corridor_count": len(corridors),
        "threshold_quantile": quantile,
        "minimum_edge_count": max(1, int(minimum_edge_count)),
        "thresholds": thresholds,
    }
    return collection, summary
