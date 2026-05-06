import os
import sys
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import store.agent_session_repo as agent_session_repo_module
import modules.agent.session_service as agent_session_service
from modules.agent.schemas import AgentTurnResponse
from store.models import Base

_AGENT_ROUTE_PATH = ROOT_DIR / "router" / "domains" / "agent.py"
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location("test_agent_session_route_module", _AGENT_ROUTE_PATH)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)
agent_router = agent_router_module.router


def _build_test_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def _install_test_session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(agent_session_repo_module, "SessionLocal", testing_session_local)


def test_agent_session_crud_api(monkeypatch):
    _install_test_session(monkeypatch)
    with TestClient(_build_test_app()) as client:
        put_resp = client.put(
            "/api/v1/analysis/agent/sessions/agent-1",
            json={
                "title": "商业分析",
                "preview": "开始一段新的分析对话",
                "status": "idle",
                "history_id": "history-current",
                "panel_kind": "commercial_summary",
                "is_pinned": False,
                "input": "",
                "messages": [{"role": "user", "content": "总结这个区域"}],
                "cards": [],
                "execution_trace": [],
                "used_tools": [],
                "citations": [],
                "research_notes": [],
                "thinking_timeline": [{"id": "thinking-1", "phase": "gating", "title": "输入检查完成", "detail": "已确认范围。", "state": "completed"}],
                "next_suggestions": [],
                "clarification_question": "",
                "risk_prompt": "",
                "error": "",
                "risk_confirmations": [],
            },
        )

        assert put_resp.status_code == 200
        assert put_resp.json()["title"] == "商业分析"
        assert put_resp.json()["history_id"] == "history-current"
        assert put_resp.json()["panel_kind"] == "commercial_summary"
        assert put_resp.json()["title_source"] == "user"

        patch_resp = client.patch(
            "/api/v1/analysis/agent/sessions/agent-1",
            json={"title": "商业分析-重命名", "is_pinned": True},
        )

        assert patch_resp.status_code == 200
        assert patch_resp.json()["title"] == "商业分析-重命名"
        assert patch_resp.json()["is_pinned"] is True
        assert patch_resp.json()["title_source"] == "user"

        list_resp = client.get("/api/v1/analysis/agent/sessions")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["id"] == "agent-1"
        assert list_resp.json()[0]["history_id"] == "history-current"
        assert list_resp.json()[0]["panel_kind"] == "commercial_summary"

        detail_resp = client.get("/api/v1/analysis/agent/sessions/agent-1")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["history_id"] == "history-current"
        assert detail_resp.json()["messages"][0]["content"] == "总结这个区域"
        assert detail_resp.json()["diagnostics"]["thinking_timeline"][0]["id"] == "thinking-1"

        delete_resp = client.delete("/api/v1/analysis/agent/sessions/agent-1")
        assert delete_resp.status_code == 200

        missing_resp = client.get("/api/v1/analysis/agent/sessions/agent-1")
        assert missing_resp.status_code == 404


