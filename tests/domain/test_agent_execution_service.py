import pytest

import modules.agent.execution_service as service
from modules.agent.providers.client import LLMRuntimeConfig
from modules.agent.schemas import AgentExecutionProfileRequest, AgentMessage, AgentTurnRequest
from modules.agent.skill_catalog import AgentSkillView


class SessionRepo:
    def __init__(self, profile=None):
        self.profile = profile or {}

    def get_record(self, _session_id):
        return {"snapshot": {"conversation_execution_profile": self.profile}}


def runtime(model):
    return LLMRuntimeConfig(provider="openai_compatible", base_url="https://example.test", api_key="secret", model=model)


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    def resolve(model_id=""):
        selected = model_id or "system-default"
        view = service.AgentModelProfileView(
            id=selected, display_name=selected, source="system" if selected == "system-default" else "personal",
            provider="openai_compatible", base_url="https://example.test", model=selected,
            enabled=True, has_api_key=True,
        )
        return view, runtime(selected)

    def skill(skill_id):
        if skill_id == "missing":
            raise ValueError("未知 Skill：missing")
        return AgentSkillView(id=skill_id, display_name=skill_id, executable=True)

    monkeypatch.setattr(service, "resolve_model_runtime", resolve)
    monkeypatch.setattr(service, "get_agent_skill", skill)


def request(text="分析项目", *, model="", skill="", scope="turn"):
    return AgentTurnRequest(
        conversation_id="conversation-1",
        messages=[AgentMessage(role="user", content=text)],
        execution_profile=AgentExecutionProfileRequest(model_profile_id=model, skill_id=skill, skill_scope=scope),
    )


def test_parse_slash_skill_strips_only_leading_command():
    assert service.parse_slash_skill("/urban-strategy-stage1 生成报告") == ("urban-strategy-stage1", "生成报告")
    assert service.parse_slash_skill("请使用 /urban-strategy-stage1") == ("", "请使用 /urban-strategy-stage1")


def test_slash_skill_overrides_explicit_and_pinned_skill():
    prepared = service.prepare_agent_turn(
        request("/slash-skill 生成报告", skill="explicit-skill", scope="conversation"),
        SessionRepo({"model_profile_id": "conversation-model", "pinned_skill_id": "pinned-skill"}),
    )
    assert prepared.payload.messages[-1].content == "生成报告"
    assert prepared.effective_profile.skill_id == "slash-skill"
    assert prepared.effective_profile.skill_scope == "turn"
    assert prepared.conversation_profile.pinned_skill_id == "pinned-skill"


def test_explicit_overrides_conversation_defaults():
    prepared = service.prepare_agent_turn(
        request(skill="explicit-skill", model="request-model"),
        SessionRepo({"model_profile_id": "conversation-model", "pinned_skill_id": "pinned-skill"}),
    )
    assert prepared.effective_profile.model_profile_id == "request-model"
    assert prepared.effective_profile.skill_id == "explicit-skill"


def test_conversation_defaults_are_used_without_turn_override():
    prepared = service.prepare_agent_turn(
        request(), SessionRepo({"model_profile_id": "conversation-model", "pinned_skill_id": "pinned-skill"}),
    )
    assert prepared.effective_profile.model_profile_id == "conversation-model"
    assert prepared.effective_profile.skill_id == "pinned-skill"
    assert prepared.effective_profile.skill_scope == "conversation"


def test_unknown_skill_is_rejected_without_fallback():
    with pytest.raises(ValueError, match="未知 Skill"):
        service.prepare_agent_turn(request(skill="missing"), SessionRepo())
