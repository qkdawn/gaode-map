from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from core.spatial import transform_polygon_payload_coords
from modules.poi import service as poi_service
from modules.poi.schemas import PoiMultiYearRequest, PoiMultiYearResponse, PoiRequest, PoiResponse
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
from store.history_repo import history_repo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/v1/analysis/pois", response_model=PoiResponse)
async def fetch_pois_analysis(payload: PoiRequest):
    source = (payload.source or "local").strip().lower()
    try:
        results = await poi_service.fetch_single_year_pois(payload)
    except Exception as exc:
        logger.exception("POI fetch failed: source=%s", source)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.save_history:
        s_center = payload.center
        if s_center:
            wx, wy = gcj02_to_wgs84(s_center[0], s_center[1])
            s_center = [wx, wy]

        s_poly = []
        if payload.polygon:
            s_poly = transform_polygon_payload_coords(payload.polygon, gcj02_to_wgs84)

        s_pois = []
        for p in results:
            np = p.copy()
            if np.get("location"):
                lx, ly = np["location"]
                nwx, nwy = gcj02_to_wgs84(lx, ly)
                np["location"] = [nwx, nwy]
            s_pois.append(np)

        desc = f"{payload.keywords} - {len(results)} POIs"
        if payload.time_min:
            desc = f"{payload.time_min}min - {desc}"

        history_repo.create_record(
            {
                "center": s_center,
                "time_min": payload.time_min,
                "keywords": payload.keywords,
                "mode": payload.mode,
                "source": source,
                "year": payload.year,
                "years": [int(payload.year)] if payload.year is not None else [],
            },
            s_poly,
            s_pois,
            desc,
            poi_results_by_year=[{"source": source, "year": payload.year, "pois": s_pois}],
        )

    return {"pois": results, "count": len(results)}


@router.post("/api/v1/analysis/pois/multi-year", response_model=PoiMultiYearResponse)
async def fetch_multi_year_pois_analysis(payload: PoiMultiYearRequest):
    try:
        result = await poi_service.fetch_multi_year_pois(payload)
    except Exception as exc:
        logger.exception("Multi-year POI fetch failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result
