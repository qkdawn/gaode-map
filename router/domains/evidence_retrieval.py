from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from modules.evidence_retrieval import (
    EmptySearchQuestion,
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    search_evidence,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/search", response_model=EvidenceSearchResponse)
async def post_evidence_search(payload: EvidenceSearchRequest) -> EvidenceSearchResponse:
    try:
        return await search_evidence(payload)
    except EmptySearchQuestion as exc:
        raise HTTPException(status_code=400, detail="empty_search_question") from exc
    except Exception as exc:
        logger.warning("PageIndex search failed", exc_info=exc)
        raise HTTPException(status_code=503, detail="pageindex_search_unavailable") from exc
