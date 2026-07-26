import asyncio

from modules.agent.context_builder import build_context_bundle
from modules.agent.memory import create_working_memory
from modules.agent.runtime import _run_required_skill_dependencies
from modules.agent.schemas import AgentMessage, AgentTurnRequest, EffectiveExecutionProfile, ToolLoopResult
from modules.agent.skill_dependencies import resolve_skill_dependencies


def _payload(text: str) -> AgentTurnRequest:
    return AgentTurnRequest(
        history_id="history-latest",
        messages=[AgentMessage(role="user", content=text)],
    )


def test_spatial_business_skill_triggers_cultural_dependency_for_tourism_project():
    deps = resolve_skill_dependencies(
        _payload("请分析这个历史建筑文旅活化项目"),
        EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
    )
    assert [(item.skill_id, item.when) for item in deps] == [
        ("cultural-tourism-theme-research", "cultural_heritage_or_destination_activation")
    ]


def test_spatial_business_skill_does_not_trigger_dependency_for_plain_metric_question():
    deps = resolve_skill_dependencies(
        _payload("请分析这个区域的夜光和路网结构"),
        EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
    )
    assert deps == []


def test_dependency_artifact_is_published_before_parent_loop(monkeypatch):
    calls = []

    async def fake_loop(**kwargs):
        calls.append(kwargs["system_instruction"])
        return ToolLoopResult(
            status="completed",
            assistant_summary="八类资源已完成本轮调研，保留待验证缺口。",
            artifacts={"research_report": "current-turn"},
            used_tools=["query_history_project_dataset"],
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()
    events = []

    async def emit_thinking(item, item_id):
        events.append((item_id, item["state"]))

    error = asyncio.run(
        _run_required_skill_dependencies(
            payload=_payload("这个地方有历史建筑和非遗，先做文旅资源普查"),
            effective_profile=EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert error == ""
    assert calls and "cultural-tourism-theme-research" in calls[0]
    assert memory.artifacts["cultural_tourism_research"]["status"] == "completed"
    assert memory.artifacts["cultural_tourism_research"]["summary"].startswith("八类资源")
    assert events[-1] == ("dependency-complete:cultural-tourism-theme-research", "completed")
