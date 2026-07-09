import asyncio

from modules.agent.executor import execute_plan_step
from modules.agent.schemas import AnalysisSnapshot, PlanStep, ToolResult, ToolSpec
from modules.agent.tools import RegisteredTool


def _snapshot_with_scope() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        scope={
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        }
    )


def _registered_tool(name: str, requires: list[str], runner) -> RegisteredTool:
    return RegisteredTool(
        spec=ToolSpec(
            name=name,
            description="测试工具",
            category="processing",
            layer="L1",
            requires=requires,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        runner=runner,
    )


def test_executor_injects_scope_polygon_from_snapshot_before_running_tool():
    snapshot = _snapshot_with_scope()
    artifacts = {}
    seen = {}

    async def runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        seen["scope_polygon"] = artifacts.get("scope_polygon")
        seen["scope_data"] = artifacts.get("scope_data")
        return ToolResult(tool_name="compute_h3_metrics_from_scope_and_pois", status="success")

    result, trace = asyncio.run(
        execute_plan_step(
            registered_tool=_registered_tool("compute_h3_metrics_from_scope_and_pois", ["scope_polygon"], runner),
            step=PlanStep(tool_name="compute_h3_metrics_from_scope_and_pois"),
            snapshot=snapshot,
            artifacts=artifacts,
            question="总结这个区域",
        )
    )

    assert result.status == "success"
    assert trace.status == "success"
    assert seen["scope_polygon"] == snapshot.scope["polygon"]
    assert seen["scope_data"] == snapshot.scope
    assert artifacts["scope_polygon"] == snapshot.scope["polygon"]


def test_executor_still_fails_when_scope_is_missing():
    async def runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        raise AssertionError("runner should not execute when scope is missing")

    result, trace = asyncio.run(
        execute_plan_step(
            registered_tool=_registered_tool("compute_h3_metrics_from_scope_and_pois", ["scope_polygon"], runner),
            step=PlanStep(tool_name="compute_h3_metrics_from_scope_and_pois"),
            snapshot=AnalysisSnapshot(),
            artifacts={},
            question="总结这个区域",
        )
    )

    assert result.status == "failed"
    assert result.error == "missing_requirements"
    assert "scope_polygon" in result.warnings[0]
    assert trace.status == "failed"


def test_executor_injects_current_pois_from_snapshot_before_running_tool():
    snapshot = AnalysisSnapshot(
        pois=[{"id": "poi-1"}, {"id": "poi-2"}],
        poi_summary={"total": 2},
    )
    artifacts = {}
    seen = {}

    async def runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        seen["current_pois"] = artifacts.get("current_pois")
        seen["current_poi_summary"] = artifacts.get("current_poi_summary")
        return ToolResult(tool_name="poi_dependent_tool", status="success")

    result, trace = asyncio.run(
        execute_plan_step(
            registered_tool=_registered_tool("poi_dependent_tool", ["current_pois"], runner),
            step=PlanStep(tool_name="poi_dependent_tool"),
            snapshot=snapshot,
            artifacts=artifacts,
            question="总结这个区域",
        )
    )

    assert result.status == "success"
    assert trace.status == "success"
    assert seen["current_pois"] == snapshot.pois
    assert seen["current_poi_summary"] == snapshot.poi_summary
    assert artifacts["current_pois"] == snapshot.pois

