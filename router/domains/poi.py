from __future__ import annotations

import logging
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.spatial import transform_polygon_payload_coords
from modules.poi import service as poi_service
from modules.poi.aggregation import build_poi_shared_grid
from modules.poi.schemas import PoiGridRequest, PoiGridResponse, PoiMultiYearRequest, PoiMultiYearResponse, PoiRequest, PoiResponse
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
from store.history_repo import history_repo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/v1/analysis/pois", response_model=PoiResponse)
async def fetch_pois_analysis(payload: PoiRequest):
    source = (payload.source or "local").strip().lower()
    try:
        results, diagnostics = await poi_service.fetch_single_year_pois_with_diagnostics(payload)
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

    return {"pois": results, "count": len(results), "diagnostics": diagnostics}


@router.post("/api/v1/analysis/pois/multi-year", response_model=PoiMultiYearResponse)
async def fetch_multi_year_pois_analysis(payload: PoiMultiYearRequest):
    try:
        result = await poi_service.fetch_multi_year_pois(payload)
    except Exception as exc:
        logger.exception("Multi-year POI fetch failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.post("/api/v1/analysis/pois/multi-year/stream")
async def stream_multi_year_pois_analysis(payload: PoiMultiYearRequest):
    async def event_stream():
        try:
            async for event in poi_service.stream_fetch_multi_year_pois(payload):
                event_type = str(event.get("type") or "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Multi-year POI stream failed")
            error_payload = {"type": "error", "message": str(exc)}
            yield f"event: error\ndata: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/v1/analysis/pois/grid", response_model=PoiGridResponse)
async def build_poi_grid_analysis(payload: PoiGridRequest):
    try:
        return build_poi_shared_grid(
            polygon=payload.polygon,
            coord_type=payload.coord_type,
            pois=payload.pois,
            poi_coord_type=payload.poi_coord_type,
            categories=payload.categories,
            year=payload.year,
        )
    except Exception as exc:
        logger.exception("POI shared grid aggregation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
