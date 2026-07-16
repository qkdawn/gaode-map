from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from modules.spatial_action import (
    EntranceRelationAnalysisRequest,
    EntranceRelationResult,
    LocalPatternAnalysisRequest,
    LocalizedPatternResult,
    PathRelationAnalysisRequest,
    PathRelationResult,
    SpatialActionService,
    ValhallaRouteBlocked,
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


@router.post(
    "/api/v1/analysis/spatial-actions/entrances",
    response_model=list[EntranceRelationResult],
)
async def analyze_entrance_relations(payload: EntranceRelationAnalysisRequest):
    try:
        return await asyncio.to_thread(
            _service.analyze_entrance_relations,
            entrances=payload.entrances,
            road_segments=payload.road_segments,
            project_boundary=payload.project_boundary,
            hotspot_zones=payload.hotspot_zones,
            catchments=payload.catchments,
            demand_features=payload.demand_features,
            directional_exposure=payload.directional_exposure,
            target_road_segment_ids=payload.target_road_segment_ids,
            nearby_radius_m=payload.nearby_radius_m,
            dedupe_tolerance_m=payload.dedupe_tolerance_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/api/v1/analysis/spatial-actions/paths",
    response_model=list[PathRelationResult],
)
async def analyze_path_relations(payload: PathRelationAnalysisRequest):
    try:
        return await asyncio.to_thread(
            _service.analyze_path_relations,
            entrances=payload.entrances,
            destinations=payload.destinations,
            pairs=[(item.entrance_id, item.destination_id) for item in payload.pairs],
            road_segments=payload.road_segments,
            match_tolerance_m=payload.match_tolerance_m,
        )
    except ValhallaRouteBlocked as exc:
        raise HTTPException(
            status_code=502,
            detail={"status": "blocked", "reason": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
