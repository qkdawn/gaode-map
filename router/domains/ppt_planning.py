from fastapi import APIRouter, HTTPException

from modules.ppt_planning.schemas import (
    DeckBriefRequest,
    DeckBriefResponse,
    PptDataPackageRequest,
    PptDataPackageResponse,
    PptDataSourceSummary,
    PptPoiNearbyRequest,
    PptPoiQueryRequest,
    PptPoiQueryResponse,
    PptSourceGroupClassifyRequest,
    PptSourceGroupClassifyResponse,
    PptSpecRequest,
    PptSpecResponse,
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
    generate_ppt_spec,
)

router = APIRouter()


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


@router.get("/api/v1/analysis/ppt/data/sources", response_model=list[PptDataSourceSummary])
async def get_ppt_data_sources(area_id: str):
    try:
        return list_ppt_sources(area_id)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.get("/api/v1/analysis/ppt/data/source-summary", response_model=PptDataSourceSummary)
async def get_ppt_data_source_summary(area_id: str, source_id: str):
    try:
        return read_ppt_source_summary(area_id, source_id)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/data/query-poi-points", response_model=PptPoiQueryResponse)
async def post_ppt_query_poi_points(payload: PptPoiQueryRequest):
    try:
        return query_poi_points(payload)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/data/nearby-pois", response_model=PptPoiQueryResponse)
async def post_ppt_nearby_pois(payload: PptPoiNearbyRequest):
    try:
        return query_nearby_poi_points(payload)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/data/packages", response_model=PptDataPackageResponse)
async def post_ppt_data_package(payload: PptDataPackageRequest):
    try:
        return await create_ppt_data_package(payload)
    except RuntimeError as exc:
        _raise_ppt_data_error(exc)


@router.post("/api/v1/analysis/ppt/source-groups/classify", response_model=PptSourceGroupClassifyResponse)
async def post_ppt_source_group_classification(payload: PptSourceGroupClassifyRequest) -> PptSourceGroupClassifyResponse:
    try:
        return await classify_ppt_source_groups(payload)
    except PptPlanningLlmUnavailable as exc:
        raise HTTPException(status_code=503, detail="ppt_planning_llm_unavailable") from exc


@router.post("/api/v1/analysis/ppt/spec", response_model=PptSpecResponse)
async def create_ppt_spec(payload: PptSpecRequest) -> PptSpecResponse:
    try:
        return await generate_ppt_spec(payload)
    except PptPlanningLlmUnavailable as exc:
        raise HTTPException(status_code=503, detail="ppt_planning_llm_unavailable") from exc
    except PptPlanningInvalidResponse as exc:
        raise HTTPException(status_code=502, detail="ppt_planning_invalid_ai_response") from exc


@router.post("/api/v1/analysis/ppt/deck-brief", response_model=DeckBriefResponse)
async def create_deck_brief(payload: DeckBriefRequest) -> DeckBriefResponse:
    try:
        return await generate_deck_brief(payload)
    except PptPlanningLlmUnavailable as exc:
        raise HTTPException(status_code=503, detail="ppt_planning_llm_unavailable") from exc
    except PptPlanningInvalidResponse as exc:
        raise HTTPException(status_code=502, detail="ppt_planning_invalid_ai_response") from exc
