"""Verified POI supply structure for decision-report visuals.

This module accepts only report-approved type selections.  It resolves every
selected POI through the shared real taxonomy, verifies its point against a
saved 15-minute walking isochrone, and optionally computes a separate local
road-network five-minute count.  It never assigns a project positioning,
creates a free-text category, or replaces missing roads with straight lines.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, Sequence

from shapely.geometry import MultiPolygon, Point, Polygon, shape

from core.poi_taxonomy import PoiTaxonomyItem, get_poi_taxonomy, normalize_typecode
from .focused_poi_accessibility import DEFAULT_WALKING_SPEED_M_PER_S
from .road_network_routing import RoadNetworkRoutingUnavailable

Coordinate = tuple[float, float]
PoiSupplyRole = Literal["complementary_anchor", "comparison_supply"]
PoiSupplyStatus = Literal["available", "partial", "unavailable"]
PoiSupplyGroupStatus = Literal["available", "partial", "unavailable"]

MAX_POI_SUPPLY_GROUPS_PER_ROLE = 6
DEFAULT_NEARBY_DURATION_S = 5 * 60.0


class LocalRoadReachability(Protocol):
    def reachable_distances(
        self,
        origin: Coordinate,
        destinations: Sequence[Coordinate],
        *,
        max_distance_m: float,
    ) -> list[float | None]: ...


@dataclass(frozen=True)
class PoiSupplyCandidate:
    poi_id: str
    poi_type: str | None
    location: Sequence[float] | None


@dataclass(frozen=True)
class PoiSupplyGroup:
    group_id: str
    title: str
    role: PoiSupplyRole
    type_codes: tuple[str, ...]
    statement_ref: str


@dataclass(frozen=True)
class PoiSupplyGroupResult:
    """Trace of an editorial type selection; ``title`` is not a chart label."""

    group_id: str
    title: str
    role: str
    statement_ref: str
    requested_type_codes: tuple[str, ...]
    matched_type_codes: tuple[str, ...]
    status: PoiSupplyGroupStatus
    isochrone_poi_count: int = 0
    nearby_5_min_poi_count: int | None = None
    route_status: PoiSupplyGroupStatus = "unavailable"
    routable_candidate_count: int = 0
    unroutable_poi_count: int = 0
    omission_reason: str | None = None


@dataclass(frozen=True)
class PoiSupplyClassificationRow:
    role: PoiSupplyRole
    main_category: str
    subcategory: str
    isochrone_poi_count: int
    nearby_5_min_poi_count: int | None
    selected_type_codes: tuple[str, ...]
    source_group_ids: tuple[str, ...]
    statement_refs: tuple[str, ...]


@dataclass(frozen=True)
class PoiSupplyAudit:
    isochrone_included_poi_count: int = 0
    outside_isochrone_poi_count: int = 0
    missing_coordinate_poi_count: int = 0
    invalid_coordinate_poi_count: int = 0
    unmapped_poi_count: int = 0
    unmapped_type_codes: tuple[str, ...] = ()
    five_minute_accessibility_status: PoiSupplyStatus = "unavailable"


@dataclass(frozen=True)
class PoiSupplyStructureResult:
    status: PoiSupplyStatus
    origin: Coordinate | None
    groups: tuple[PoiSupplyGroupResult, ...]
    classified_rows: tuple[PoiSupplyClassificationRow, ...]
    audit: PoiSupplyAudit
    error_reason: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class _MatchedPoi:
    candidate: PoiSupplyCandidate
    location: Coordinate
    matched_groups: tuple[PoiSupplyGroup, ...]
    taxonomy: PoiTaxonomyItem | None
    type_codes: tuple[str, ...]


class PoiSupplyStructureService:
    """Owns selected-category validation, isochrone membership and road counts."""

    def __init__(
        self,
        router: LocalRoadReachability | None = None,
        *,
        nearby_duration_s: float = DEFAULT_NEARBY_DURATION_S,
        walking_speed_m_per_s: float = DEFAULT_WALKING_SPEED_M_PER_S,
    ) -> None:
        self._router = router
        self._nearby_duration_s = max(1.0, float(nearby_duration_s))
        self._walking_speed_m_per_s = max(0.1, float(walking_speed_m_per_s))

    def analyze(
        self,
        *,
        analysis_geometry: Mapping[str, Any] | None,
        isochrone_geometry: Mapping[str, Any],
        raw_groups: Any,
        pois: Sequence[PoiSupplyCandidate],
    ) -> PoiSupplyStructureResult:
        groups, input_errors = _parse_groups(raw_groups)
        origin, origin_error = _centroid_from_analysis_geometry(analysis_geometry)
        isochrone, isochrone_error = _polygon_from_geojson(isochrone_geometry, "isochrone")
        if isochrone_error:
            return PoiSupplyStructureResult(
                status="unavailable", origin=origin, groups=(), classified_rows=(), audit=PoiSupplyAudit(),
                error_reason=isochrone_error, diagnostics=(isochrone_error,),
            )
        if input_errors:
            return PoiSupplyStructureResult(
                status="unavailable", origin=origin, groups=(), classified_rows=(), audit=PoiSupplyAudit(),
                error_reason="invalid_groups", diagnostics=tuple(input_errors),
            )

        existing_type_codes = _snapshot_type_codes(pois)
        validation_errors = {group.group_id: _validate_group_against_snapshot(group, existing_type_codes) for group in groups}
        valid_groups = tuple(group for group in groups if not validation_errors[group.group_id])
        group_results: dict[str, PoiSupplyGroupResult] = {
            group.group_id: _unavailable_group(group, validation_errors[group.group_id])
            for group in groups if validation_errors[group.group_id]
        }
        if not valid_groups:
            diagnostics = tuple(f"{group.group_id}:{validation_errors[group.group_id]}" for group in groups)
            return PoiSupplyStructureResult(
                status="unavailable", origin=origin, groups=tuple(group_results[group.group_id] for group in groups),
                classified_rows=(), audit=PoiSupplyAudit(), error_reason="no_valid_type_groups", diagnostics=diagnostics,
            )

        included, audit = self._filter_and_resolve(isochrone, pois, valid_groups)
        trace_by_group: dict[str, list[_MatchedPoi]] = defaultdict(list)
        classified: dict[tuple[str, str, str], list[_MatchedPoi]] = defaultdict(list)
        for matched in included:
            for group in matched.matched_groups:
                trace_by_group[group.group_id].append(matched)
                if matched.taxonomy is not None:
                    classified[(group.role, matched.taxonomy.main_category, matched.taxonomy.subcategory)].append(matched)

        row_distances, road_status, road_diagnostic = self._reachability(origin, classified)
        audit = PoiSupplyAudit(
            isochrone_included_poi_count=audit.isochrone_included_poi_count,
            outside_isochrone_poi_count=audit.outside_isochrone_poi_count,
            missing_coordinate_poi_count=audit.missing_coordinate_poi_count,
            invalid_coordinate_poi_count=audit.invalid_coordinate_poi_count,
            unmapped_poi_count=audit.unmapped_poi_count,
            unmapped_type_codes=audit.unmapped_type_codes,
            five_minute_accessibility_status=road_status,
        )
        if origin_error and self._router is not None:
            road_diagnostic = road_diagnostic or origin_error
        rows = tuple(
            self._classification_row(key, matched, row_distances.get(key), valid_groups)
            for key, matched in sorted(classified.items(), key=lambda item: (item[0][0], item[0][1], item[0][2]))
        )
        for group in valid_groups:
            matching = trace_by_group[group.group_id]
            distances = [
                distance for key, values in classified.items() if group in values[0].matched_groups
                for distance in (row_distances.get(key) or []) if distance is not None
            ]
            route_status: PoiSupplyGroupStatus = "available" if road_status == "available" else "unavailable"
            nearby = None if road_status == "unavailable" else sum(distance <= self._nearby_distance_m for distance in distances)
            omission_reason = None if road_status == "available" else road_diagnostic
            group_results[group.group_id] = PoiSupplyGroupResult(
                group_id=group.group_id, title=group.title, role=group.role, statement_ref=group.statement_ref,
                requested_type_codes=group.type_codes,
                matched_type_codes=_matched_snapshot_type_codes(matching),
                status="available" if road_status == "available" else "partial",
                isochrone_poi_count=len(matching), nearby_5_min_poi_count=nearby,
                route_status=route_status, routable_candidate_count=len(distances),
                unroutable_poi_count=max(0, len(matching) - len(distances)), omission_reason=omission_reason,
            )

        ordered_groups = tuple(group_results[group.group_id] for group in groups)
        if not rows:
            diagnostics = tuple(filter(None, ["no_mapped_pois_in_isochrone", road_diagnostic]))
            return PoiSupplyStructureResult(
                status="unavailable", origin=origin, groups=ordered_groups, classified_rows=(), audit=audit,
                error_reason="no_mapped_pois_in_isochrone", diagnostics=diagnostics,
            )
        overall: PoiSupplyStatus = "available" if road_status == "available" else "partial"
        diagnostics = tuple(filter(None, [road_diagnostic, *(f"{item.group_id}:{item.omission_reason}" for item in ordered_groups if item.omission_reason)]))
        return PoiSupplyStructureResult(overall, origin, ordered_groups, rows, audit, diagnostics=diagnostics)

    @property
    def _nearby_distance_m(self) -> float:
        return self._nearby_duration_s * self._walking_speed_m_per_s

    def _filter_and_resolve(
        self,
        isochrone: Polygon | MultiPolygon,
        pois: Sequence[PoiSupplyCandidate],
        groups: Sequence[PoiSupplyGroup],
    ) -> tuple[list[_MatchedPoi], PoiSupplyAudit]:
        included: list[_MatchedPoi] = []
        outside = missing = invalid = unmapped = 0
        unmapped_codes: set[str] = set()
        taxonomy = get_poi_taxonomy()
        for poi in pois:
            type_codes = _split_type_codes(poi.poi_type)
            matched_groups = tuple(group for group in groups if _poi_matches_type_codes(poi.poi_type, group.type_codes))
            # The audit is scoped to POIs selected by the reviewed category groups.
            # Unselected snapshot records have no bearing on this chart and must not
            # make the isochrone filtering audit look worse than the visual input.
            if not matched_groups:
                continue
            if poi.location is None:
                missing += 1
                continue
            location = _normalized_coordinate(poi.location)
            if location is None:
                invalid += 1
                continue
            if not isochrone.covers(Point(location)):
                outside += 1
                continue
            item = next((resolved for code in type_codes if (resolved := taxonomy.resolve_typecode(code)) is not None), None)
            if item is None:
                unmapped += 1
                unmapped_codes.update(type_codes)
            included.append(_MatchedPoi(poi, location, matched_groups, item, type_codes))
        return included, PoiSupplyAudit(
            isochrone_included_poi_count=len(included), outside_isochrone_poi_count=outside,
            missing_coordinate_poi_count=missing, invalid_coordinate_poi_count=invalid,
            unmapped_poi_count=unmapped, unmapped_type_codes=tuple(sorted(unmapped_codes)),
        )

    def _reachability(
        self,
        origin: Coordinate | None,
        classified: Mapping[tuple[str, str, str], Sequence[_MatchedPoi]],
    ) -> tuple[dict[tuple[str, str, str], list[float | None]], PoiSupplyStatus, str | None]:
        if self._router is None:
            return {}, "unavailable", "local_road_network_unavailable"
        if origin is None:
            return {}, "unavailable", "project_centroid_unavailable"
        keyed_values = [
            (key, poi)
            for key, pois in classified.items()
            for poi in pois
        ]
        if not keyed_values:
            return {}, "unavailable", "no_mapped_pois_in_isochrone"
        try:
            distances = self._router.reachable_distances(
                origin,
                [poi.location for _, poi in keyed_values],
                max_distance_m=self._nearby_distance_m,
            )
        except RoadNetworkRoutingUnavailable as exc:
            return {}, "unavailable", str(exc)
        if len(distances) != len(keyed_values):
            return {}, "unavailable", "local_road_distance_result_incomplete"
        grouped: dict[tuple[str, str, str], list[float | None]] = defaultdict(list)
        for (key, _), distance in zip(keyed_values, distances):
            grouped[key].append(distance)
        if not any(distance is not None for distance in distances):
            return grouped, "unavailable", "no_local_road_path"
        return grouped, "available", None

    def _classification_row(
        self,
        key: tuple[str, str, str],
        matched: Sequence[_MatchedPoi],
        distances: Sequence[float | None] | None,
        groups: Sequence[PoiSupplyGroup],
    ) -> PoiSupplyClassificationRow:
        role, main_category, subcategory = key
        selected_groups = [group for group in groups if any(group in poi.matched_groups for poi in matched)]
        nearby = None if distances is None or not any(distance is not None for distance in distances) else sum(
            distance <= self._nearby_distance_m for distance in distances if distance is not None
        )
        return PoiSupplyClassificationRow(
            role=role, main_category=main_category, subcategory=subcategory, isochrone_poi_count=len(matched),
            nearby_5_min_poi_count=nearby,
            selected_type_codes=tuple(sorted({code for poi in matched for code in poi.type_codes})),
            source_group_ids=tuple(group.group_id for group in selected_groups),
            statement_refs=tuple(group.statement_ref for group in selected_groups),
        )


def _parse_groups(raw_groups: Any) -> tuple[tuple[PoiSupplyGroup, ...], list[str]]:
    if not isinstance(raw_groups, list) or not raw_groups:
        return (), ["groups_required"]
    counts = {"complementary_anchor": 0, "comparison_supply": 0}
    groups: list[PoiSupplyGroup] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    selections: list[tuple[str, tuple[str, ...]]] = []
    for index, raw in enumerate(raw_groups):
        if not isinstance(raw, Mapping):
            errors.append(f"group_{index + 1}_invalid")
            continue
        group_id = str(raw.get("group_id") or "").strip()
        title = str(raw.get("title") or "").strip()
        role = str(raw.get("role") or "").strip()
        statement_ref = str(raw.get("statement_ref") or "").strip()
        type_codes = _normalized_type_codes(raw.get("type_codes"))
        if not group_id or group_id in seen_ids:
            errors.append(f"group_{index + 1}_invalid_group_id")
        if not title:
            errors.append(f"group_{index + 1}_missing_title")
        if role not in counts:
            errors.append(f"group_{index + 1}_invalid_role")
        if not statement_ref:
            errors.append(f"group_{index + 1}_missing_statement_ref")
        if not type_codes:
            errors.append(f"group_{index + 1}_missing_type_codes")
        if any(error.startswith(f"group_{index + 1}_") for error in errors):
            continue
        if counts[role] >= MAX_POI_SUPPLY_GROUPS_PER_ROLE:
            errors.append(f"{role}_max_groups_exceeded")
            continue
        if any(_selections_overlap(type_codes, prior) for _, prior in selections):
            errors.append("type_codes_overlap_across_groups:" + ",".join(type_codes))
            continue
        seen_ids.add(group_id)
        counts[role] += 1
        selections.append((group_id, type_codes))
        groups.append(PoiSupplyGroup(group_id, title, role, type_codes, statement_ref))
    return tuple(groups), errors


def _selections_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    return any(_type_code_matches(item, other) or _type_code_matches(other, item) for item in left for other in right)


def _validate_group_against_snapshot(group: PoiSupplyGroup, existing_type_codes: set[str]) -> str | None:
    missing = [code for code in group.type_codes if not any(_type_code_matches(existing, code) for existing in existing_type_codes)]
    return "requested_type_code_not_in_poi_snapshot:" + ",".join(missing) if missing else None


def _unavailable_group(group: PoiSupplyGroup, reason: str | None) -> PoiSupplyGroupResult:
    return PoiSupplyGroupResult(group.group_id, group.title, group.role, group.statement_ref, group.type_codes, (), "unavailable", omission_reason=reason)


def _polygon_from_geojson(raw: Mapping[str, Any] | None, label: str) -> tuple[Polygon | MultiPolygon | None, str | None]:
    if not isinstance(raw, Mapping) or raw.get("type") not in {"Polygon", "MultiPolygon"}:
        return None, f"{label}_geometry_must_be_geojson_polygon_or_multipolygon"
    try:
        geometry = shape(dict(raw))
    except Exception:
        return None, f"{label}_geometry_invalid"
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or not geometry.is_valid:
        return None, f"{label}_geometry_invalid"
    return geometry, None


def _centroid_from_analysis_geometry(analysis_geometry: Mapping[str, Any] | None) -> tuple[Coordinate | None, str | None]:
    geometry, error = _polygon_from_geojson(analysis_geometry, "analysis")
    if error or geometry is None:
        return None, error
    centroid = geometry.centroid
    origin = _normalized_coordinate((centroid.x, centroid.y))
    return (origin, None) if origin else (None, "project_centroid_invalid")


def _snapshot_type_codes(pois: Sequence[PoiSupplyCandidate]) -> set[str]:
    return {code for poi in pois for code in _split_type_codes(poi.poi_type)}


def _matched_snapshot_type_codes(pois: Sequence[_MatchedPoi]) -> tuple[str, ...]:
    return tuple(sorted({code for poi in pois for code in poi.type_codes}))


def _poi_matches_type_codes(poi_type: str | None, requested: Sequence[str]) -> bool:
    return any(_type_code_matches(code, target) for code in _split_type_codes(poi_type) for target in requested)


def _type_code_matches(poi_code: str, requested_code: str) -> bool:
    if poi_code == requested_code:
        return True
    parent_prefix = requested_code.rstrip("0")
    return len(parent_prefix) >= 2 and poi_code.startswith(parent_prefix)


def _normalized_type_codes(raw: Any) -> tuple[str, ...]:
    values = [raw] if isinstance(raw, str) else raw if isinstance(raw, (list, tuple)) else ()
    return tuple(dict.fromkeys(code for value in values for code in _split_type_codes(str(value))))


def _split_type_codes(value: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(code for part in str(value or "").split("|") if (code := normalize_typecode(part))))


def _normalized_coordinate(value: Any) -> Coordinate | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        return None
    try:
        longitude, latitude = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return longitude, latitude
