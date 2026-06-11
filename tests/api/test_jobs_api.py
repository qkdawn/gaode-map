from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from modules.jobs import JobNotFound, JobRecord
from router.domains import jobs
from router.domains.jobs import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _job(job_id="job-1"):
    return JobRecord(
        id=job_id,
        project_id=None,
        job_type="parse_document",
        target_type="document",
        target_id="doc-1",
        status="running",
        progress=5,
        message="running",
        error="",
        created_at=datetime(2026, 6, 12, 1, 0, 0),
        started_at=datetime(2026, 6, 12, 1, 0, 1),
        finished_at=None,
    )


def test_jobs_api_returns_job(monkeypatch):
    monkeypatch.setattr(jobs, "get_job", lambda job_id: _job(job_id))

    with TestClient(_build_test_app()) as client:
        response = client.get("/jobs/job-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "job-1"
    assert payload["job_type"] == "parse_document"
    assert payload["status"] == "running"


def test_jobs_api_maps_missing_and_database_errors(monkeypatch):
    def missing(_job_id):
        raise JobNotFound("job_not_found")

    monkeypatch.setattr(jobs, "get_job", missing)
    with TestClient(_build_test_app()) as client:
        response = client.get("/jobs/missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "job_not_found"

    def db_down(_job_id):
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(jobs, "get_job", db_down)
    with TestClient(_build_test_app()) as client:
        response = client.get("/jobs/job-1")
    assert response.status_code == 503
    assert response.json()["detail"] == "job_database_unavailable"
