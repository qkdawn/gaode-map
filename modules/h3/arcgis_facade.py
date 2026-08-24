from __future__ import annotations

from typing import Any, Dict, List

from .arcgis_bridge import run_arcgis_h3_analysis


def run_h3_arcgis_analysis(
    *,
    features: List[Dict[str, Any]],
    stats_by_cell: Dict[str, Dict[str, Any]],
    timeout_sec: int,
) -> Dict[str, Any]:
    try:
        return run_arcgis_h3_analysis(
            features=features,
            stats_by_cell=stats_by_cell,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:
        raise RuntimeError(f"ArcGIS桥接失败: {exc}") from exc
