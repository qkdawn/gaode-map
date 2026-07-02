import logging

from fastapi import APIRouter, HTTPException

from modules.ppt_planning.schemas import (
    PptDataPackageResponse,
    PptWebSourceCommitRequest,
    PptWebSourceLocationDefaultRequest,
    PptWebSourceLocationDefaultResponse,
    PptWebSourceSearchRequest,
)
from modules.ppt_web_source.service import (
    PptWebSourceAreaNotFound,
    PptWebSourceSearchUnavailable,
    build_web_source_location_default,
    commit_ppt_web_source,
    preview_ppt_web_source,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _raise_ppt_web_source_error(exc: Exception) -> None:
    if isinstance(exc, PptWebSourceAreaNotFound):
        raise HTTPException(status_code=404, detail=str(exc) or "ppt_web_source_area_not_found") from exc
    if isinstance(exc, PptWebSourceSearchUnavailable):
        raise HTTPException(status_code=503, detail=str(exc) or "searxng_unavailable") from exc
    logger.exception("PPT web source request failed")
    raise HTTPException(status_code=500, detail="ppt_web_source_failed") from exc


@router.post("/api/v1/analysis/ppt/web-sources/location-default", response_model=PptWebSourceLocationDefaultResponse)
async def post_ppt_web_source_location_default(payload: PptWebSourceLocationDefaultRequest) -> PptWebSourceLocationDefaultResponse:
    try:
        return build_web_source_location_default(payload)
    except Exception as exc:
        _raise_ppt_web_source_error(exc)


@router.post("/api/v1/analysis/ppt/web-sources/preview", response_model=PptDataPackageResponse)
async def post_ppt_web_source_preview(payload: PptWebSourceSearchRequest) -> PptDataPackageResponse:
    try:
        return await preview_ppt_web_source(payload)
    except Exception as exc:
        _raise_ppt_web_source_error(exc)


@router.post("/api/v1/analysis/ppt/web-sources/commit", response_model=PptDataPackageResponse)
async def post_ppt_web_source_commit(payload: PptWebSourceCommitRequest) -> PptDataPackageResponse:
    try:
        return commit_ppt_web_source(payload)
    except Exception as exc:
        _raise_ppt_web_source_error(exc)
