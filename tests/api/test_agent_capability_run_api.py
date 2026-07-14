from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import store.analysis_run_repo as analysis_run_repo_module  # noqa: E402
from store.models import Base  # noqa: E402
from store.analysis_run_storage import AnalysisRunStorage  # noqa: E402

_AGENT_ROUTE_PATH = ROOT_DIR / "router" / "domains" / "agent.py"
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location(
    "test_agent_analysis_run_route_module",
    _AGENT_ROUTE_PATH,
)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)


def _install_run_store(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(analysis_run_repo_module, "SessionLocal", factory)
    monkeypatch.setattr(
        analysis_run_repo_module.analysis_run_repo,
        "storage",
        AnalysisRunStorage(tmp_path / "analysis-runs"),
    )
    return analysis_run_repo_module.analysis_run_repo


def _app():
    app = FastAPI()
    app.include_router(agent_router_module.router)
    return app


def _manifest(run_id: str, capability_id: str = "urban-strategy-stage1"):
    return {
        "run_id": run_id,
        "capability_id": capability_id,
        "project_context": {},
        "configuration_snapshot": {"history_id": "history-api"},
        "execution_profile": {},
        "input_artifact_refs": [],
        "status": "completed",
        "current_stage": "report",
        "stage_records": [],
        "diagnostics": [],
        "stale_input_artifact_ids": [],
        "output_artifact_refs": [
            {
                "artifact_id": "stage1-report",
                "artifact_type": "report",
                "title": "第一阶段报告",
                "version": run_id,
                "filename": "stage1-report.md",
                "source_run_id": run_id,
                "source_artifact_refs": [],
                "evidence_refs": [],
                "content_digest": "sha256:test",
                "created_at": "2026-07-12T00:00:00Z",
            }
        ],
        "created_at": "2026-07-12T00:00:00Z",
        "completed_at": "2026-07-12T00:01:00Z",
    }


def test_analysis_run_list_and_detail_api(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(
        history_id="history-api",
        manifest=_manifest("run-api"),
        artifact_payloads={"stage1-report": "# 已审计报告"},
    )
    repo.save(
        history_id="history-api",
        manifest=_manifest("run-other", "other-capability"),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/analysis/agent/analysis/runs",
            params={
                "history_id": "history-api",
                "capability_id": "urban-strategy-stage1",
            },
        )
        assert response.status_code == 200
        assert [item["run_id"] for item in response.json()] == ["run-api"]

        detail = client.get(
            "/api/v1/analysis/agent/analysis/runs/run-api"
        )
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["history_id"] == "history-api"
        assert payload["run"]["run_id"] == "run-api"
        assert payload["artifacts"][0]["payload"] == "# 已审计报告"


def test_analysis_run_api_rejects_missing_history_and_unknown_run(monkeypatch, tmp_path):
    _install_run_store(monkeypatch, tmp_path)

    with TestClient(_app()) as client:
        missing_history = client.get(
            "/api/v1/analysis/agent/analysis/runs",
            params={"history_id": ""},
        )
        assert missing_history.status_code == 422
        assert missing_history.json()["detail"] == "history_id_required"

        missing_run = client.get(
            "/api/v1/analysis/agent/analysis/runs/unknown"
        )
        assert missing_run.status_code == 404
        assert missing_run.json()["detail"] == "analysis_run_not_found"

def test_analysis_run_comparison_api_returns_structured_diff(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    base = _manifest("run-base")
    target = _manifest("run-target")
    base["configuration_snapshot"]["question"] = "形成初稿"
    target["configuration_snapshot"]["question"] = "补充约束后复算"
    base["output_artifact_refs"][0]["content_digest"] = "sha256:base"
    target["output_artifact_refs"][0]["content_digest"] = "sha256:target"
    repo.save(
        history_id="history-api",
        manifest=base,
        artifact_payloads={"stage1-report": "# 初稿"},
    )
    repo.save(
        history_id="history-api",
        manifest=target,
        artifact_payloads={"stage1-report": "# 复算稿"},
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={
                "base_run_id": "run-base",
                "target_run_id": "run-target",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_run"]["run_id"] == "run-base"
    assert payload["target_run"]["run_id"] == "run-target"
    assert payload["has_changes"] is True
    assert payload["configuration_changes"][0]["field"] == "configuration_snapshot.question"
    assert payload["artifact_changes"][0]["artifact_id"] == "stage1-report"


def test_analysis_run_comparison_api_rejects_unknown_or_same_run(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(history_id="history-api", manifest=_manifest("run-one"))

    with TestClient(_app()) as client:
        missing = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={"base_run_id": "run-one", "target_run_id": "unknown"},
        )
        same = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={"base_run_id": "run-one", "target_run_id": "run-one"},
        )

    assert missing.status_code == 404
    assert missing.json()["detail"] == "analysis_run_not_found"
    assert same.status_code == 422
    assert same.json()["detail"] == "analysis_run_comparison_requires_distinct_runs"
