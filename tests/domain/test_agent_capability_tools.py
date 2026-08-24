import asyncio

from modules.agent.schemas import AnalysisSnapshot, ToolResult
from modules.agent.tool_adapters import capability_tools


def test_ensure_area_data_readiness_readonly_does_not_compute(monkeypatch):
    called = []

    async def fake_read_scope(**_):
        return ToolResult(
            tool_name="read_current_scope",
            status="success",
            artifacts={"scope_polygon": [[0, 0], [1, 0], [1, 1]]},
        )

    async def fake_read_results(**_):
        return ToolResult(
            tool_name="read_current_results",
            status="success",
            result={
                "poi_count": 8,
                "has_h3_summary": False,
                "has_population_summary": False,
                "has_nightlight_summary": True,
                "has_road_summary": False,
            },
        )

    async def fake_compute(**kwargs):
        called.append(kwargs)
        return ToolResult(tool_name="unexpected_compute", status="failed", error="should_not_run")

    monkeypatch.setattr(capability_tools, "read_current_scope", fake_read_scope)
    monkeypatch.setattr(capability_tools, "read_current_results", fake_read_results)
    monkeypatch.setattr(capability_tools, "fetch_pois_in_scope", fake_compute)
    monkeypatch.setattr(capability_tools, "compute_h3_metrics_from_scope_and_pois", fake_compute)
    monkeypatch.setattr(capability_tools, "compute_population_overview_from_scope", fake_compute)
    monkeypatch.setattr(capability_tools, "compute_nightlight_overview_from_scope", fake_compute)
    monkeypatch.setattr(capability_tools, "read_persisted_road_syntax", fake_compute)

    result = asyncio.run(
        capability_tools.ensure_area_data_readiness(
            arguments={"auto_fetch": False},
            snapshot=AnalysisSnapshot(scope={"polygon": [[0, 0], [1, 0], [1, 1]]}),
            artifacts={},
            question="summary_readiness_precheck",
        )
    )

    assert called == []
    assert result["status"] == "success"
    assert result["error"] == ""
    assert result["data_readiness"] == {
        "checked": True,
        "reused": ["poi", "nightlight"],
        "fetched": [],
        "ready": False,
    }
    skipped_tools = {
        item["tool_name"]
        for item in result["tool_statuses"]
        if item.get("status") == "skipped"
    }
    assert skipped_tools == {
        "compute_h3_metrics_from_scope_and_pois",
        "compute_population_overview_from_scope",
        "read_persisted_road_syntax",
    }
