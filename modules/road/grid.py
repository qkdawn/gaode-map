import math
from typing import Any, Dict, Iterable, List, Tuple

from shapely.geometry import shape
from shapely.strtree import STRtree

from .geometry import haversine_m, safe_round


_METRICS = ("choice", "integration", "connectivity", "control", "depth")


def _line_length_km(geometry: Any) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    if geometry.geom_type == "LineString":
        coords = list(geometry.coords)
        return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:])) / 1000.0
    if geometry.geom_type == "MultiLineString":
        return sum(_line_length_km(part) for part in geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return sum(_line_length_km(part) for part in geometry.geoms)
    return 0.0


def _polygon_area_km2(geometry: Any) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    centroid = geometry.centroid
    scale_x = 111.32 * math.cos(math.radians(float(centroid.y)))
    scale_y = 110.57
    area = abs(float(geometry.area)) * scale_x * scale_y
    return max(0.0, area)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _candidate_indices(tree: STRtree, line: Any, geometry_indices: Dict[int, int]) -> Iterable[int]:
    for candidate in tree.query(line):
        if not hasattr(candidate, "geom_type"):
            yield int(candidate)
            continue
        index = geometry_indices.get(id(candidate))
        if index is not None:
            yield index


def build_road_grid(road_edges: List[Dict[str, Any]], population_grid: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Aggregate immutable analysis edges onto the population/POI/nightlight grid."""
    cells: List[Dict[str, Any]] = []
    for feature in population_grid.get("features") or []:
        if not isinstance(feature, dict):
            continue
        try:
            geometry = shape(feature.get("geometry") or {})
        except (TypeError, ValueError):
            continue
        if geometry.is_empty:
            continue
        cells.append({"feature": feature, "geometry": geometry, "length_km": 0.0, "segment_count": 0, "sums": {}})

    if not cells:
        return {"type": "FeatureCollection", "features": [], "count": 0}, {"cell_count": 0, "covered_cell_count": 0, "network_length_km": 0.0, "metric_ranges": {}}

    cell_geometries = [cell["geometry"] for cell in cells]
    tree = STRtree(cell_geometries)
    geometry_indices = {id(geometry): index for index, geometry in enumerate(cell_geometries)}
    for edge in road_edges:
        try:
            line = shape(edge.get("geometry") or {})
        except (TypeError, ValueError):
            continue
        if line.is_empty:
            continue
        props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
        for index in _candidate_indices(tree, line, geometry_indices):
            cell = cells[index]
            clipped = cell["geometry"].intersection(line)
            length_km = _line_length_km(clipped)
            if length_km <= 1e-9:
                continue
            cell["length_km"] += length_km
            cell["segment_count"] += 1
            for metric in _METRICS:
                value = _finite(props.get(f"{metric}_score"))
                if value is not None:
                    weighted_sum, weight = cell["sums"].get(metric, (0.0, 0.0))
                    cell["sums"][metric] = (weighted_sum + length_km * value, weight + length_km)

    features: List[Dict[str, Any]] = []
    metric_values: Dict[str, List[float]] = {metric: [] for metric in _METRICS}
    network_length_km = 0.0
    covered_count = 0
    for cell in cells:
        source = cell["feature"]
        props = dict(source.get("properties") or {})
        length_km = float(cell["length_km"])
        area_km2 = _polygon_area_km2(cell["geometry"])
        has_data = length_km > 1e-9
        props.update({
            "grid_type": "shared_raster",
            "road_has_data": has_data,
            "road_length_km": safe_round(length_km, 6),
            "road_length_km_per_km2": safe_round(length_km / max(area_km2, 1e-9), 6) if has_data else 0.0,
            "road_segment_count": int(cell["segment_count"]),
        })
        if has_data:
            covered_count += 1
            network_length_km += length_km
        for metric in _METRICS:
            weighted = cell["sums"].get(metric)
            value = safe_round(weighted[0] / weighted[1], 8) if weighted and weighted[1] > 0 else None
            props[f"road_{metric}"] = value
            if value is not None:
                metric_values[metric].append(float(value))
        features.append({"type": "Feature", "geometry": source.get("geometry"), "properties": props})

    ranges = {
        metric: {"min": safe_round(min(values), 8), "max": safe_round(max(values), 8)}
        for metric, values in metric_values.items() if values
    }
    return (
        {"type": "FeatureCollection", "features": features, "count": len(features)},
        {"cell_count": len(features), "covered_cell_count": covered_count, "network_length_km": safe_round(network_length_km, 6), "metric_ranges": ranges},
    )
