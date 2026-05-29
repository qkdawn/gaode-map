from __future__ import annotations

from typing import Any, Dict

from ..schemas import AnalysisSnapshot, ToolResult


def _safe_summary_block(block: Any) -> Dict[str, Any]:
    return block if isinstance(block, dict) else {}


async def read_current_results(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, artifacts, question
    poi_summary = _safe_summary_block(snapshot.poi_summary)
    raw_poi_total = poi_summary.get("total")
    poi_count = int(raw_poi_total) if raw_poi_total is not None else None
    h3_payload = _safe_summary_block(snapshot.h3)
    road_payload = _safe_summary_block(snapshot.road)
    population_payload = _safe_summary_block(snapshot.population)
    nightlight_payload = _safe_summary_block(snapshot.nightlight)

    h3_summary = _safe_summary_block(h3_payload.get("summary"))
    road_summary = _safe_summary_block(road_payload.get("summary"))
    population_summary = _safe_summary_block(population_payload.get("summary"))
    nightlight_summary = _safe_summary_block(nightlight_payload.get("summary"))

    evidence = [
        {"field": "poi.count", "value": poi_count},
        {"field": "poi.total_available", "value": poi_count is not None},
        {"field": "h3.has_summary", "value": bool(h3_summary)},
        {"field": "road.has_summary", "value": bool(road_summary)},
        {"field": "population.has_summary", "value": bool(population_summary)},
        {"field": "population.summary.total_population", "value": population_summary.get("total_population")},
        {"field": "population.summary.male_ratio", "value": population_summary.get("male_ratio")},
        {"field": "population.summary.female_ratio", "value": population_summary.get("female_ratio")},
        {"field": "nightlight.has_summary", "value": bool(nightlight_summary)},
        {"field": "nightlight.summary.total_radiance", "value": nightlight_summary.get("total_radiance")},
        {"field": "nightlight.summary.mean_radiance", "value": nightlight_summary.get("mean_radiance")},
        {"field": "nightlight.summary.peak_radiance", "value": nightlight_summary.get("max_radiance")},
        {"field": "nightlight.summary.lit_pixel_ratio", "value": nightlight_summary.get("lit_pixel_ratio")},
    ]
    return ToolResult(
        tool_name="read_current_results",
        status="success",
        result={
            "poi_count": poi_count,
            "has_h3_summary": bool(h3_summary),
            "has_road_summary": bool(road_summary),
            "has_population_summary": bool(population_summary),
            "has_nightlight_summary": bool(nightlight_summary),
            "population_total": population_summary.get("total_population"),
            "population_male_ratio": population_summary.get("male_ratio"),
            "population_female_ratio": population_summary.get("female_ratio"),
            "nightlight_total_radiance": nightlight_summary.get("total_radiance"),
            "nightlight_mean_radiance": nightlight_summary.get("mean_radiance"),
            "nightlight_peak_radiance": nightlight_summary.get("max_radiance"),
            "nightlight_lit_pixel_ratio": nightlight_summary.get("lit_pixel_ratio"),
        },
        evidence=evidence,
        artifacts={
            "current_pois": list(snapshot.pois or []),
            "current_poi_summary": poi_summary,
            "current_poi_h3": h3_payload,
            "current_poi_h3_grid": _safe_summary_block(h3_payload.get("grid")),
            "current_poi_h3_summary": h3_summary,
            "current_poi_h3_charts": _safe_summary_block(h3_payload.get("charts")),
            "current_road": road_payload,
            "current_road_summary": road_summary,
            "current_population": population_payload,
            "current_population_summary": population_summary,
            "current_nightlight": nightlight_payload,
            "current_nightlight_summary": nightlight_summary,
            "current_frontend_analysis": dict(snapshot.frontend_analysis or {}),
        },
    )
