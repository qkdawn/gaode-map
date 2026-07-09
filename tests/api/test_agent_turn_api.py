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
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location("test_agent_main_loop_route_module", _AGENT_ROUTE_PATH)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)
agent_router = agent_router_module.router


def _build_test_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def test_stream_main_loop_serializes_persisted_final_response(monkeypatch):
    async def fake_stream_main_loop(_payload):
        yield agent_router_module.AgentTurnStreamEvent(
            type="final",
            payload={
                "response": {
                    "status": "answered",
                    "stage": "answered",
                    "output": {"answer": "已完成。"},
                    "diagnostics": {
                        "execution_trace": [],
                        "used_tools": [],
                        "citations": [],
                        "research_notes": [],
                        "audit_issues": [],
                        "thinking_timeline": [],
                        "error": "",
                    },
                    "context_summary": {},
                    "plan": {},
                }
            },
        )

    async def fake_persist_streamed_main_agent_loop_response(_payload, response, _repo, *, logger=None):
        diagnostics = response.diagnostics.model_copy(
            update={
                "research_notes": ["persisted via helper"],
                "error": "persist_marker",
            }
        )
        return response.model_copy(update={"diagnostics": diagnostics})

    monkeypatch.setattr(agent_router_module, "stream_main_agent_loop", fake_stream_main_loop)
    monkeypatch.setattr(
        agent_router_module,
        "persist_streamed_main_agent_loop_response",
        fake_persist_streamed_main_agent_loop_response,
    )

    payload = {
        "conversation_id": "agent-1",
        "history_id": "history-1",
        "messages": [{"role": "user", "content": "深度分析"}],
        "analysis_snapshot": {"context": {"history_id": "history-1"}},
    }

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/main-loop/stream", json=payload)

    assert response.status_code == 200
    body = response.text
    assert "event: final" in body
    assert "已完成。" in body
    assert "persist_marker" in body
    assert "persisted via helper" in body
