import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from modules.charting import delete_chart_file
from modules.ppt_planning.schemas import (
    DeckBriefSlideRequest,
    DeckBriefJobCreateResponse,
    DeckBriefJobStatusResponse,
    DeckBriefRequest,
    DeckBriefResponse,
    DeckNarrativePlanRequest,
    DeckNarrativePlanResponse,
    PptDataPackageRequest,
    PptDataPackageResponse,
    PptDataSourceSummary,
    DeckSlideBrief,
    PptOutlineSectionRequest,
    PptOutlineItem,
    PptPoiNearbyRequest,
    PptPoiQueryRequest,
    PptPoiQueryResponse,
    PptSourceGroupClassifyRequest,
    PptSourceGroupClassifyResponse,
    PptSpecRequest,
    PptSpecResponse,
    PptVisualArtifactRequest,
    PptVisualArtifactResponse,
)
from modules.ppt_planning.data_tools import (
    PptDataAreaNotFound,
    PptDataIntentLlmUnavailable,
    PptDataInvalidIntentPlan,
    PptDataSourceNotFound,
    create_ppt_data_package,
    list_ppt_sources,
    query_nearby_poi_points,
    query_poi_points,
    read_ppt_source_summary,
)
from modules.ppt_planning.service import (
    PptPlanningInvalidResponse,
    PptPlanningLlmUnavailable,
    classify_ppt_source_groups,
    generate_deck_brief,
    create_deck_brief_job,
    get_deck_brief_job,
    generate_narrative_plan,
    generate_ppt_spec,
    generate_visual_artifacts_for_slide,
    regenerate_deck_brief_slide,
    regenerate_ppt_outline_section,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class PptVisualArtifactCleanupRequest(BaseModel):
    filenames: list[str] = Field(default_factory=list)


def _raise_ppt_database_error(exc: SQLAlchemyError) -> None:
    logger.warning("PPT planning database request failed", exc_info=exc)
    raise HTTPException(status_code=503, detail="ppt_database_unavailable") from exc


def _raise_ppt_llm_error(exc: Exception, *, detail_prefix: str) -> None:
    logger.warning("PPT planning LLM request failed", exc_info=exc)
    if isinstance(exc, httpx.TimeoutException):
        raise HTTPException(status_code=504, detail=f"{detail_prefix}_timeout") from exc
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = int(getattr(exc.response, "status_code", 502) or 502)
        status_code = 502 if status_code >= 500 else 400
        raise HTTPException(status_code=status_code, detail=f"{detail_prefix}_http_error") from exc
    if isinstance(exc, httpx.RequestError):
        raise HTTPException(status_code=503, detail=f"{detail_prefix}_request_failed") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=502, detail=f"{detail_prefix}_invalid_response") from exc
    raise HTTPException(status_code=500, detail=f"{detail_prefix}_failed") from exc


def _raise_ppt_data_error(exc: RuntimeError) -> None:
    if isinstance(exc, PptDataAreaNotFound):
        raise HTTPException(status_code=404, detail=str(exc) or "ppt_data_area_not_found") from exc
    if isinstance(exc, PptDataSourceNotFound):
        raise HTTPException(status_code=404, detail=str(exc) or "ppt_data_source_not_found") from exc
    if isinstance(exc, PptDataIntentLlmUnavailable):
        raise HTTPException(status_code=503, detail="ppt_data_intent_llm_unavailable") from exc
    if isinstance(exc, PptDataInvalidIntentPlan):
        raise HTTPException(status_code=502, detail="ppt_data_invalid_intent_plan") from exc
    raise HTTPException(status_code=500, detail="ppt_data_tool_failed") from exc


