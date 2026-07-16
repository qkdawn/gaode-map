from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .schemas import (
    DestinationAnchor,
    EntranceAnchor,
    EntranceRelationResult,
    LocalizedPatternCell,
    LocalizedPatternInputCell,
    LocalizedPatternResult,
    LocalizedPatternZone,
    PathRelationResult,
    RoadSegmentRef,
)
from .valhalla import ValhallaRouteAdapter

_EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class _MetricProjection:
    lon0: float
    lat0: float

    @classmethod
    def around(cls, geometry: BaseGeometry) -> "_MetricProjection":
        centroid = geometry.centroid
        return cls(math.radians(float(centroid.x)), math.radians(float(centroid.y)))

    def forward(self, geometry: BaseGeometry) -> BaseGeometry:
        scale_x = _EARTH_RADIUS_M * math.cos(self.lat0)

        def project(x, y, z=None):
            try:
                return (
                    tuple((math.radians(float(v)) - self.lon0) * scale_x for v in x),
                    tuple((math.radians(float(v)) - self.lat0) * _EARTH_RADIUS_M for v in y),
                )
            except TypeError:
                return (
                    (math.radians(float(x)) - self.lon0) * scale_x,
                    (math.radians(float(y)) - self.lat0) * _EARTH_RADIUS_M,
                )

        return transform(project, geometry)


def _point_geometry(value: dict[str, Any], *, label: str) -> Point:
    geom = shape(value)
    if not isinstance(geom, Point) or geom.is_empty:
        raise ValueError(f"{label} geometry must be a non-empty Point")
    return geom


