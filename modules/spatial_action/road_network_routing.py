"""Local shortest-path routing over a saved road-edge snapshot.

The module deliberately never requests a third-party route service.  It nodes the
actual road LineStrings, snaps supplied WGS84 points to that network, and returns
only paths assembled from those road segments.  A missing or disconnected network
is a domain failure: callers must omit the route rather than draw a straight line.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import heapq
from math import cos, radians
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, box, mapping, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

Coordinate = tuple[float, float]
_EARTH_RADIUS_M = 6_371_008.8
# Small report maps should retain a complete local road backdrop.  This is high
# enough for the current project-sized route extent (1,194 clipped edges) while
# still protecting SVG/PDF exports from unbounded network snapshots.
_REPORT_ROUTE_MAP_MAX_ROAD_EDGES = 1_600


class RoadNetworkRoutingUnavailable(RuntimeError):
    """No auditable path can be produced from the saved road snapshot."""


@dataclass(frozen=True)
class RoadNetworkRoute:
    """A route whose geometry is entirely composed of saved road segments."""

    geometry: dict[str, Any]
    distance_m: float
    origin_snap: Coordinate
    destination_snap: Coordinate
    origin_snap_distance_m: float
    destination_snap_distance_m: float
    algorithm: str = "local_road_network_shortest_path"


@dataclass(frozen=True)
class _RoadEdge:
    edge_id: int
    line: LineString
    start: str
    end: str
    length_m: float


@dataclass(frozen=True)
class _Arc:
    target: str
    length_m: float
    line: LineString


@dataclass(frozen=True)
class _Snap:
    edge: _RoadEdge
    position_m: float
    point: Point
    distance_m: float


class LocalRoadNetworkRouter:
    """Route over a real WGS84 road snapshot using an in-memory Dijkstra graph.

    The graph is built once.  Each route only adds two temporary nodes at the
    nearest road positions, so it remains deterministic and never invents an
    off-network connector.  Coordinates are projected into a local metre plane
    only for topology, distance and routing; emitted geometry is WGS84.
    """

    def __init__(
        self,
        road_geometries: Iterable[LineString | MultiLineString | Mapping[str, Any]],
        *,
        max_snap_distance_m: float = 120.0,
        node_tolerance_m: float = 0.25,
    ) -> None:
        source_lines = [line for value in road_geometries for line in _lines(value)]
        if not source_lines:
            raise RoadNetworkRoutingUnavailable("road_snapshot_has_no_lines")
        self._projection = _LocalMetricProjection.from_lines(source_lines)
        projected = [self._projection.forward(line) for line in source_lines]
        noded = unary_union(projected)
        lines = [line for line in _lines(noded) if line.length > 0.01]
        if not lines:
            raise RoadNetworkRoutingUnavailable("road_snapshot_has_no_routable_lines")
        self._max_snap_distance_m = max(1.0, float(max_snap_distance_m))
        self._node_tolerance_m = max(0.01, float(node_tolerance_m))
        self._edges: list[_RoadEdge] = []
        self._graph: dict[str, list[_Arc]] = defaultdict(list)
        self._node_coordinates: dict[str, Coordinate] = {}
        for line in lines:
            start = self._node_id(tuple(line.coords[0]))
            end = self._node_id(tuple(line.coords[-1]))
            if start == end:
                continue
            edge = _RoadEdge(len(self._edges), line, start, end, float(line.length))
            self._edges.append(edge)
            self._graph[start].append(_Arc(end, edge.length_m, line))
            self._graph[end].append(_Arc(start, edge.length_m, _reverse_line(line)))
        if not self._edges:
            raise RoadNetworkRoutingUnavailable("road_snapshot_has_no_routable_edges")
        self._tree = STRtree([edge.line for edge in self._edges])

    @property
    def road_edge_count(self) -> int:
        return len(self._edges)

    def route(self, origin: Coordinate, destination: Coordinate) -> RoadNetworkRoute:
        origin_point = self._projection.forward(Point(_coordinate(origin)))
        destination_point = self._projection.forward(Point(_coordinate(destination)))
        origin_snap = self._snap(origin_point)
        destination_snap = self._snap(destination_point)
        if origin_snap.distance_m > self._max_snap_distance_m:
            raise RoadNetworkRoutingUnavailable("origin_too_far_from_saved_road_network")
        if destination_snap.distance_m > self._max_snap_distance_m:
            raise RoadNetworkRoutingUnavailable("destination_too_far_from_saved_road_network")

        graph = {node: list(arcs) for node, arcs in self._graph.items()}
        origin_node = self._attach(graph, origin_snap, "origin")
        destination_node = self._attach(graph, destination_snap, "destination")
        if origin_snap.edge.edge_id == destination_snap.edge.edge_id and origin_node != destination_node:
            direct = _subline(origin_snap.edge.line, origin_snap.position_m, destination_snap.position_m)
            if direct.length > 0.001:
                _add_bidirectional(graph, origin_node, destination_node, direct)

        distance_m, arcs = _dijkstra(graph, origin_node, destination_node)
        if distance_m is None or not arcs:
            raise RoadNetworkRoutingUnavailable("saved_road_network_has_no_connected_path")
        route_line = _merge_arcs(arcs)
        if route_line is None or route_line.length <= 0:
            raise RoadNetworkRoutingUnavailable("saved_road_network_path_geometry_invalid")
        wgs_line = self._projection.inverse(route_line)
        origin_wgs = self._projection.inverse(origin_snap.point)
        destination_wgs = self._projection.inverse(destination_snap.point)
        return RoadNetworkRoute(
            geometry=mapping(wgs_line),
            distance_m=round(float(distance_m), 3),
            origin_snap=(float(origin_wgs.x), float(origin_wgs.y)),
            destination_snap=(float(destination_wgs.x), float(destination_wgs.y)),
            origin_snap_distance_m=round(float(origin_snap.distance_m), 3),
            destination_snap_distance_m=round(float(destination_snap.distance_m), 3),
        )

    def reachable_distances(
        self,
        origin: Coordinate,
        destinations: Sequence[Coordinate],
        *,
        max_distance_m: float,
    ) -> list[float | None]:
        """Return shortest saved-road distances from one origin to many destinations.

        The graph is expanded once from the origin and is capped at the supplied
        road-distance threshold.  ``None`` means the destination could not be
        snapped to, or reached through, the saved continuous road network; it is
        intentionally never replaced with a direct-distance estimate.
        """
        origin_point = self._projection.forward(Point(_coordinate(origin)))
        origin_snap = self._snap(origin_point)
        if origin_snap.distance_m > self._max_snap_distance_m:
            raise RoadNetworkRoutingUnavailable("origin_too_far_from_saved_road_network")
        if max_distance_m <= 0:
            raise RoadNetworkRoutingUnavailable("route_distance_threshold_invalid")

        graph = {node: list(arcs) for node, arcs in self._graph.items()}
        origin_node = self._attach(graph, origin_snap, "origin")
        road_budget_m = max(0.0, float(max_distance_m) - origin_snap.distance_m)
        distances = _dijkstra_distances(graph, origin_node, max_distance_m=road_budget_m)
        result: list[float | None] = []
        for index, destination in enumerate(destinations):
            try:
                destination_point = self._projection.forward(Point(_coordinate(destination)))
                destination_snap = self._snap(destination_point)
            except (RoadNetworkRoutingUnavailable, TypeError, ValueError):
                result.append(None)
                continue
            if destination_snap.distance_m > self._max_snap_distance_m:
                result.append(None)
                continue
            start_distance = distances.get(destination_snap.edge.start)
            end_distance = distances.get(destination_snap.edge.end)
            direct_same_edge = (
                abs(destination_snap.position_m - origin_snap.position_m)
                if destination_snap.edge.edge_id == origin_snap.edge.edge_id
                else None
            )
            candidates = [
                origin_snap.distance_m + distance + destination_snap.distance_m
                for distance in (
                    start_distance + destination_snap.position_m if start_distance is not None else None,
                    end_distance + (destination_snap.edge.length_m - destination_snap.position_m) if end_distance is not None else None,
                    direct_same_edge,
                )
                if distance is not None
                and origin_snap.distance_m + distance + destination_snap.distance_m <= max_distance_m + 1e-6
            ]
            result.append(round(float(min(candidates)), 3) if candidates else None)
        return result

    def _snap(self, point: Point) -> _Snap:
        nearest = self._tree.nearest(point)
        if nearest is None:
            raise RoadNetworkRoutingUnavailable("road_snapshot_has_no_nearest_edge")
        index = int(nearest) if not isinstance(nearest, LineString) else next(
            (edge.edge_id for edge in self._edges if edge.line.equals(nearest)), -1
        )
        if index < 0 or index >= len(self._edges):
            raise RoadNetworkRoutingUnavailable("road_snapshot_nearest_edge_invalid")
        edge = self._edges[index]
        position = float(edge.line.project(point))
        snapped = edge.line.interpolate(position)
        return _Snap(edge=edge, position_m=position, point=snapped, distance_m=float(point.distance(snapped)))

    def _attach(self, graph: dict[str, list[_Arc]], snap: _Snap, name: str) -> str:
        if snap.position_m <= 0.01:
            return snap.edge.start
        if snap.edge.length_m - snap.position_m <= 0.01:
            return snap.edge.end
        node = f"{name}:{snap.edge.edge_id}:{round(snap.position_m, 3)}"
        graph.setdefault(node, [])
        _add_bidirectional(graph, node, snap.edge.start, _subline(snap.edge.line, snap.position_m, 0.0))
        _add_bidirectional(graph, node, snap.edge.end, _subline(snap.edge.line, snap.position_m, snap.edge.length_m))
        return node

    def _node_id(self, coordinate: Coordinate) -> str:
        key = (round(coordinate[0] / self._node_tolerance_m), round(coordinate[1] / self._node_tolerance_m))
        node = f"n:{key[0]}:{key[1]}"
        self._node_coordinates.setdefault(node, coordinate)
        return node


@dataclass(frozen=True)
class _LocalMetricProjection:
    lon0: float
    lat0: float
    metres_per_degree_lon: float
    metres_per_degree_lat: float = _EARTH_RADIUS_M * 3.141592653589793 / 180.0

    @classmethod
    def from_lines(cls, lines: Sequence[LineString]) -> "_LocalMetricProjection":
        coordinates = [coordinate for line in lines for coordinate in line.coords]
        lon0 = sum(float(point[0]) for point in coordinates) / len(coordinates)
        lat0 = sum(float(point[1]) for point in coordinates) / len(coordinates)
        return cls(lon0=lon0, lat0=lat0, metres_per_degree_lon=max(1.0, cls.metres_per_degree_lat * cos(radians(lat0))))

    def forward(self, geometry: Any) -> Any:
        return transform(lambda x, y, z=None: ((x - self.lon0) * self.metres_per_degree_lon, (y - self.lat0) * self.metres_per_degree_lat), geometry)

    def inverse(self, geometry: Any) -> Any:
        return transform(lambda x, y, z=None: (x / self.metres_per_degree_lon + self.lon0, y / self.metres_per_degree_lat + self.lat0), geometry)


def build_route_map_context(
    *,
    analysis_geometry: Mapping[str, Any],
    origin: Coordinate,
    route_geometries: Sequence[Mapping[str, Any]],
    road_records: Iterable[Any],
    max_road_edges: int = _REPORT_ROUTE_MAP_MAX_ROAD_EDGES,
) -> dict[str, Any]:
    """Return a complete small-area or safely bounded large-area road backdrop."""
    try:
        analysis_area = shape(dict(analysis_geometry))
    except Exception as exc:
        raise RoadNetworkRoutingUnavailable("analysis_geometry_invalid_for_route_map") from exc
    route_lines = [shape(dict(geometry)) for geometry in route_geometries if isinstance(geometry, Mapping)]
    route_lines = [line for line in route_lines if isinstance(line, LineString) and not line.is_empty]
    if not route_lines:
        raise RoadNetworkRoutingUnavailable("route_map_has_no_path_geometry")
    combined = unary_union([analysis_area, Point(origin), *route_lines])
    minx, miny, maxx, maxy = combined.bounds
    margin = max(maxx - minx, maxy - miny, 0.001) * 0.14
    extent = box(minx - margin, miny - margin, maxx + margin, maxy + margin)
    features: list[dict[str, Any]] = []
    for record in road_records:
        geometry = getattr(record, "geometry", None)
        if geometry is None or geometry.is_empty or not isinstance(geometry, (LineString, MultiLineString)):
            continue
        clipped = geometry.intersection(extent)
        for line in _lines(clipped):
            if line.length == 0:
                continue
            raw = getattr(record, "raw", {}) if isinstance(getattr(record, "raw", {}), dict) else {}
            properties = getattr(record, "properties", {}) if isinstance(getattr(record, "properties", {}), dict) else {}
            features.append({
                "type": "Feature",
                "geometry": mapping(line.simplify(0.000003, preserve_topology=True)),
                "properties": {
                    "edge_id": str(raw.get("edge_id") or properties.get("edge_id") or getattr(record, "record_id", "")),
                    "is_skeleton": bool(raw.get("is_skeleton_choice_top20") or raw.get("is_skeleton_integration_top20") or properties.get("is_skeleton_choice_top20") or properties.get("is_skeleton_integration_top20")),
                },
            })
    features.sort(key=lambda feature: (not feature["properties"]["is_skeleton"], feature["properties"]["edge_id"]))
    return {
        "road_source_id": "current:dataset:road_edges",
        "routing_algorithm": "local_road_network_shortest_path",
        "analysis_geometry": mapping(analysis_area),
        "origin": [float(origin[0]), float(origin[1])],
        "road_edges": features[:max(1, int(max_road_edges))],
        "road_edges_clipped_count": len(features),
        "road_edges_rendered_count": min(len(features), max(1, int(max_road_edges))),
        "extent": list(extent.bounds),
    }


def _lines(value: Any) -> list[LineString]:
    if isinstance(value, Mapping):
        try:
            value = shape(dict(value))
        except Exception:
            return []
    if isinstance(value, LineString):
        return [value] if not value.is_empty and len(value.coords) >= 2 else []
    if isinstance(value, MultiLineString):
        return [line for line in value.geoms if not line.is_empty and len(line.coords) >= 2]
    if isinstance(value, GeometryCollection):
        return [line for geometry in value.geoms for line in _lines(geometry)]
    return []


def _coordinate(value: Sequence[float]) -> Coordinate:
    if len(value) != 2:
        raise RoadNetworkRoutingUnavailable("route_coordinate_invalid")
    lon, lat = float(value[0]), float(value[1])
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise RoadNetworkRoutingUnavailable("route_coordinate_invalid")
    return lon, lat


def _reverse_line(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def _subline(line: LineString, start: float, end: float) -> LineString:
    reverse = start > end
    low, high = (end, start) if reverse else (start, end)
    low = max(0.0, min(float(low), line.length))
    high = max(0.0, min(float(high), line.length))
    if high - low <= 0.001:
        point = line.interpolate(low)
        return LineString([point.coords[0], point.coords[0]])
    coordinates: list[Coordinate] = [tuple(line.interpolate(low).coords[0])]
    accumulated = 0.0
    source = list(line.coords)
    for first, second in zip(source, source[1:]):
        segment = LineString([first, second])
        next_accumulated = accumulated + segment.length
        if low < next_accumulated - 1e-9 and high > accumulated + 1e-9:
            if accumulated >= low - 1e-9 and accumulated <= high + 1e-9:
                coordinates.append(tuple(first))
            if next_accumulated >= low - 1e-9 and next_accumulated <= high + 1e-9:
                coordinates.append(tuple(second))
        accumulated = next_accumulated
    coordinates.append(tuple(line.interpolate(high).coords[0]))
    cleaned = _dedupe_coords(coordinates)
    result = LineString(cleaned if len(cleaned) >= 2 else [coordinates[0], coordinates[-1]])
    return _reverse_line(result) if reverse else result


def _add_bidirectional(graph: dict[str, list[_Arc]], start: str, end: str, line: LineString) -> None:
    if start == end or line.length <= 0.001:
        return
    graph.setdefault(start, []).append(_Arc(end, float(line.length), line))
    graph.setdefault(end, []).append(_Arc(start, float(line.length), _reverse_line(line)))


def _dijkstra(graph: dict[str, list[_Arc]], start: str, destination: str) -> tuple[float | None, list[_Arc]]:
    queue: list[tuple[float, int, str]] = [(0.0, 0, start)]
    counter = 0
    distance: dict[str, float] = {start: 0.0}
    previous: dict[str, tuple[str, _Arc]] = {}
    while queue:
        current_distance, _, node = heapq.heappop(queue)
        if current_distance > distance.get(node, float("inf")) + 1e-9:
            continue
        if node == destination:
            break
        for arc in graph.get(node, ()):
            candidate = current_distance + arc.length_m
            if candidate + 1e-9 >= distance.get(arc.target, float("inf")):
                continue
            distance[arc.target] = candidate
            previous[arc.target] = (node, arc)
            counter += 1
            heapq.heappush(queue, (candidate, counter, arc.target))
    if destination not in distance:
        return None, []
    arcs: list[_Arc] = []
    node = destination
    while node != start:
        prior = previous.get(node)
        if prior is None:
            return None, []
        node, arc = prior
        arcs.append(arc)
    arcs.reverse()
    return distance[destination], arcs


def _dijkstra_distances(graph: dict[str, list[_Arc]], start: str, *, max_distance_m: float) -> dict[str, float]:
    """Compute one bounded shortest-path tree without leaking graph details upstream."""
    queue: list[tuple[float, int, str]] = [(0.0, 0, start)]
    counter = 0
    distances: dict[str, float] = {start: 0.0}
    while queue:
        current_distance, _, node = heapq.heappop(queue)
        if current_distance != distances.get(node) or current_distance > max_distance_m:
            continue
        for arc in graph.get(node, []):
            candidate = current_distance + arc.length_m
            if candidate > max_distance_m + 1e-6 or candidate >= distances.get(arc.target, float("inf")):
                continue
            distances[arc.target] = candidate
            counter += 1
            heapq.heappush(queue, (candidate, counter, arc.target))
    return distances


def _merge_arcs(arcs: Sequence[_Arc]) -> LineString | None:
    coordinates: list[Coordinate] = []
    for arc in arcs:
        coordinates.extend(tuple(point) for point in arc.line.coords)
    cleaned = _dedupe_coords(coordinates)
    return LineString(cleaned) if len(cleaned) >= 2 else None


def _dedupe_coords(coordinates: Iterable[Coordinate]) -> list[Coordinate]:
    result: list[Coordinate] = []
    for coordinate in coordinates:
        point = (float(coordinate[0]), float(coordinate[1]))
        if not result or point != result[-1]:
            result.append(point)
    return result
