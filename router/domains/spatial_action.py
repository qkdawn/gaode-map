from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from modules.spatial_action import (
    LocalPatternAnalysisRequest,
    LocalizedPatternResult,
    SpatialActionService,
)

router = APIRouter()
_service = SpatialActionService()


@router.post(
    "/api/v1/analysis/spatial-actions/local-patterns",
    response_model=LocalizedPatternResult,
)
async def analyze_local_patterns(payload: LocalPatternAnalysisRequest):
    try:
        return await asyncio.to_thread(
            _service.analyze_local_patterns,
            payload.cells,
            alpha=payload.alpha,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
