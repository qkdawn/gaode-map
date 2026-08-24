from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional, Tuple

import h3
import numpy as np
from scipy.stats import entropy as scipy_entropy

from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84

from .category_rules import CATEGORY_KEYS, CATEGORY_RULES, CategoryKey, empty_category_counts, infer_category_key


def safe_round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    if value is None:
        return None
    try:
        if not math.isfinite(value):
            return None
        return round(float(value), ndigits)
    except Exception:
        return None


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except Exception:
        return None


def calc_continuous_stats(values: List[Optional[float]]) -> Dict[str, Any]:
    valid = np.asarray(
        [float(v) for v in values if isinstance(v, (int, float, np.floating)) and math.isfinite(float(v))],
        dtype=float,
    )
    if valid.size <= 0:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "p10": None,
            "p50": None,
            "p90": None,
        }
    return {
        "count": int(valid.size),
        "mean": safe_round(float(np.mean(valid)), 6),
        "std": safe_round(float(np.std(valid, ddof=0)), 6),
        "min": safe_round(float(np.min(valid)), 6),
        "max": safe_round(float(np.max(valid)), 6),
        "p10": safe_round(float(np.percentile(valid, 10)), 6),
        "p50": safe_round(float(np.percentile(valid, 50)), 6),
        "p90": safe_round(float(np.percentile(valid, 90)), 6),
    }


def build_gi_render_meta() -> Dict[str, Any]:
    return {"mode": "fixed_z", "min": -3.0, "max": 3.0, "center": 0.0}


def build_lisa_render_meta(lisa_i_stats: Dict[str, Any]) -> Dict[str, Any]:
    mean_val = safe_float(lisa_i_stats.get("mean"))
    std_val = safe_float(lisa_i_stats.get("std"))
    min_val = safe_float(lisa_i_stats.get("min"))
    max_val = safe_float(lisa_i_stats.get("max"))
    count = int(lisa_i_stats.get("count") or 0)
    degraded = bool(
        count <= 1
        or mean_val is None
        or std_val is None
        or (not math.isfinite(std_val))
        or std_val <= 0.0
    )
    if degraded:
        center = safe_round(mean_val, 6) if mean_val is not None else 0.0
        return {
            "mode": "stddev",
            "mean": safe_round(mean_val, 6),
            "std": safe_round(std_val, 6),
            "min": safe_round(min_val, 6),
            "max": safe_round(max_val, 6),
            "clip_min": center,
            "clip_max": center,
            "degraded": True,
            "message": "LMiIndex方差不足",
        }

    p10_val = safe_float(lisa_i_stats.get("p10"))
    p90_val = safe_float(lisa_i_stats.get("p90"))
    std_clip_min = mean_val - 2.0 * std_val
    std_clip_max = mean_val + 2.0 * std_val
    clip_min_raw = max(v for v in [std_clip_min, p10_val, min_val] if v is not None and math.isfinite(v))
    clip_max_raw = min(v for v in [std_clip_max, p90_val, max_val] if v is not None and math.isfinite(v))
    if clip_max_raw <= clip_min_raw:
        clip_min_raw = p10_val if p10_val is not None else min_val
        clip_max_raw = p90_val if p90_val is not None else max_val
    if clip_min_raw is None or clip_max_raw is None or clip_max_raw <= clip_min_raw:
        clip_min_raw = min_val
        clip_max_raw = max_val
    if clip_min_raw is None or clip_max_raw is None or clip_max_raw <= clip_min_raw:
        clip_min_raw = mean_val - 2.0 * std_val
        clip_max_raw = mean_val + 2.0 * std_val

    return {
        "mode": "stddev",
        "mean": safe_round(mean_val, 6),
        "std": safe_round(std_val, 6),
        "min": safe_round(min_val, 6),
        "max": safe_round(max_val, 6),
        "clip_min": safe_round(clip_min_raw, 6),
        "clip_max": safe_round(clip_max_raw, 6),
        "degraded": False,
        "message": None,
    }


def new_local_spatial_stat() -> Dict[str, Any]:
    return {
        "lisa_i": None,
        "lisa_z_score": None,
        "gi_star_value": None,
        "gi_star_z_score": None,
        "p_value": None,
        "adjusted_p_value": None,
        "cluster_type": None,
    }


def latlng_to_cell(lat: float, lng: float, resolution: int) -> Optional[str]:
    try:
        if hasattr(h3, "latlng_to_cell"):
            return h3.latlng_to_cell(lat, lng, resolution)
        if hasattr(h3, "geo_to_h3"):
            return h3.geo_to_h3(lat, lng, resolution)
    except Exception:
        return None
    return None


