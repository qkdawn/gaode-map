from modules.business_analyst import BusinessAnalystInput, build_business_analyst_skeleton
from modules.business_analyst.model_graph import default_model_graph
from modules.business_analyst.skill_registry import suggest_skills


def _input_with_scope() -> BusinessAnalystInput:
    return BusinessAnalystInput(scope={"polygon": [[112.98, 28.19], [112.99, 28.19], [112.99, 28.20], [112.98, 28.19]]})


def test_default_model_graph_keeps_business_relations_as_data():
    graph = default_model_graph()

    assert graph.nodes["TradeAreaModel"].role == "boundary"
    assert graph.nodes["RetailGapModel"].role == "supply_gap"
    assert graph.nodes["OpportunityCategoryScreeningModel"].role == "opportunity_screening"
    assert graph.nodes["HuffGravityModel"].required is False
    assert any(edge.relation == "adjusts_for_competition" for edge in graph.in_edges("SiteSuitabilityModel"))


def test_skill_registry_selects_site_selection_skill_from_question_type():
    skills = suggest_skills("这里适合开咖啡店吗，推荐哪个位置？", "site_selection")

    assert skills[0].skill_id == "ba.single_category_site_selection"
    assert "SiteSuitabilityModel" in skills[0].required_path
    assert "HuffGravityModel" in skills[0].optional_branches["competition"]["model"]


def test_build_business_analyst_skeleton_returns_compact_graph_and_tool_map():
    skeleton = build_business_analyst_skeleton(
        question="这个范围里缺什么商业，便利店适合补在哪里？",
        question_type="facility_gap",
        analysis_input=_input_with_scope(),
    )

    assert skeleton["status"] == "ready"
    assert skeleton["selected_skill"]["skill_id"] == "ba.area_commercial_diagnosis"
    assert skeleton["model_graph"]["graph_id"] == "ba.business_analyst_model_graph.v1"
    assert skeleton["recommended_path"] == ["TradeAreaModel", "MarketPotentialModel", "RetailGapModel", "OpportunityCategoryScreeningModel"]
    assert "RetailGapModel" in skeleton["model_tool_map"]
    assert "no_revenue_without_source" in skeleton["guardrails"]
    assert skeleton["path_relations"]
    assert "required_report_sections" not in skeleton


def test_skill_registry_selects_open_opportunity_screening_without_target_category():
    skills = suggest_skills("这个区域适合做什么，引入什么业态？", "")

    assert skills[0].skill_id == "ba.open_opportunity_screening"
    assert skills[0].required_path[-1] == "OpportunityCategoryScreeningModel"


def test_business_analyst_skeleton_is_partial_without_scope():
    skeleton = build_business_analyst_skeleton(
        question="这里适合开咖啡店吗？",
        question_type="site_selection",
        analysis_input=BusinessAnalystInput(),
    )

    assert skeleton["status"] == "partial"
    assert skeleton["reason"] == "matched_but_scope_missing"
