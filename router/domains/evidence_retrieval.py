from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from modules.evidence_retrieval import (
    AiDatabaseUnavailable,
    EmbeddingServiceUnavailable,
    EmptySearchQuestion,
    EvidenceIndexRequest,
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    schedule_evidence_index,
    search_evidence,
)
from modules.jobs import JobCreateResponse


router = APIRouter()
logger = logging.getLogger(__name__)


def _raise_ai_database_error(exc: Exception) -> None:
    logger.warning("Evidence retrieval database request failed", exc_info=exc)
    raise HTTPException(status_code=503, detail="ai_database_unavailable") from exc


@router.post("/evidence/index", response_model=JobCreateResponse)
async def post_evidence_index(payload: EvidenceIndexRequest | None = None) -> JobCreateResponse:
    try:
        return schedule_evidence_index(None if payload is None else payload.document_id)
    except (AiDatabaseUnavailable, SQLAlchemyError) as exc:
        _raise_ai_database_error(exc)


@router.post("/search", response_model=EvidenceSearchResponse)
async def post_evidence_search(payload: EvidenceSearchRequest) -> EvidenceSearchResponse:
    try:
        return await search_evidence(payload)
    except EmptySearchQuestion as exc:
        raise HTTPException(status_code=400, detail="empty_search_question") from exc
    except EmbeddingServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="embedding_service_unavailable") from exc
    except (AiDatabaseUnavailable, SQLAlchemyError) as exc:
        _raise_ai_database_error(exc)
