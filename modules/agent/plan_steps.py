from __future__ import annotations

from .schemas import PlanStep


def scope_step() -> PlanStep:
    return PlanStep(
        tool_name="read_current_scope",
        reason="读取当前分析范围",
        expected_artifacts=["scope_polygon", "scope_data", "isochrone_feature"],
    )


def results_step(reason: str) -> PlanStep:
    return PlanStep(
        tool_name="read_current_results",
        reason=reason,
        expected_artifacts=[
            "current_pois",
            "current_poi_summary",
            "current_poi_h3",
            "current_poi_h3_summary",
            "current_road",
            "current_road_summary",
            "current_population",
            "current_population_summary",
            "current_nightlight",
            "current_nightlight_summary",
        ],
    )


def road_step(reason: str) -> PlanStep:
    return PlanStep(
        tool_name="compute_road_syntax_from_scope",
        reason=reason,
        expected_artifacts=["current_road", "current_road_summary"],
    )


def population_step(reason: str) -> PlanStep:
    return PlanStep(
        tool_name="compute_population_overview_from_scope",
        reason=reason,
        expected_artifacts=["current_population", "current_population_summary"],
    )


def nightlight_step(reason: str) -> PlanStep:
    return PlanStep(
        tool_name="compute_nightlight_overview_from_scope",
        reason=reason,
        expected_artifacts=["current_nightlight", "current_nightlight_summary"],
    )
