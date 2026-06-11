from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from modules.jobs.service import JobNotFound, create_job, get_job, run_job
from store.ai_models import Job


class FakeSession:
    def __init__(self, state):
        self.state = state
        self.jobs = state["jobs"]
        self.closed = False
        self.rolled_back = False

    def add(self, record):
        self.jobs.append(record)

    def commit(self):
        self.state["commits"] += 1

    def refresh(self, _record):
        pass

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def get(self, model, record_id):
        if model is Job:
            for row in self.jobs:
                if row.id == record_id:
                    return row
        return None


def _job(job_id="job-1", *, status="pending"):
    return Job(
        id=job_id,
        project_id=None,
        job_type="parse_document",
        target_type="document",
        target_id="doc-1",
        status=status,
        progress=0,
        message="",
        error="",
        created_at=datetime(2026, 6, 12, 1, 0, 0),
    )


def test_create_and_get_job(monkeypatch):
    state = {"jobs": [], "commits": 0}
    monkeypatch.setattr("modules.jobs.service.SessionLocal", lambda: FakeSession(state))

    record = create_job(job_type="parse_document", target_type="document", target_id="doc-1")

    assert record.status == "pending"
    assert record.job_type == "parse_document"
    assert record.target_type == "document"
    assert record.target_id == "doc-1"
    assert state["commits"] == 1
    assert get_job(record.id).id == record.id


def test_get_job_missing_raises(monkeypatch):
    state = {"jobs": [], "commits": 0}
    monkeypatch.setattr("modules.jobs.service.SessionLocal", lambda: FakeSession(state))

    with pytest.raises(JobNotFound):
        get_job("missing")


def test_run_job_marks_running_then_succeeded(monkeypatch):
    state = {"jobs": [_job()], "commits": 0}
    monkeypatch.setattr("modules.jobs.service.SessionLocal", lambda: FakeSession(state))
    called = []

    async def handler(target_id):
        called.append(target_id)

    record = asyncio.run(run_job("job-1", handler))

    assert called == ["doc-1"]
    assert record.status == "succeeded"
    assert record.progress == 100
    assert state["jobs"][0].started_at is not None
    assert state["jobs"][0].finished_at is not None


def test_run_job_marks_failed(monkeypatch):
    state = {"jobs": [_job()], "commits": 0}
    monkeypatch.setattr("modules.jobs.service.SessionLocal", lambda: FakeSession(state))

    async def handler(_target_id):
        raise RuntimeError("parse failed")

    with pytest.raises(RuntimeError):
        asyncio.run(run_job("job-1", handler))

    assert state["jobs"][0].status == "failed"
    assert state["jobs"][0].error == "parse failed"
    assert state["jobs"][0].finished_at is not None
