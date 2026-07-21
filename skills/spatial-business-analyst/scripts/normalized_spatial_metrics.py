#!/usr/bin/env python3
"""Compute area-normalized sector and distance-band POI metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import Point, Polygon
from shapely.ops import transform

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

EARTH_RADIUS_M = 6_371_008.8
METHOD = "reachable_polygon_area_normalization_v2"
CANONICAL_CRS = "wgs84"
SECTORS = (
    ("east", "东", 315.0, 405.0),
    ("north", "北", 45.0, 135.0),
    ("west", "西", 135.0, 225.0),
    ("south", "南", 225.0, 315.0),
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coord(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    lon, lat = _number(value[0]), _number(value[1])
    return (lon, lat) if lon is not None and lat is not None else None


def _wgs84_center(value: Any, crs: Any) -> tuple[float, float]:
    center = _coord(value)
    if center is None:
        raise ValueError("center must be [longitude, latitude]")
    if str(crs or "").strip().lower() != CANONICAL_CRS:
        raise ValueError("center_crs must be wgs84; convert coordinates at the input boundary")
    return center


def _digest(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _analysis_scope_ring(payload: Any) -> list[tuple[float, float]]:
    value = payload
    if isinstance(value, dict):
        value = value.get("coordinates") or []
    while isinstance(value, list) and value and _coord(value[0]) is None:
        value = value[0]
    points = [point for item in (value or []) if (point := _coord(item)) is not None]
    if points and points[0] != points[-1]:
        points.append(points[0])
    if len(points) < 4:
        raise ValueError("analysis_scope must contain a polygon ring")
    return points


def _projector(center: tuple[float, float]):
    lon0, lat0 = map(math.radians, center)
    scale_x = EARTH_RADIUS_M * math.cos(lat0)

    def project(x: Any, y: Any, z: Any = None):
        try:
            return (
                tuple((math.radians(float(item)) - lon0) * scale_x for item in x),
                tuple((math.radians(float(item)) - lat0) * EARTH_RADIUS_M for item in y),
            )
        except TypeError:
            return (
                (math.radians(float(x)) - lon0) * scale_x,
                (math.radians(float(y)) - lat0) * EARTH_RADIUS_M,
            )

    return project


def _record_properties(record: dict[str, Any]) -> dict[str, Any]:
    props = record.get("properties")
    return props if isinstance(props, dict) else record


def _record_location(record: dict[str, Any]) -> tuple[float, float] | None:
    props = _record_properties(record)
    for key in ("location", "centroid", "coordinates"):
        point = _coord(props.get(key))
        if point is not None:
            return point
    return None


def _category_rules() -> list[tuple[str, str, tuple[str, ...]]]:
    try:
        from modules.h3.category_rules import CATEGORY_RULES

        return list(CATEGORY_RULES)
    except Exception:
        return [
            ("food", "餐饮", ("05",)),
            ("retail", "购物", ("06",)),
            ("medical", "医疗", ("09",)),
            ("tourism", "旅游", ("11",)),
            ("business", "商务住宅", ("12",)),
            ("culture", "科教文化", ("14",)),
            ("transport", "交通", ("15",)),
            ("company", "公司", ("17",)),
        ]


def _record_category(record: dict[str, Any]) -> tuple[str, str]:
    props = _record_properties(record)
    explicit = str(props.get("category_label") or "").strip()
    raw = str(props.get("typecode") or props.get("type") or props.get("category") or "").strip()
    digits = "".join(char for char in raw if char.isdigit())[:6]
    for key, label, codes in _category_rules():
        if explicit == label:
            return key, label
        if any(digits == code or digits.startswith(code) or (len(digits) >= 2 and digits[:2] == code[:2]) for code in codes):
            return key, label
    return (explicit or raw or "unclassified", explicit or "未分类")


def _record_key(record: dict[str, Any], location: tuple[float, float]) -> str:
    props = _record_properties(record)
    record_id = str(record.get("record_id") or props.get("record_id") or props.get("id") or "").strip()
    if record_id:
        return f"id:{record_id}"
    name = str(record.get("title") or props.get("name") or "").strip()
    return f"name:{name}|{location[0]:.6f},{location[1]:.6f}"


def _wedge(start_deg: float, end_deg: float, radius: float) -> Polygon:
    steps = max(int(end_deg - start_deg), 2)
    arc = []
    for index in range(steps + 1):
        angle = math.radians(start_deg + (end_deg - start_deg) * index / steps)
        arc.append((radius * math.cos(angle), radius * math.sin(angle)))
    return Polygon([(0.0, 0.0), *arc, (0.0, 0.0)])


def _sector_name(point: Point) -> str:
    angle = math.degrees(math.atan2(point.y, point.x)) % 360.0
    if angle >= 315.0 or angle < 45.0:
        return "east"
    if angle < 135.0:
        return "north"
    if angle < 225.0:
        return "west"
    return "south"


def _band_name(distance: float, edges: list[float]) -> str:
    for lower, upper in zip(edges, edges[1:]):
        if lower <= distance < upper:
            return f"{int(lower)}-{int(upper)}m"
    return f"{int(edges[-1])}m+"


def _category_metrics(unit_counts: Counter[str], unit_total: int, totals: Counter[str], total: int, labels: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for key, count in unit_counts.most_common():
        overall_count = totals.get(key, 0)
        unit_share = count / unit_total if unit_total else 0.0
        overall_share = overall_count / total if total else 0.0
        rows.append(
            {
                "category": key,
                "label": labels.get(key, key),
                "count": count,
                "share": round(unit_share, 6),
                "location_quotient": round(unit_share / overall_share, 4) if overall_share else None,
            }
        )
    return rows


def compute(payload: dict[str, Any]) -> dict[str, Any]:
    center = _wgs84_center(payload.get("center"), payload.get("center_crs"))
    ring = _analysis_scope_ring(payload.get("analysis_scope"))
    project = _projector(center)
    scope = transform(project, Polygon(ring)).buffer(0)
    if scope.is_empty or scope.area <= 0:
        raise ValueError("analysis_scope has no usable area")

    raw_edges = payload.get("bands_m") or [0, 500, 1000, 1500]
    edges = sorted({float(value) for value in raw_edges if _number(value) is not None and float(value) >= 0})
    if not edges or edges[0] != 0:
        edges.insert(0, 0.0)

    accepted: list[tuple[Point, str]] = []
    seen: set[str] = set()
    duplicate_count = 0
    invalid_location_count = 0
    outside_count = 0
    labels: dict[str, str] = {}
    digest_rows = []
    for record in payload.get("records") or []:
        if not isinstance(record, dict):
            continue
        location = _record_location(record)
        if location is None:
            invalid_location_count += 1
            continue
        key = _record_key(record, location)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        point = transform(project, Point(location))
        if not (scope.contains(point) or scope.touches(point)):
            outside_count += 1
            continue
        category, label = _record_category(record)
        labels[category] = label
        accepted.append((point, category))
        digest_rows.append((key, round(location[0], 7), round(location[1], 7), category))

    total = len(accepted)
    total_area_km2 = scope.area / 1_000_000.0
    total_density = total / total_area_km2 if total_area_km2 else 0.0
    category_totals = Counter(category for _, category in accepted)
    radius = max(Point(0, 0).distance(Point(x, y)) for x, y in scope.exterior.coords) + 10.0

    sectors = []
    for key, label, start, end in SECTORS:
        area = scope.intersection(_wedge(start, end, radius)).area / 1_000_000.0
        items = [(point, category) for point, category in accepted if _sector_name(point) == key]
        counts = Counter(category for _, category in items)
        density = len(items) / area if area else None
        sectors.append(
            {
                "geometry_id": f"sector:{key}",
                "label": label,
                "area_km2": round(area, 6),
                "count": len(items),
                "count_share": round(len(items) / total, 6) if total else 0.0,
                "density_poi_per_km2": round(density, 4) if density is not None else None,
                "density_index": round(density / total_density, 4) if density is not None and total_density else None,
                "categories": _category_metrics(counts, len(items), category_totals, total, labels),
            }
        )

    bands = []
    max_distance = max((point.distance(Point(0, 0)) for point, _ in accepted), default=edges[-1])
    boundaries = [*edges, max(radius, max_distance) + 1.0]
    for index, (lower, upper) in enumerate(zip(boundaries, boundaries[1:])):
        if index == len(boundaries) - 2:
            label = f"{int(lower)}m+"
        else:
            label = f"{int(lower)}-{int(upper)}m"
        outer = Point(0, 0).buffer(upper, resolution=96)
        inner = Point(0, 0).buffer(lower, resolution=96) if lower else None
        zone = outer.difference(inner) if inner is not None else outer
        area = scope.intersection(zone).area / 1_000_000.0
        items = [(point, category) for point, category in accepted if _band_name(point.distance(Point(0, 0)), edges) == label]
        counts = Counter(category for _, category in items)
        density = len(items) / area if area else None
        bands.append(
            {
                "geometry_id": f"band:{label}",
                "label": label,
                "area_km2": round(area, 6),
                "count": len(items),
                "count_share": round(len(items) / total, 6) if total else 0.0,
                "density_poi_per_km2": round(density, 4) if density is not None else None,
                "density_index": round(density / total_density, 4) if density is not None and total_density else None,
                "categories": _category_metrics(counts, len(items), category_totals, total, labels),
            }
        )

    dataset_digest_payload = {
        "history_id": payload.get("history_id"),
        "source_id": payload.get("source_id"),
        "year": payload.get("year"),
        "analysis_scope": ring,
        "records": sorted(digest_rows),
    }
    dataset_digest = _digest(dataset_digest_payload)
    analysis_spec = {
        "method": METHOD,
        "analysis_origin": [round(center[0], 12), round(center[1], 12)],
        "analysis_crs": CANONICAL_CRS,
        "distance_band_edges_m": edges,
        "sectors": [list(item) for item in SECTORS],
    }
    analysis_spec_digest = _digest(analysis_spec)
    run_digest = _digest(
        {
            "dataset_content_sha256": dataset_digest,
            "analysis_spec_sha256": analysis_spec_digest,
        }
    )
    source_ref = f"{payload.get('source_id')}@sha256:{dataset_digest}"
    result_id = f"result:poi.normalized_spatial:{run_digest[:16]}"
    quality_flags = [
        {"code": code, "severity": "info", "effect": f"excluded_record_count:{count}"}
        for code, count in (
            ("duplicate_records_excluded", duplicate_count),
            ("invalid_locations_excluded", invalid_location_count),
            ("outside_scope_records_excluded", outside_count),
        )
        if count
    ]
    return {
        "result_id": result_id,
        "tool_ids": ["poi.count", "poi.grid_density", "poi.lq"],
        "status": "available",
        "summary": "分析范围 POI 总量、方向、有效距离带和类别区位商。",
        "input_sources": [source_ref],
        "time_scope": {"year": payload.get("year")},
        "spatial_scope": {
            "scope_sha256": f"sha256:{dataset_digest}",
            "partition_origin": list(center),
            "crs": CANONICAL_CRS,
        },
        "structured_result": {
            "method": METHOD,
            "dataset_content_sha256": f"sha256:{dataset_digest}",
            "analysis_spec_sha256": f"sha256:{analysis_spec_digest}",
            "analysis_spec": analysis_spec,
            "scope_area_km2": round(total_area_km2, 6),
            "accepted_record_count": total,
            "total_density_poi_per_km2": round(total_density, 4),
            "duplicate_count": duplicate_count,
            "invalid_location_count": invalid_location_count,
            "outside_scope_count": outside_count,
            "category_level": "single configured top-level category",
            "sectors": [unit for unit in sectors if unit["area_km2"] > 0],
            "distance_bands": [unit for unit in bands if unit["area_km2"] > 0],
            "quality_flags": quality_flags,
        },
        "limitations": [
            "Area uses a local metric approximation suitable for neighborhood-scale analysis.",
            "Density measures mapped POI supply, not demand, footfall, employment, or operating performance.",
            "Distance bands use straight-line distance inside the walk-network coverage area.",
        ],
    }


def _load(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_history(history_id: str, year: int) -> dict[str, Any]:
    try:
        from modules.spatial_projects.service import SpatialProjectService
        from modules.scope_datasets.service import ScopeDatasetRepository
        from store.history_repo import HistoryRepo
    except Exception as exc:
        raise RuntimeError("history mode must run from the gaode-map repository environment") from exc

    service = SpatialProjectService()
    project = service.read_history_project(history_id)
    history = HistoryRepo().get_detail(history_id, include_pois=False)
    params = history.get("params") if isinstance(history, dict) and isinstance(history.get("params"), dict) else {}
    center = _coord(params.get("center"))
    if center is None:
        raise ValueError("history params.center is required")
    records: list[dict[str, Any]] = []
    repository = ScopeDatasetRepository()
    for row in repository.list_poi_results(history_id):
        if int(row.get("year") or 0) != year:
            continue
        for poi in repository.get_poi_data(row.get("id")):
            if not isinstance(poi, dict):
                continue
            props = dict(poi)
            props["year"] = year
            props["source"] = row.get("source") or "local"
            records.append(
                {
                    "record_id": poi.get("id") or poi.get("uid") or poi.get("poi_id") or "",
                    "properties": props,
                }
            )
    return {
        "history_id": history_id,
        "source_id": "current:dataset:poi",
        "year": year,
        "center": list(center),
        "center_crs": CANONICAL_CRS,
        "analysis_scope": project.get("scope") or [],
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="JSON input path, or - for stdin")
    parser.add_argument("--history-id", help="Read a history-backed project directly")
    parser.add_argument("--year", type=int, help="POI year for history mode")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--workspace", help="Run workspace; writes normalized metrics under artifacts/")
    args = parser.parse_args()
    if args.history_id:
        if args.year is None:
            parser.error("--history-id requires --year")
        payload = _load_history(args.history_id, args.year)
    elif args.input:
        payload = _load(args.input)
    else:
        parser.error("provide an input path or --history-id")
    result = compute(payload)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    output = args.output
    if args.workspace:
        workspace = Path(args.workspace).resolve()
        output_path = workspace / "artifacts" / "normalized_spatial_metrics.json"
        if output and Path(output).resolve() != output_path:
            raise ValueError("workspace metrics output must be artifacts/normalized_spatial_metrics.json")
        output = str(output_path)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
