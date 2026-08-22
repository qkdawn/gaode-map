"""POI evidence computed strictly within a saved isochrone scope."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Sequence

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from core.poi_taxonomy import get_poi_taxonomy
from modules.scope_datasets.service import ScopeRecord


_DIRECTIONS = (
    ("N", "北", 90.0),
    ("NE", "东北", 45.0),
    ("E", "东", 0.0),
    ("SE", "东南", 315.0),
    ("S", "南", 270.0),
    ("SW", "西南", 225.0),
    ("W", "西", 180.0),
    ("NW", "西北", 135.0),
)


def build_poi_scope_profile(
    poi_records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    *,
    h3_records: Sequence[ScopeRecord] = (),
) -> dict[str, Any]:
    """Describe facility supply and category mix inside one saved isochrone."""

    pois = _covered_points(poi_records, scope_geometry)
    category_counts: Counter[tuple[str, str]] = Counter()
    subcategory_counts: Counter[str] = Counter()
    uncategorized_count = 0
    for record in pois:
        category = resolve_poi_category(record)
        if category is None:
            uncategorized_count += 1
        else:
            category_counts[category] += 1
        subcategory = _subcategory(record)
        if subcategory:
            subcategory_counts[subcategory] += 1

    total = len(pois)
    categorized_total = sum(category_counts.values())
    entropy = _shannon_entropy(category_counts.values())
    observed_categories = len(category_counts)
    normalized_entropy = (
        entropy / math.log(observed_categories)
        if observed_categories > 1
        else 0.0
    )
    area_km2 = _area_km2(scope_geometry)
    local_entropy = []
    in_scope_h3_count = 0
    for record in h3_records:
        if not _overlaps(record.geometry, scope_geometry):
            continue
        in_scope_h3_count += 1
        cell_geometry = record.geometry.intersection(scope_geometry)
        cell_counts = Counter(
            category
            for poi in _covered_points(pois, cell_geometry)
            if (category := resolve_poi_category(poi)) is not None
        )
        local_entropy.append(_shannon_entropy(cell_counts.values()))

    return {
        "spatial_universe": "saved_isochrone",
        "poi_count": total,
        "area_km2": _rounded(area_km2),
        "density_poi_per_km2": _rounded(total / area_km2) if area_km2 > 0 else None,
        "category_count": observed_categories,
        "categorized_poi_count": categorized_total,
        "uncategorized_poi_count": uncategorized_count,
        "categories": [
            {
                "key": key,
                "label": label,
                "count": count,
                "share": _rounded(count / total) if total else 0.0,
            }
            for (key, label), count in sorted(
                category_counts.items(),
                key=lambda item: (-item[1], item[0][1]),
            )
        ],
        "subcategories": [
            {
                "label": label,
                "count": count,
                "share": _rounded(count / total) if total else 0.0,
            }
            for label, count in sorted(
                subcategory_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "mix": {
            "shannon_entropy": _rounded(entropy),
            "normalized_shannon_entropy": _rounded(normalized_entropy),
            "normalization_category_count": observed_categories,
            "local_entropy_distribution": _distribution(local_entropy, in_scope_h3_count),
        },
    }


def build_poi_neighborhood_profile(
    *,
    target: ScopeRecord,
    neighbors: Sequence[ScopeRecord],
    poi_records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    named_limit: int,
) -> dict[str, Any]:
    """Compare one H3 cell with its in-isochrone neighboring cells."""

    target_geometry = target.geometry.intersection(scope_geometry)
    neighbor_geometries = [
        record.geometry.intersection(scope_geometry)
        for record in neighbors
        if record.geometry is not None and _overlaps(record.geometry, scope_geometry)
    ]
    neighborhood_geometry = unary_union(neighbor_geometries) if neighbor_geometries else None
    target_pois = _covered_points(poi_records, target_geometry)
    neighbor_pois = (
        _covered_points(poi_records, neighborhood_geometry)
        if neighborhood_geometry is not None and not neighborhood_geometry.is_empty
        else []
    )
    target_poi_refs = {(record.source_id, record.record_id) for record in target_pois}
    neighbor_pois = [
        record
        for record in neighbor_pois
        if (record.source_id, record.record_id) not in target_poi_refs
    ]
    target_area = _area_km2(target_geometry)
    neighbor_area = _area_km2(neighborhood_geometry)
    target_density = len(target_pois) / target_area if target_area > 0 else None
    neighbor_density = len(neighbor_pois) / neighbor_area if neighbor_area > 0 else None
    neighbor_mean_count = len(neighbor_pois) / len(neighbor_geometries) if neighbor_geometries else None

    named = sorted(
        [*target_pois, *neighbor_pois],
        key=lambda record: (
            0 if record in target_pois else 1,
            _distance_m(target_geometry.centroid, record.geometry.centroid),
            record.title,
            record.record_id,
        ),
    )
    return {
        "spatial_universe": "saved_isochrone",
        "target": {
            "poi_count": len(target_pois),
            "density_poi_per_km2": _rounded(target_density),
            "category_structure": _category_structure(target_pois),
        },
        "neighbors": {
            "cell_count": len(neighbor_geometries),
            "poi_count": len(neighbor_pois),
            "mean_poi_count_per_cell": _rounded(neighbor_mean_count),
            "density_poi_per_km2": _rounded(neighbor_density),
            "category_structure": _category_structure(neighbor_pois),
        },
        "comparison": {
            "poi_count_delta_from_neighbor_mean": _rounded(
                len(target_pois) - neighbor_mean_count
                if neighbor_mean_count is not None
                else None
            ),
            "density_delta_poi_per_km2": _rounded(
                target_density - neighbor_density
                if target_density is not None and neighbor_density is not None
                else None
            ),
        },
        "named_facilities": [
            {
                "record_ref": f"{record.source_id}/{record.record_id}",
                "name": str(record.properties.get("name") or record.title or record.record_id),
                "category": (resolve_poi_category(record) or (None, None))[1],
                "subcategory": _subcategory(record) or None,
                "relation": "inside_target" if record in target_pois else "inside_neighbor",
                "distance_to_target_center_m": round(
                    _distance_m(target_geometry.centroid, record.geometry.centroid),
                    1,
                ),
            }
            for record in named[: max(1, named_limit)]
        ],
    }


def build_poi_direction_profile(
    poi_records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    center: tuple[float, float],
) -> dict[str, Any]:
    """Describe POI supply by direction and its equal-facility spatial distribution."""

    pois = _covered_points(poi_records, scope_geometry)
    groups = []
    for key, label, angle in _DIRECTIONS:
        geometry = _direction_sector(center, scope_geometry, angle)
        members = _covered_points(pois, geometry)
        area_km2 = _area_km2(geometry)
        groups.append({
            "key": key,
            "label": label,
            "poi_count": len(members),
            "poi_share": _rounded(len(members) / len(pois)) if pois else 0.0,
            "area_km2": _rounded(area_km2),
            "density_poi_per_km2": _rounded(len(members) / area_km2) if area_km2 > 0 else None,
            "category_structure": _category_structure(members),
        })
    dominant = max(groups, key=lambda item: (item["poi_count"], item["density_poi_per_km2"] or 0.0), default=None)
    return {
        "spatial_universe": "saved_isochrone",
        "summary": {
            "poi_count": len(pois),
            "dominant_direction": dominant["key"] if dominant else None,
            "dominant_direction_label": dominant["label"] if dominant else None,
            "distribution": _equal_weight_distribution(pois, scope_geometry),
        },
        "groups": groups,
    }


def build_poi_category_colocation_profile(
    poi_records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    category_pair: Sequence[tuple[str, str]],
    *,
    named_pair_limit: int = 20,
) -> dict[str, Any]:
    """Describe directional nearest-neighbor colocation for two POI categories."""

    if len(category_pair) != 2 or category_pair[0] == category_pair[1]:
        raise ValueError("poi_colocation_requires_two_distinct_categories")
    pois = _covered_points(poi_records, scope_geometry)
    categorized = [
        (record, category)
        for record in pois
        if (category := resolve_poi_category(record)) is not None
    ]
    categories = tuple(category_pair)
    category_counts = Counter(category for _, category in categorized)
    points = [record.geometry.centroid for record, _ in categorized]
    tree = STRtree(points) if len(points) >= 2 else None
    coordinate_members: dict[tuple[float, float], list[int]] = {}
    for index, point in enumerate(points):
        coordinate_members.setdefault((float(point.x), float(point.y)), []).append(index)

    directed = [
        _directed_colocation(
            categorized,
            points,
            tree,
            coordinate_members,
            category_counts,
            source_category=source,
            target_category=target,
        )
        for source, target in (categories, categories[::-1])
    ]
    named_pairs = []
    for source_index, (source_record, source_category) in enumerate(categorized):
        if source_category not in categories:
            continue
        target_category = categories[1] if source_category == categories[0] else categories[0]
        for neighbor_index in _nearest_other_indices(
            source_index,
            points,
            tree,
            coordinate_members,
        ):
            neighbor_record, neighbor_category = categorized[neighbor_index]
            if neighbor_category != target_category:
                continue
            named_pairs.append({
                "source_record_ref": f"{source_record.source_id}/{source_record.record_id}",
                "source_name": str(source_record.properties.get("name") or source_record.title or source_record.record_id),
                "source_category": {"key": source_category[0], "label": source_category[1]},
                "nearest_record_ref": f"{neighbor_record.source_id}/{neighbor_record.record_id}",
                "nearest_name": str(neighbor_record.properties.get("name") or neighbor_record.title or neighbor_record.record_id),
                "nearest_category": {"key": neighbor_category[0], "label": neighbor_category[1]},
                "distance_m": round(_distance_m(points[source_index], points[neighbor_index]), 1),
            })
    named_pairs.sort(key=lambda item: (item["distance_m"], item["source_record_ref"], item["nearest_record_ref"]))
    return {
        "spatial_universe": "saved_isochrone",
        "category_pair": [
            {"key": key, "label": label, "poi_count": category_counts[(key, label)]}
            for key, label in categories
        ],
        "categorized_poi_count": len(categorized),
        "uncategorized_poi_count": len(pois) - len(categorized),
        "directed_colocation": directed,
        "named_nearest_pairs": named_pairs[: max(1, int(named_pair_limit))],
    }


def build_poi_inspect_profile(
    *,
    targets: Sequence[ScopeRecord],
    poi_records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
    named_limit: int,
) -> dict[str, Any]:
    """Expand referenced cells into category structure and named facilities."""

    scoped_pois = _covered_points(poi_records, scope_geometry)
    groups = []
    named_facilities = []
    for target in targets:
        target_geometry = target.geometry.intersection(scope_geometry)
        inside = _covered_points(scoped_pois, target_geometry)
        inside_refs = {(record.source_id, record.record_id) for record in inside}
        nearest = sorted(
            (
                record
                for record in scoped_pois
                if (record.source_id, record.record_id) not in inside_refs
            ),
            key=lambda record: (
                _distance_m(target_geometry.centroid, record.geometry.centroid),
                record.title,
                record.record_id,
            ),
        )
        selected = [*inside, *nearest][: max(1, named_limit)]
        area_km2 = _area_km2(target_geometry)
        groups.append({
            "key": f"{target.source_id}/{target.record_id}",
            "poi_count": len(inside),
            "area_km2": _rounded(area_km2),
            "density_poi_per_km2": _rounded(len(inside) / area_km2) if area_km2 > 0 else None,
            "category_structure": _category_structure(inside),
            "named_facility_count": len(selected),
        })
        for record in selected:
            named_facilities.append({
                "record_ref": f"{record.source_id}/{record.record_id}",
                "target_record_ref": f"{target.source_id}/{target.record_id}",
                "name": str(record.properties.get("name") or record.title or record.record_id),
                "category": (resolve_poi_category(record) or (None, None))[1],
                "subcategory": _subcategory(record) or None,
                "relation": "inside_target" if record in inside else "nearest_in_scope",
                "distance_to_target_center_m": round(
                    _distance_m(target_geometry.centroid, record.geometry.centroid),
                    1,
                ),
            })
    return {
        "spatial_universe": "saved_isochrone",
        "summary": {"matched_target_count": len(groups)},
        "groups": groups,
        "named_facilities": named_facilities[:20],
    }


def resolve_poi_category(record_or_value: ScopeRecord | Any) -> tuple[str, str] | None:
    taxonomy = get_poi_taxonomy()
    if isinstance(record_or_value, ScopeRecord):
        record = record_or_value
        category = record.properties.get("category")
        typecode = record.properties.get("typecode") or record.raw.get("typecode")
    else:
        category = record_or_value
        typecode = None

    normalized = str(category or "").strip().casefold()
    aliases = {
        "公司企业": "公司",
        "风景名胜": "旅游",
        "交通设施服务": "交通",
        "购物服务": "购物",
        "餐饮服务": "餐饮",
        "体育休闲服务": "体育",
        "医疗保健服务": "医疗",
        "住宿服务": "住宿",
        "政府机构及社会团体": "政府机构",
        "科教文化服务": "科教文化",
    }
    rules = taxonomy.category_rules()
    by_value = {
        str(value).casefold(): (group_id, label)
        for group_id, label, _ in rules
        for value in (group_id, label)
    }
    alias_label = aliases.get(str(category or "").strip())
    if alias_label:
        resolved_alias = next(
            ((group_id, label) for group_id, label, _ in rules if label == alias_label),
            None,
        )
        if resolved_alias is not None:
            return resolved_alias
    if normalized in by_value:
        return by_value[normalized]
    item = taxonomy.resolve_typecode(typecode)
    return (item.group_id, item.main_category) if item is not None else None


def _category_structure(records: Sequence[ScopeRecord]) -> list[dict[str, Any]]:
    counts = Counter(
        category
        for record in records
        if (category := resolve_poi_category(record)) is not None
    )
    total = len(records)
    return [
        {"key": key, "label": label, "count": count, "share": _rounded(count / total) if total else 0.0}
        for (key, label), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][1]))
    ]


def _covered_points(records: Sequence[ScopeRecord], geometry: BaseGeometry) -> list[ScopeRecord]:
    if geometry is None or geometry.is_empty:
        return []
    return [
        record
        for record in records
        if record.geometry is not None
        and not record.geometry.is_empty
        and geometry.covers(record.geometry)
    ]


def _subcategory(record: ScopeRecord) -> str:
    direct = str(record.properties.get("subcategory") or "").strip()
    if direct:
        return direct
    typecode = record.properties.get("typecode") or record.raw.get("typecode")
    item = get_poi_taxonomy().resolve_typecode(typecode)
    return item.subcategory if item is not None else ""


def _shannon_entropy(values: Sequence[int]) -> float:
    total = sum(max(0, int(value)) for value in values)
    if total <= 0:
        return 0.0
    return -sum(
        (value / total) * math.log(value / total)
        for value in values
        if value > 0
    )


def _distribution(values: Sequence[float], total_count: int) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"valid_count": 0, "missing_count": total_count}
    return {
        "valid_count": len(ordered),
        "missing_count": max(0, total_count - len(ordered)),
        "min": _rounded(ordered[0]),
        "mean": _rounded(sum(ordered) / len(ordered)),
        "max": _rounded(ordered[-1]),
    }


def _overlaps(left: BaseGeometry | None, right: BaseGeometry) -> bool:
    if left is None or left.is_empty or right.is_empty:
        return False
    intersection = left.intersection(right)
    return not intersection.is_empty and intersection.area > 0


def _area_km2(geometry: BaseGeometry | None) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    centroid = geometry.centroid
    scale_x = 111.32 * math.cos(math.radians(float(centroid.y)))
    return abs(float(geometry.area)) * scale_x * 110.574


def _distance_m(left: BaseGeometry, right: BaseGeometry) -> float:
    lat = math.radians((float(left.y) + float(right.y)) / 2.0)
    dx = (float(right.x) - float(left.x)) * 111_320.0 * math.cos(lat)
    dy = (float(right.y) - float(left.y)) * 110_574.0
    return math.hypot(dx, dy)


def _direction_sector(
    center: tuple[float, float],
    scope_geometry: BaseGeometry,
    angle: float,
) -> BaseGeometry:
    min_x, min_y, max_x, max_y = scope_geometry.bounds
    radius = max(
        math.hypot(x - center[0], y - center[1])
        for x, y in ((min_x, min_y), (min_x, max_y), (max_x, min_y), (max_x, max_y))
    ) * 4.0
    low = math.radians(angle - 22.5)
    high = math.radians(angle + 22.5)
    sector = Polygon([
        center,
        (center[0] + math.cos(low) * radius, center[1] + math.sin(low) * radius),
        (center[0] + math.cos(high) * radius, center[1] + math.sin(high) * radius),
        center,
    ])
    return sector.intersection(scope_geometry)


def _equal_weight_distribution(
    records: Sequence[ScopeRecord],
    scope_geometry: BaseGeometry,
) -> dict[str, Any]:
    origin = scope_geometry.centroid
    lon0 = float(origin.x)
    lat0 = float(origin.y)
    radius_m = 6_371_008.8
    longitude_scale = math.cos(math.radians(lat0))
    samples = []
    for record in records:
        point = record.geometry.centroid
        x = radius_m * math.radians(float(point.x) - lon0) * longitude_scale
        y = radius_m * math.radians(float(point.y) - lat0)
        samples.append((x, y))
    if not samples or abs(longitude_scale) <= 1e-12:
        return {
            "weighted_center_wgs84": None,
            "standard_deviation_ellipse": None,
            "facility_count": 0,
        }
    mean_x = sum(x for x, _ in samples) / len(samples)
    mean_y = sum(y for _, y in samples) / len(samples)
    variance_x = sum((x - mean_x) ** 2 for x, _ in samples) / len(samples)
    variance_y = sum((y - mean_y) ** 2 for _, y in samples) / len(samples)
    covariance_xy = sum((x - mean_x) * (y - mean_y) for x, y in samples) / len(samples)
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
        "weighted_center_wgs84": [round(center_lon, 6), round(center_lat, 6)],
        "standard_deviation_ellipse": {
            "major_axis_standard_distance_m": round(math.sqrt(major_variance), 1),
            "minor_axis_standard_distance_m": round(math.sqrt(minor_variance), 1),
            "orientation_degrees_clockwise_from_north": round(orientation, 1),
        },
        "facility_count": len(samples),
    }


def _directed_colocation(
    categorized: Sequence[tuple[ScopeRecord, tuple[str, str]]],
    points: Sequence[BaseGeometry],
    tree: STRtree | None,
    coordinate_members: dict[tuple[float, float], list[int]],
    category_counts: Counter[tuple[str, str]],
    *,
    source_category: tuple[str, str],
    target_category: tuple[str, str],
) -> dict[str, Any]:
    source_indices = [
        index
        for index, (_, category) in enumerate(categorized)
        if category == source_category
    ]
    target_count = category_counts[target_category]
    eligible_source_count = 0
    target_neighbor_weight = 0.0
    for source_index in source_indices:
        nearest = _nearest_other_indices(
            source_index,
            points,
            tree,
            coordinate_members,
        )
        if not nearest:
            continue
        eligible_source_count += 1
        target_neighbor_weight += sum(
            categorized[index][1] == target_category
            for index in nearest
        ) / len(nearest)
    total_count = len(categorized)
    observed_share = (
        target_neighbor_weight / eligible_source_count
        if eligible_source_count
        else None
    )
    expected_share = target_count / (total_count - 1) if total_count > 1 else None
    quotient = (
        observed_share / expected_share
        if observed_share is not None and expected_share is not None and expected_share > 0
        else None
    )
    return {
        "source_category": {"key": source_category[0], "label": source_category[1]},
        "neighbor_category": {"key": target_category[0], "label": target_category[1]},
        "source_poi_count": len(source_indices),
        "eligible_source_poi_count": eligible_source_count,
        "target_poi_count": target_count,
        "nearest_neighbor_target_weight": _rounded(target_neighbor_weight),
        "observed_nearest_neighbor_share": _rounded(observed_share),
        "expected_scope_share": _rounded(expected_share),
        "clq": _rounded(quotient),
    }


def _nearest_other_indices(
    source_index: int,
    points: Sequence[BaseGeometry],
    tree: STRtree | None,
    coordinate_members: dict[tuple[float, float], list[int]],
) -> list[int]:
    if tree is None:
        return []
    point = points[source_index]
    coincident = [
        index
        for index in coordinate_members.get((float(point.x), float(point.y)), ())
        if index != source_index
    ]
    if coincident:
        return coincident
    indices = tree.query_nearest(point, exclusive=True, all_matches=True)
    return sorted({int(index) for index in indices if int(index) != source_index})


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)
