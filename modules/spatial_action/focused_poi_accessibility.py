"""Focused POI accessibility over the saved local road network.

This domain module turns report-approved POI type groups into nearby reference
places.  It uses a project's Polygon/MultiPolygon centroid as its only origin,
then routes on the stored ``current:dataset:road_edges`` snapshot.  It never
calls a remote routing provider and never fabricates a straight-line route.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any, Literal, Mapping, Protocol, Sequence

from shapely.geometry import MultiPolygon, Polygon, shape

from .road_network_routing import RoadNetworkRoute

Coordinate = tuple[float, float]
FocusedPoiRole = Literal["complementary_anchor", "comparison_supply"]
FocusedPoiGroupStatus = Literal["available", "omitted"]
FocusedPoiAccessibilityStatus = Literal["complete", "partial", "omitted", "error"]

MAX_FOCUSED_POI_GROUPS = 4
MAX_ROUTE_VERIFIED_POIS_PER_GROUP = 3
DEFAULT_ROUTE_CANDIDATES_PER_GROUP = 30
DEFAULT_MAX_CANDIDATE_DISTANCE_M = 2_000.0
DEFAULT_MAX_WALKING_DURATION_S = 15 * 60.0
DEFAULT_WALKING_SPEED_M_PER_S = 1.25  # 4.5 km/h; transparent presentation convention.


class LocalRoadRouter(Protocol):
    """The minimum local-road routing contract needed by this domain service."""

    def route(self, origin: Coordinate, destination: Coordinate) -> RoadNetworkRoute: ...


@dataclass(frozen=True)
class FocusedPoiCandidate:
    """One real POI snapshot record eligible for focused accessibility analysis."""

    poi_id: str
    name: str
    poi_type: str | None
    location: Sequence[float]
    address: str | None = None


@dataclass(frozen=True)
class FocusedPoiTypeGroup:
    """A report-approved POI type group, not a user-use scenario."""

    group_id: str
    title: str
    role: FocusedPoiRole
    type_codes: tuple[str, ...]
    statement_ref: str


@dataclass(frozen=True)
class RouteVerifiedPoi:
    """A POI reachable through a route assembled from saved road edges."""

    poi_id: str
    name: str
    poi_type: str | None
    location: Coordinate
    address: str | None
    walking_distance_m: float
    walking_duration_s: float
    route_geometry: dict[str, Any]
    route_geometry_status: Literal["available"]
    route_length_m: float
    origin_snap_distance_m: float
    destination_snap_distance_m: float
    origin_snap: Coordinate
    destination_snap: Coordinate
    routing_algorithm: str = "local_road_network_shortest_path"


@dataclass(frozen=True)
class FocusedPoiGroupResult:
    group_id: str
    title: str
    role: str
    status: FocusedPoiGroupStatus
    matched_type_codes: tuple[str, ...]
    statement_ref: str
    pois: tuple[RouteVerifiedPoi, ...] = ()
    candidates_considered: int = 0
    route_failures: int = 0
    omission_reason: str | None = None


@dataclass(frozen=True)
class FocusedPoiAccessibilityResult:
    """The complete result suitable for visual planning and report rendering."""

    status: FocusedPoiAccessibilityStatus
    origin: Coordinate | None
    groups: tuple[FocusedPoiGroupResult, ...]
    error_reason: str | None = None
    diagnostics: tuple[str, ...] = ()


class FocusedPoiAccessibilityService:
    """Find nearby POIs using local shortest paths on an injected road snapshot.

    Haversine distance only limits the candidate pool to the nearest 2 km.  It
    is never exposed as a route distance or a duration.  Minutes are derived
    consistently from the resulting road-network path length at a disclosed
    4.5 km/h reference walking speed.
    """

    def __init__(
        self,
        router: LocalRoadRouter,
        *,
        max_groups: int = MAX_FOCUSED_POI_GROUPS,
        max_candidates_per_group: int = DEFAULT_ROUTE_CANDIDATES_PER_GROUP,
        max_results_per_group: int = MAX_ROUTE_VERIFIED_POIS_PER_GROUP,
        max_candidate_distance_m: float = DEFAULT_MAX_CANDIDATE_DISTANCE_M,
        max_walking_duration_s: float = DEFAULT_MAX_WALKING_DURATION_S,
        walking_speed_m_per_s: float = DEFAULT_WALKING_SPEED_M_PER_S,
    ) -> None:
        self._router = router
        self._max_groups = min(MAX_FOCUSED_POI_GROUPS, max(1, int(max_groups)))
        self._max_candidates_per_group = max(1, int(max_candidates_per_group))
        self._max_results_per_group = min(MAX_ROUTE_VERIFIED_POIS_PER_GROUP, max(1, int(max_results_per_group)))
        self._max_candidate_distance_m = max(1.0, float(max_candidate_distance_m))
        self._max_walking_duration_s = max(1.0, float(max_walking_duration_s))
        self._walking_speed_m_per_s = max(0.1, float(walking_speed_m_per_s))

    def analyze(
        self,
        *,
        analysis_geometry: Mapping[str, Any],
        groups: Sequence[FocusedPoiTypeGroup],
        pois: Sequence[FocusedPoiCandidate],
    ) -> FocusedPoiAccessibilityResult:
        origin, geometry_error = _centroid_from_analysis_geometry(analysis_geometry)
        if geometry_error is not None:
            return FocusedPoiAccessibilityResult(status="error", origin=None, groups=(), error_reason=geometry_error, diagnostics=(geometry_error,))

        group_results: list[FocusedPoiGroupResult] = []
        for index, group in enumerate(groups):
            if index >= self._max_groups:
                group_results.append(_omitted_group(group, "max_groups_exceeded"))
                continue
            invalid_reason = _validate_group(group)
            if invalid_reason is not None:
                group_results.append(_omitted_group(group, invalid_reason))
                continue
            group_results.append(self._analyze_group(origin, group, pois))

        statuses = {result.status for result in group_results}
        overall_status: FocusedPoiAccessibilityStatus
        if not group_results or statuses == {"omitted"}:
            overall_status = "omitted"
        elif statuses == {"available"}:
            overall_status = "complete"
        else:
            overall_status = "partial"
        diagnostics = tuple(f"{result.group_id}:{result.omission_reason}" for result in group_results if result.omission_reason)
        return FocusedPoiAccessibilityResult(status=overall_status, origin=origin, groups=tuple(group_results), diagnostics=diagnostics)

    def _analyze_group(self, origin: Coordinate, group: FocusedPoiTypeGroup, pois: Sequence[FocusedPoiCandidate]) -> FocusedPoiGroupResult:
        matched = [
            (poi, location)
            for poi in pois
            if _poi_matches_type_codes(poi.poi_type, group.type_codes)
            if (location := _normalized_coordinate(poi.location)) is not None
            if _haversine_m(origin, location) <= self._max_candidate_distance_m
        ]
        if not matched:
            return _omitted_group(group, "no_matching_pois")
        candidates = sorted(matched, key=lambda item: (_haversine_m(origin, item[1]), item[0].poi_id, item[0].name))[: self._max_candidates_per_group]
        routed: list[RouteVerifiedPoi] = []
        failures = 0
        for poi, destination in candidates:
            try:
                route = self._router.route(origin, destination)
                _validate_route(route)
            except Exception:
                failures += 1
                continue
            duration_s = route.distance_m / self._walking_speed_m_per_s
            if duration_s > self._max_walking_duration_s:
                continue
            routed.append(RouteVerifiedPoi(
                poi_id=poi.poi_id,
                name=poi.name,
                poi_type=poi.poi_type,
                location=destination,
                address=poi.address,
                walking_distance_m=route.distance_m,
                walking_duration_s=duration_s,
                route_geometry=route.geometry,
                route_geometry_status="available",
                route_length_m=route.distance_m,
                origin_snap_distance_m=route.origin_snap_distance_m,
                destination_snap_distance_m=route.destination_snap_distance_m,
                origin_snap=route.origin_snap,
                destination_snap=route.destination_snap,
                routing_algorithm=route.algorithm,
            ))
        if not routed:
            return _omitted_group(group, "no_local_road_path")
        selected = tuple(sorted(routed, key=lambda poi: (poi.walking_duration_s, poi.walking_distance_m, poi.poi_id))[: self._max_results_per_group])
        return FocusedPoiGroupResult(
            group_id=group.group_id,
            title=group.title,
            role=group.role,
            status="available",
            matched_type_codes=_normalized_type_codes(group.type_codes),
            statement_ref=group.statement_ref,
            pois=selected,
            candidates_considered=len(candidates),
            route_failures=failures,
        )


def _validate_route(route: RoadNetworkRoute) -> None:
    if not isinstance(route, RoadNetworkRoute) or route.distance_m <= 0:
        raise ValueError("local_road_route_invalid")
    geometry = route.geometry
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise ValueError("local_road_route_geometry_invalid")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, Sequence) or isinstance(coordinates, (str, bytes)) or len(coordinates) < 2:
        raise ValueError("local_road_route_geometry_invalid")
    if any(_normalized_coordinate(coordinate) is None for coordinate in coordinates):
        raise ValueError("local_road_route_geometry_invalid")


def _centroid_from_analysis_geometry(analysis_geometry: Mapping[str, Any]) -> tuple[Coordinate | None, str | None]:
    if not isinstance(analysis_geometry, Mapping) or analysis_geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None, "analysis_geometry_must_be_geojson_polygon_or_multipolygon"
    try:
        geometry = shape(dict(analysis_geometry))
    except Exception:
        return None, "analysis_geometry_invalid"
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or not geometry.is_valid:
        return None, "analysis_geometry_invalid"
    centroid = geometry.centroid
    origin = (float(centroid.x), float(centroid.y))
    if not _valid_coordinate(origin):
        return None, "project_centroid_invalid"
    return origin, None


def _validate_group(group: FocusedPoiTypeGroup) -> str | None:
    if group.role not in {"complementary_anchor", "comparison_supply"}:
        return "invalid_role"
    if not str(group.group_id).strip() or not str(group.title).strip():
        return "invalid_group_identity"
    if not _normalized_type_codes(group.type_codes):
        return "missing_type_codes"
    if not str(group.statement_ref).strip():
        return "missing_statement_ref"
    return None


def _omitted_group(group: FocusedPoiTypeGroup, reason: str) -> FocusedPoiGroupResult:
    return FocusedPoiGroupResult(
        group_id=group.group_id,
        title=group.title,
        role=group.role,
        status="omitted",
        matched_type_codes=_normalized_type_codes(group.type_codes),
        statement_ref=group.statement_ref,
        omission_reason=reason,
    )


def _poi_matches_type_codes(poi_type: str | None, requested_type_codes: Sequence[str]) -> bool:
    poi_codes = _split_type_codes(poi_type)
    requested_codes = _normalized_type_codes(requested_type_codes)
    return any(_type_code_matches(poi_code, requested) for poi_code in poi_codes for requested in requested_codes)


def _type_code_matches(poi_code: str, requested_code: str) -> bool:
    if poi_code == requested_code:
        return True
    parent_prefix = requested_code.rstrip("0")
    return len(parent_prefix) >= 2 and poi_code.startswith(parent_prefix)


def _normalized_type_codes(type_codes: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(code for raw in type_codes for code in _split_type_codes(raw)))


def _split_type_codes(value: str | None) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(part.strip() for part in value.split("|") if part.strip())


def _valid_coordinate(coordinate: Any) -> bool:
    return _normalized_coordinate(coordinate) is not None


def _normalized_coordinate(coordinate: Any) -> Coordinate | None:
    if not isinstance(coordinate, Sequence) or isinstance(coordinate, (str, bytes)) or len(coordinate) != 2:
        return None
    try:
        lon, lat = float(coordinate[0]), float(coordinate[1])
    except (TypeError, ValueError):
        return None
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        return None
    return lon, lat


def _haversine_m(origin: Coordinate, destination: Coordinate) -> float:
    lon1, lat1 = origin
    lon2, lat2 = destination
    lat_delta = radians(lat2 - lat1)
    lon_delta = radians(lon2 - lon1)
    a = sin(lat_delta / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(lon_delta / 2) ** 2
    return 6_371_008.8 * 2 * asin(sqrt(a))
