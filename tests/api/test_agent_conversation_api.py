from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.agent_conversation.schemas import (
    ConversationMessage,
    ConversationSessionDetail,
    ConversationSessionSummary,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
_ROUTE_PATH = ROOT_DIR / "router" / "domains" / "agent.py"
_SPEC = importlib.util.spec_from_file_location("test_agent_conversation_route", _ROUTE_PATH)
route_module = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(route_module)


class FakeConversationService:
    def list_sessions(self):
        return [
            ConversationSessionSummary(
                id="conversation-1",
                history_id="history-1",
                panel_kind="analysis",
                title="区域判断",
            )
        ]

    async def get_session(self, session_id):
        return ConversationSessionDetail(
            id=session_id,
            history_id="history-1",
            panel_kind="analysis",
            title="区域判断",
            messages=[
                ConversationMessage(id="user-1", role="user", content="问题"),
                ConversationMessage(id="agent-1", role="assistant", content="回答"),
            ],
        )

    async def update_session(self, session_id, payload):
        detail = await self.get_session(session_id)
        return detail.model_copy(update={"title": payload.title or detail.title})

    async def delete_session(self, session_id):
        return {"status": "success", "id": session_id}

    async def stream_turn(self, _request, payload):
        yield "thread", {"conversation_id": payload.conversation_id}
        yield "message_delta", {"item_id": "agent-1", "delta": "回答"}
        yield "turn_completed", {"turn_id": "turn-1", "status": "completed", "error": ""}


def app():
    instance = FastAPI()
    instance.include_router(route_module.router)
    return instance


def test_conversation_stream_and_session_contract(monkeypatch):
    monkeypatch.setattr(route_module, "codex_conversation_service", FakeConversationService())
    with TestClient(app()) as client:
        response = client.post(
            "/api/v1/analysis/agent/conversations/turns/stream",
            json={
                "conversation_id": "conversation-1",
                "history_id": "history-1",
                "message": "问题",
                "map_context": {"active_panel": "poi"},
            },
        )
        detail = client.get("/api/v1/analysis/agent/sessions/conversation-1")
        renamed = client.patch(
            "/api/v1/analysis/agent/sessions/conversation-1",
            json={"title": "新标题"},
        )

    assert response.status_code == 200
    assert "event: message_delta" in response.text
    assert "event: turn_completed" in response.text
    assert detail.json()["messages"][-1]["content"] == "回答"
    assert renamed.json()["title"] == "新标题"
    assert "snapshot" not in detail.json()


def test_removed_custom_runtime_routes_are_not_exposed(monkeypatch):
    monkeypatch.setattr(route_module, "codex_conversation_service", FakeConversationService())
    with TestClient(app()) as client:
        assert client.post("/api/v1/analysis/agent/main-loop/stream", json={}).status_code == 404
        assert client.post("/api/v1/analysis/agent/context-ask", json={}).status_code == 404
        assert client.post("/api/v1/analysis/agent/context-ask/stream", json={}).status_code == 404
        assert client.get("/api/v1/analysis/agent/capabilities").status_code == 404
        assert client.post("/api/v1/analysis/agent/model-profiles", json={}).status_code == 404
