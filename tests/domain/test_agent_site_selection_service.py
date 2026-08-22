import asyncio

from modules.agent.schemas import AgentSiteSelectionRequest, AnalysisSnapshot, ToolResult
from modules.agent.site_selection_service import generate_site_selection_pack
from modules.agent.tool_adapters.scope_tools import extract_scope_polygon


def test_generate_site_selection_pack_calls_tool_with_place_type(monkeypatch):
    received = {}

    async def fake_run_site_selection_pack(*, arguments, snapshot, artifacts, question):
        received["arguments"] = arguments
        received["snapshot"] = snapshot
        received["artifacts"] = artifacts
        received["question"] = question
        return ToolResult(
            tool_name="run_site_selection_pack",
            status="success",
            result={"candidate_sites": [{"source_order": 1}]},
            artifacts={
                "site_selection_pack": {"candidate_sites": [{"source_order": 1}]},
                "current_target_supply_gap": {"place_type": "咖啡店"},
                "current_site_candidate_facts": {"candidate_count": 1},
            },
            warnings=["population_missing"],
        )

    monkeypatch.setattr(
        "modules.agent.site_selection_service.run_site_selection_pack",
        fake_run_site_selection_pack,
    )

    response = asyncio.run(
        generate_site_selection_pack(
            AgentSiteSelectionRequest(
                analysis_snapshot=AnalysisSnapshot(scope={"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}),
                place_type="咖啡店",
                strategy="supply_gap",
                scenario="commuter",
                source="local",
                year=2020,
            )
        )
    )

    assert received["arguments"]["place_type"] == "咖啡店"
    assert received["arguments"]["policy_key"] == "business_catchment_1km"
    assert received["arguments"]["strategy"] == "supply_gap"
    assert received["arguments"]["scenario"] == "commuter"
    assert received["arguments"]["source"] == "local"
    assert received["arguments"]["year"] == 2020
    assert received["artifacts"] == {}
    assert response.status == "success"
    assert response.site_selection_pack["candidate_sites"][0]["source_order"] == 1
    assert response.site_selection_pack["request_context"] == {
        "place_type": "咖啡店",
        "strategy": "supply_gap",
        "scenario": "commuter",
    }
    assert "overall_verdict" not in response.site_selection_pack
    assert "ranking" not in response.site_selection_pack
    assert response.current_site_candidate_facts == {"candidate_count": 1}
    assert response.current_target_supply_gap["place_type"] == "咖啡店"
    assert response.warnings == ["population_missing"]


def test_generate_site_selection_pack_does_not_invent_verdict_without_candidates(monkeypatch):
    async def fake_run_site_selection_pack(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="run_site_selection_pack",
            status="success",
            result={
                "candidate_sites": [],
            },
            artifacts={},
        )

    monkeypatch.setattr(
        "modules.agent.site_selection_service.run_site_selection_pack",
        fake_run_site_selection_pack,
    )

    response = asyncio.run(generate_site_selection_pack(AgentSiteSelectionRequest(place_type="咖啡店")))

    assert response.status == "success"
    assert response.site_selection_pack["candidate_sites"] == []
    assert "overall_verdict" not in response.site_selection_pack
    assert "avoid_areas" not in response.site_selection_pack
    assert "not_recommended_reason" not in response.site_selection_pack


def test_generate_site_selection_pack_returns_failed_for_missing_place_type():
    response = asyncio.run(generate_site_selection_pack(AgentSiteSelectionRequest(place_type="")))

    assert response.status == "failed"
    assert response.error == "missing_place_type"


def test_generate_site_selection_pack_accepts_supported_scope_sources(monkeypatch):
    scopes = [
        {"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]},
        {"drawn_polygon": [[2, 2], [2, 3], [3, 3], [2, 2]]},
        {
            "isochrone_feature": {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[3, 3], [3, 4], [4, 4], [3, 3]]],
                },
                "properties": {"mode": "drawn_polygon"},
            }
        },
    ]
    seen = []

    async def fake_run_site_selection_pack(*, arguments, snapshot, artifacts, question):
        del arguments, artifacts, question
        polygon = extract_scope_polygon(snapshot)
        seen.append(polygon)
        return ToolResult(
            tool_name="run_site_selection_pack",
            status="success",
            result={"candidate_sites": [], "ranking": [], "confidence": "weak"},
            artifacts={"site_selection_pack": {"candidate_sites": [], "ranking": [], "confidence": "weak"}},
        )

    monkeypatch.setattr(
        "modules.agent.site_selection_service.run_site_selection_pack",
        fake_run_site_selection_pack,
    )

    for scope in scopes:
        response = asyncio.run(
            generate_site_selection_pack(
                AgentSiteSelectionRequest(
                    analysis_snapshot=AnalysisSnapshot(scope=scope),
                    place_type="咖啡店",
                )
            )
        )
        assert response.status == "success"

    assert seen == [
        scopes[0]["polygon"],
        scopes[1]["drawn_polygon"],
        scopes[2]["isochrone_feature"]["geometry"]["coordinates"],
    ]
