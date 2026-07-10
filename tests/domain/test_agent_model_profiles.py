import asyncio

from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest

import modules.agent.model_profiles as profiles


class MemoryRepo:
    def __init__(self):
        self.rows = {}

    def list_records(self):
        return list(self.rows.values())

    def get_record(self, profile_id):
        return self.rows.get(profile_id)

    def upsert_record(self, profile_id, values):
        row = {"id": profile_id, "enabled": True, "is_default": False, **self.rows.get(profile_id, {}), **values}
        self.rows[profile_id] = row
        return row

    def delete_record(self, profile_id):
        return self.rows.pop(profile_id, None) is not None


@pytest.fixture
def repo(monkeypatch):
    value = MemoryRepo()
    monkeypatch.setattr(profiles, "agent_model_profile_repo", value)
    monkeypatch.setattr(profiles.settings, "ai_model_config_secret", Fernet.generate_key().decode())
    return value


def test_personal_api_key_is_encrypted_and_never_exposed(repo):
    view = profiles.create_model_profile(profiles.AgentModelProfileCreate(
        display_name="个人模型", provider="openai_compatible",
        base_url="https://example.test/v1", model="model-x", api_key="plain-secret",
    ))
    stored = repo.get_record(view.id)
    assert "plain-secret" not in stored["api_key_ciphertext"]
    assert view.has_api_key is True
    assert "api_key" not in view.model_dump()
    assert "ciphertext" not in str(view.model_dump())


def test_blank_patch_key_preserves_existing_ciphertext(repo):
    view = profiles.create_model_profile(profiles.AgentModelProfileCreate(
        display_name="个人模型", provider="deepseek", base_url="https://example.test",
        model="model-x", api_key="plain-secret",
    ))
    original = repo.get_record(view.id)["api_key_ciphertext"]
    profiles.update_model_profile(view.id, profiles.AgentModelProfilePatch(display_name="已改名", api_key=""))
    assert repo.get_record(view.id)["api_key_ciphertext"] == original


def test_disabled_or_missing_selected_model_never_falls_back(repo):
    repo.upsert_record("disabled", {
        "display_name": "Disabled", "provider": "openai_compatible",
        "base_url": "https://example.test", "model_name": "x",
        "api_key_ciphertext": profiles._encrypt_api_key("secret"), "enabled": False,
    })
    with pytest.raises(HTTPException, match="已禁用"):
        profiles.resolve_model_runtime("disabled")
    with pytest.raises(HTTPException, match="不存在"):
        profiles.resolve_model_runtime("deleted")


def test_system_profile_cannot_be_changed_or_deleted(repo):
    with pytest.raises(HTTPException) as update_error:
        profiles.update_model_profile(profiles.SYSTEM_PROFILE_ID, profiles.AgentModelProfilePatch(enabled=False))
    with pytest.raises(HTTPException) as delete_error:
        profiles.delete_model_profile(profiles.SYSTEM_PROFILE_ID)
    assert update_error.value.status_code == 403
    assert delete_error.value.status_code == 403


def test_model_connection_error_redacts_api_key_and_authorization(repo, monkeypatch):
    secret = "sk-test-secret-value"

    class FailingClient:
        async def chat_text(self, **_kwargs):
            raise RuntimeError(
                f"Authorization: Bearer {secret}; api_key={secret}; "
                f"https://user:{secret}@example.test/v1"
            )

    monkeypatch.setattr(profiles, "get_llm_provider_client", lambda runtime: FailingClient())
    result = asyncio.run(profiles.test_model_profile(profiles.AgentModelProfileTestRequest(
        provider="openai_compatible", base_url="https://example.test/v1",
        model="model-x", api_key=secret,
    )))

    assert result.success is False
    assert secret not in result.message
    assert "[REDACTED]" in result.message
