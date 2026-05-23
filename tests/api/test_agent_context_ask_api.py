import os
import sys
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

_AGENT_ROUTE_PATH = ROOT_DIR / "router" / "domains" / "agent.py"
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location("test_agent_context_ask_route_module", _AGENT_ROUTE_PATH)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)
agent_router = agent_router_module.router


def _build_test_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def _payload(question="为什么这么判断？"):
    return {
        "conversation_id": "agent-1",
        "history_id": "history-1",
        "question": question,
        "analysis_snapshot": {"context": {"scope_label": "测试区域"}},
        "target": {
            "type": "report_section",
            "id": "headline",
            "title": "核心判断",
            "source": "report",
            "summary": "该区域商业活力较强。",
            "evidence": [{"metric": "poi_count", "value": 120}],
            "artifact_refs": ["summary_pack.headline"],
            "payload": {"section_key": "headline"},
        },
    }


def test_context_ask_returns_fallback_when_ai_disabled(monkeypatch):
    monkeypatch.setattr(agent_router_module, "answer_context_ask", agent_router_module.answer_context_ask)
    import modules.agent.context_ask_service as service

    monkeypatch.setattr(service, "is_llm_enabled", lambda: False)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "核心判断" in data["answer"]
    assert data["evidence"]
    assert data["citations"] == ["summary_pack.headline"]
    assert data["warnings"]


def test_context_ask_rejects_empty_question():
    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=_payload(question=""))

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "invalid_question"


def test_context_ask_invalid_target_type_returns_validation_error():
    payload = _payload()
    payload["target"]["type"] = "unknown"

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 422


def test_context_ask_ai_provider_exception_falls_back(monkeypatch):
    import modules.agent.context_ask_service as service

    class BrokenClient:
        async def chat_json(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: BrokenClient())

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "AI 调用失败" in "；".join(data["warnings"])
