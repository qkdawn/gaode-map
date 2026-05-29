from modules.agent.planner import build_planning_fallback
from modules.agent.schemas import AnalysisSnapshot, WorkingMemory


def _snapshot_with_scope(**kwargs) -> AnalysisSnapshot:
    payload = {
        "scope": {
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        }
    }
    payload.update(kwargs)
    return AnalysisSnapshot(**payload)


def test_planner_area_character_prefers_scene_pack():
    snapshot = _snapshot_with_scope(
        poi_summary={"total": 10},
        h3={"summary": {"grid_count": 4}},
        population={"summary": {"total_population": 1000}},
        nightlight={"summary": {"max_radiance": 4.0}},
        road={"summary": {"node_count": 8}},
        frontend_analysis={
            "poi": {"category_stats": {"labels": ["餐饮"], "values": [10]}},
            "h3": {"derived_stats": {"structureSummary": {"rows": [{"h3_id": "a", "is_structure_signal": True}]}}},
            "population": {"age_distribution": [{"age_band_label": "25-34岁", "total": 100}], "layer_summary": {}},
            "nightlight": {"analysis": {"core_hotspot_count": 1}},
            "road": {"regression": {"r2": 0.51}},
        },
    )
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})

    result = build_planning_fallback(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        memory=memory,
    )

    tool_names = [step.tool_name for step in result.steps]
    assert tool_names[:2] == ["read_current_scope", "read_current_results"]
    assert "run_area_character_pack" in tool_names
    assert result.question_type == "area_character"


def test_planner_next_analysis_uses_analysis_options_tool():
    snapshot = _snapshot_with_scope(
        poi_summary={"total": 10},
        h3={"summary": {"grid_count": 4}},
        population={"summary": {"total_population": 1000}},
        nightlight={"summary": {"max_radiance": 4.0}},
        road={"summary": {"node_count": 8}},
    )
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})

    result = build_planning_fallback(
        question="下一步做什么分析",
        snapshot=snapshot,
        memory=memory,
    )

    tool_names = [step.tool_name for step in result.steps]
    assert result.question_type == "next_analysis"
    assert tool_names[:2] == ["read_current_scope", "read_current_results"]
    assert "rank_next_analysis_options" in tool_names
    assert "run_area_character_pack" not in tool_names


def test_planner_area_character_still_uses_scene_pack_when_dimensions_empty():
    snapshot = _snapshot_with_scope(
        poi_summary={"total": 2931},
        frontend_analysis={
            "poi": {"category_stats": {"labels": ["餐饮", "购物"], "values": [1000, 565]}},
            "h3": {},
            "population": {},
            "nightlight": {},
            "road": {},
        },
    )
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})

    result = build_planning_fallback(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        memory=memory,
    )

    tool_names = [step.tool_name for step in result.steps]
    assert "run_area_character_pack" in tool_names
    assert tool_names[:2] == ["read_current_scope", "read_current_results"]


def test_planner_population_question_prefers_population_profile_tool():
    snapshot = _snapshot_with_scope(population={"summary": {"total_population": 1000}}, frontend_analysis={"population": {"analysis_view": "age"}})
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})

    result = build_planning_fallback(
        question="这个区域人口怎么样",
        snapshot=snapshot,
        memory=memory,
    )

    tool_names = [step.tool_name for step in result.steps]
    assert "read_population_profile_analysis" in tool_names or "compute_population_overview_from_scope" in tool_names
    assert "compute_population_overview_from_scope" not in tool_names


def test_planner_site_selection_prefers_scene_pack():
    snapshot = _snapshot_with_scope(
        poi_summary={"total": 5, "types": "050500|050501|050502|050503|050504", "keywords": "咖啡厅"},
        h3={"summary": {"grid_count": 4, "avg_density_poi_per_km2": 5.2}},
    )
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_pois": [{"id": "coffee-1"}],
            "current_poi_summary": {"total": 5, "types": "050500|050501|050502|050503|050504", "keywords": "咖啡厅"},
            "current_poi_h3_summary": {"grid_count": 4, "avg_density_poi_per_km2": 5.2},
        }
    )

    result = build_planning_fallback(
        question="我想在这里开一家咖啡店，给我建议",
        snapshot=snapshot,
        memory=memory,
    )

    tool_names = [step.tool_name for step in result.steps]
    assert "run_site_selection_pack" in tool_names
    assert result.question_type == "site_selection"


def test_planner_hotspot_question_uses_h3_structure_and_hotspot_tools():
    snapshot = _snapshot_with_scope()
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})

    result = build_planning_fallback(
        question="这个区域的商业核心集中在哪",
        snapshot=snapshot,
        memory=memory,
    )

    tool_names = [step.tool_name for step in result.steps]
    assert "read_h3_structure_analysis" in tool_names
    assert "detect_commercial_hotspots" in tool_names
