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
from store.analysis_run_storage import AnalysisRunStorage  # noqa: E402
from store.models import Base  # noqa: E402

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


def _stage1_manifest(run_id: str):
    return {
        "run_id": run_id,
        "capability_id": "urban-strategy-stage1",
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
                "content_digest": "sha256:test",
            }
        ],
        "created_at": "2026-07-12T00:00:00Z",
        "completed_at": "2026-07-12T00:01:00Z",
    }


def test_analysis_run_list_and_detail_api_for_stage1(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(
        history_id="history-api",
        manifest=_stage1_manifest("run-api"),
        artifact_payloads={"stage1-report": "# 已审计报告"},
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
    assert detail.json()["artifacts"][0]["payload"] == "# 已审计报告"


def test_codex_only_spatial_report_runs_are_not_read_by_agent_api(
    monkeypatch,
    tmp_path,
):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(
        history_id="history-api",
        manifest={
            "schema_version": "4.1",
            "run_id": "retired-spatial-run",
            "capability_id": "spatial-business-analyst",
            "status": "completed",
            "output_artifact_refs": [],
        },
        artifact_payloads={},
    )

    with TestClient(_app()) as client:
        listing = client.get(
            "/api/v1/analysis/agent/analysis/runs",
            params={"history_id": "history-api"},
        )
        detail = client.get(
            "/api/v1/analysis/agent/analysis/runs/retired-spatial-run"
        )
        comparison = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={
                "base_run_id": "retired-spatial-run",
                "target_run_id": "retired-spatial-run",
            },
        )

    assert listing.status_code == 200
    assert listing.json() == []
    assert detail.status_code == 404
    assert comparison.status_code == 404


def test_analysis_run_api_rejects_missing_history_and_unknown_run(
    monkeypatch,
    tmp_path,
):
    _install_run_store(monkeypatch, tmp_path)

    with TestClient(_app()) as client:
        missing_history = client.get(
            "/api/v1/analysis/agent/analysis/runs",
            params={"history_id": ""},
        )
        missing_run = client.get(
            "/api/v1/analysis/agent/analysis/runs/unknown"
        )

    assert missing_history.status_code == 422
    assert missing_run.status_code == 404
