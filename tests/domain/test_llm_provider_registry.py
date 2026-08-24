from modules.agent.providers import client as llm_provider


def test_is_llm_enabled_uses_registry(monkeypatch):
    monkeypatch.setattr(llm_provider.settings, "ai_enabled", True)
    monkeypatch.setattr(llm_provider.settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(llm_provider.settings, "ai_base_url", "https://example.com/v1")
    monkeypatch.setattr(llm_provider.settings, "ai_api_key", "test-key")
    monkeypatch.setattr(llm_provider.settings, "ai_model", "test-model")

    assert llm_provider.is_llm_enabled() is True


def test_is_llm_enabled_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(llm_provider.settings, "ai_enabled", True)
    monkeypatch.setattr(llm_provider.settings, "ai_provider", "unknown_provider")
    monkeypatch.setattr(llm_provider.settings, "ai_base_url", "https://example.com/v1")
    monkeypatch.setattr(llm_provider.settings, "ai_api_key", "test-key")
    monkeypatch.setattr(llm_provider.settings, "ai_model", "test-model")

    assert llm_provider.is_llm_enabled() is False


def test_get_llm_provider_client_supports_json_mode():
    client = llm_provider.get_llm_provider_client("deepseek")
    assert client is not None
    assert client.supports_json_mode is True