def test_agent_turn_persists_multiple_statuses(monkeypatch):
    _install_test_session(monkeypatch)
    async def fake_generate_title(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_session_service, "generate_agent_session_title", fake_generate_title)
    with TestClient(_build_test_app()) as client:
        statuses = [
            ("answered", {"output": {"cards": [{"type": "summary", "title": "概览", "content": "已完成分析", "items": []}]}, "diagnostics": {"thinking_timeline": [{"id": "thinking-answer", "phase": "answering", "title": "回答生成完成", "state": "completed"}]}}),
            ("requires_clarification", {"output": {"clarification_question": "请补充范围"}, "diagnostics": {"thinking_timeline": [{"id": "thinking-clarify", "phase": "gating", "title": "需要补充信息", "state": "failed"}]}}),
            ("requires_risk_confirmation", {"output": {"risk_prompt": "工具 `compute_road_syntax_from_scope` 属于高成本执行，请确认后重试。"}, "diagnostics": {"thinking_timeline": [{"id": "thinking-risk", "phase": "planned", "title": "等待风险确认", "state": "failed"}]}}),
            ("failed", {"diagnostics": {"thinking_timeline": [{"id": "thinking-failed", "phase": "answering", "title": "回答生成失败", "state": "failed"}]}}),
        ]

        for index, (status, extra) in enumerate(statuses, start=1):
            async def fake_process_agent_turn(_payload, *, _status=status, _extra=extra):
                return AgentTurnResponse(status=_status, **_extra)

            monkeypatch.setattr(agent_router_module, "process_agent_turn", fake_process_agent_turn)

            resp = client.post(
                "/api/v1/analysis/agent/turn",
                json={
                    "conversation_id": f"agent-{index}",
                    "history_id": f"history-{index}",
                    "messages": [{"role": "user", "content": f"问题-{index}"}],
                    "analysis_snapshot": {"scope": {"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}},
                },
            )

            assert resp.status_code == 200
            assert resp.json()["status"] == status

        list_resp = client.get("/api/v1/analysis/agent/sessions")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 4
        assert {item["history_id"] for item in list_resp.json()} == {"history-1", "history-2", "history-3", "history-4"}
        assert {item["panel_kind"] for item in list_resp.json()} == {"followup"}

        answered_detail = client.get("/api/v1/analysis/agent/sessions/agent-1")
        assert answered_detail.status_code == 200
        assert answered_detail.json()["history_id"] == "history-1"
        assert answered_detail.json()["panel_kind"] == "followup"
        assert answered_detail.json()["messages"][-1]["role"] == "assistant"
        assert answered_detail.json()["diagnostics"]["thinking_timeline"][0]["id"] == "thinking-answer"

        clarification_detail = client.get("/api/v1/analysis/agent/sessions/agent-2")
        assert clarification_detail.status_code == 200
        assert clarification_detail.json()["output"]["clarification_question"] == "请补充范围"

        risk_detail = client.get("/api/v1/analysis/agent/sessions/agent-3")
        assert risk_detail.status_code == 200
        assert "compute_road_syntax_from_scope" in risk_detail.json()["output"]["risk_prompt"]

        failed_detail = client.get("/api/v1/analysis/agent/sessions/agent-4")
        assert failed_detail.status_code == 200
        assert failed_detail.json()["status"] == "failed"
        assert failed_detail.json()["diagnostics"]["thinking_timeline"][0]["id"] == "thinking-failed"


def test_agent_turn_generates_title_only_for_first_persist(monkeypatch):
    _install_test_session(monkeypatch)
    generated_titles = []

    async def fake_generate_title(_payload, _response):
        generated_titles.append("called")
        return "AI 自动标题"

    monkeypatch.setattr(agent_session_service, "generate_agent_session_title", fake_generate_title)

    with TestClient(_build_test_app()) as client:
        async def fake_process_agent_turn(_payload):
            return AgentTurnResponse(
                status="answered",
                output={"cards": [{"type": "summary", "title": "概览", "content": "已完成分析", "items": []}]},
            )

        monkeypatch.setattr(agent_router_module, "process_agent_turn", fake_process_agent_turn)

        first = client.post(
            "/api/v1/analysis/agent/turn",
            json={
                "conversation_id": "agent-title",
                "history_id": "history-1",
                "messages": [{"role": "user", "content": "总结这个区域的商业结构"}],
                "analysis_snapshot": {"scope": {"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}},
            },
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/analysis/agent/turn",
            json={
                "conversation_id": "agent-title",
                "history_id": "history-2",
                "messages": [
                    {"role": "user", "content": "总结这个区域的商业结构"},
                    {"role": "assistant", "content": "已完成分析"},
                    {"role": "user", "content": "再看一下路网"},
                ],
                "analysis_snapshot": {"scope": {"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}},
            },
        )
        assert second.status_code == 200

        detail_resp = client.get("/api/v1/analysis/agent/sessions/agent-title")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["history_id"] == "history-2"
        assert detail_resp.json()["title"] == "AI 自动标题"
        assert detail_resp.json()["title_source"] == "ai"
        assert len(generated_titles) == 1


def test_agent_turn_keeps_user_title_without_auto_override(monkeypatch):
    _install_test_session(monkeypatch)
    generated_titles = []

    async def fake_generate_title(_payload, _response):
        generated_titles.append("called")
        return "不会生效"

    monkeypatch.setattr(agent_session_service, "generate_agent_session_title", fake_generate_title)

    with TestClient(_build_test_app()) as client:
        put_resp = client.put(
            "/api/v1/analysis/agent/sessions/agent-user-title",
            json={
                "title": "手动标题",
                "preview": "开始一段新的分析对话",
                "status": "idle",
                "history_id": "history-1",
                "panel_kind": "followup",
                "input": "",
                "messages": [],
                "cards": [],
                "execution_trace": [],
                "used_tools": [],
                "citations": [],
                "research_notes": [],
                "next_suggestions": [],
                "clarification_question": "",
                "risk_prompt": "",
                "error": "",
                "risk_confirmations": [],
            },
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["title_source"] == "user"

        async def fake_process_agent_turn(_payload):
            return AgentTurnResponse(
                status="answered",
                output={"cards": [{"type": "summary", "title": "概览", "content": "已完成分析", "items": []}]},
            )

        monkeypatch.setattr(agent_router_module, "process_agent_turn", fake_process_agent_turn)

        turn_resp = client.post(
            "/api/v1/analysis/agent/turn",
            json={
                "conversation_id": "agent-user-title",
                "history_id": "history-1",
                "messages": [{"role": "user", "content": "总结这个区域"}],
                "analysis_snapshot": {"scope": {"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}},
            },
        )
        assert turn_resp.status_code == 200

        detail_resp = client.get("/api/v1/analysis/agent/sessions/agent-user-title")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["title"] == "手动标题"
        assert detail_resp.json()["title_source"] == "user"
        assert generated_titles == []
