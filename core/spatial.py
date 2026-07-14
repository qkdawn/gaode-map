from __future__ import annotations

from hashlib import sha1, sha256
from typing import Any, Callable, Sequence

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84, wgs84_to_gcj02


def is_coord_pair(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    )


def normalize_ring(points: Sequence[Any]) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for item in points or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            coords.append((float(item[0]), float(item[1])))
        except (TypeError, ValueError):
            continue
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def round_float(value: Any, digits: int = 6) -> float:
    try:
        return round(float(value), digits)
    except Exception:
        return 0.0


def pick_largest_polygon(geom: Any) -> Polygon | None:
    if geom is None:
        return None
    if isinstance(geom, Polygon):
        return geom if not geom.is_empty else None
    if isinstance(geom, MultiPolygon):
        geoms = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
        if not geoms:
            return None
        return max(geoms, key=lambda g: g.area)
    if isinstance(geom, GeometryCollection) or getattr(geom, "geom_type", "") == "GeometryCollection":
        polygons: list[Polygon] = []
        for item in getattr(geom, "geoms", []):
            picked = pick_largest_polygon(item)
            if picked is not None:
                polygons.append(picked)
        if not polygons:
            return None
        return max(polygons, key=lambda g: g.area)
    return None


def geometry_has_area(geom: Any) -> bool:
    return bool(geom is not None and getattr(geom, "is_empty", True) is False)


def polygon_from_payload(polygon: list) -> BaseGeometry:
    if not isinstance(polygon, list) or not polygon:
        return Polygon()
    if is_coord_pair(polygon[0]):
        ring = normalize_ring(polygon)
        return Polygon(ring) if len(ring) >= 4 else Polygon()

    polygons: list[Polygon] = []
    for item in polygon:
        ring_source = item
        if (
            isinstance(item, list)
            and item
            and isinstance(item[0], list)
            and item[0]
            and isinstance(item[0][0], (list, tuple))
        ):
            ring_source = item[0]
        ring = normalize_ring(ring_source)
        if len(ring) < 4:
            continue
        poly = Polygon(ring)
        repaired = poly if poly.is_valid else poly.buffer(0)
        if repaired.is_empty:
            continue
        if isinstance(repaired, Polygon):
            polygons.append(repaired)
        elif isinstance(repaired, MultiPolygon):
            polygons.extend(part for part in repaired.geoms if isinstance(part, Polygon) and not part.is_empty)
    if not polygons:
        return Polygon()
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def convert_geometry(
    geom: BaseGeometry,
    converter: Callable[[float, float], tuple[float, float]],
) -> BaseGeometry:
    def _transform(x, y, z=None):
        try:
            iter(x)
            converted = [converter(float(px), float(py)) for px, py in zip(x, y)]
            xs, ys = zip(*converted) if converted else ((), ())
            return tuple(xs), tuple(ys)
        except Exception:
            return converter(float(x), float(y))

    return transform(_transform, geom)


def to_wgs84_geometry(polygon: list, coord_type: str) -> BaseGeometry:
    geom = polygon_from_payload(polygon)
    if geom.is_empty:
        raise ValueError("invalid polygon")
    if coord_type == "gcj02":
        geom = convert_geometry(geom, gcj02_to_wgs84)
    geom = geom.buffer(0)
    if geom.is_empty:
        raise ValueError("invalid polygon")
    return geom


def transform_geometry_to_coord_type(geom: Any, coord_type: str) -> Any:
    if coord_type != "gcj02" or geom is None:
        return geom
    return convert_geometry(geom, wgs84_to_gcj02)


def transform_point_from_wgs84(lon: float, lat: float, coord_type: str) -> list[float]:
    if coord_type == "gcj02":
        tlon, tlat = wgs84_to_gcj02(float(lon), float(lat))
        return [float(tlon), float(tlat)]
    return [float(lon), float(lat)]


def transform_polygon_payload_coords(raw: Any, transformer) -> list:
    if not isinstance(raw, list) or not raw:
        return []
    if is_coord_pair(raw[0]):
        out: list[list[float]] = []
        for point in raw:
            if not is_coord_pair(point):
                continue
            out.append(list(transformer(float(point[0]), float(point[1]))))
        return out
    nested: list[list[Any]] = []
    for item in raw:
        transformed = transform_polygon_payload_coords(item, transformer)
        if transformed:
            nested.append(transformed)
    return nested


def transform_nested_coords(raw: Any, transformer) -> Any:
    if not isinstance(raw, list):
        return raw
    if len(raw) >= 2 and isinstance(raw[0], (int, float)) and isinstance(raw[1], (int, float)):
        try:
            nx, ny = transformer(float(raw[0]), float(raw[1]))
            out = [nx, ny]
            if len(raw) > 2:
                out.extend(raw[2:])
            return out
        except Exception:
            return raw
    return [transform_nested_coords(item, transformer) for item in raw]


def transform_geojson_coordinates(value: Any, transformer) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "coordinates":
                out[key] = transform_nested_coords(item, transformer)
            else:
                out[key] = transform_geojson_coordinates(item, transformer)
        return out
    if isinstance(value, list):
        return [transform_geojson_coordinates(item, transformer) for item in value]
    return value


def build_scope_id(geom_wgs84: BaseGeometry, *parts: Any) -> str:
    prefix = ":".join(str(part) for part in parts if part is not None).encode("utf-8")
    digest = sha1(prefix + b":" + geom_wgs84.wkb).hexdigest()
    return digest[:24]


def build_scope_fingerprint(polygon_wgs84: list) -> str:
    geom = polygon_from_payload(polygon_wgs84)
    if geom.is_empty:
        return ""
    normalized = geom.buffer(0)
    if normalized.is_empty:
        return ""
    return f"scope:{sha256(normalized.wkb).hexdigest()}"
