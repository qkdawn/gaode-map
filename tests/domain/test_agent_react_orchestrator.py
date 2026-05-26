import asyncio

from modules.agent.providers.tool_loop import chat_completion_tools
from modules.agent.tools import get_tool_registry
from modules.agent.react_orchestrator import create_react_run, stream_react_run
from modules.agent.schemas import AgentReactRunRequest, AnalysisSnapshot, ToolLoopResult


def _snapshot_with_scope() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        scope={
            "polygon": [
                [116.38, 39.90],
                [116.39, 39.90],
                [116.39, 39.91],
                [116.38, 39.91],
                [116.38, 39.90],
            ]
        },
        poi_summary={"total": 2},
        pois=[{"name": "A"}, {"name": "B"}],
        road={"summary": {"node_count": 3, "edge_count": 2}},
    )


def test_react_run_streams_ordered_events_and_final_evidence(monkeypatch):
    monkeypatch.setattr("modules.agent.react_orchestrator.is_llm_enabled", lambda: False)

    async def collect():
        response = await create_react_run(
            AgentReactRunRequest(
                question="等时圈内有什么问题",
                analysis_snapshot=_snapshot_with_scope(),
                options={"max_steps": 2, "tool_timeout_seconds": 5},
            )
        )
        return [event async for event in stream_react_run(response.run_id)]

    events = asyncio.run(collect())
    event_types = [event.type for event in events]

    assert event_types[0] == "status"
    assert "thought" in event_types
    assert "action" in event_types
    assert "observation" in event_types
    assert event_types[-1] == "final"
    assert events[-1].payload["conclusion"]
    assert all(step <= events[-1].step for step in events[-1].payload["evidence_steps"])


def test_react_run_handles_missing_scope_without_crashing(monkeypatch):
    monkeypatch.setattr("modules.agent.react_orchestrator.is_llm_enabled", lambda: False)

    async def collect():
        response = await create_react_run(
            AgentReactRunRequest(
                question="帮我判断范围问题",
                analysis_snapshot=AnalysisSnapshot(),
                options={"max_steps": 1},
            )
        )
        return [event async for event in stream_react_run(response.run_id)]

    events = asyncio.run(collect())

    assert events[-1].type == "final"
    assert events[-1].payload["confidence"] < 0.7
    assert any(event.type == "observation" for event in events)


def test_react_run_uses_langgraph_tool_loop_events(monkeypatch):
    monkeypatch.setattr("modules.agent.react_orchestrator.is_llm_enabled", lambda: True)
    captured = {}

    async def fake_loop(**kwargs):
        captured["registry_names"] = sorted((kwargs.get("registry") or {}).keys())
        captured["include_secondary_tools"] = kwargs.get("include_secondary_tools")
        emit = kwargs["emit"]
        await emit("thinking", {"phase": "planned", "title": "分析当前证据", "detail": "需要先读取范围。"})
        await emit(
            "trace",
            {
                "tool_name": "read_current_scope",
                "status": "start",
                "message": "开始执行工具",
                "arguments_summary": "无参数",
            },
        )
        await emit(
            "trace",
            {
                "tool_name": "read_current_scope",
                "status": "success",
                "message": "执行成功",
                "result_summary": "has_scope=true",
                "evidence_count": 1,
            },
        )
        await emit("reasoning_delta", {"delta": "hidden raw reasoning"})
        return ToolLoopResult(status="completed", assistant_summary="范围可用，下一步应检查 POI 供给。")

    monkeypatch.setattr("modules.agent.react_orchestrator.run_langgraph_react_loop", fake_loop)

    async def collect():
        response = await create_react_run(
            AgentReactRunRequest(question="等时圈内有什么问题", analysis_snapshot=_snapshot_with_scope())
        )
        return [event async for event in stream_react_run(response.run_id)]

    events = asyncio.run(collect())
    event_types = [event.type for event in events]

    assert captured["include_secondary_tools"] is True
    assert "read_current_scope" in captured["registry_names"]
    assert "fetch_pois_in_scope" in captured["registry_names"]
    assert "compute_population_overview_from_scope" in captured["registry_names"]
    assert "compute_nightlight_overview_from_scope" in captured["registry_names"]
    assert "compute_road_syntax_from_scope" in captured["registry_names"]
    assert "run_area_character_pack" in captured["registry_names"]
    assert "run_vitality_assessment_pack" not in captured["registry_names"]
    assert "thought" in event_types
    assert "action" in event_types
    assert "observation" in event_types
    assert "reasoning_delta" not in event_types
    assert events[-1].type == "final"
    assert "范围可用" in events[-1].payload["conclusion"]
    assert events[-1].payload["evidence_steps"]


def test_react_tool_catalog_exposes_curated_analysis_tools():
    registry = get_tool_registry()
    safe_names = (
        "read_current_scope",
        "read_current_results",
        "fetch_pois_in_scope",
        "compute_population_overview_from_scope",
        "compute_nightlight_overview_from_scope",
        "compute_road_syntax_from_scope",
        "analyze_poi_structure",
    )
    safe_registry = {name: registry[name] for name in safe_names}
    default_names = [item["function"]["name"] for item in chat_completion_tools(safe_registry)]
    names = [item["function"]["name"] for item in chat_completion_tools(safe_registry, include_secondary=True)]

    assert "fetch_pois_in_scope" not in default_names
    assert "read_current_scope" in names
    assert "fetch_pois_in_scope" in names
    assert "compute_population_overview_from_scope" in names
    assert "compute_nightlight_overview_from_scope" in names
    assert "compute_road_syntax_from_scope" in names
    assert "analyze_poi_structure" in names
