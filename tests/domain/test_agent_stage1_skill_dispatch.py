import asyncio

import pytest

import modules.agent.runtime as agent_runtime
from modules.agent.providers.client import LLMRuntimeConfig
from modules.agent.runtime import stream_main_agent_loop
from modules.agent.schemas import AgentMessage, AgentTurnOutput, AgentTurnRequest, AgentTurnResponse
from modules.agent.skill_catalog import get_agent_skill, list_agent_skills


STAGE1_SKILL_ID = "urban-strategy-stage1"


def test_stage1_skill_is_listed_but_not_executable():
    skills = {skill.id: skill for skill in list_agent_skills()}

    assert skills[STAGE1_SKILL_ID].executable is False
    assert skills[STAGE1_SKILL_ID].diagnostic == "Skill 尚未注册执行器"
    with pytest.raises(ValueError, match="尚未注册执行器"):
        get_agent_skill(STAGE1_SKILL_ID)


def test_streaming_stage1_selection_uses_generic_agent_loop(monkeypatch):
    observed = {}

    async def fake_main_loop(payload, *, emit=None, llm_runtime=None, effective_profile=None):
        observed.update(
            payload=payload,
            emit=emit,
            llm_runtime=llm_runtime,
            effective_profile=effective_profile,
        )
        return AgentTurnResponse(
            status="answered",
            output=AgentTurnOutput(answer="generic agent response"),
        )

    monkeypatch.setattr(agent_runtime, "_run_main_agent_loop", fake_main_loop)
    payload = AgentTurnRequest(messages=[AgentMessage(role="user", content="生成报告")])
    runtime = LLMRuntimeConfig(
        provider="openai_compatible",
        base_url="https://example.test",
        api_key="test-key",
        model="test-model",
    )

    async def collect_events():
        return [
            event
            async for event in stream_main_agent_loop(
                payload,
                llm_runtime=runtime,
                skill_id=STAGE1_SKILL_ID,
            )
        ]

    events = asyncio.run(collect_events())

    assert observed["payload"] is payload
    assert observed["llm_runtime"] is runtime
    assert callable(observed["emit"])
    assert next(event for event in events if event.type == "final").payload["response"]["output"]["answer"] == "generic agent response"
