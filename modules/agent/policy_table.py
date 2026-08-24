from __future__ import annotations

from typing import Any, Dict


POLICY_TABLE: Dict[str, Dict[str, Any]] = {
    "community_life_circle": {
        "label": "社区生活圈",
        "buffer_m": 500,
        "time_min": 15,
        "mode": "walking",
        "h3_resolution": 10,
        "include_mode": "intersects",
        "min_overlap_ratio": 0.0,
    },
    "business_catchment_1km": {
        "label": "商圈辐射 1km",
        "buffer_m": 1000,
        "drive_time_min": 10,
        "walk_time_min": 15,
        "mode": "driving",
        "h3_resolution": 10,
        "include_mode": "intersects",
        "min_overlap_ratio": 0.0,
    },
    "tod_station_area": {
        "label": "TOD 站城范围",
        "buffer_m": 800,
        "time_min": 10,
        "mode": "walking",
        "h3_resolution": 10,
        "include_mode": "centroid",
        "min_overlap_ratio": 0.15,
    },
    "neighborhood_commerce": {
        "label": "邻里商业",
        "buffer_m": 600,
        "time_min": 15,
        "mode": "walking",
        "h3_resolution": 10,
        "include_mode": "intersects",
        "min_overlap_ratio": 0.0,
    },
    "district_summary": {
        "label": "片区画像",
        "buffer_m": 1200,
        "time_min": 20,
        "mode": "walking",
        "h3_resolution": 10,
        "include_mode": "intersects",
        "min_overlap_ratio": 0.0,
    },
}


def resolve_policy(policy_key: str | None, *, fallback: str = "district_summary") -> Dict[str, Any]:
    key = str(policy_key or "").strip()
    if key and key in POLICY_TABLE:
        return {"policy_key": key, **POLICY_TABLE[key]}
    return {"policy_key": fallback, **POLICY_TABLE[fallback]}
