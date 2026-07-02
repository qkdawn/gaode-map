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


def test_context_ask_require_ai_fails_when_ai_disabled(monkeypatch):
    import modules.agent.context_ask_service as service

    payload = _payload()
    payload["require_ai"] = True
    monkeypatch.setattr(service, "is_llm_enabled", lambda: False)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "ai_unavailable"
    assert data["answer"] == ""


def test_context_ask_require_ai_provider_exception_fails(monkeypatch):
    import modules.agent.context_ask_service as service

    class BrokenClient:
        async def chat_json(self, **kwargs):
            raise RuntimeError("boom")

    payload = _payload()
    payload["require_ai"] = True
    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: BrokenClient())

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "ai_call_failed"
    assert data["answer"] == ""


def test_context_ask_accepts_ppt_sources_and_sends_target_payload(monkeypatch):
    import modules.agent.context_ask_service as service

    captured = {}

    class FakeClient:
        async def chat_json(self, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "已基于 PPT 已选来源回答。",
                "evidence": [{"source_id": "current:scope"}],
                "citations": ["current:scope"],
                "warnings": [],
            }

    payload = _payload()
    payload["require_ai"] = True
    payload["target"] = {
        "type": "ppt_sources",
        "id": "ppt-selected-sources",
        "title": "PPT 已选来源",
        "source": "ppt_planning",
        "summary": "已选择 1 个来源。",
        "evidence": [{"source_id": "current:scope", "title": "当前等时圈范围", "text": "范围摘要"}],
        "payload": {
            "sources": [{
                "source_id": "current:scope",
                "title": "当前等时圈范围",
                "included": ["scope", "evidence"],
                "scope": {"has_polygon": True},
                "evidence_nodes": [{
                    "id": "current:scope:evidence:1",
                    "source_id": "current:scope",
                    "source_type": "system",
                    "title": "范围",
                    "content": "当前区域",
                }],
            }],
        },
    }
    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: FakeClient())

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["answer"] == "已基于 PPT 已选来源回答。"
    target = captured["user_payload"]["target"]
    assert target["type"] == "ppt_sources"
    assert target["source"] == "ppt_planning"
    assert target["evidence"][0]["source_id"] == "current:scope"
    assert target["payload"]["sources"][0]["source_id"] == "current:scope"
    assert captured["user_payload"]["ppt_sources_summary"]["source_count"] == 1
    assert captured["user_payload"]["ppt_sources_summary"]["sources"][0]["source_id"] == "current:scope"
    assert captured["user_payload"]["ppt_sources_summary"]["sources"][0]["evidence_count"] == 1
    assert captured["user_payload"]["ppt_sources_summary"]["sources"][0]["evidence_nodes"][0]["id"] == "current:scope:evidence:1"
