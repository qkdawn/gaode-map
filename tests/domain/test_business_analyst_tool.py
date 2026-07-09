import asyncio

from modules.business_analyst.skill_registry import validate_model_tool_map
from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tools import get_tool_registry


def test_business_analyst_tool_registered_as_readonly_primary_safe():
    registry = get_tool_registry()
    registered = registry["plan_business_analyst_analysis"]

    assert registered.spec.readonly is True
    assert registered.spec.cost_level == "safe"
    assert registered.spec.risk_level == "safe"
    assert registered.spec.llm_exposure == "primary"
    assert registered.spec.produces == ["business_analyst_skeleton"]


def test_business_analyst_tool_returns_skeleton_not_report_sections():
    registered = get_tool_registry()["plan_business_analyst_analysis"]
    result = asyncio.run(
        registered.runner(
            arguments={"mode": "opportunity_screening", "question": "这个区域适合做什么，引入什么业态？"},
            snapshot=AnalysisSnapshot(scope={"polygon": [[112.98, 28.19], [112.99, 28.19], [112.99, 28.2], [112.98, 28.19]]}),
            artifacts={},
            question="",
        )
    )

    skeleton = result.artifacts["business_analyst_skeleton"]
    assert result.status == "success"
    assert result.tool_name == "plan_business_analyst_analysis"
    assert skeleton["selected_skill"]["skill_id"] == "ba.open_opportunity_screening"
    assert skeleton["recommended_path"][-1] == "OpportunityCategoryScreeningModel"
    assert "answer_guidance" in skeleton
    assert "required_report_sections" not in skeleton
    assert "business_analyst_report" not in skeleton


def test_business_analyst_model_tool_map_matches_registered_agent_tools():
    registry = get_tool_registry()

    assert validate_model_tool_map(set(registry.keys())) == []
