from __future__ import annotations

import math
import time
import hashlib
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from shapely.geometry import LineString, Polygon
from shapely.prepared import prep

from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02

from .arcgis_bridge import ArcGISRoadSyntaxBridgeError, run_arcgis_road_syntax_webgl
from .geometry import clip_line_to_polygon_segment, haversine_m, safe_round
from .metrics import (
    build_road_orientation_analysis,
    column_numeric_stats,
    linear_regression,
    metric_bounds,
    norm,
    pearson_corr,
    percentile_rank,
    sample_scatter_points,
    select_metric_columns,
    select_single_metric_column,
)
from .overpass import normalize_label, radius_label_from_header


def to_output_coord(
    lon: float,
    lat: float,
    output_coord_type: Literal["gcj02", "wgs84"],
) -> Tuple[float, float]:
    if output_coord_type == "gcj02":
        return wgs84_to_gcj02(lon, lat)
    return lon, lat


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _coord_key(point: List[float], digits: int = 6) -> Tuple[float, float]:
    return (safe_round(float(point[0]), digits), safe_round(float(point[1]), digits))


def _vector_from_to(a: List[float], b: List[float]) -> Tuple[float, float]:
    return (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _cosine_similarity(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    n1 = math.hypot(v1[0], v1[1])
    n2 = math.hypot(v2[0], v2[1])
    if n1 <= 1e-12 or n2 <= 1e-12:
        return -1.0
    return max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))


