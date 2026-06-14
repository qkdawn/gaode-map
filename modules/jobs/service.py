from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import uuid4

from store.ai_database import SessionLocal
from store.ai_models import Job

from .schemas import JobRecord, JobType

logger = logging.getLogger(__name__)

JobHandler = Callable[[str], Awaitable[object]]

SUPPORTED_JOB_TYPES: set[str] = {
    "parse_document",
    "profile_dataset",
    "build_package",
    "generate_ppt",
}


class JobNotFound(LookupError):
    pass


class UnsupportedJobType(ValueError):
    pass


def _job_payload(record: Job) -> JobRecord:
    return JobRecord.model_validate(record)


def create_job(
    *,
    job_type: JobType,
    target_type: str,
    target_id: str,
    project_id: str | None = None,
) -> JobRecord:
    normalized_job_type = str(job_type or "").strip()
    normalized_target_type = str(target_type or "").strip()
    normalized_target_id = str(target_id or "").strip()
    if normalized_job_type not in SUPPORTED_JOB_TYPES:
        raise UnsupportedJobType("unsupported_job_type")
    if not normalized_target_type or not normalized_target_id:
        raise ValueError("invalid_job_target")

    now = datetime.utcnow()
    record = Job(
        id=uuid4().hex,
        project_id=str(project_id).strip() or None if project_id is not None else None,
        job_type=normalized_job_type,
        target_type=normalized_target_type,
        target_id=normalized_target_id,
        status="pending",
        progress=0,
        message="",
        error="",
        created_at=now,
    )
    session = SessionLocal()
    try:
        session.add(record)
        session.commit()
        session.refresh(record)
        return _job_payload(record)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_job(job_id: str) -> JobRecord:
    normalized_id = str(job_id or "").strip()
    if not normalized_id:
        raise JobNotFound("job_not_found")
    session = SessionLocal()
    try:
        record = session.get(Job, normalized_id)
        if record is None:
            raise JobNotFound("job_not_found")
        return _job_payload(record)
    finally:
        session.close()


def schedule_job(job_id: str, handler: JobHandler) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run_job(job_id, handler))
    except RuntimeError:
        asyncio.run(run_job(job_id, handler))


async def run_job(job_id: str, handler: JobHandler) -> JobRecord:
    record = _mark_running(job_id)
    try:
        await handler(record.target_id)
    except Exception as exc:
        logger.warning("Job %s failed", job_id, exc_info=exc)
        _mark_failed(job_id, str(exc) or exc.__class__.__name__)
        raise
    return _mark_succeeded(job_id)


def _mark_running(job_id: str) -> JobRecord:
    session = SessionLocal()
    try:
        record = session.get(Job, job_id)
        if record is None:
            raise JobNotFound("job_not_found")
        now = datetime.utcnow()
        record.status = "running"
        record.progress = max(int(record.progress or 0), 5)
        record.message = "running"
        record.error = ""
        record.started_at = now
        session.commit()
        session.refresh(record)
        return _job_payload(record)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _mark_succeeded(job_id: str) -> JobRecord:
    session = SessionLocal()
    try:
        record = session.get(Job, job_id)
        if record is None:
            raise JobNotFound("job_not_found")
        record.status = "succeeded"
        record.progress = 100
        record.message = "succeeded"
        record.error = ""
        record.finished_at = datetime.utcnow()
        session.commit()
        session.refresh(record)
        return _job_payload(record)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _mark_failed(job_id: str, error: str) -> JobRecord:
    session = SessionLocal()
    try:
        record = session.get(Job, job_id)
        if record is None:
            raise JobNotFound("job_not_found")
        record.status = "failed"
        record.progress = int(record.progress or 0)
        record.message = "failed"
        record.error = str(error or "job_failed")[:4000]
        record.finished_at = datetime.utcnow()
        session.commit()
        session.refresh(record)
        return _job_payload(record)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
