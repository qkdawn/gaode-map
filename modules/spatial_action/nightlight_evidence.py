"""Nightlight evidence computed within one saved isochrone.

The public operation is the question semantic.  Radiance summaries are an
implementation detail and never act as evidence of visits, spending, or use.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Sequence

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from modules.scope_datasets.service import ScopeRecord


_DIRECTIONS = (
    ("north", "北"),
    ("northeast", "东北"),
    ("east", "东"),
    ("southeast", "东南"),
    ("south", "南"),
    ("southwest", "西南"),
    ("west", "西"),
    ("northwest", "西北"),
)


def build_nightlight_scope_profile(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
) -> dict[str, Any]:
    """Describe brightness coverage, distribution, and concentration."""

    observations = _observations(records, scope_geometry)
    profile = _profile(observations, scope_geometry)
    profile["spatial_distribution"] = _weighted_distribution(observations, scope_geometry)
    profile["center_edge_gradient"] = _center_edge_gradient(observations, scope_geometry)
    profile["quality_diagnostics"] = _quality_diagnostics(records, observations, scope_geometry)
    return profile


def build_nightlight_accessibility_profile(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    band_geometries: Sequence[tuple[tuple[float, float], BaseGeometry]],
) -> dict[str, Any]:
    """Compare incremental and cumulative brightness inside network-time bands."""

    groups: list[dict[str, Any]] = []
    cumulative_geometries: list[BaseGeometry] = []
    for band, geometry in band_geometries:
        cumulative_geometries.append(geometry)
        cumulative = unary_union(cumulative_geometries).intersection(scope_geometry)
        key = f"{_format_number(band[0])}-{_format_number(band[1])}min"
        groups.append({
            "key": key,
            "travel_time_band_min": [float(band[0]), float(band[1])],
            "incremental": _profile(_observations(records, geometry), geometry),
            "cumulative": _profile(_observations(records, cumulative), cumulative),
        })
    return {
        "summary": _profile(_observations(records, scope_geometry), scope_geometry),
        "groups": groups,
    }


def build_nightlight_direction_profile(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    center: tuple[float, float],
) -> dict[str, Any]:
    """Compare eight directions using only cells covered by the isochrone."""

    all_observations = _observations(records, scope_geometry)
    sectors = _direction_sectors(scope_geometry, center)
    total_index = sum(item.radiance * item.weight for item in all_observations)
    groups = []
    for key, label in _DIRECTIONS:
        geometry = sectors[key]
        observations = _clip_observations(all_observations, geometry)
        profile = _profile(observations, geometry)
        direction_index = sum(item.radiance * item.weight for item in observations)
        groups.append({
            "key": key,
            "label": label,
            **profile,
            "radiance_index_share": _rounded(direction_index / total_index) if total_index > 0 else 0.0,
        })
    ranked = sorted(
        (group for group in groups if group["valid_cell_count"]),
        key=lambda group: (group.get("mean_radiance") or 0.0, group["radiance_index_share"]),
        reverse=True,
    )
    return {
        "summary": {
            "dominant_direction": ranked[0]["label"] if ranked else None,
            "secondary_direction": ranked[1]["label"] if len(ranked) > 1 else None,
            "valid_cell_count": len(all_observations),
            "comparison_basis": "area_weighted_mean_radiance_within_saved_isochrone",
            "spatial_distribution": _weighted_distribution(all_observations, scope_geometry),
        },
        "groups": groups,
    }


def build_nightlight_neighborhood_profile(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    record_refs: Sequence[str],
    *,
    neighbor_steps: int,
) -> dict[str, Any]:
    """Compare referenced nightlight cells with their geometric neighbors."""

    cells = [record for record in records if _usable_record(record, scope_geometry)]
    targets = [record for record in cells if _record_ref(record) in set(record_refs)]
    groups = []
    for target in targets:
        neighbors = _neighbors(cells, target, neighbor_steps)
        target_profile = _profile(_observations([target], scope_geometry), target.geometry.intersection(scope_geometry))
        neighbor_geometry = unary_union([record.geometry for record in neighbors]).intersection(scope_geometry) if neighbors else None
        neighbor_profile = _profile(_observations(neighbors, scope_geometry), neighbor_geometry)
        target_mean = target_profile.get("mean_radiance")
        neighbor_mean = neighbor_profile.get("mean_radiance")
        groups.append({
            "key": _record_ref(target),
            "target": target_profile,
            "neighbors": {"cell_count": len(neighbors), **neighbor_profile},
            "contrast": {
                "mean_radiance_delta": _rounded(
                    target_mean - neighbor_mean
                    if target_mean is not None and neighbor_mean is not None
                    else None
                ),
                "target_to_neighbor_ratio": _rounded(
                    target_mean / neighbor_mean
                    if target_mean is not None and neighbor_mean not in (None, 0)
                    else None
                ),
            },
        })
    return {
        "summary": {"target_count": len(targets), "neighbor_steps": int(neighbor_steps)},
        "groups": groups,
    }


def build_nightlight_rank_profile(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    center: tuple[float, float],
    *,
    rank_order: str,
    top_k: int,
) -> dict[str, Any]:
    """Return the brightest or darkest valid in-isochrone cells."""

    observations = _observations(records, scope_geometry)
    ordered = sorted(
        observations,
        key=lambda item: (item.radiance, item.record.record_id),
        reverse=rank_order == "highest",
    )
    highlights = []
    for rank, observation in enumerate(ordered[:top_k], start=1):
        centroid = observation.geometry.centroid
        distance_m, direction = _distance_direction(center, (float(centroid.x), float(centroid.y)))
        highlights.append({
            "rank": rank,
            "record_ref": _record_ref(observation.record),
            "title": observation.record.title,
            "radiance": _rounded(observation.radiance),
            "year": observation.record.properties.get("year") or observation.record.time_scope.get("year"),
            "scope_coverage_fraction": _rounded(observation.coverage_fraction),
            "direction": direction,
            "straight_line_distance_m": round(distance_m, 1),
        })
    return {
        "summary": {
            "ranked_measure": "cell_mean_radiance",
            "order": rank_order,
            "valid_cell_count": len(observations),
        },
        "highlights": highlights,
    }


def build_nightlight_inspect_profile(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    center: tuple[float, float],
    record_refs: Sequence[str],
) -> dict[str, Any]:
    """Explain a referenced cell against the isochrone and its local context."""

    observations = _observations(records, scope_geometry)
    by_ref = {_record_ref(item.record): item for item in observations}
    ordered_values = sorted(item.radiance for item in observations)
    highlights = []
    for record_ref in record_refs:
        observation = by_ref.get(record_ref)
        if observation is None:
            continue
        neighbors = _neighbors([item.record for item in observations], observation.record, 1)
        neighbor_values = [value for record in neighbors if (value := _radiance(record)) is not None]
        centroid = observation.geometry.centroid
        distance_m, direction = _distance_direction(center, (float(centroid.x), float(centroid.y)))
        percentile = (
            sum(value <= observation.radiance for value in ordered_values) / len(ordered_values)
            if ordered_values
            else None
        )
        highlights.append({
            "record_ref": record_ref,
            "title": observation.record.title,
            "radiance": _rounded(observation.radiance),
            "year": observation.record.properties.get("year") or observation.record.time_scope.get("year"),
            "within_scope_percentile": _rounded(percentile),
            "neighbor_cell_count": len(neighbor_values),
            "neighbor_mean_radiance": _rounded(sum(neighbor_values) / len(neighbor_values)) if neighbor_values else None,
            "direction": direction,
            "straight_line_distance_m": round(distance_m, 1),
            "scope_coverage_fraction": _rounded(observation.coverage_fraction),
            "quality": {
                key: observation.record.properties.get(key)
                for key in ("cf_cvg", "observation_count", "valid_pixel_count", "quality_flag")
                if observation.record.properties.get(key) is not None
            },
        })
    return {
        "summary": {
            "matched_record_count": len(highlights),
            "comparison_basis": "within_saved_isochrone_distribution_and_immediate_neighbors",
        },
        "highlights": highlights,
    }


def build_nightlight_change_profile(
    records_by_year: dict[int, Sequence[ScopeRecord]],
    scope_geometry: BaseGeometry,
    center: tuple[float, float],
    *,
    analysis: str,
    record_refs: Sequence[str] = (),
    neighbor_steps: int = 1,
    rank_order: str = "highest",
    top_k: int = 10,
) -> dict[str, Any]:
    """Describe annual radiance change without trend or emerging-hotspot claims."""

    years = sorted(records_by_year)
    if len(years) < 2:
        return {"summary": {"year_count": len(years)}, "groups": [], "highlights": []}
    first_year, last_year = years[0], years[-1]
    by_year = {
        year: {
            _stable_cell_id(record): record
            for record in records
            if _usable_record(record, scope_geometry)
        }
        for year, records in records_by_year.items()
    }
    common_ids = sorted(set(by_year[first_year]) & set(by_year[last_year]))
    changes = []
    for cell_id in common_ids:
        first = by_year[first_year][cell_id]
        last = by_year[last_year][cell_id]
        before = _radiance(first)
        after = _radiance(last)
        if before is None or after is None:
            continue
        clipped = last.geometry.intersection(scope_geometry)
        centroid = clipped.centroid
        changes.append({
            "cell_id": cell_id,
            "record": last,
            "geometry": clipped,
            "yearly_radiance": [
                {"year": year, "radiance": _rounded(_radiance(by_year[year][cell_id]))}
                for year in years
                if cell_id in by_year[year] and _radiance(by_year[year][cell_id]) is not None
            ],
            "from_radiance": _rounded(before),
            "to_radiance": _rounded(after),
            "delta_radiance": _rounded(after - before),
            "change_rate": _rounded((after - before) / before if before > 0 else None),
            "direction": _distance_direction(center, (float(centroid.x), float(centroid.y)))[1],
        })
    summary = {
        "period": f"{first_year}-{last_year}",
        "year_count": len(years),
        "matched_cell_count": len(changes),
        "change_class_counts": {
            "increase": sum(float(item["delta_radiance"] or 0.0) > 0 for item in changes),
            "decrease": sum(float(item["delta_radiance"] or 0.0) < 0 for item in changes),
            "stable": sum(float(item["delta_radiance"] or 0.0) == 0 for item in changes),
        },
        "brightness_center_migration": _brightness_center_migration(
            records_by_year[first_year],
            records_by_year[last_year],
            scope_geometry,
        ),
        "time_series_semantics": "descriptive_annual_change",
    }
    if analysis == "direction":
        sectors = _direction_sectors(scope_geometry, center)
        groups = []
        for key, label in _DIRECTIONS:
            members = []
            for item in changes:
                intersection = item["geometry"].intersection(sectors[key])
                weight = float(intersection.area)
                if not intersection.is_empty and weight > 0:
                    members.append((item, weight))
            total_weight = sum(weight for _, weight in members)
            groups.append({
                "key": key,
                "label": label,
                "cell_count": len(members),
                "mean_delta_radiance": _rounded(
                    sum(float(item["delta_radiance"] or 0.0) * weight for item, weight in members)
                    / total_weight
                    if total_weight > 0 else None
                ),
                "increase_cell_count": sum(float(item["delta_radiance"] or 0.0) > 0 for item, _ in members),
                "decrease_cell_count": sum(float(item["delta_radiance"] or 0.0) < 0 for item, _ in members),
                "allocation": "cell_sector_intersection_area",
            })
        return {"summary": summary, "groups": groups, "highlights": []}
    if analysis == "neighborhood":
        selected_refs = set(record_refs)
        targets = [item for item in changes if _record_ref(item["record"]) in selected_refs]
        change_by_ref = {_record_ref(item["record"]): item for item in changes}
        groups = []
        for target in targets:
            neighbors = _neighbors(
                [item["record"] for item in changes],
                target["record"],
                neighbor_steps,
            )
            neighbor_deltas = [
                float(change_by_ref[_record_ref(record)]["delta_radiance"] or 0.0)
                for record in neighbors
                if _record_ref(record) in change_by_ref
            ]
            neighbor_mean = sum(neighbor_deltas) / len(neighbor_deltas) if neighbor_deltas else None
            groups.append({
                "key": _record_ref(target["record"]),
                "target_delta_radiance": target["delta_radiance"],
                "neighbor_count": len(neighbor_deltas),
                "neighbor_mean_delta_radiance": _rounded(neighbor_mean),
                "delta_from_neighbor_mean": _rounded(
                    float(target["delta_radiance"] or 0.0) - neighbor_mean
                    if neighbor_mean is not None else None
                ),
            })
        return {"summary": summary, "groups": groups, "highlights": []}
    selected = changes
    if analysis == "inspect":
        selected_refs = set(record_refs)
        selected = [item for item in changes if _record_ref(item["record"]) in selected_refs]
    ordered = sorted(
        selected,
        key=lambda item: (float(item["delta_radiance"] or 0.0), item["cell_id"]),
        reverse=rank_order == "highest",
    )
    highlights = [
        {
            "rank": index,
            "record_ref": _record_ref(item["record"]),
            "cell_id": item["cell_id"],
            "from_year": first_year,
            "to_year": last_year,
            "from_radiance": item["from_radiance"],
            "to_radiance": item["to_radiance"],
            "delta_radiance": item["delta_radiance"],
            "change_rate": item["change_rate"],
            "direction": item["direction"],
            "yearly_radiance": item["yearly_radiance"],
        }
        for index, item in enumerate(ordered[:top_k], start=1)
    ]
    return {"summary": summary, "groups": [], "highlights": highlights}


class _Observation:
    __slots__ = ("record", "geometry", "radiance", "coverage_fraction", "weight")

    def __init__(
        self,
        record: ScopeRecord,
        geometry: BaseGeometry,
        radiance: float,
        coverage_fraction: float,
        weight: float,
    ) -> None:
        self.record = record
        self.geometry = geometry
        self.radiance = radiance
        self.coverage_fraction = coverage_fraction
        self.weight = weight


def _observations(records: Sequence[ScopeRecord], geometry: BaseGeometry) -> list[_Observation]:
    if geometry is None or geometry.is_empty:
        return []
    observations = []
    for record in records:
        if not _usable_record(record, geometry):
            continue
        radiance = _radiance(record)
        if radiance is None:
            continue
        intersection = record.geometry.intersection(geometry)
        weight = float(intersection.area)
        if weight <= 0:
            continue
        coverage_fraction = weight / float(record.geometry.area) if record.geometry.area > 0 else 0.0
        observations.append(_Observation(record, intersection, radiance, coverage_fraction, weight))
    return observations


def _clip_observations(
    observations: Sequence[_Observation],
    geometry: BaseGeometry,
) -> list[_Observation]:
    clipped = []
    for observation in observations:
        intersection = observation.geometry.intersection(geometry)
        weight = float(intersection.area)
        if intersection.is_empty or weight <= 0:
            continue
        source_area = float(observation.record.geometry.area)
        clipped.append(_Observation(
            observation.record,
            intersection,
            observation.radiance,
            weight / source_area if source_area > 0 else 0.0,
            weight,
        ))
    return clipped


def _direction_sectors(
    scope_geometry: BaseGeometry,
    center: tuple[float, float],
) -> dict[str, BaseGeometry]:
    """Partition the full scope into eight wedges around the project center."""

    minx, miny, maxx, maxy = scope_geometry.bounds
    radius = max(
        math.hypot(x - center[0], y - center[1])
        for x in (minx, maxx)
        for y in (miny, maxy)
    ) * 2.0
    radius = max(radius, 1e-9)
    sectors: dict[str, BaseGeometry] = {}
    for index, (key, _) in enumerate(_DIRECTIONS):
        center_bearing = index * 45.0
        bearings = [center_bearing - 22.5 + step * 2.5 for step in range(19)]
        arc = [
            (
                center[0] + math.sin(math.radians(bearing)) * radius,
                center[1] + math.cos(math.radians(bearing)) * radius,
            )
            for bearing in bearings
        ]
        wedge = Polygon([center, *arc, center])
        sectors[key] = scope_geometry.intersection(wedge)
    return sectors


def _profile(observations: Sequence[_Observation], geometry: BaseGeometry | None) -> dict[str, Any]:
    area_km2 = _area_km2(geometry)
    if not observations:
        return {
            "area_km2": _rounded(area_km2),
            "valid_cell_count": 0,
            "mean_radiance": None,
            "median_radiance": None,
            "p90_radiance": None,
            "max_radiance": None,
            "lit_area_ratio": None,
            "radiance_sum_index": None,
            "top_20_percent_area_radiance_share": None,
        }
    total_weight = sum(item.weight for item in observations)
    weighted_mean = sum(item.radiance * item.weight for item in observations) / total_weight
    radiance_index = sum(item.radiance * item.coverage_fraction for item in observations)
    return {
        "area_km2": _rounded(area_km2),
        "valid_cell_count": len(observations),
        "mean_radiance": _rounded(weighted_mean),
        "median_radiance": _rounded(_weighted_quantile(observations, 0.5)),
        "p90_radiance": _rounded(_weighted_quantile(observations, 0.9)),
        "max_radiance": _rounded(max(item.radiance for item in observations)),
        "lit_area_ratio": _rounded(
            sum(item.weight for item in observations if item.radiance > 0) / total_weight
        ),
        "radiance_sum_index": _rounded(radiance_index),
        "top_20_percent_area_radiance_share": _rounded(_top_area_radiance_share(observations, 0.2)),
    }


def _weighted_quantile(observations: Sequence[_Observation], quantile: float) -> float | None:
    ordered = sorted(observations, key=lambda item: item.radiance)
    total_weight = sum(item.weight for item in ordered)
    if total_weight <= 0:
        return None
    threshold = total_weight * quantile
    cumulative = 0.0
    for item in ordered:
        cumulative += item.weight
        if cumulative >= threshold:
            return item.radiance
    return ordered[-1].radiance


def _top_area_radiance_share(observations: Sequence[_Observation], area_fraction: float) -> float | None:
    total_area = sum(item.weight for item in observations)
    total_radiance = sum(item.radiance * item.weight for item in observations)
    if total_area <= 0 or total_radiance <= 0:
        return None
    remaining_area = total_area * area_fraction
    selected_radiance = 0.0
    for item in sorted(observations, key=lambda value: value.radiance, reverse=True):
        used_area = min(item.weight, remaining_area)
        selected_radiance += item.radiance * used_area
        remaining_area -= used_area
        if remaining_area <= 1e-15:
            break
    return selected_radiance / total_radiance


def _weighted_distribution(
    observations: Sequence[_Observation],
    scope_geometry: BaseGeometry,
) -> dict[str, Any]:
    origin = scope_geometry.centroid
    lon0 = float(origin.x)
    lat0 = float(origin.y)
    radius_m = 6_371_008.8
    longitude_scale = math.cos(math.radians(lat0))
    samples = []
    for observation in observations:
        weight = observation.radiance * observation.weight
        if weight <= 0:
            continue
        point = observation.geometry.centroid
        x = radius_m * math.radians(float(point.x) - lon0) * longitude_scale
        y = radius_m * math.radians(float(point.y) - lat0)
        samples.append((x, y, weight))
    total_weight = sum(weight for _, _, weight in samples)
    if total_weight <= 0 or abs(longitude_scale) <= 1e-12:
        return {
            "brightness_weighted_center_wgs84": None,
            "standard_deviation_ellipse": None,
            "weighted_cell_count": 0,
        }
    mean_x = sum(x * weight for x, _, weight in samples) / total_weight
    mean_y = sum(y * weight for _, y, weight in samples) / total_weight
    variance_x = sum(weight * (x - mean_x) ** 2 for x, _, weight in samples) / total_weight
    variance_y = sum(weight * (y - mean_y) ** 2 for _, y, weight in samples) / total_weight
    covariance_xy = sum(
        weight * (x - mean_x) * (y - mean_y)
        for x, y, weight in samples
    ) / total_weight
    trace = variance_x + variance_y
    delta = math.sqrt(max(0.0, (variance_x - variance_y) ** 2 + 4.0 * covariance_xy ** 2))
    major_variance = max(0.0, (trace + delta) / 2.0)
    minor_variance = max(0.0, (trace - delta) / 2.0)
    if abs(covariance_xy) > 1e-12:
        vector_x = major_variance - variance_y
        vector_y = covariance_xy
    elif variance_x >= variance_y:
        vector_x, vector_y = 1.0, 0.0
    else:
        vector_x, vector_y = 0.0, 1.0
    orientation = math.degrees(math.atan2(vector_x, vector_y)) % 180.0
    center_lon = lon0 + math.degrees(mean_x / (radius_m * longitude_scale))
    center_lat = lat0 + math.degrees(mean_y / radius_m)
    return {
        "brightness_weighted_center_wgs84": [round(center_lon, 6), round(center_lat, 6)],
        "standard_deviation_ellipse": {
            "major_axis_standard_distance_m": round(math.sqrt(major_variance), 1),
            "minor_axis_standard_distance_m": round(math.sqrt(minor_variance), 1),
            "orientation_degrees_clockwise_from_north": round(orientation, 1),
        },
        "weighted_cell_count": len(samples),
    }


def _center_edge_gradient(
    observations: Sequence[_Observation],
    scope_geometry: BaseGeometry,
) -> dict[str, Any]:
    if not observations:
        return {
            "inner_mean_radiance": None,
            "outer_mean_radiance": None,
            "inner_to_outer_ratio": None,
            "radial_split": "half_maximum_cell_centroid_distance_from_scope_center",
        }
    center = scope_geometry.centroid
    distances = [center.distance(item.geometry.centroid) for item in observations]
    maximum = max(distances, default=0.0)
    threshold = maximum / 2.0
    inner = [item for item, distance in zip(observations, distances) if distance <= threshold]
    outer = [item for item, distance in zip(observations, distances) if distance > threshold]

    def mean(items: Sequence[_Observation]) -> float | None:
        weight = sum(item.weight for item in items)
        return sum(item.radiance * item.weight for item in items) / weight if weight > 0 else None

    inner_mean = mean(inner)
    outer_mean = mean(outer)
    return {
        "inner_mean_radiance": _rounded(inner_mean),
        "outer_mean_radiance": _rounded(outer_mean),
        "inner_to_outer_ratio": _rounded(
            inner_mean / outer_mean
            if inner_mean is not None and outer_mean not in (None, 0)
            else None
        ),
        "radial_split": "half_maximum_cell_centroid_distance_from_scope_center",
    }


def _quality_diagnostics(
    records: Sequence[ScopeRecord],
    observations: Sequence[_Observation],
    scope_geometry: BaseGeometry,
) -> dict[str, Any]:
    intersecting = [
        record
        for record in records
        if record.geometry is not None
        and not record.geometry.is_empty
        and record.geometry.intersection(scope_geometry).area > 0
    ]
    quality_fields = ("cf_cvg", "observation_count", "valid_pixel_count", "quality_flag")
    available_fields = [
        field
        for field in quality_fields
        if any(record.properties.get(field) is not None for record in intersecting)
    ]
    return {
        "intersecting_cell_count": len(intersecting),
        "valid_radiance_cell_count": len(observations),
        "excluded_invalid_cell_count": max(0, len(intersecting) - len(observations)),
        "available_quality_fields": available_fields,
        "observation_quality_available": bool(available_fields),
        "limitation": (
            None
            if available_fields
            else "当前快照未提供观测次数或质量标记，无法识别低质量像元。"
        ),
    }


def _stable_cell_id(record: ScopeRecord) -> str:
    return str(record.properties.get("cell_id") or record.record_id)


def _brightness_center_migration(
    first_records: Sequence[ScopeRecord],
    last_records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
) -> dict[str, Any]:
    first = _weighted_distribution(_observations(first_records, scope_geometry), scope_geometry)
    last = _weighted_distribution(_observations(last_records, scope_geometry), scope_geometry)
    first_center = first.get("brightness_weighted_center_wgs84")
    last_center = last.get("brightness_weighted_center_wgs84")
    if not isinstance(first_center, list) or not isinstance(last_center, list):
        return {"from_center_wgs84": first_center, "to_center_wgs84": last_center, "distance_m": None, "direction": None}
    distance_m, direction = _distance_direction(
        (float(first_center[0]), float(first_center[1])),
        (float(last_center[0]), float(last_center[1])),
    )
    return {
        "from_center_wgs84": first_center,
        "to_center_wgs84": last_center,
        "distance_m": round(distance_m, 1),
        "direction": direction,
    }


def _neighbors(records: Sequence[ScopeRecord], target: ScopeRecord, steps: int) -> list[ScopeRecord]:
    pool = [record for record in records if record is not target and record.geometry is not None]
    sizes = [
        max(record.geometry.bounds[2] - record.geometry.bounds[0], record.geometry.bounds[3] - record.geometry.bounds[1])
        for record in records
        if record.geometry is not None and not record.geometry.is_empty
    ]
    tolerance = (median(sizes) * 0.15) if sizes else 1e-12

    def adjacent(left: ScopeRecord, right: ScopeRecord) -> bool:
        left_center = left.geometry.centroid
        right_center = right.geometry.centroid
        left_size = max(left.geometry.bounds[2] - left.geometry.bounds[0], left.geometry.bounds[3] - left.geometry.bounds[1])
        right_size = max(right.geometry.bounds[2] - right.geometry.bounds[0], right.geometry.bounds[3] - right.geometry.bounds[1])
        return (
            left.geometry.distance(right.geometry) <= tolerance
            and left_center.distance(right_center) <= max(left_size, right_size) * 1.7
        )

    selected: dict[str, ScopeRecord] = {}
    frontier = [target]
    for _ in range(max(1, int(steps))):
        next_frontier = []
        for candidate in pool:
            ref = _record_ref(candidate)
            if ref in selected or any(adjacent(item, candidate) for item in frontier):
                if ref not in selected and any(adjacent(item, candidate) for item in frontier):
                    selected[ref] = candidate
                    next_frontier.append(candidate)
        frontier = next_frontier
        if not frontier:
            break
    return list(selected.values())


def _usable_record(record: ScopeRecord, geometry: BaseGeometry) -> bool:
    if record.geometry is None or record.geometry.is_empty or geometry.is_empty:
        return False
    intersection = record.geometry.intersection(geometry)
    return not intersection.is_empty and intersection.area > 0 and _radiance(record) is not None


def _radiance(record: ScopeRecord) -> float | None:
    value = record.properties.get("radiance")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, number) if math.isfinite(number) else None


def _record_ref(record: ScopeRecord) -> str:
    return f"{record.source_id}/{record.record_id}"


def _direction_key(center: tuple[float, float], point: tuple[float, float]) -> str:
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    return _DIRECTIONS[int(((bearing + 22.5) % 360.0) // 45.0)][0]


def _distance_direction(center: tuple[float, float], point: tuple[float, float]) -> tuple[float, str]:
    lat = math.radians((center[1] + point[1]) / 2.0)
    dx = (point[0] - center[0]) * 111_320.0 * math.cos(lat)
    dy = (point[1] - center[1]) * 110_574.0
    return math.hypot(dx, dy), dict(_DIRECTIONS)[_direction_key(center, point)]


def _area_km2(geometry: BaseGeometry | None) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    centroid = geometry.centroid
    scale_x = 111.32 * math.cos(math.radians(float(centroid.y)))
    return abs(float(geometry.area)) * scale_x * 110.574


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(float(value))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)
