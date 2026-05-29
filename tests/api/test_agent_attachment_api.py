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
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location("test_agent_attachment_route_module", _AGENT_ROUTE_PATH)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)
agent_router = agent_router_module.router


def _build_test_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def test_agent_attachment_upload_and_list(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.retrieval.attachments.settings.agent_attachment_upload_dir", str(tmp_path))
    monkeypatch.setattr(agent_router_module, "schedule_attachment_ingest", lambda _record: None)

    with TestClient(_build_test_app()) as client:
        upload = client.post(
            "/api/v1/analysis/agent/attachments",
            data={"conversation_id": "agent-1", "history_id": "history-1"},
            files={"file": ("note.txt", b"hello attachment", "text/plain")},
        )
        assert upload.status_code == 200
        payload = upload.json()
        assert payload["filename"] == "note.txt"
        assert payload["status"] == "processing"

        listed = client.get("/api/v1/analysis/agent/attachments", params={"conversation_id": "agent-1"})
        assert listed.status_code == 200
        assert listed.json()[0]["attachment_id"] == payload["attachment_id"]


def test_agent_attachment_rejects_unsupported_type(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.retrieval.attachments.settings.agent_attachment_upload_dir", str(tmp_path))

    with TestClient(_build_test_app()) as client:
        upload = client.post(
            "/api/v1/analysis/agent/attachments",
            data={"conversation_id": "agent-1"},
            files={"file": ("script.exe", b"nope", "application/octet-stream")},
        )
        assert upload.status_code == 400
        assert upload.json()["detail"] == "unsupported_attachment_type"