def cell_area_km2(cell_id: str, resolution: int) -> float:
    try:
        if hasattr(h3, "cell_area"):
            return float(h3.cell_area(cell_id, unit="km^2"))
        if hasattr(h3, "hex_area"):
            return float(h3.hex_area(resolution, unit="km^2"))
    except Exception:
        return 0.0
    return 0.0


def neighbors(cell_id: str) -> List[str]:
    try:
        if hasattr(h3, "grid_disk"):
            return list(h3.grid_disk(cell_id, 1))
        if hasattr(h3, "k_ring"):
            return list(h3.k_ring(cell_id, 1))
    except Exception:
        return []
    return []


def has_density_variance(stats_by_cell: Dict[str, Dict[str, Any]], tol: float = 1e-12) -> bool:
    if not stats_by_cell:
        return False
    values = [float(bucket.get("density_poi_per_km2") or 0.0) for bucket in stats_by_cell.values()]
    if len(values) < 2:
        return False
    return (max(values) - min(values)) > float(tol)


def shannon_entropy(category_counts: Dict[CategoryKey, int]) -> float:
    counts = np.asarray(list(category_counts.values()), dtype=float)
    if counts.size <= 0:
        return 0.0
    counts = counts[counts > 0]
    if counts.size <= 0:
        return 0.0
    probs = counts / counts.sum()
    return float(scipy_entropy(probs, base=math.e))


def aggregate_pois_to_h3(
    grid_ids: List[str],
    pois: List[Dict[str, Any]],
    resolution: int,
    poi_coord_type: Literal["gcj02", "wgs84"] = "gcj02",
) -> Tuple[Dict[str, Dict[str, Any]], int, Dict[CategoryKey, int]]:
    grid_set = set(grid_ids)
    global_category_counts = empty_category_counts()
    stats_by_cell: Dict[str, Dict[str, Any]] = {
        cell_id: {
            "poi_count": 0,
            "category_counts": empty_category_counts(),
            "subcategory_counts": {},
            "density_poi_per_km2": 0.0,
            "local_entropy": 0.0,
            "neighbor_mean_density": 0.0,
            "neighbor_mean_entropy": 0.0,
            "neighbor_count": 0,
        }
        for cell_id in grid_ids
    }
    assigned_poi_count = 0

    for poi in pois or []:
        location = poi.get("location")
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            continue
        try:
            lng = float(location[0])
            lat = float(location[1])
        except (TypeError, ValueError):
            continue
        if poi_coord_type == "gcj02":
            lng, lat = gcj02_to_wgs84(lng, lat)
        cell_id = latlng_to_cell(lat, lng, resolution)
        if not cell_id or cell_id not in grid_set:
            continue
        assigned_poi_count += 1
        bucket = stats_by_cell[cell_id]
        bucket["poi_count"] += 1
        category_key = infer_category_key(poi.get("type"))
        if category_key:
            bucket["category_counts"][category_key] += 1
            global_category_counts[category_key] += 1
        point_type = str(poi.get("type") or "").strip()
        if point_type:
            bucket["subcategory_counts"][point_type] = int(bucket["subcategory_counts"].get(point_type, 0)) + 1

    return stats_by_cell, assigned_poi_count, global_category_counts


def compute_cell_metrics(stats_by_cell: Dict[str, Dict[str, Any]], resolution: int) -> None:
    for cell_id, stats in stats_by_cell.items():
        area_km2 = cell_area_km2(cell_id, resolution)
        poi_count = stats["poi_count"]
        stats["density_poi_per_km2"] = float((poi_count / area_km2) if area_km2 > 0 else 0.0)
        stats["local_entropy"] = float(shannon_entropy(stats["category_counts"]))


def compute_neighbor_metrics(stats_by_cell: Dict[str, Dict[str, Any]]) -> None:
    cell_ids = list(stats_by_cell.keys())
    if not cell_ids:
        return
    cell_set = set(cell_ids)
    for cell_id in cell_ids:
        neighbor_ids = [nid for nid in neighbors(cell_id) if nid in cell_set and nid != cell_id]
        neighbor_count = int(len(neighbor_ids))
        stats = stats_by_cell[cell_id]
        stats["neighbor_count"] = neighbor_count
        if neighbor_count <= 0:
            stats["neighbor_mean_density"] = 0.0
            stats["neighbor_mean_entropy"] = 0.0
            continue
        density_sum = 0.0
        entropy_sum = 0.0
        for neighbor_id in neighbor_ids:
            neighbor_stats = stats_by_cell.get(neighbor_id) or {}
            density_sum += float(neighbor_stats.get("density_poi_per_km2", 0.0) or 0.0)
            entropy_sum += float(neighbor_stats.get("local_entropy", 0.0) or 0.0)
        stats["neighbor_mean_density"] = float(density_sum / neighbor_count)
        stats["neighbor_mean_entropy"] = float(entropy_sum / neighbor_count)


