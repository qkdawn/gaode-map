from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from modules.spatial_cells.schemas import SharedGridRequest, SharedGridResponse
from modules.spatial_cells.service import build_shared_grid_analysis

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/v1/analysis/shared-grid", response_model=SharedGridResponse)
async def build_shared_grid(payload: SharedGridRequest):
    try:
        return build_shared_grid_analysis(
            polygon=payload.polygon,
            coord_type=payload.coord_type,
            population_year=payload.population_year,
            nightlight_year=payload.nightlight_year,
            pois=payload.pois,
            poi_coord_type=payload.poi_coord_type,
            poi_year=payload.poi_year,
            poi_ready=payload.poi_ready,
            road_features=payload.road_features,
            road_ready=payload.road_ready,
            categories=payload.categories,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("shared grid aggregation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