def _line_geometry(value: dict[str, Any], *, label: str) -> LineString:
    geom = shape(value)
    if not isinstance(geom, LineString) or geom.is_empty:
        raise ValueError(f"{label} geometry must be a non-empty LineString")
    return geom


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _bh_adjust(raw: list[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(raw, key=lambda item: item[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        cell_id, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * count / rank)
        adjusted[cell_id] = min(1.0, running)
    return adjusted


def _adjacency(cells: list[LocalizedPatternInputCell]) -> dict[str, set[str]]:
    ids = {cell.cell_id for cell in cells}
    adjacency = {cell.cell_id: set(cell.neighbor_ids).intersection(ids) for cell in cells}
    geoms = {cell.cell_id: shape(cell.geometry) for cell in cells}
    for index, left in enumerate(cells):
        for right in cells[index + 1 :]:
            if right.cell_id in adjacency[left.cell_id] or left.cell_id in adjacency[right.cell_id]:
                adjacency[left.cell_id].add(right.cell_id)
                adjacency[right.cell_id].add(left.cell_id)
                continue
            left_geom = geoms[left.cell_id]
            right_geom = geoms[right.cell_id]
            if left_geom.touches(right_geom) or left_geom.intersects(right_geom):
                adjacency[left.cell_id].add(right.cell_id)
                adjacency[right.cell_id].add(left.cell_id)
    return adjacency


def _components(selected: dict[str, str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    remaining = set(selected)
    groups: list[list[str]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        pattern_type = selected[seed]
        queue = deque([seed])
        group = [seed]
        while queue:
            current = queue.popleft()
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in remaining and selected.get(neighbor) == pattern_type:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
                    group.append(neighbor)
        groups.append(sorted(group))
    return groups


def _extract_points(geometry: BaseGeometry) -> list[Point]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if geometry.geom_type == "MultiPoint":
        return list(geometry.geoms)
    if geometry.geom_type in {"LineString", "LinearRing"}:
        coords = list(geometry.coords)
        return [Point(coords[0]), Point(coords[-1])] if coords else []
    if hasattr(geometry, "geoms"):
        points: list[Point] = []
        for part in geometry.geoms:
            points.extend(_extract_points(part))
        return points
    return []


class SpatialActionService:
    """Decision-facing spatial actions; backend details stay behind three high-level methods."""

    def __init__(self, *, route_adapter: ValhallaRouteAdapter | None = None) -> None:
        self._route_adapter = route_adapter or ValhallaRouteAdapter()

    def analyze_local_patterns(
        self,
        cells: Iterable[LocalizedPatternInputCell | dict[str, Any]],
        *,
        alpha: float = 0.05,
    ) -> LocalizedPatternResult:
        normalized = [
            item if isinstance(item, LocalizedPatternInputCell) else LocalizedPatternInputCell.model_validate(item)
            for item in cells
        ]
        if not normalized:
            return LocalizedPatternResult(
                evidence_state="proxy",
                pattern_label="无局部模式",
                cells=[],
                zones=[],
                diagnostics=["no_cells"],
            )
        adjacency = _adjacency(normalized)
        raw_p = [(cell.cell_id, cell.p_value) for cell in normalized if cell.p_value is not None]
        has_significance = bool(raw_p)
        adjusted = _bh_adjust([(cell_id, float(p)) for cell_id, p in raw_p]) if raw_p else {}
        selected: dict[str, str] = {}
        diagnostics: list[str] = []
        if has_significance:
            if len(raw_p) != len(normalized):
                diagnostics.append("cells_without_p_value_excluded_from_significance")
            for cell in normalized:
                adjusted_p = cell.adjusted_p_value
                if adjusted_p is None:
                    adjusted_p = adjusted.get(cell.cell_id)
                if adjusted_p is None or adjusted_p > alpha:
                    continue
                cluster = cell.cluster_type.strip().lower()
                if not cluster:
                    cluster = "hotspot" if (cell.z_score or cell.statistic or 0.0) >= 0 else "coldspot"
                selected[cell.cell_id] = cluster
            evidence_state = "measured"
            pattern_label = "统计显著局部模式"
            significance_method = f"benjamini_hochberg_fdr_alpha_{alpha:g}"
        else:
            high_threshold = _percentile([cell.value for cell in normalized], 0.75)
            for cell in normalized:
                if high_threshold is not None and cell.value >= high_threshold:
                    selected[cell.cell_id] = "high_value_concentration"
            evidence_state = "proxy"
            pattern_label = "高值集中区"
            significance_method = "descriptive_upper_quartile_no_significance"
            diagnostics.append("p_values_missing_not_statistical_hotspot")

        by_id = {cell.cell_id: cell for cell in normalized}
        output_cells: list[LocalizedPatternCell] = []
        zones: list[LocalizedPatternZone] = []
        for zone_index, cell_ids in enumerate(_components(selected, adjacency), start=1):
            original_pattern = selected[cell_ids[0]]
            pattern_type = (
                original_pattern
                if len(cell_ids) > 1
                else ("local_outlier" if has_significance else "isolated_high_value")
            )
            zone_id = f"zone:{zone_index:03d}"
            zone_geometry = unary_union([shape(by_id[cell_id].geometry) for cell_id in cell_ids])
            zones.append(
                LocalizedPatternZone(
                    zone_id=zone_id,
                    pattern_type=pattern_type,
                    cell_ids=cell_ids,
                    geometry=mapping(zone_geometry),
                    source_metric_ids=sorted({by_id[cell_id].metric_id for cell_id in cell_ids}),
                    significance_method=significance_method,
                )
            )
            for cell_id in cell_ids:
                cell = by_id[cell_id]
                output_cells.append(
                    LocalizedPatternCell(
                        cell_id=cell.cell_id,
                        metric_id=cell.metric_id,
                        value=cell.value,
                        statistic=cell.statistic,
                        z_score=cell.z_score,
                        p_value=cell.p_value,
                        adjusted_p_value=cell.adjusted_p_value if cell.adjusted_p_value is not None else adjusted.get(cell.cell_id),
                        cluster_type=selected[cell_id],
                        zone_id=zone_id,
                    )
                )
        return LocalizedPatternResult(
            evidence_state=evidence_state,
            pattern_label=pattern_label,
            cells=sorted(output_cells, key=lambda item: item.cell_id),
            zones=zones,
            diagnostics=diagnostics,
        )

    def analyze_entrance_relations(
        self,
        *,
        entrances: Iterable[EntranceAnchor | dict[str, Any]],
        road_segments: Iterable[RoadSegmentRef | dict[str, Any]],
        project_boundary: dict[str, Any] | None = None,
        hotspot_zones: Iterable[LocalizedPatternZone | dict[str, Any]] = (),
        catchments: Iterable[dict[str, Any]] = (),
        demand_features: Iterable[dict[str, Any]] = (),
        directional_exposure: dict[str, dict[str, float]] | None = None,
        target_road_segment_ids: Iterable[str] = (),
        nearby_radius_m: float = 250.0,
        dedupe_tolerance_m: float = 8.0,
    ) -> list[EntranceRelationResult]:
        roads = [item if isinstance(item, RoadSegmentRef) else RoadSegmentRef.model_validate(item) for item in road_segments]
        anchors = [item if isinstance(item, EntranceAnchor) else EntranceAnchor.model_validate(item) for item in entrances]
        if not anchors:
            if project_boundary is None:
                return []
            anchors = self._infer_entrances(project_boundary, roads, dedupe_tolerance_m=dedupe_tolerance_m)
        zones = [item if isinstance(item, LocalizedPatternZone) else LocalizedPatternZone.model_validate(item) for item in hotspot_zones]
        catchment_items = list(catchments)
        demand_items = list(demand_features)
        direction_by_id = directional_exposure or {}
        target_segment_ids = list(dict.fromkeys(str(item) for item in target_road_segment_ids))
        road_geometries = [(road, _line_geometry(road.geometry, label=road.segment_id)) for road in roads if road.walkable]
        results: list[EntranceRelationResult] = []
        for anchor in anchors:
            point = _point_geometry(anchor.geometry, label=anchor.entrance_id)
            projection = _MetricProjection.around(point.buffer(0.001))
            projected_point = projection.forward(point)
            nearest: tuple[RoadSegmentRef, float] | None = None
            for road, line in road_geometries:
                distance = projected_point.distance(projection.forward(line))
                if nearest is None or distance < nearest[1]:
                    nearest = (road, float(distance))
            nearby_zone_ids = []
            metric_buffer = projected_point.buffer(float(nearby_radius_m))
            for zone in zones:
                if metric_buffer.intersects(projection.forward(shape(zone.geometry))):
                    nearby_zone_ids.append(zone.zone_id)
            catchment_ids = []
            for item in catchment_items:
                geometry = shape(item.get("geometry") or {})
                if not geometry.is_empty and (geometry.contains(point) or geometry.touches(point)):
                    catchment_ids.append(str(item.get("catchment_id") or item.get("id") or ""))
            exposure: defaultdict[str, float] = defaultdict(float)
            for feature in demand_items:
                geom = shape(feature.get("geometry") or {})
                if geom.is_empty or not metric_buffer.intersects(projection.forward(geom)):
                    continue
                for metric_id, value in (feature.get("metrics") or {}).items():
                    try:
                        exposure[str(metric_id)] += float(value)
                    except (TypeError, ValueError):
                        continue
            diagnostics: list[str] = []
            target_distances: dict[str, float] = {}
            if nearest is None:
                diagnostics.append("no_walkable_road_segment")
            elif target_segment_ids:
                target_distances = self._network_distances_from_segment(
                    source_segment_id=nearest[0].segment_id,
                    source_point=projected_point,
                    target_segment_ids=target_segment_ids,
                    road_geometries=road_geometries,
                    projection=projection,
                )
                missing_targets = sorted(set(target_segment_ids) - set(target_distances))
                diagnostics.extend(f"target_road_unreachable:{item}" for item in missing_targets)
            evidence_state = "experimental_assumption" if anchor.source_type == "inferred_candidate" else "measured"
            results.append(
                EntranceRelationResult(
                    entrance_id=anchor.entrance_id,
                    geometry=anchor.geometry,
                    source_type=anchor.source_type,
                    evidence_state=evidence_state,
                    snapped_road_segment_id=nearest[0].segment_id if nearest else "",
                    snap_distance_m=round(nearest[1], 3) if nearest else None,
                    target_road_distances_m=target_distances,
                    catchment_ids=sorted(filter(None, catchment_ids)),
                    nearby_hotspot_zone_ids=sorted(nearby_zone_ids),
                    local_integration=nearest[0].integration if nearest else None,
                    local_choice=nearest[0].choice if nearest else None,
                    demand_exposure_metrics=dict(sorted(exposure.items())),
                    directional_exposure=dict(direction_by_id.get(anchor.entrance_id) or {}),
                    diagnostics=diagnostics,
                )
            )
        return results

    def _network_distances_from_segment(
        self,
        *,
        source_segment_id: str,
        source_point: Point,
        target_segment_ids: list[str],
        road_geometries: list[tuple[RoadSegmentRef, LineString]],
        projection: _MetricProjection,
    ) -> dict[str, float]:
        projected = {road.segment_id: projection.forward(line) for road, line in road_geometries}
        if source_segment_id not in projected:
            return {}
        node_for: dict[tuple[float, float], str] = {}
        graph: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)
        segment_nodes: dict[str, tuple[str, str, float]] = {}
        for segment_id, line in projected.items():
            coords = list(line.coords)
            if len(coords) < 2:
                continue
            keys = []
            for coordinate in (coords[0], coords[-1]):
                key = (round(float(coordinate[0]), 2), round(float(coordinate[1]), 2))
                keys.append(node_for.setdefault(key, f"node:{len(node_for) + 1}"))
            length = float(line.length)
            segment_nodes[segment_id] = (keys[0], keys[1], length)
            graph[keys[0]].append((keys[1], length))
            graph[keys[1]].append((keys[0], length))
        source = segment_nodes.get(source_segment_id)
        if source is None:
            return {}
        source_line = projected[source_segment_id]
        source_position = float(source_line.project(source_point))
        distances: dict[str, float] = {
            source[0]: source_position,
            source[1]: max(0.0, source[2] - source_position),
        }
        queue = [(distance, node) for node, distance in distances.items()]
        heapq.heapify(queue)
        while queue:
            distance, node = heapq.heappop(queue)
            if distance > distances.get(node, math.inf):
                continue
            for neighbor, weight in graph.get(node, []):
                candidate = distance + weight
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))
        result: dict[str, float] = {}
        for target_id in target_segment_ids:
            if target_id == source_segment_id:
                result[target_id] = 0.0
                continue
            target = segment_nodes.get(target_id)
            if target is None:
                continue
            best = min(distances.get(target[0], math.inf), distances.get(target[1], math.inf))
            if math.isfinite(best):
                result[target_id] = round(float(best), 3)
        return result

    def _infer_entrances(
        self,
        project_boundary: dict[str, Any],
        roads: list[RoadSegmentRef],
        *,
        dedupe_tolerance_m: float,
    ) -> list[EntranceAnchor]:
        boundary = shape(project_boundary)
        if not isinstance(boundary, Polygon) or boundary.is_empty:
            raise ValueError("project_boundary must be a non-empty Polygon")
        candidates: list[Point] = []
        for road in roads:
            if not road.walkable:
                continue
            intersection = boundary.boundary.intersection(_line_geometry(road.geometry, label=road.segment_id))
            candidates.extend(_extract_points(intersection))
        projection = _MetricProjection.around(boundary)
        kept: list[Point] = []
        projected_kept: list[Point] = []
        for point in sorted(candidates, key=lambda item: (item.x, item.y)):
            projected = projection.forward(point)
            if any(projected.distance(existing) <= dedupe_tolerance_m for existing in projected_kept):
                continue
            kept.append(point)
            projected_kept.append(projected)
        return [
            EntranceAnchor(
                entrance_id=f"entrance:candidate:{index:03d}",
                geometry=mapping(point),
                label=f"推断入口候选 {index}",
                source_type="inferred_candidate",
                source_ref="boundary_walkable_road_intersection",
            )
            for index, point in enumerate(kept, start=1)
        ]

    def analyze_path_relations(
        self,
        *,
        entrances: Iterable[EntranceAnchor | dict[str, Any]],
        destinations: Iterable[DestinationAnchor | dict[str, Any]],
        pairs: Iterable[tuple[str, str]],
        road_segments: Iterable[RoadSegmentRef | dict[str, Any]] | None = None,
        match_tolerance_m: float = 12.0,
    ) -> list[PathRelationResult]:
        entrance_by_id = {
            item.entrance_id: item
            for raw in entrances
            for item in [raw if isinstance(raw, EntranceAnchor) else EntranceAnchor.model_validate(raw)]
        }
        destination_by_id = {
            item.destination_id: item
            for raw in destinations
            for item in [raw if isinstance(raw, DestinationAnchor) else DestinationAnchor.model_validate(raw)]
        }
        roads = None if road_segments is None else [
            item if isinstance(item, RoadSegmentRef) else RoadSegmentRef.model_validate(item)
            for item in road_segments
        ]
        results: list[PathRelationResult] = []
        for entrance_id, destination_id in pairs:
            if entrance_id not in entrance_by_id or destination_id not in destination_by_id:
                raise ValueError(f"unknown entrance-destination pair: {entrance_id}/{destination_id}")
            entrance = entrance_by_id[entrance_id]
            destination = destination_by_id[destination_id]
            origin_point = _point_geometry(entrance.geometry, label=entrance_id)
            destination_point = _point_geometry(destination.geometry, label=destination_id)
            route = self._route_adapter.route(
                (float(origin_point.x), float(origin_point.y)),
                (float(destination_point.x), float(destination_point.y)),
            )
            route_line = _line_geometry(route.geometry, label="valhalla_route")
            projection = _MetricProjection.around(route_line)
            projected_route = projection.forward(route_line)
            straight_distance = projection.forward(origin_point).distance(projection.forward(destination_point))
            detour_ratio = route.distance_m / straight_distance if straight_distance > 0 else None
            matched_ids: list[str] = []
            low_access_ids: list[str] = []
            high_choice_ratio: float | None = None
            high_integration_ratio: float | None = None
            barriers: list[dict[str, Any]] = []
            diagnostics: list[str] = []
            if roads is None:
                diagnostics.append("depthmapx_syntax_unavailable")
            else:
                projected_roads = [(road, projection.forward(_line_geometry(road.geometry, label=road.segment_id))) for road in roads]
                overlaps: dict[str, float] = {}
                for road, line in projected_roads:
                    overlap = projected_route.intersection(line.buffer(match_tolerance_m)).length
                    if overlap > 0:
                        matched_ids.append(road.segment_id)
                        overlaps[road.segment_id] = float(overlap)
                by_id = {road.segment_id: road for road in roads}
                choice_threshold = _percentile([road.choice for road in roads if road.choice is not None], 0.75)
                integration_threshold = _percentile([road.integration for road in roads if road.integration is not None], 0.75)
                choice_low = _percentile([road.choice for road in roads if road.choice is not None], 0.25)
                integration_low = _percentile([road.integration for road in roads if road.integration is not None], 0.25)
                denominator = max(float(projected_route.length), 1e-9)

                def route_overlap_ratio(segment_ids: list[str]) -> float:
                    selected_buffers = [
                        line.buffer(match_tolerance_m)
                        for road, line in projected_roads
                        if road.segment_id in segment_ids
                    ]
                    if not selected_buffers:
                        return 0.0
                    covered = projected_route.intersection(unary_union(selected_buffers)).length
                    return min(1.0, float(covered) / denominator)

                if choice_threshold is not None:
                    high_choice_ratio = route_overlap_ratio([
                        segment_id
                        for segment_id in matched_ids
                        if by_id[segment_id].choice is not None
                        and by_id[segment_id].choice >= choice_threshold
                    ])
                else:
                    diagnostics.append("choice_metric_blocked")
                if integration_threshold is not None:
                    high_integration_ratio = route_overlap_ratio([
                        segment_id
                        for segment_id in matched_ids
                        if by_id[segment_id].integration is not None
                        and by_id[segment_id].integration >= integration_threshold
                    ])
                else:
                    diagnostics.append("integration_metric_blocked")
                for segment_id in matched_ids:
                    road = by_id[segment_id]
                    low_choice = choice_low is not None and road.choice is not None and road.choice <= choice_low
                    low_integration = integration_low is not None and road.integration is not None and road.integration <= integration_low
                    if low_choice and low_integration:
                        low_access_ids.append(segment_id)
                matched_union = unary_union([line.buffer(match_tolerance_m) for road, line in projected_roads if road.segment_id in overlaps]) if overlaps else None
                coords = list(route_line.coords)
                for start, end in zip(coords, coords[1:]):
                    original_part = LineString([start, end])
                    projected_part = projection.forward(original_part)
                    if matched_union is None or not projected_part.intersects(matched_union):
                        midpoint = original_part.interpolate(0.5, normalized=True)
                        barriers.append(mapping(midpoint))
                if not matched_ids:
                    diagnostics.append("route_not_matched_to_depthmapx_segments")
            results.append(
                PathRelationResult(
                    route_id=f"route:{entrance_id}:{destination_id}",
                    entrance_id=entrance_id,
                    destination_id=destination_id,
                    geometry=route.geometry,
                    road_segment_ids=sorted(set(matched_ids)),
                    network_distance_m=round(route.distance_m, 3),
                    duration_s=round(route.duration_s, 3),
                    straight_line_distance_m=round(float(straight_distance), 3),
                    detour_ratio=round(detour_ratio, 6) if detour_ratio is not None else None,
                    high_choice_overlap_ratio=round(high_choice_ratio, 6) if high_choice_ratio is not None else None,
                    high_integration_overlap_ratio=round(high_integration_ratio, 6) if high_integration_ratio is not None else None,
                    low_access_segment_ids=sorted(set(low_access_ids)),
                    barrier_or_break_points=barriers,
                    diagnostics=diagnostics,
                )
            )
        return results