def compute_global_moran_i(
    stats_by_cell: Dict[str, Dict[str, Any]],
    value_key: str = "density_poi_per_km2",
) -> Optional[float]:
    cell_ids = list(stats_by_cell.keys())
    n = len(cell_ids)
    if n < 2:
        return None
    values = {cell_id: float(stats_by_cell[cell_id].get(value_key, 0.0) or 0.0) for cell_id in cell_ids}
    mean_value = sum(values.values()) / n
    denominator = sum((values[cell_id] - mean_value) ** 2 for cell_id in cell_ids)
    if denominator <= 0:
        return None

    numerator = 0.0
    s0 = 0
    cell_set = set(cell_ids)
    for cell_id in cell_ids:
        cell_neighbors = [nid for nid in neighbors(cell_id) if nid in cell_set and nid != cell_id]
        for neighbor_id in cell_neighbors:
            numerator += (values[cell_id] - mean_value) * (values[neighbor_id] - mean_value)
            s0 += 1
    if s0 <= 0:
        return None
    return safe_round((n / s0) * (numerator / denominator), 6)


def build_local_spatial_stats_from_arcgis(
    stats_by_cell: Dict[str, Dict[str, Any]],
    arcgis_cells: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
    local_stats: Dict[str, Dict[str, Any]] = {cell_id: new_local_spatial_stat() for cell_id in stats_by_cell.keys()}
    if not arcgis_cells:
        return finalize_native_spatial_fields(local_stats)
    for item in arcgis_cells:
        h3_id = str((item or {}).get("h3_id") or "")
        if not h3_id or h3_id not in local_stats:
            continue
        stats = local_stats[h3_id]
        row = item or {}
        gi_z = safe_round(safe_float(row.get("gi_z_score")), 6)
        p_value = row.get("p_value")
        if p_value is None:
            p_value = row.get("gi_p_value", row.get("lisa_p_value"))
        adjusted_p_value = row.get("adjusted_p_value")
        if adjusted_p_value is None:
            adjusted_p_value = row.get("fdr_p_value")
        cluster_type = row.get("cluster_type") or row.get("lisa_cluster_type") or row.get("gi_cluster_type")
        stats.update(
            {
                "lisa_i": safe_round(safe_float(row.get("lisa_i")), 6),
                "lisa_z_score": safe_round(safe_float(row.get("lisa_z_score")), 6),
                "gi_star_value": safe_round(safe_float(row.get("gi_star_value")), 6),
                "gi_star_z_score": gi_z,
                "p_value": safe_round(safe_float(p_value), 8),
                "adjusted_p_value": safe_round(safe_float(adjusted_p_value), 8),
                "cluster_type": str(cluster_type).strip() if cluster_type is not None else None,
            }
        )
    return finalize_native_spatial_fields(local_stats)


def empty_spatial_structure_counts() -> Dict[str, int]:
    return {}


def finalize_native_spatial_fields(
    local_stats: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
    return local_stats, empty_spatial_structure_counts()


def build_chart_payload(
    global_category_counts: Dict[CategoryKey, int],
    density_values: List[float],
) -> Dict[str, Any]:
    labels = [label for _key, label, _codes in CATEGORY_RULES]
    keys = [key for key, _label, _codes in CATEGORY_RULES]
    values = [int(global_category_counts.get(key, 0)) for key in keys]

    edges = np.asarray([0, 1, 2, 5, 10, 20, 50, 100, 200], dtype=float)
    hist_labels = [f"{int(edges[i])}-{int(edges[i + 1])}" for i in range(len(edges) - 1)] + [f">={int(edges[-1])}"]
    hist_counts = np.zeros(len(hist_labels), dtype=np.int64)
    if density_values:
        density_arr = np.asarray(density_values, dtype=float)
        density_arr = density_arr[np.isfinite(density_arr)]
        if density_arr.size > 0:
            bin_edges = np.concatenate([edges, np.asarray([np.inf])])
            bin_indices = np.digitize(density_arr, bin_edges, right=False) - 1
            bin_indices = np.clip(bin_indices, 0, len(hist_labels) - 1)
            hist_counts = np.bincount(bin_indices, minlength=len(hist_labels))

    return {
        "category_distribution": {"labels": labels, "values": values},
        "density_histogram": {"bins": hist_labels, "counts": [int(item) for item in hist_counts.tolist()]},
    }