def _raise_ppt_planning_error(exc: Exception) -> None:
    if isinstance(exc, PptPlanningLlmUnavailable):
        raise HTTPException(status_code=503, detail="ppt_planning_llm_unavailable") from exc
    if isinstance(exc, PptPlanningInvalidResponse):
        detail = exc.detail if getattr(exc, "detail", None) else str(exc) or "ppt_planning_invalid_ai_response"
        logger.warning(
            "PPT planning invalid response",
            extra={
                "ppt_planning_error": {
                    "message": str(exc) or "ppt_planning_invalid_ai_response",
                    "detail": detail,
                },
            },
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    if isinstance(exc, SQLAlchemyError):
        _raise_ppt_database_error(exc)
    if isinstance(exc, (httpx.HTTPError, ValueError)):
        _raise_ppt_llm_error(exc, detail_prefix="ppt_planning_llm")
    logger.exception("PPT planning request failed")
    raise HTTPException(status_code=500, detail="ppt_planning_failed") from exc


@router.get("/api/v1/analysis/ppt/data/sources", response_model=list[PptDataSourceSummary])
async def get_ppt_data_sources(area_id: str):
    try:
        return list_ppt_sources(area_id)
    except SQLAlchemyError as exc:
        _raise_ppt_database_error(exc)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.get("/api/v1/analysis/ppt/data/source-summary", response_model=PptDataSourceSummary)
async def get_ppt_data_source_summary(area_id: str, source_id: str):
    try:
        return read_ppt_source_summary(area_id, source_id)
    except SQLAlchemyError as exc:
        _raise_ppt_database_error(exc)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/data/query-poi-points", response_model=PptPoiQueryResponse)
async def post_ppt_query_poi_points(payload: PptPoiQueryRequest):
    try:
        return query_poi_points(payload)
    except SQLAlchemyError as exc:
        _raise_ppt_database_error(exc)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/data/nearby-pois", response_model=PptPoiQueryResponse)
async def post_ppt_nearby_pois(payload: PptPoiNearbyRequest):
    try:
        return query_nearby_poi_points(payload)
    except SQLAlchemyError as exc:
        _raise_ppt_database_error(exc)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/data/packages", response_model=PptDataPackageResponse)
async def post_ppt_data_package(payload: PptDataPackageRequest):
    try:
        return await create_ppt_data_package(payload)
    except SQLAlchemyError as exc:
        _raise_ppt_database_error(exc)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)
    except (httpx.HTTPError, ValueError) as exc:
        _raise_ppt_llm_error(exc, detail_prefix="ppt_data_llm")


@router.post("/api/v1/analysis/ppt/source-groups/classify", response_model=PptSourceGroupClassifyResponse)
async def post_ppt_source_group_classification(payload: PptSourceGroupClassifyRequest) -> PptSourceGroupClassifyResponse:
    try:
        return await classify_ppt_source_groups(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/spec", response_model=PptSpecResponse)
async def create_ppt_spec(payload: PptSpecRequest) -> PptSpecResponse:
    try:
        return await generate_ppt_spec(payload)
    except PptPlanningInvalidResponse as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "invalid_ppt_outline") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="ppt_outline_llm_timeout") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="ppt_outline_invalid_response") from exc
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/spec/section", response_model=PptOutlineItem)
async def create_ppt_spec_section(payload: PptOutlineSectionRequest) -> PptOutlineItem:
    try:
        return await regenerate_ppt_outline_section(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/narrative-plan", response_model=DeckNarrativePlanResponse)
async def create_deck_narrative_plan(payload: DeckNarrativePlanRequest) -> DeckNarrativePlanResponse:
    try:
        return await generate_narrative_plan(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/deck-brief", response_model=DeckBriefResponse)
async def create_deck_brief(payload: DeckBriefRequest) -> DeckBriefResponse:
    try:
        return await generate_deck_brief(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/deck-brief/jobs", response_model=DeckBriefJobCreateResponse)
async def create_deck_brief_job_route(payload: DeckBriefRequest) -> DeckBriefJobCreateResponse:
    try:
        return await create_deck_brief_job(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.get("/api/v1/analysis/ppt/deck-brief/jobs/{job_id}", response_model=DeckBriefJobStatusResponse)
async def get_deck_brief_job_route(job_id: str) -> DeckBriefJobStatusResponse:
    try:
        return await get_deck_brief_job(job_id)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/deck-brief/slide", response_model=DeckSlideBrief)
async def create_deck_brief_slide(payload: DeckBriefSlideRequest) -> DeckSlideBrief:
    try:
        return await regenerate_deck_brief_slide(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/visual-artifacts", response_model=PptVisualArtifactResponse)
async def create_ppt_visual_artifacts(payload: PptVisualArtifactRequest) -> PptVisualArtifactResponse:
    try:
        return generate_visual_artifacts_for_slide(payload)
    except Exception as exc:
        _raise_ppt_planning_error(exc)


@router.post("/api/v1/analysis/ppt/visual-artifacts/cleanup")
async def cleanup_ppt_visual_artifacts(payload: PptVisualArtifactCleanupRequest):
    deleted: list[str] = []
    missing: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for filename in payload.filenames:
        name = str(filename or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            result = delete_chart_file(name)
        except OSError:
            result = "skipped"
        if result == "deleted":
            deleted.append(name)
        elif result == "missing":
            missing.append(name)
        else:
            skipped.append(name)
    return {"deleted": deleted, "missing": missing, "skipped": skipped}
