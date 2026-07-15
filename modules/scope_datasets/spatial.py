from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, transform
from shapely.strtree import STRtree

from modules.providers.amap.utils.transform_posi import (
    gcj02_to_wgs84,
    wgs84_to_gcj02,
)


SUPPORTED_SPATIAL_RELATIONS = {
    "at_point",
    "nearest",
    "within_distance",
    "intersects",
}
EARTH_RADIUS_M = 6_378_137.0
MAX_INDEX_CACHE_ENTRIES = 32


class SpatialQueryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(message)


@dataclass(frozen=True)
class SpatialMatch:
    relation: str
    distance_m: float | None = None
    geometry_type: str = ""
    matched_point: list[float] | None = None
    overlap_area_m2: float | None = None
    record_overlap_ratio: float | None = None
    query_overlap_ratio: float | None = None
    intersection_length_m: float | None = None
    coord_type: str = "wgs84"
    calculation_crs: str = "local_equirectangular"
    distance_unit: str = "m"

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "relation": self.relation,
            "geometry_type": self.geometry_type,
            "coord_type": self.coord_type,
            "calculation_crs": self.calculation_crs,
            "distance_unit": self.distance_unit,
        }
        optional = {
            "distance_m": self.distance_m,
            "matched_point": self.matched_point,
            "overlap_area_m2": self.overlap_area_m2,
            "record_overlap_ratio": self.record_overlap_ratio,
            "query_overlap_ratio": self.query_overlap_ratio,
            "intersection_length_m": self.intersection_length_m,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return payload


@dataclass(frozen=True)
class SpatialQueryResult:
    matches: dict[int, SpatialMatch]
    warnings: list[str]
    skipped_record_count: int


@dataclass
class _SpatialIndex:
    geometries: list[BaseGeometry]
    record_positions: list[int]
    tree: STRtree


_INDEX_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: OrderedDict[str, _SpatialIndex] = OrderedDict()


def clear_spatial_index_cache() -> None:
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE.clear()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _transform_geometry(geometry: BaseGeometry, coord_type: str) -> BaseGeometry:
    normalized = str(coord_type or "").strip().lower()
    if normalized == "wgs84":
        return geometry
    if normalized == "gcj02":
        return transform(
            lambda x, y, z=None: _transform_xy(x, y, gcj02_to_wgs84),
            geometry,
        )
    raise SpatialQueryError("spatial_coord_type_unknown", f"不支持的空间坐标系: {coord_type}")


def _transform_xy(x: Any, y: Any, converter):
    if hasattr(x, "__iter__"):
        converted = [converter(float(px), float(py)) for px, py in zip(x, y)]
        xs, ys = zip(*converted) if converted else ((), ())
        return tuple(xs), tuple(ys)
    return converter(float(x), float(y))


def normalize_geometry(value: Any, coord_type: str) -> BaseGeometry:
    if isinstance(value, BaseGeometry):
        geometry = value
    elif isinstance(value, dict):
        try:
            geometry = shape(value)
        except Exception as exc:
            raise SpatialQueryError("spatial_query_invalid", "查询 geometry 不是有效 GeoJSON") from exc
    else:
        raise SpatialQueryError("spatial_query_invalid", "查询 geometry 必须是 GeoJSON 对象")
    if geometry.is_empty or not geometry.is_valid:
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty:
            raise SpatialQueryError("spatial_query_invalid", "查询 geometry 为空或无效")
    normalized = _transform_geometry(geometry, coord_type)
    if normalized.is_empty:
        raise SpatialQueryError("spatial_query_invalid", "查询 geometry 转换后为空")
    return normalized


def normalize_spatial_target(spatial: dict[str, Any]) -> tuple[str, BaseGeometry, str]:
    if not isinstance(spatial, dict):
        raise SpatialQueryError("spatial_query_invalid", "spatial 必须是对象")
    relation = str(spatial.get("relation") or "").strip().lower()
    if relation not in SUPPORTED_SPATIAL_RELATIONS:
        raise SpatialQueryError("spatial_relation_unsupported", f"不支持的空间关系: {relation or '空'}")
    target_fields = [field for field in ("point", "geometry") if spatial.get(field) is not None]
    if len(target_fields) != 1:
        raise SpatialQueryError("spatial_query_invalid", "spatial 必须且只能提供 point 或 geometry")
    coord_type = str(spatial.get("coord_type") or "").strip().lower()
    if coord_type not in {"gcj02", "wgs84"}:
        raise SpatialQueryError("spatial_coord_type_unknown", "spatial.coord_type 必须是 gcj02 或 wgs84")

    point = spatial.get("point")
    if point is not None:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise SpatialQueryError("spatial_query_invalid", "spatial.point 必须是 [lng, lat]")
        lon = _finite_number(point[0])
        lat = _finite_number(point[1])
        if lon is None or lat is None or not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise SpatialQueryError("spatial_query_invalid", "spatial.point 坐标无效")
        target = Point(lon, lat)
        target = _transform_geometry(target, coord_type)
    elif spatial.get("geometry") is not None:
        target = normalize_geometry(spatial.get("geometry"), coord_type)
    else:
        raise SpatialQueryError("spatial_query_invalid", "spatial 必须提供 point 或 geometry")

    if relation == "at_point" and target.geom_type != "Point":
        raise SpatialQueryError("spatial_query_invalid", "at_point 只能使用 Point 目标")
    if relation in {"nearest", "within_distance"}:
        max_distance = spatial.get("max_distance_m")
        if max_distance is not None and (_finite_number(max_distance) is None or float(max_distance) < 0):
            raise SpatialQueryError("spatial_query_invalid", "max_distance_m 必须是非负数")
        if relation == "within_distance" and max_distance is None:
            raise SpatialQueryError("spatial_query_invalid", "within_distance 必须提供 max_distance_m")
    min_overlap = spatial.get("min_overlap_ratio")
    if min_overlap is not None and (_finite_number(min_overlap) is None or not 0 <= float(min_overlap) <= 1):
        raise SpatialQueryError("spatial_query_invalid", "min_overlap_ratio 必须位于 0 到 1 之间")
    return relation, target, coord_type


def _metric_transform(origin: BaseGeometry):
    center = origin.centroid
    lon0 = math.radians(float(center.x))
    lat0 = math.radians(float(center.y))

    def to_metric(x, y, z=None):
        def convert(px: float, py: float) -> tuple[float, float]:
            return (
                EARTH_RADIUS_M * math.radians(px - math.degrees(lon0)) * math.cos(lat0),
                EARTH_RADIUS_M * math.radians(py - math.degrees(lat0)),
            )
        return _transform_xy(x, y, convert)

    def from_metric(x, y, z=None):
        def convert(px: float, py: float) -> tuple[float, float]:
            return (
                math.degrees(lon0) + math.degrees(px / (EARTH_RADIUS_M * math.cos(lat0))),
                math.degrees(lat0) + math.degrees(py / EARTH_RADIUS_M),
            )
        return _transform_xy(x, y, convert)

    return to_metric, from_metric


def _record_geometry(record: Any) -> BaseGeometry | None:
    geometry = getattr(record, "geometry", None)
    return geometry if isinstance(geometry, BaseGeometry) and not geometry.is_empty else None


def _build_index(records: Sequence[Any], cache_key: str) -> tuple[_SpatialIndex | None, int]:
    geometries = [_record_geometry(record) for record in records]
    record_positions = [index for index, geometry in enumerate(geometries) if geometry is not None]
    valid = [geometries[index] for index in record_positions]
    skipped = len(geometries) - len(valid)
    if not valid:
        return None, skipped
    if cache_key:
        with _INDEX_CACHE_LOCK:
            cached = _INDEX_CACHE.get(cache_key)
            if cached is not None and len(cached.geometries) == len(valid):
                _INDEX_CACHE.move_to_end(cache_key)
                return cached, skipped
    index = _SpatialIndex(valid, record_positions, STRtree(valid))
    if cache_key:
        with _INDEX_CACHE_LOCK:
            _INDEX_CACHE[cache_key] = index
            _INDEX_CACHE.move_to_end(cache_key)
            while len(_INDEX_CACHE) > MAX_INDEX_CACHE_ENTRIES:
                _INDEX_CACHE.popitem(last=False)
    return index, skipped


def _candidate_positions(index: _SpatialIndex, target: BaseGeometry, relation: str, max_distance_m: float | None) -> Iterable[int]:
    if relation in {"at_point", "intersects"}:
        return index.tree.query(target, predicate="intersects").tolist()
    if max_distance_m is not None:
        to_metric, from_metric = _metric_transform(target)
        metric_search_area = transform(to_metric, target).buffer(float(max_distance_m))
        search_area = transform(from_metric, metric_search_area)
        return index.tree.query(search_area).tolist()
    return range(len(index.geometries))


def _ratio(value: float, denominator: float) -> float | None:
    return round(value / denominator, 6) if denominator > 1e-9 else None


def _linear_length(geometry: BaseGeometry) -> float:
    if geometry.geom_type in {"LineString", "MultiLineString"}:
        return float(geometry.length)
    if geometry.geom_type == "GeometryCollection":
        return sum(_linear_length(part) for part in geometry.geoms)
    return 0.0


def query_spatial_records(records: Sequence[Any], spatial: dict[str, Any], *, cache_key: str = "") -> SpatialQueryResult:
    relation, target, output_coord_type = normalize_spatial_target(spatial)
    index, skipped = _build_index(records, cache_key)
    if index is None:
        raise SpatialQueryError("spatial_geometry_missing", "当前数据记录没有可用 geometry")

    to_metric, from_metric = _metric_transform(target)
    metric_target = transform(to_metric, target)
    query_area = metric_target.area
    max_distance_m = _finite_number(spatial.get("max_distance_m"))
    min_overlap = _finite_number(spatial.get("min_overlap_ratio"))
    matches: dict[int, SpatialMatch] = {}

    for position in _candidate_positions(index, target, relation, max_distance_m):
        if position < 0 or position >= len(index.geometries):
            continue
        geometry = index.geometries[position]
        metric_geometry = transform(to_metric, geometry)
        distance_m = float(metric_geometry.distance(metric_target))
        if relation == "at_point" and not geometry.covers(target):
            continue
        if relation == "intersects" and not geometry.intersects(target):
            continue
        if relation in {"nearest", "within_distance"} and max_distance_m is not None and distance_m > max_distance_m + 1e-6:
            continue

        overlap_area = None
        record_ratio = None
        query_ratio = None
        intersection_length = None
        if relation == "intersects":
            intersection = metric_geometry.intersection(metric_target)
            if metric_geometry.area > 1e-9 and metric_target.area > 1e-9:
                overlap_area = float(intersection.area)
                record_ratio = _ratio(overlap_area, float(metric_geometry.area))
                query_ratio = _ratio(overlap_area, float(metric_target.area))
                if min_overlap is not None and (record_ratio or 0.0) < min_overlap:
                    continue
            linear_length = _linear_length(intersection)
            if linear_length > 0:
                intersection_length = round(linear_length, 3)

        if relation in {"nearest", "within_distance"}:
            _, metric_match = nearest_points(metric_target, metric_geometry)
            matched_wgs = transform(from_metric, metric_match)
        else:
            matched_wgs = target if target.geom_type == "Point" else geometry.representative_point()
        matched_point = [float(matched_wgs.x), float(matched_wgs.y)]
        if output_coord_type == "gcj02":
            matched_point = list(wgs84_to_gcj02(*matched_point))
        matches[index.record_positions[position]] = SpatialMatch(
            relation=relation,
            distance_m=round(distance_m, 3) if relation in {"nearest", "within_distance"} else None,
            geometry_type=geometry.geom_type,
            matched_point=matched_point,
            overlap_area_m2=round(overlap_area, 3) if overlap_area is not None else None,
            record_overlap_ratio=record_ratio,
            query_overlap_ratio=query_ratio,
            intersection_length_m=intersection_length,
            coord_type=output_coord_type,
        )

    if relation in {"nearest", "within_distance"}:
        matches = dict(sorted(matches.items(), key=lambda item: (item[1].distance_m is None, item[1].distance_m or 0.0)))
    warnings = []
    if skipped:
        warnings.append(f"{skipped} 条记录缺少可用 geometry，已跳过。")
    return SpatialQueryResult(matches=matches, warnings=warnings, skipped_record_count=skipped)
