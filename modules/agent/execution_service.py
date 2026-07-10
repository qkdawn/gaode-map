from __future__ import annotations

import re
from dataclasses import dataclass

from .model_profiles import AgentModelProfileView, resolve_model_runtime
from .providers.client import LLMRuntimeConfig
from .schemas import AgentMessage, AgentTurnRequest, ConversationExecutionProfile, EffectiveExecutionProfile
from .skill_catalog import AgentSkillView, get_agent_skill, list_agent_skills

_SLASH_SKILL = re.compile(r"^\s*/([a-zA-Z0-9][a-zA-Z0-9_-]*)(?:\s+|$)")


@dataclass(frozen=True)
class PreparedAgentTurn:
    payload: AgentTurnRequest
    runtime: LLMRuntimeConfig
    effective_profile: EffectiveExecutionProfile
    skill: AgentSkillView | None
    conversation_profile: ConversationExecutionProfile


def parse_slash_skill(text: str) -> tuple[str, str]:
    raw = str(text or "")
    match = _SLASH_SKILL.match(raw)
    if not match:
        return "", raw
    return match.group(1), raw[match.end():].lstrip()


def _conversation_profile(conversation_id: str, repo) -> ConversationExecutionProfile:
    if not conversation_id:
        return ConversationExecutionProfile()
    record = repo.get_record(conversation_id)
    snapshot = record.get("snapshot") if isinstance(record, dict) and isinstance(record.get("snapshot"), dict) else {}
    raw = snapshot.get("conversation_execution_profile")
    return ConversationExecutionProfile(**raw) if isinstance(raw, dict) else ConversationExecutionProfile()


def prepare_agent_turn(payload: AgentTurnRequest, repo) -> PreparedAgentTurn:
    conversation = _conversation_profile(payload.conversation_id, repo)
    messages = [item.model_copy(deep=True) for item in payload.messages]
    slash_skill_id = ""
    if messages and messages[-1].role == "user":
        slash_skill_id, cleaned = parse_slash_skill(messages[-1].content)
        if slash_skill_id:
            messages[-1] = messages[-1].model_copy(update={"content": cleaned})
    requested_skill = str(payload.execution_profile.skill_id or "").strip()
    skill_id = slash_skill_id or requested_skill or str(conversation.pinned_skill_id or "").strip()
    skill = get_agent_skill(skill_id) if skill_id else None
    model_id = str(payload.execution_profile.model_profile_id or conversation.model_profile_id or "").strip()
    model_view, runtime = resolve_model_runtime(model_id)
    skill_scope = "turn" if slash_skill_id else payload.execution_profile.skill_scope
    if not slash_skill_id and not requested_skill and conversation.pinned_skill_id:
        skill_scope = "conversation"
    effective = EffectiveExecutionProfile(
        model_profile_id=model_view.id,
        model_display_name=model_view.display_name,
        provider=model_view.provider,
        model=model_view.model,
        skill_id=skill.id if skill else "",
        skill_display_name=skill.display_name if skill else "",
        skill_scope=skill_scope,
    )
    next_conversation = ConversationExecutionProfile(
        model_profile_id=model_view.id,
        pinned_skill_id=(skill.id if skill and skill_scope == "conversation" else conversation.pinned_skill_id),
    )
    prepared_payload = payload.model_copy(update={"messages": messages})
    return PreparedAgentTurn(prepared_payload, runtime, effective, skill, next_conversation)


def agent_capabilities() -> dict:
    from .model_profiles import list_model_profiles

    models = list_model_profiles()
    default_model = next((item.id for item in models if item.enabled and item.is_default), "")
    return {
        "models": [item.model_dump(mode="json") for item in models],
        "skills": [item.model_dump(mode="json") for item in list_agent_skills()],
        "default_model_profile_id": default_model,
        "model_available": any(item.enabled for item in models),
    }
