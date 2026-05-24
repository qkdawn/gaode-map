import asyncio

from modules.agent.react_orchestrator import create_react_run, stream_react_run
from modules.agent.schemas import AgentReactRunRequest, AnalysisSnapshot


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


def test_react_run_streams_ordered_events_and_final_evidence():
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


def test_react_run_handles_missing_scope_without_crashing():
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