def _line_length_by_coords(coords: List[List[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        total += haversine_m(float(a[0]), float(a[1]), float(b[0]), float(b[1]))
    return max(0.0, total)


def _merge_feature_properties(features: List[Dict[str, Any]], lengths_m: List[float]) -> Dict[str, Any]:
    if not features:
        return {}
    props_list = [((feature.get("properties") or {}) if isinstance(feature, dict) else {}) for feature in features]
    keys = set()
    for props in props_list:
        keys.update(props.keys())

    out: Dict[str, Any] = {}
    total_w = sum(max(0.0, float(weight)) for weight in lengths_m)
    if total_w <= 1e-9:
        weights = [1.0 for _ in features]
    else:
        weights = [max(0.0, float(weight)) for weight in lengths_m]

    for key in keys:
        values = [props.get(key) for props in props_list]
        non_none = [value for value in values if value is not None]
        if not non_none:
            continue

        if all(isinstance(value, bool) for value in non_none):
            out[key] = any(bool(value) for value in non_none)
            continue

        if all(_is_finite_number(value) for value in non_none):
            acc = 0.0
            weight_sum = 0.0
            for value, weight in zip(values, weights):
                if not _is_finite_number(value):
                    continue
                safe_weight = max(0.0, float(weight))
                acc += float(value) * safe_weight
                weight_sum += safe_weight
            if weight_sum <= 1e-9:
                out[key] = 0.0
            elif key == "length_m":
                out[key] = safe_round(acc / weight_sum, 2)
            else:
                out[key] = safe_round(acc / weight_sum, 8)
            continue

        out[key] = non_none[0]

    out["length_m"] = safe_round(sum(max(0.0, float(value)) for value in lengths_m), 2)
    return out


def merge_linestring_features(
    features: List[Dict[str, Any]],
    bucket_step: float = 0.025,
    angle_cos_min: float = 0.92,
) -> List[Dict[str, Any]]:
    if len(features) < 2:
        return list(features)

    step = max(0.005, min(0.2, float(bucket_step)))
    segments: List[Dict[str, Any]] = []
    node_map: Dict[Tuple[float, float], List[int]] = {}
    passthrough: List[Dict[str, Any]] = []

    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        if geometry.get("type") != "LineString":
            passthrough.append(feature)
            continue
        coords_raw = geometry.get("coordinates") or []
        coords: List[List[float]] = []
        for pt in coords_raw:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                continue
            try:
                coords.append([float(pt[0]), float(pt[1])])
            except (TypeError, ValueError):
                continue
        if len(coords) < 2:
            passthrough.append(feature)
            continue

        props = ((feature or {}).get("properties") or {})
        start_key = _coord_key(coords[0], 6)
        end_key = _coord_key(coords[-1], 6)
        if start_key == end_key:
            passthrough.append(feature)
            continue
        acc_score = float(props.get("accessibility_score", props.get("integration_score", 0.0)) or 0.0)
        bucket = int(round(max(0.0, min(1.0, acc_score)) / step))
        flags = (
            bool(props.get("is_skeleton_choice_top20", False)),
            bool(props.get("is_skeleton_integration_top20", False)),
        )
        length_m = float(props.get("length_m", 0.0) or 0.0)
        if length_m <= 0:
            length_m = _line_length_by_coords(coords)
        seg_id = len(segments)
        segment = {
            "id": seg_id,
            "feature": feature,
            "coords": coords,
            "start_key": start_key,
            "end_key": end_key,
            "bucket": bucket,
            "flags": flags,
            "length_m": max(0.0, length_m),
        }
        segments.append(segment)
        node_map.setdefault(start_key, []).append(seg_id)
        node_map.setdefault(end_key, []).append(seg_id)

    if len(segments) < 2:
        return list(features)

    visited: set[int] = set()
    merged_out: List[Dict[str, Any]] = []

    for segment in segments:
        seg_id = int(segment["id"])
        if seg_id in visited:
            continue
        visited.add(seg_id)
        chain_ids: List[int] = [seg_id]
        chain_bucket = int(segment["bucket"])
        chain_flags = segment["flags"]
        path: List[List[float]] = [list(point) for point in segment["coords"]]

        def _extend_side(at_start: bool) -> bool:
            nonlocal path
            if len(path) < 2:
                return False
            current_pt = path[0] if at_start else path[-1]
            current_key = _coord_key(current_pt, 6)
            if len(node_map.get(current_key, [])) != 2:
                return False
            candidates = [cid for cid in node_map.get(current_key, []) if cid not in visited]
            if len(candidates) != 1:
                return False
            next_id = int(candidates[0])
            next_seg = segments[next_id]
            if int(next_seg["bucket"]) != chain_bucket or next_seg["flags"] != chain_flags:
                return False

            oriented = next_seg["coords"] if next_seg["start_key"] == current_key else list(reversed(next_seg["coords"]))
            if len(oriented) < 2:
                return False
            other_pt = oriented[-1]
            if at_start:
                inner_pt = path[1]
                v_in = _vector_from_to(current_pt, inner_pt)
                v_next = (float(current_pt[0]) - float(other_pt[0]), float(current_pt[1]) - float(other_pt[1]))
            else:
                inner_pt = path[-2]
                v_in = _vector_from_to(inner_pt, current_pt)
                v_next = _vector_from_to(current_pt, other_pt)
            if _cosine_similarity(v_in, v_next) < angle_cos_min:
                return False

            if at_start:
                prepend = list(reversed(oriented))
                path = prepend[:-1] + path
            else:
                path = path + oriented[1:]
            visited.add(next_id)
            chain_ids.append(next_id)
            return True

        while True:
            changed = False
            if _extend_side(True):
                changed = True
            if _extend_side(False):
                changed = True
            if not changed:
                break

        chain_features = [segments[cid]["feature"] for cid in chain_ids]
        chain_lengths = [float(segments[cid]["length_m"]) for cid in chain_ids]
        merged_props = _merge_feature_properties(chain_features, chain_lengths)
        merged_out.append(
            {
                "type": "Feature",
                "properties": merged_props,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[safe_round(point[0], 6), safe_round(point[1], 6)] for point in path],
                },
            }
        )

    if not merged_out:
        return list(features)
    return merged_out + passthrough


def empty_result(
    mode: str,
    coord_type: Literal["gcj02", "wgs84"],
    radii_m: Optional[List[int]] = None,
    metric: str = "choice",
    analysis_engine: str = "depthmapxcli",
    webgl_status: str = "disabled:empty_result",
) -> Dict[str, Any]:
    local_labels = [normalize_label(r) for r in sorted({int(value) for value in (radii_m or []) if int(value) > 0})]
    default_radius_label = local_labels[0] if local_labels else "global"
    return {
        "summary": {
            "node_count": 0,
            "edge_count": 0,
            "rendered_edge_count": 0,
            "edge_merge_ratio": 1.0,
            "network_length_km": 0.0,
            "avg_degree": 0.0,
            "avg_closeness": 0.0,
            "avg_choice": 0.0,
            "avg_accessibility_global": 0.0,
            "avg_connectivity": 0.0,
            "avg_control": 0.0,
            "avg_depth": 0.0,
            "control_source_column": "",
            "control_valid_count": 0,
            "depth_source_column": "",
            "depth_valid_count": 0,
            "avg_intelligibility": 0.0,
            "avg_intelligibility_r2": 0.0,
            "avg_integration_global": 0.0,
            "avg_choice_global": 0.0,
            "avg_integration_local": 0.0,
            "avg_choice_local": 0.0,
            "avg_integration_by_radius": {label: 0.0 for label in local_labels},
            "avg_choice_by_radius": {label: 0.0 for label in local_labels},
            "radius_labels": local_labels,
            "mode": mode,
            "coord_type": coord_type,
            "default_metric": metric,
            "default_radius_label": default_radius_label,
            "analysis_engine": str(analysis_engine or "depthmapxcli"),
            "road_orientation_analysis": build_road_orientation_analysis([]),
        },
        "top_nodes": [],
        "road_edges": {"type": "FeatureCollection", "features": [], "count": 0},
        "road_grid": {"type": "FeatureCollection", "features": [], "count": 0},
        "roads": {"type": "FeatureCollection", "features": [], "count": 0},
        "nodes": {"type": "FeatureCollection", "features": [], "count": 0},
        "diagnostics": {
            "intelligibility_scatter": [],
            "regression": {"slope": 0.0, "intercept": 0.0, "r": 0.0, "r2": 0.0, "n": 0},
        },
        "webgl": {
            "enabled": False,
            "backend": "none",
            "status": str(webgl_status or "disabled:empty_result"),
            "metric_field": "",
            "coord_type": coord_type,
            "roads": {"type": "FeatureCollection", "features": [], "count": 0},
            "elapsed_ms": 0.0,
        },
    }


def build_road_analysis_result(
    *,
    rows: List[Dict[str, Any]],
    fieldnames: List[str],
    context_wgs_poly: Polygon,
    output_wgs_poly: Polygon,
    mode: str,
    local_radii: List[int],
    requested_local_labels: List[str],
    render_metric: str,
    include_geojson: bool,
    max_edge_features: Optional[int],
    merge_geojson_edges: bool,
    merge_bucket_step: float,
    use_arcgis_webgl: bool,
    arcgis_timeout_sec: int,
    arcgis_metric_field: Optional[str],
    analysis_engine_label: str,
    started_at: float,
    report_progress: Optional[Callable[[str, str, Optional[int], Optional[Dict[str, Any]]], None]] = None,
) -> Dict[str, Any]:
    if report_progress is None:
        report_progress = lambda stage, message, step=None, extra=None: None

    choice_columns = select_metric_columns(fieldnames, "choice", radius_label_from_header)
    integration_columns = select_metric_columns(fieldnames, "integration", radius_label_from_header)
    connectivity_columns = select_metric_columns(fieldnames, "connectivity", radius_label_from_header)
    control_col = select_single_metric_column(
        fieldnames,
        include_patterns=[("controllability",), ("control",)],
        rows=rows,
        preferred_tokens=("controllability", "control"),
    )
    depth_col = select_single_metric_column(
        fieldnames,
        include_patterns=[("mean", "depth"), ("meandepth",), ("depth",)],
        rows=rows,
        preferred_tokens=("mean depth", "meandepth", "depth"),
    )
    connectivity_col = select_single_metric_column(
        fieldnames,
        include_patterns=[("connectivity",)],
        rows=rows,
        preferred_tokens=("connectivity",),
    )

    allow_labels = set(requested_local_labels)
    allow_labels.add("global")
    choice_columns = {key: value for key, value in choice_columns.items() if key in allow_labels}
    integration_columns = {key: value for key, value in integration_columns.items() if key in allow_labels}
    connectivity_columns = {key: value for key, value in connectivity_columns.items() if key in allow_labels}
    local_labels = [
        label
        for label in requested_local_labels
        if label in choice_columns and label in integration_columns
    ]
    default_radius_label = local_labels[0] if local_labels else "global"
    allow_labels = set(local_labels)
    allow_labels.add("global")

    if not connectivity_col:
        connectivity_col = connectivity_columns.get("global")
    if not connectivity_col and connectivity_columns:
        connectivity_col = sorted(connectivity_columns.values(), key=len)[0]

    prepared_context_poly = prep(context_wgs_poly)
    prepared_output_poly = prep(output_wgs_poly)
    metric_values_choice: Dict[str, List[float]] = {key: [] for key in choice_columns}
    metric_values_integ: Dict[str, List[float]] = {key: [] for key in integration_columns}
    metric_values_conn_raw: List[float] = []
    metric_values_control_raw: List[float] = []
    metric_values_depth_raw: List[float] = []
    parsed_edges_context: List[Dict[str, Any]] = []

    for row in rows:
        try:
            x1 = float(row.get("x1", ""))
            y1 = float(row.get("y1", ""))
            x2 = float(row.get("x2", ""))
            y2 = float(row.get("y2", ""))
        except (TypeError, ValueError):
            continue

        line = LineString([(x1, y1), (x2, y2)])
        if line.is_empty or not prepared_context_poly.intersects(line):
            continue

        raw_choice: Dict[str, Optional[float]] = {}
        raw_integration: Dict[str, Optional[float]] = {}
        raw_connectivity: Optional[float] = None
        raw_control: Optional[float] = None
        raw_depth: Optional[float] = None

        for label, col in choice_columns.items():
            try:
                value = float(row.get(col, ""))
            except (TypeError, ValueError):
                value = None
            raw_choice[label] = value
            if value is not None and math.isfinite(value):
                metric_values_choice[label].append(value)

        for label, col in integration_columns.items():
            try:
                value = float(row.get(col, ""))
            except (TypeError, ValueError):
                value = None
            raw_integration[label] = value
            if value is not None and math.isfinite(value):
                metric_values_integ[label].append(value)

        if connectivity_col:
            try:
                conn_value = float(row.get(connectivity_col, ""))
            except (TypeError, ValueError):
                conn_value = None
            if conn_value is not None and math.isfinite(conn_value):
                raw_connectivity = conn_value
                metric_values_conn_raw.append(conn_value)

        if control_col:
            try:
                control_value = float(row.get(control_col, ""))
            except (TypeError, ValueError):
                control_value = None
            if control_value is not None and math.isfinite(control_value):
                raw_control = control_value
                metric_values_control_raw.append(control_value)

        if depth_col:
            try:
                depth_value = float(row.get(depth_col, ""))
            except (TypeError, ValueError):
                depth_value = None
            if depth_value is not None and math.isfinite(depth_value):
                raw_depth = depth_value
                metric_values_depth_raw.append(depth_value)

        key1 = (safe_round(x1, 7), safe_round(y1, 7))
        key2 = (safe_round(x2, 7), safe_round(y2, 7))
        parsed_edges_context.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "key1": key1,
                "key2": key2,
                "length_m": haversine_m(x1, y1, x2, y2),
                "raw_choice": raw_choice,
                "raw_integration": raw_integration,
                "raw_connectivity": raw_connectivity,
                "raw_control": raw_control,
                "raw_depth": raw_depth,
            }
        )

    parsed_edges: List[Dict[str, Any]] = []
    neighbor_sets: Dict[Tuple[float, float], set] = {}
    total_length_m = 0.0
    for item in parsed_edges_context:
        line = LineString([(item["x1"], item["y1"]), (item["x2"], item["y2"])])
        if line.is_empty or not prepared_output_poly.intersects(line):
            continue
        clipped_seg = clip_line_to_polygon_segment(line, output_wgs_poly)
        if not clipped_seg:
            continue
        x1c, y1c, x2c, y2c = clipped_seg
        edge = dict(item)
        edge["x1"] = x1c
        edge["y1"] = y1c
        edge["x2"] = x2c
        edge["y2"] = y2c
        edge["key1"] = (safe_round(x1c, 7), safe_round(y1c, 7))
        edge["key2"] = (safe_round(x2c, 7), safe_round(y2c, 7))
        edge["length_m"] = haversine_m(x1c, y1c, x2c, y2c)
        parsed_edges.append(edge)
        key1 = edge["key1"]
        key2 = edge["key2"]
        if key1 != key2:
            neighbor_sets.setdefault(key1, set()).add(key2)
            neighbor_sets.setdefault(key2, set()).add(key1)
        total_length_m += max(0.0, float(edge.get("length_m", 0.0)))

    if not parsed_edges:
        return empty_result(
            mode,
            coord_type="gcj02",
            radii_m=local_radii,
            metric=render_metric,
            analysis_engine=analysis_engine_label,
            webgl_status="disabled:no_edges_in_output_polygon",
        )

    def _build_topology_control_values() -> Tuple[List[float], Dict[Tuple[float, float], float]]:
        degree_by_node = {key: len(neighbors) for key, neighbors in neighbor_sets.items()}
        control_by_node: Dict[Tuple[float, float], float] = {}
        for key, neighbors in neighbor_sets.items():
            control_val = 0.0
            for nb in neighbors:
                nb_deg = int(degree_by_node.get(nb, 0))
                if nb_deg > 0:
                    control_val += 1.0 / float(nb_deg)
            control_by_node[key] = control_val
        edge_values: List[float] = []
        for item in parsed_edges:
            c1 = control_by_node.get(item["key1"])
            c2 = control_by_node.get(item["key2"])
            finite_vals = [float(value) for value in (c1, c2) if value is not None and math.isfinite(float(value))]
            if not finite_vals:
                item["raw_control_topology"] = None
                continue
            value = sum(finite_vals) / float(len(finite_vals))
            item["raw_control_topology"] = value
            edge_values.append(value)
        return edge_values, control_by_node

    control_values_from_depthmap = list(metric_values_control_raw)
    control_col_source = str(control_col or "")
    control_topology_values, _ = _build_topology_control_values()
    control_depthmap_spread = float(max(control_values_from_depthmap) - min(control_values_from_depthmap)) if control_values_from_depthmap else 0.0
    use_topology_control_fallback = (not control_values_from_depthmap) or (
        control_depthmap_spread <= 1e-12 and len(control_topology_values) > 0
    )
    if use_topology_control_fallback and control_topology_values:
        metric_values_control_raw = control_topology_values
        control_col_source = "topology_fallback"
        for item in parsed_edges:
            raw_topology = item.get("raw_control_topology")
            item["raw_control"] = raw_topology if raw_topology is not None else item.get("raw_control")

    choice_bounds = metric_bounds(metric_values_choice)
    integ_bounds = metric_bounds(metric_values_integ)
    conn_bounds = (min(metric_values_conn_raw), max(metric_values_conn_raw)) if metric_values_conn_raw else None
    control_bounds = (min(metric_values_control_raw), max(metric_values_control_raw)) if metric_values_control_raw else None
    depth_bounds = (min(metric_values_depth_raw), max(metric_values_depth_raw)) if metric_values_depth_raw else None

    global_choice_values: List[float] = []
    global_integ_values: List[float] = []
    global_conn_values_raw: List[float] = []
    global_control_values: List[float] = []
    global_depth_values: List[float] = []
    local_choice_values: Dict[str, List[float]] = {label: [] for label in local_labels}
    local_integ_values: Dict[str, List[float]] = {label: [] for label in local_labels}
    node_integ_sum: Dict[Tuple[float, float], float] = {}
    node_integ_cnt: Dict[Tuple[float, float], int] = {}
    scored_edges: List[Dict[str, Any]] = []

    for item in parsed_edges:
        choice_by_label: Dict[str, float] = {}
        integ_by_label: Dict[str, float] = {}
        for label in allow_labels:
            choice_by_label[label] = norm(item["raw_choice"].get(label), choice_bounds.get(label))
            integ_by_label[label] = norm(item["raw_integration"].get(label), integ_bounds.get(label))

        global_choice_values.append(choice_by_label.get("global", 0.0))
        global_integ_values.append(integ_by_label.get("global", 0.0))
        for label in local_labels:
            local_choice_values[label].append(choice_by_label.get(label, 0.0))
            local_integ_values[label].append(integ_by_label.get(label, 0.0))

        default_choice = choice_by_label.get(default_radius_label, choice_by_label.get("global", 0.0))
        default_integ = integ_by_label.get(default_radius_label, integ_by_label.get("global", 0.0))
        raw_connectivity = item.get("raw_connectivity")
        connectivity_score = norm(raw_connectivity, conn_bounds)
        raw_control = item.get("raw_control")
        control_score = norm(float(raw_control), control_bounds) if raw_control is not None and control_bounds is not None and math.isfinite(float(raw_control)) else None
        raw_depth = item.get("raw_depth")
        depth_score = norm(float(raw_depth), depth_bounds) if raw_depth is not None and depth_bounds is not None and math.isfinite(float(raw_depth)) else None
        if raw_connectivity is not None and math.isfinite(float(raw_connectivity)):
            global_conn_values_raw.append(float(raw_connectivity))
        if control_score is not None:
            global_control_values.append(float(control_score))
        if depth_score is not None:
            global_depth_values.append(float(depth_score))

        out1 = to_output_coord(item["x1"], item["y1"], output_coord_type="gcj02")
        out2 = to_output_coord(item["x2"], item["y2"], output_coord_type="gcj02")
        props: Dict[str, Any] = {
            "edge_id": "edge:" + hashlib.sha256(
                ":".join(sorted((
                    f"{safe_round(item['x1'], 7):.7f},{safe_round(item['y1'], 7):.7f}",
                    f"{safe_round(item['x2'], 7):.7f},{safe_round(item['y2'], 7):.7f}",
                ))).encode("utf-8")
            ).hexdigest()[:20],
            "record_id": "",
            "length_m": safe_round(item["length_m"], 2),
            "choice_score": safe_round(default_choice, 8),
            "integration_score": safe_round(default_integ, 8),
            "accessibility_score": safe_round(default_integ, 8),
            "connectivity_score": safe_round(connectivity_score, 8),
            "degree_score": 0.0,
            "intelligibility_score": 0.0,
            "choice_global": safe_round(choice_by_label.get("global", 0.0), 8),
            "integration_global": safe_round(integ_by_label.get("global", 0.0), 8),
            "accessibility_global": safe_round(integ_by_label.get("global", 0.0), 8),
            "rank_quantile_choice": 0.0,
            "rank_quantile_integration": 0.0,
            "rank_quantile_accessibility": 0.0,
            "is_skeleton_choice_top20": False,
            "is_skeleton_integration_top20": False,
        }
        props["record_id"] = props["edge_id"]
        for label in local_labels:
            props[f"choice_{label}"] = safe_round(choice_by_label.get(label, 0.0), 8)
            props[f"integration_{label}"] = safe_round(integ_by_label.get(label, 0.0), 8)
            props[f"accessibility_{label}"] = safe_round(integ_by_label.get(label, 0.0), 8)
        if control_score is not None:
            props["control_score"] = safe_round(control_score, 8)
            props["control_global"] = safe_round(control_score, 8)
        if depth_score is not None:
            props["depth_score"] = safe_round(depth_score, 8)
            props["depth_global"] = safe_round(depth_score, 8)

        edge_integ_global = float(integ_by_label.get("global", 0.0))
        endpoint_keys = [item["key1"], item["key2"]]
        if endpoint_keys[0] == endpoint_keys[1]:
            endpoint_keys = endpoint_keys[:1]
        for node_key in endpoint_keys:
            node_integ_sum[node_key] = float(node_integ_sum.get(node_key, 0.0)) + edge_integ_global
            node_integ_cnt[node_key] = int(node_integ_cnt.get(node_key, 0)) + 1

        scored_edges.append(
            {
                "metric": default_integ if render_metric == "integration" else default_choice,
                "key1": item["key1"],
                "key2": item["key2"],
                "feature": {
                    "type": "Feature",
                    "properties": props,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [safe_round(out1[0], 6), safe_round(out1[1], 6)],
                            [safe_round(out2[0], 6), safe_round(out2[1], 6)],
                        ],
                    },
                },
            }
        )

    degree_by_node: Dict[Tuple[float, float], float] = {key: float(len(neighbors)) for key, neighbors in neighbor_sets.items()}
    degree_values = [value for value in degree_by_node.values() if math.isfinite(value)]
    degree_bounds = (min(degree_values), max(degree_values)) if degree_values else None
    degree_score_by_node: Dict[Tuple[float, float], float] = {key: norm(value, degree_bounds) for key, value in degree_by_node.items()}
    integ_global_by_node: Dict[Tuple[float, float], float] = {}
    for key in neighbor_sets.keys():
        count = int(node_integ_cnt.get(key, 0))
        if count <= 0:
            integ_global_by_node[key] = 0.0
            continue
        integ_global_by_node[key] = max(0.0, min(1.0, float(node_integ_sum.get(key, 0.0)) / float(count)))

    intelligibility_x: List[float] = []
    intelligibility_y: List[float] = []
    for scored in scored_edges:
        props = ((scored.get("feature") or {}).get("properties") or {})
        connectivity_value = float(props.get("connectivity_score", 0.0))
        integration_value = float(props.get("integration_global", 0.0))
        if math.isfinite(connectivity_value) and math.isfinite(integration_value):
            intelligibility_x.append(connectivity_value)
            intelligibility_y.append(integration_value)
    intelligibility_corr = pearson_corr(intelligibility_x, intelligibility_y)
    intelligibility_r2 = intelligibility_corr * intelligibility_corr
    reg_slope, reg_intercept = linear_regression(intelligibility_x, intelligibility_y)
    sampled_scatter = sample_scatter_points(list(zip(intelligibility_x, intelligibility_y)), max_points=3000, bins=20)

    default_choice_has_local = default_radius_label != "global" and default_radius_label in choice_columns
    default_integration_has_local = default_radius_label != "global" and default_radius_label in integration_columns

    def _resolve_rank_metric(props: Dict[str, Any], prefix: str) -> float:
        local_available = default_choice_has_local if prefix == "choice" else prefix in ("integration", "accessibility") and default_integration_has_local
        local_key = f"{prefix}_{default_radius_label}"
        global_key = f"{prefix}_global"
        if local_available and local_key in props:
            value = float(props.get(local_key, 0.0))
            if math.isfinite(value):
                return value
        value = float(props.get(global_key, props.get(f"{prefix}_score", 0.0)))
        return value if math.isfinite(value) else 0.0

    choice_sorted = sorted(_resolve_rank_metric((scored.get("feature") or {}).get("properties") or {}, "choice") for scored in scored_edges)
    integ_sorted = sorted(_resolve_rank_metric((scored.get("feature") or {}).get("properties") or {}, "integration") for scored in scored_edges)
    access_sorted = sorted(_resolve_rank_metric((scored.get("feature") or {}).get("properties") or {}, "accessibility") for scored in scored_edges)

    for scored in scored_edges:
        key1 = scored.get("key1")
        key2 = scored.get("key2")
        degree_1 = float(degree_score_by_node.get(key1, 0.0))
        degree_2 = float(degree_score_by_node.get(key2, 0.0))
        degree_score = max(0.0, min(1.0, (degree_1 + degree_2) / 2.0))
        props = ((scored.get("feature") or {}).get("properties") or {})
        connectivity_score = float(props.get("connectivity_score", degree_score))
        if not math.isfinite(connectivity_score):
            connectivity_score = degree_score
        connectivity_score = max(0.0, min(1.0, connectivity_score))
        props["connectivity_score"] = safe_round(connectivity_score, 8)
        props["degree_score"] = safe_round(degree_score, 8)
        props["intelligibility_score"] = safe_round(intelligibility_corr, 8)
        choice_rank = percentile_rank(choice_sorted, _resolve_rank_metric(props, "choice"))
        integ_rank = percentile_rank(integ_sorted, _resolve_rank_metric(props, "integration"))
        access_rank = percentile_rank(access_sorted, _resolve_rank_metric(props, "accessibility"))
        props["rank_quantile_choice"] = safe_round(choice_rank, 8)
        props["rank_quantile_integration"] = safe_round(integ_rank, 8)
        props["rank_quantile_accessibility"] = safe_round(access_rank, 8)
        props["is_skeleton_choice_top20"] = bool(choice_rank >= 0.8)
        props["is_skeleton_integration_top20"] = bool(integ_rank >= 0.8)

    node_features: List[Dict[str, Any]] = []
    for node_key, deg in degree_by_node.items():
        lon_wgs, lat_wgs = node_key
        lon_out, lat_out = to_output_coord(lon_wgs, lat_wgs, output_coord_type="gcj02")
        degree_raw = float(deg)
        degree_score = float(degree_score_by_node.get(node_key, 0.0))
        integ_global = float(integ_global_by_node.get(node_key, 0.0))
        node_id = f"{safe_round(lon_out, 6):.6f},{safe_round(lat_out, 6):.6f}"
        node_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [safe_round(lon_out, 6), safe_round(lat_out, 6)]},
                "properties": {
                    "node_id": node_id,
                    "degree": int(round(degree_raw)),
                    "degree_score": safe_round(degree_score, 8),
                    "integration_global": safe_round(integ_global, 8),
                },
            }
        )

    all_scored_features = [item["feature"] for item in scored_edges]
    max_features = len(scored_edges) if max_edge_features is None else max(100, int(max_edge_features))
    features_out = all_scored_features[:max_features] if include_geojson else []
    pre_merge_feature_count = len(features_out)
    if include_geojson and merge_geojson_edges and len(features_out) >= 2:
        features_out = merge_linestring_features(features_out, bucket_step=merge_bucket_step, angle_cos_min=0.92)
    rendered_edge_count = len(features_out) if include_geojson else 0
    road_orientation_analysis = build_road_orientation_analysis(all_scored_features)
    raw_edge_count = int(len(parsed_edges))
    edge_merge_ratio = 1.0 if pre_merge_feature_count <= 0 else max(0.0, min(1.0, float(rendered_edge_count) / float(pre_merge_feature_count)))

    node_count = len(neighbor_sets)
    avg_degree = (sum(len(value) for value in neighbor_sets.values()) / float(node_count)) if node_count > 0 else 0.0

    def _avg(values: List[float]) -> float:
        finite = [float(value) for value in values if math.isfinite(float(value))]
        return (sum(finite) / float(len(finite))) if finite else 0.0

    avg_choice_global = _avg(global_choice_values)
    avg_integration_global = _avg(global_integ_values)
    avg_connectivity_value = _avg(global_conn_values_raw) if global_conn_values_raw else avg_degree
    avg_control_value = _avg(global_control_values)
    avg_depth_value = _avg(global_depth_values)
    control_valid_count = len(metric_values_control_raw)
    depth_valid_count = len(metric_values_depth_raw)
    avg_choice_by_radius = {label: _avg(local_choice_values.get(label, [])) for label in local_labels}
    avg_integration_by_radius = {label: _avg(local_integ_values.get(label, [])) for label in local_labels}
    avg_choice_local = avg_choice_by_radius.get(default_radius_label, avg_choice_global)
    avg_integration_local = avg_integration_by_radius.get(default_radius_label, avg_integration_global)

    default_webgl_metric_field = str(arcgis_metric_field or "").strip() or (
        "integration_score" if render_metric == "integration" else "accessibility_score"
    )
    if not use_arcgis_webgl:
        webgl_disabled_reason = "disabled:not_requested"
    elif not include_geojson:
        webgl_disabled_reason = "disabled:geojson_disabled"
    elif not features_out:
        webgl_disabled_reason = "disabled:no_renderable_features"
    else:
        webgl_disabled_reason = "disabled:unknown"
    webgl_payload: Dict[str, Any] = {
        "enabled": False,
        "backend": "none",
        "status": webgl_disabled_reason,
        "metric_field": default_webgl_metric_field,
        "coord_type": "gcj02",
        "roads": {"type": "FeatureCollection", "features": [], "count": 0},
        "elapsed_ms": 0.0,
    }
    if use_arcgis_webgl and include_geojson and features_out:
        bridge_started = time.perf_counter()
        try:
            arcgis_result = run_arcgis_road_syntax_webgl(
                road_features=features_out,
                metric_field=default_webgl_metric_field,
                target_coord_type="gcj02",
                timeout_sec=int(max(5, int(arcgis_timeout_sec or 20))),
            )
            webgl_payload = {
                "enabled": True,
                "backend": "arcgis_bridge",
                "status": str(arcgis_result.get("status") or "ok"),
                "metric_field": str(arcgis_result.get("metric_field") or default_webgl_metric_field),
                "coord_type": str(arcgis_result.get("coord_type") or "gcj02"),
                "roads": arcgis_result.get("roads") or {"type": "FeatureCollection", "features": [], "count": 0},
                "elapsed_ms": safe_round((time.perf_counter() - bridge_started) * 1000.0, 2),
            }
        except ArcGISRoadSyntaxBridgeError as exc:
            webgl_payload = {
                "enabled": False,
                "backend": "arcgis_bridge",
                "status": f"bridge_error: {exc}",
                "metric_field": default_webgl_metric_field,
                "coord_type": "gcj02",
                "roads": {"type": "FeatureCollection", "features": [], "count": 0},
                "elapsed_ms": safe_round((time.perf_counter() - bridge_started) * 1000.0, 2),
            }

    elapsed_ms = safe_round((time.perf_counter() - started_at) * 1000.0, 2)
    report_progress(
        "completed",
        "路网句法计算完成，正在返回结果",
        9,
        {
            "context_edge_count": len(parsed_edges_context),
            "output_edge_count": len(parsed_edges),
            "elapsed_ms": elapsed_ms,
        },
    )
    return {
        "summary": {
            "node_count": int(node_count),
            "edge_count": raw_edge_count,
            "rendered_edge_count": int(rendered_edge_count),
            "edge_merge_ratio": safe_round(edge_merge_ratio, 6),
            "network_length_km": safe_round(total_length_m / 1000.0, 4),
            "avg_degree": safe_round(avg_degree, 4),
            "avg_closeness": safe_round(avg_integration_global, 8),
            "avg_choice": safe_round(avg_choice_global, 8),
            "avg_accessibility_global": safe_round(avg_integration_global, 8),
            "avg_connectivity": safe_round(avg_connectivity_value, 8),
            "avg_control": safe_round(avg_control_value, 8),
            "avg_depth": safe_round(avg_depth_value, 8),
            "control_source_column": str(control_col_source or ""),
            "control_valid_count": int(control_valid_count),
            "depth_source_column": str(depth_col or ""),
            "depth_valid_count": int(depth_valid_count),
            "avg_intelligibility": safe_round(intelligibility_corr, 8),
            "avg_intelligibility_r2": safe_round(intelligibility_r2, 8),
            "avg_integration_global": safe_round(avg_integration_global, 8),
            "avg_choice_global": safe_round(avg_choice_global, 8),
            "avg_integration_local": safe_round(avg_integration_local, 8),
            "avg_choice_local": safe_round(avg_choice_local, 8),
            "avg_integration_by_radius": {label: safe_round(value, 8) for label, value in avg_integration_by_radius.items()},
            "avg_choice_by_radius": {label: safe_round(value, 8) for label, value in avg_choice_by_radius.items()},
            "radius_labels": local_labels,
            "mode": mode,
            "coord_type": "gcj02",
            "default_metric": render_metric,
            "default_radius_label": default_radius_label,
            "analysis_engine": analysis_engine_label,
            "road_orientation_analysis": road_orientation_analysis,
        },
        "top_nodes": [],
        "road_edges": {"type": "FeatureCollection", "features": all_scored_features, "count": len(all_scored_features)},
        "road_grid": {"type": "FeatureCollection", "features": [], "count": 0},
        "roads": {"type": "FeatureCollection", "features": features_out, "count": len(features_out)},
        "nodes": {"type": "FeatureCollection", "features": node_features, "count": len(node_features)},
        "diagnostics": {
            "intelligibility_scatter": [{"x": safe_round(x, 8), "y": safe_round(y, 8)} for x, y in sampled_scatter],
            "regression": {
                "slope": safe_round(reg_slope, 8),
                "intercept": safe_round(reg_intercept, 8),
                "r": safe_round(intelligibility_corr, 8),
                "r2": safe_round(intelligibility_r2, 8),
                "n": int(len(intelligibility_x)),
            },
        },
        "webgl": webgl_payload,
    }
