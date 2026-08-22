"""Focused POI accessibility over the saved local road network.

This domain module turns report-approved POI type groups into nearby reference
places.  It uses a project's Polygon/MultiPolygon centroid as its only origin,
then routes on the stored ``current:dataset:road_edges`` snapshot.  It never
calls a remote routing provider and never fabricates a straight-line route.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Any, Literal, Mapping, Protocol, Sequence

from shapely.geometry import MultiPolygon, Polygon, shape

from .road_network_routing import RoadNetworkRoute, RoadNetworkRoutingUnavailable

Coordinate = tuple[float, float]
FocusedPoiRole = Literal["category_supply", "complementary_anchor", "comparison_supply"]
FocusedPoiGroupStatus = Literal["available", "omitted"]
FocusedPoiAccessibilityStatus = Literal["complete", "partial", "omitted", "error"]

MAX_FOCUSED_POI_GROUPS = 4
DEFAULT_ROUTE_VERIFIED_POIS_PER_GROUP = 3
MAX_ROUTE_VERIFIED_POIS_PER_GROUP = 20
DEFAULT_MAX_CANDIDATE_DISTANCE_M = 2_000.0
DEFAULT_MAX_WALKING_DURATION_S = 15 * 60.0
DEFAULT_WALKING_SPEED_M_PER_S = 1.25  # 4.5 km/h; transparent presentation convention.


class LocalRoadRouter(Protocol):
    """The minimum local-road routing contract needed by this domain service."""

    def route(self, origin: Coordinate, destination: Coordinate) -> RoadNetworkRoute: ...


class LocalRoadReachabilityRouter(Protocol):
    def reachable_distances(
        self,
        origin: Coordinate,
        destinations: Sequence[Coordinate],
        *,
        max_distance_m: float,
    ) -> list[float | None]: ...


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
    reachable_poi_count: int = 0
    reachable_count_by_minutes: tuple[tuple[float, int], ...] = ()
    outside_time_limit_count: int = 0
    omission_reason: str | None = None


@dataclass(frozen=True)
class FocusedPoiAccessibilityResult:
    """The complete result suitable for visual planning and report rendering."""

    status: FocusedPoiAccessibilityStatus
    origin: Coordinate | None
    groups: tuple[FocusedPoiGroupResult, ...]
    error_reason: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class EqualWeightFacility:
    facility_id: str
    name: str
    location: Coordinate


@dataclass(frozen=True)
class PopulationDemandPoint:
    demand_id: str
    location: Coordinate
    population: float


class EqualWeightSupplyDemandAccessibilityService:
    """Compare relative facility supply against population over one saved road graph."""

    def __init__(
        self,
        router: LocalRoadReachabilityRouter,
        *,
        walking_speed_m_per_s: float = DEFAULT_WALKING_SPEED_M_PER_S,
    ) -> None:
        self._router = router
        self._walking_speed_m_per_s = max(0.1, float(walking_speed_m_per_s))

    def analyze(
        self,
        *,
        facilities: Sequence[EqualWeightFacility],
        demand_points: Sequence[PopulationDemandPoint],
        reporting_minutes: Sequence[float],
        demand_result_limit: int = 20,
    ) -> dict[str, Any]:
        facilities = tuple(facilities)
        demand_points = tuple(item for item in demand_points if item.population > 0 and isfinite(item.population))
        minutes = tuple(sorted({float(value) for value in reporting_minutes if float(value) > 0}))
        if not facilities or not demand_points or not minutes:
            raise ValueError("equal_weight_accessibility_requires_facilities_population_and_time_bands")

        max_distance_m = minutes[-1] * 60.0 * self._walking_speed_m_per_s
        destinations = [item.location for item in demand_points]
        distance_rows: list[list[float | None]] = []
        failed_facility_origins = 0
        for facility in facilities:
            try:
                distances = self._router.reachable_distances(
                    facility.location,
                    destinations,
                    max_distance_m=max_distance_m,
                )
            except RoadNetworkRoutingUnavailable:
                distances = [None] * len(demand_points)
                failed_facility_origins += 1
            if len(distances) != len(demand_points):
                distances = [None] * len(demand_points)
                failed_facility_origins += 1
            distance_rows.append(distances)

        band_results = []
        max_band_scores: list[float] = []
        max_band_facility_rows: list[dict[str, Any]] = []
        for threshold_min in minutes:
            threshold_m = threshold_min * 60.0 * self._walking_speed_m_per_s
            facility_supply_ratios: list[float | None] = []
            facility_rows = []
            for facility, distances in zip(facilities, distance_rows):
                reachable_population = sum(
                    demand.population
                    for demand, distance in zip(demand_points, distances)
                    if distance is not None and distance <= threshold_m
                )
                ratio = 1.0 / reachable_population if reachable_population > 0 else None
                facility_supply_ratios.append(ratio)
                facility_rows.append({
                    "record_ref": facility.facility_id,
                    "name": facility.name,
                    "equal_weight": 1,
                    "reachable_population": round(reachable_population, 6),
                    "facility_supply_per_1000_residents": round(ratio * 1000.0, 6) if ratio is not None else None,
                })
            demand_scores_per_1000 = [
                sum(
                    ratio
                    for ratio, distances in zip(facility_supply_ratios, distance_rows)
                    if ratio is not None
                    and distances[demand_index] is not None
                    and distances[demand_index] <= threshold_m
                ) * 1000.0
                for demand_index in range(len(demand_points))
            ]
            total_population = sum(item.population for item in demand_points)
            population_weighted_mean = (
                sum(item.population * score for item, score in zip(demand_points, demand_scores_per_1000)) / total_population
                if total_population > 0
                else None
            )
            band_results.append({
                "minutes": threshold_min,
                "reachable_facility_count": sum(ratio is not None for ratio in facility_supply_ratios),
                "served_population_unit_count": sum(score > 0 for score in demand_scores_per_1000),
                "population_weighted_mean_facilities_per_1000_residents": (
                    round(population_weighted_mean, 9)
                    if population_weighted_mean is not None
                    else None
                ),
                "minimum_facilities_per_1000_residents": round(min(demand_scores_per_1000), 9),
                "maximum_facilities_per_1000_residents": round(max(demand_scores_per_1000), 9),
            })
            if threshold_min == minutes[-1]:
                max_band_scores = demand_scores_per_1000
                max_band_facility_rows = facility_rows

        demand_rows = [
            {
                "record_ref": demand.demand_id,
                "population": round(demand.population, 6),
                "facilities_per_1000_residents": round(score, 9),
                "reachable_facility_count": sum(
                    distance_rows[facility_index][demand_index] is not None
                    for facility_index in range(len(facilities))
                ),
            }
            for demand_index, (demand, score) in enumerate(zip(demand_points, max_band_scores))
        ]
        demand_rows.sort(key=lambda item: (item["facilities_per_1000_residents"], item["record_ref"]))
        within_max_catchment_pair_count = sum(
            distance is not None
            for distances in distance_rows
            for distance in distances
        )
        return {
            "facility_count": len(facilities),
            "population_unit_count": len(demand_points),
            "total_population": round(sum(item.population for item in demand_points), 6),
            "equal_weight_facility_count": len(facilities),
            "bands": band_results,
            "facilities": max_band_facility_rows,
            "demand_units": demand_rows[: max(1, int(demand_result_limit))],
            "route_pair_count": len(facilities) * len(demand_points),
            "within_max_catchment_pair_count": within_max_catchment_pair_count,
            "failed_facility_origins": failed_facility_origins,
        }


class FocusedPoiAccessibilityService:
    """Find nearby POIs using local shortest paths on an injected road snapshot.

    Haversine distance only limits the candidate pool to the nearest 2 km.  It
    is never exposed as a route distance or duration.  Walking distance is the
    origin access leg, saved-road shortest path and destination access leg;
    each component remains separately inspectable.  Minutes use a disclosed
    4.5 km/h reference walking speed.
    """

    def __init__(
        self,
        router: LocalRoadRouter,
        *,
        max_groups: int = MAX_FOCUSED_POI_GROUPS,
        max_candidates_per_group: int | None = None,
        max_results_per_group: int = DEFAULT_ROUTE_VERIFIED_POIS_PER_GROUP,
        max_candidate_distance_m: float = DEFAULT_MAX_CANDIDATE_DISTANCE_M,
        max_walking_duration_s: float = DEFAULT_MAX_WALKING_DURATION_S,
        walking_speed_m_per_s: float = DEFAULT_WALKING_SPEED_M_PER_S,
        reporting_minutes: Sequence[float] = (5.0, 10.0, 15.0),
    ) -> None:
        self._router = router
        self._max_groups = min(MAX_FOCUSED_POI_GROUPS, max(1, int(max_groups)))
        self._max_candidates_per_group = (
            max(1, int(max_candidates_per_group))
            if max_candidates_per_group is not None
            else None
        )
        self._max_results_per_group = min(MAX_ROUTE_VERIFIED_POIS_PER_GROUP, max(1, int(max_results_per_group)))
        self._max_candidate_distance_m = max(1.0, float(max_candidate_distance_m))
        self._max_walking_duration_s = max(1.0, float(max_walking_duration_s))
        self._walking_speed_m_per_s = max(0.1, float(walking_speed_m_per_s))
        self._reporting_minutes = tuple(sorted({
            float(value)
            for value in reporting_minutes
            if float(value) > 0 and float(value) * 60 <= self._max_walking_duration_s
        }))

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
        candidates = sorted(matched, key=lambda item: (_haversine_m(origin, item[1]), item[0].poi_id, item[0].name))
        if self._max_candidates_per_group is not None:
            candidates = candidates[: self._max_candidates_per_group]
        routed: list[RouteVerifiedPoi] = []
        failures = 0
        outside_time_limit = 0
        for poi, destination in candidates:
            try:
                route = self._router.route(origin, destination)
                _validate_route(route)
            except Exception:
                failures += 1
                continue
            walking_distance_m = (
                route.origin_snap_distance_m
                + route.distance_m
                + route.destination_snap_distance_m
            )
            duration_s = walking_distance_m / self._walking_speed_m_per_s
            if duration_s > self._max_walking_duration_s:
                outside_time_limit += 1
                continue
            routed.append(RouteVerifiedPoi(
                poi_id=poi.poi_id,
                name=poi.name,
                poi_type=poi.poi_type,
                location=destination,
                address=poi.address,
                walking_distance_m=walking_distance_m,
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
            return _omitted_group(
                group,
                "no_reachable_poi_within_time" if outside_time_limit else "no_local_road_path",
                candidates_considered=len(candidates),
                route_failures=failures,
                outside_time_limit_count=outside_time_limit,
            )
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
            reachable_poi_count=len(routed),
            reachable_count_by_minutes=tuple(
                (minutes, sum(poi.walking_duration_s <= minutes * 60 for poi in routed))
                for minutes in self._reporting_minutes
            ),
            outside_time_limit_count=outside_time_limit,
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
    if group.role not in {"category_supply", "complementary_anchor", "comparison_supply"}:
        return "invalid_role"
    if not str(group.group_id).strip() or not str(group.title).strip():
        return "invalid_group_identity"
    if not _normalized_type_codes(group.type_codes):
        return "missing_type_codes"
    if not str(group.statement_ref).strip():
        return "missing_statement_ref"
    return None


def _omitted_group(
    group: FocusedPoiTypeGroup,
    reason: str,
    *,
    candidates_considered: int = 0,
    route_failures: int = 0,
    outside_time_limit_count: int = 0,
) -> FocusedPoiGroupResult:
    return FocusedPoiGroupResult(
        group_id=group.group_id,
        title=group.title,
        role=group.role,
        status="omitted",
        matched_type_codes=_normalized_type_codes(group.type_codes),
        statement_ref=group.statement_ref,
        candidates_considered=candidates_considered,
        route_failures=route_failures,
        outside_time_limit_count=outside_time_limit_count,
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
