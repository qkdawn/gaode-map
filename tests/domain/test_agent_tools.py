import asyncio

from modules.agent.providers.tool_call_execution import execute_tool_call_step
from modules.agent.schemas import AnalysisSnapshot, ExecutionTraceItem, PlanStep
from modules.agent.executor import validate_tool_arguments
from modules.agent.tools import get_tool_registry
from modules.providers.amap.utils.get_type_info import infer_type_info_from_text, resolve_type_info


def test_get_tool_registry_exposes_stage1_tools():
    registry = get_tool_registry()

    assert {
        "read_current_scope",
        "read_current_results",
        "fetch_pois_in_scope",
        "build_h3_grid_from_scope",
        "compute_h3_metrics_from_scope_and_pois",
        "compute_population_overview_from_scope",
        "compute_nightlight_overview_from_scope",
        "compute_road_syntax_from_scope",
        "search_analysis_context",
        "read_analysis_evidence_node",
        "search_report_context",
        "read_report_evidence_node",
        "get_area_data_bundle",
        "analyze_poi_structure",
        "rank_next_analysis_options",
        "analyze_spatial_structure",
        "build_unified_spatial_cells",
        "infer_area_labels",
        "score_site_candidates",
        "run_area_character_pack",
        "run_site_selection_pack",
        "read_poi_structure_analysis",
        "analyze_target_supply_gap",
        "run_business_site_advice",
    }.issubset(set(registry.keys()))
    assert registry["read_current_scope"].spec.readonly is True
    assert registry["read_current_scope"].spec.input_schema["additionalProperties"] is False
    assert registry["read_current_scope"].spec.output_schema["properties"]["has_scope"]["type"] == "boolean"
    assert registry["read_current_scope"].spec.ui_tier == "foundation"
    assert registry["read_current_results"].spec.llm_exposure == "primary"
    assert registry["analyze_poi_structure"].spec.ui_tier == "capability"
    assert registry["analyze_poi_structure"].spec.capability_type == "analyze"
    assert registry["rank_next_analysis_options"].spec.toolkit_id == "next_analysis_pack"
    assert registry["run_area_character_pack"].spec.ui_tier == "scenario"
    assert registry["run_area_character_pack"].spec.scene_type == "area_character"
    assert registry["run_area_character_pack"].spec.llm_exposure == "primary"
    assert registry["run_site_selection_pack"].spec.scene_type == "site_selection"
    assert registry["run_site_selection_pack"].spec.default_policy_key == "business_catchment_1km"
    assert registry["read_poi_structure_analysis"].spec.readonly is True
    assert registry["analyze_target_supply_gap"].spec.input_schema["required"] == ["place_type"]
    assert registry["fetch_pois_in_scope"].spec.requires == ["scope_polygon"]
    assert registry["fetch_pois_in_scope"].spec.input_schema["properties"]["source"]["enum"] == ["local", "gaode"]
    assert registry["run_business_site_advice"].spec.layer == "L2"
    assert registry["run_business_site_advice"].spec.cost_level == "expensive"
    assert registry["run_business_site_advice"].spec.requires == ["scope_polygon"]
    assert registry["compute_population_overview_from_scope"].spec.requires == ["scope_polygon"]
    assert registry["compute_nightlight_overview_from_scope"].spec.requires == ["scope_polygon"]
    assert "search_database_context" not in registry
    assert "read_database_record" not in registry
    assert registry["compute_h3_metrics_from_scope_and_pois"].spec.produces == [
        "current_poi_h3",
        "current_poi_h3_grid",
        "current_poi_h3_summary",
        "current_poi_h3_charts",
    ]
    assert registry["compute_road_syntax_from_scope"].spec.cost_level == "expensive"
    assert registry["compute_road_syntax_from_scope"].spec.risk_level == "safe"


def test_get_tool_registry_keeps_expected_tool_order():
    registry = get_tool_registry()

    assert list(registry.keys()) == [
        "read_current_scope",
        "read_current_results",
        "fetch_pois_in_scope",
        "build_h3_grid_from_scope",
        "compute_h3_metrics_from_scope_and_pois",
        "compute_population_overview_from_scope",
        "compute_nightlight_overview_from_scope",
        "compute_road_syntax_from_scope",
        "search_analysis_context",
        "read_analysis_evidence_node",
        "search_report_context",
        "read_report_evidence_node",
        "get_area_data_bundle",
        "analyze_poi_structure",
        "rank_next_analysis_options",
        "analyze_spatial_structure",
        "build_unified_spatial_cells",
        "infer_area_labels",
        "score_site_candidates",
        "run_area_character_pack",
        "run_site_selection_pack",
        "run_vitality_assessment_pack",
        "run_tod_pack",
        "run_livability_pack",
        "run_facility_gap_pack",
        "run_renewal_priority_pack",
        "read_poi_structure_analysis",
        "read_h3_structure_analysis",
        "read_road_pattern_analysis",
        "read_population_profile_analysis",
        "read_nightlight_pattern_analysis",
        "analyze_poi_mix_from_scope",
        "detect_commercial_hotspots",
        "analyze_target_supply_gap",
        "run_business_site_advice",
    ]


def test_validate_tool_arguments_rejects_unknown_keys():
    registry = get_tool_registry()
    errors = validate_tool_arguments(
        {"types": "050000", "unexpected": True},
        registry["fetch_pois_in_scope"].spec.input_schema,
    )

    assert "arguments.unexpected 不允许出现" in errors


def test_execution_trace_item_accepts_blocked_status():
    trace = ExecutionTraceItem(tool_name="compute_road_syntax_from_scope", status="blocked")

    assert trace.status == "blocked"


def test_governance_blocked_tool_call_keeps_result_failed_and_trace_blocked():
    registry = get_tool_registry()
    step = PlanStep(tool_name="compute_road_syntax_from_scope", reason="需要路网句法")

    execution = asyncio.run(
        execute_tool_call_step(
            registered_tool=registry["compute_road_syntax_from_scope"],
            step=step,
            snapshot=AnalysisSnapshot(scope={"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}),
            artifacts={},
            question="为什么这里路网差",
            governance_mode="guarded",
            confirmed_tools=[],
        )
    )

    assert execution.trace.status == "blocked"
    assert execution.result.status == "failed"
    assert execution.result.error == "governance_blocked"
    assert execution.result.warnings


def test_resolve_type_info_supports_aliases_for_site_advice():
    coffee_by_label = resolve_type_info("咖啡厅")
    coffee_by_alias = resolve_type_info("咖啡店")
    inferred = infer_type_info_from_text("我想在这里开一家咖啡店，给我建议")

    assert coffee_by_label is not None
    assert coffee_by_alias is not None
    assert inferred is not None
    assert coffee_by_alias["types"] == coffee_by_label["types"]
    assert inferred["keywords"] == "咖啡厅"
    assert resolve_type_info("不存在的业态") is None
