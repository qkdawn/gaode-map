import asyncio
import json

from modules.agent.providers.tool_loop import chat_completion_tools
from modules.agent.providers.langgraph_react import _initial_payload, _react_tool_result_payload
from modules.agent.tools import get_tool_registry
from modules.agent.react_orchestrator import _final_payload, create_react_run, stream_react_run
from modules.agent.context_builder import build_context_bundle
from modules.agent.schemas import AgentReactRunRequest, AnalysisSnapshot, ToolLoopResult, ToolResult


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


def test_react_run_reports_unavailable_when_llm_disabled(monkeypatch):
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

    assert event_types == ["error", "final"]
    assert event_types[-1] == "final"
    assert "LLM provider 未启用" in events[0].payload["summary"]
    assert "LLM provider 未启用" in events[-1].payload["conclusion"]
    assert events[-1].payload["evidence_steps"] == []
    assert events[-1].payload["meta"]["mode"] == "llm_react"


def test_react_run_without_llm_does_not_execute_local_tool_fallback(monkeypatch):
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
    assert [event.type for event in events] == ["error", "final"]
    assert events[-1].payload["evidence_status"] == "证据不足"
    assert "confidence" not in events[-1].payload
    assert not any(event.type == "observation" for event in events)


def test_react_final_payload_does_not_append_template_next_actions():
    payload = _final_payload(
        "下一步做什么分析",
        observations=[],
        event_steps=[],
        snapshot=_snapshot_with_scope(),
    )

    assert "next_actions" not in payload
    assert "uncertainties" not in payload


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
    assert "search_analysis_context" in captured["registry_names"]
    assert "read_analysis_chunk" in captured["registry_names"]
    assert "search_report_context" in captured["registry_names"]
    assert "read_report_chunk" in captured["registry_names"]
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


def test_react_initial_payload_uses_digest_instead_of_full_snapshot():
    snapshot = AnalysisSnapshot(
        scope={"polygon": [[116.38, 39.90], [116.39, 39.90], [116.39, 39.91], [116.38, 39.90]]},
        poi_summary={"total": 1200},
        h3={
            "summary": {"grid_count": 3},
            "charts": {"huge_series": list(range(500))},
            "poi_h3_evidence": {"cells": [{"cell_id": f"cell-{index}", "poi_count": index} for index in range(120)]},
        },
        population={"summary": {"total_population": 10000}, "grid_evidence": {"cells": list(range(300))}},
        frontend_analysis={"poi": {"large": list(range(300))}, "h3": {"large": list(range(300))}},
        shared_grid={"cells": [{"cell_id": f"shared-{index}"} for index in range(200)]},
    )
    registry = get_tool_registry()
    payload = _initial_payload(
        question="这个区域怎么样",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        registry={"read_current_results": registry["read_current_results"]},
    )
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "analysis_snapshot" not in payload
    assert "analysis_snapshot_digest" in payload
    assert "huge_series" not in encoded
    assert "shared-199" not in encoded
    assert "cell-119" not in encoded
    assert "frontend_analysis_keys" in encoded


def test_react_tool_result_payload_compacts_large_results_and_artifacts():
    result = ToolResult(
        tool_name="read_current_results",
        status="success",
        result={"rows": [{"id": index, "value": index} for index in range(80)], "total": 80},
        evidence=[{"field": f"metric.{index}", "value": index} for index in range(40)],
        artifacts={
            "current_poi_h3": {"grid": [{"cell_id": f"cell-{index}"} for index in range(200)]},
            "current_frontend_analysis": {"poi": {"large": list(range(200))}},
        },
    )
    payload = json.loads(_react_tool_result_payload(result))
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["result_summary"]
    assert payload["artifact_keys"] == ["current_poi_h3", "current_frontend_analysis"]
    assert "current_frontend_analysis" in encoded
    assert "cell-199" not in encoded
    assert "metric.39" not in encoded
    assert payload["result"]["rows"]["type"] == "array"
    assert payload["evidence"]["type"] == "array"
