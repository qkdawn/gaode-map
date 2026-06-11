from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from modules.jobs import JobNotFound, JobRecord, get_job


router = APIRouter()
logger = logging.getLogger(__name__)


def _raise_database_error(exc: SQLAlchemyError) -> None:
    logger.warning("Job database request failed", exc_info=exc)
    raise HTTPException(status_code=503, detail="job_database_unavailable") from exc


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job_detail(job_id: str) -> JobRecord:
    try:
        return get_job(job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
