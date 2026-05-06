from __future__ import annotations

import asyncio
import json
import logging
from io import BytesIO
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Security
from fastapi.responses import StreamingResponse

from core.config import settings
from modules import generate_map_json
from modules.map_manage.schemas import (
    MapRequest,
    PolygonCreateRequest,
    PolygonListResponse,
    PolygonRecord,
)
from modules.providers.amap.schemas import MapGenerateRequest, MapResponse
from router.utils.deps import load_map_request, verify_api_key
from store import (
    delete_polygon,
    find_map_by_center_and_type,
    get_map_data,
    list_polygons_for_map,
    save_map_data,
    save_polygon,
)
from utils import export_map_to_xlsx

router = APIRouter()
logger = logging.getLogger(__name__)


def _default_poi_year(source: str) -> int:
    return 2020 if source == "local" else 2026


@router.post("/api/v1/generate-map", response_model=MapResponse, summary="生成地图数据")
async def generate_map(
    request: MapGenerateRequest,
    api_key_valid: bool = Security(verify_api_key),
):
    try:
        logger.info("Generating map for: %s", request.place)

        def pre_points_hook(center, search_type, place_types=None):
            normalized_pt = tuple(sorted({item for item in (place_types or []) if item}))
            src = request.source or "gaode"
            y = request.year or _default_poi_year(src)
            existing = find_map_by_center_and_type(center, search_type, normalized_pt, src, y)
            if existing:
                return existing[0], existing[1]
            return None

        src = request.source or "gaode"
        y = request.year or _default_poi_year(src)

        map_payload, cached_id = generate_map_json(
            place=request.place,
            search_type=request.type,
            place_types=request.place_types,
            radius=request.radius,
            year=y,
            source=src,
            auth_header=None,
            pre_points_hook=pre_points_hook,
        )

        map_req = MapRequest(**map_payload["body"])

        if cached_id is None:
            cached_id = await asyncio.to_thread(
                save_map_data,
                map_req.model_dump(),
                map_req.center,
                request.type,
                tuple(sorted({i for i in (request.place_types or []) if i})),
                src,
                y,
            )

        base = settings.app_base_url.rstrip("/")
        loc = f"{map_req.center['lng']},{map_req.center['lat']}"
        params = {"type": request.type, "location": loc}
        if src != "gaode":
            params["source"] = src
        if request.year:
            params["year"] = str(request.year)
        if request.place_types:
            params["place_types"] = json.dumps(request.place_types, ensure_ascii=False)

        url = f"{base}/map?{urlencode(params)}"
        return MapResponse(status=200, message="Success", url=url)
    except Exception as e:
        logger.error("Map generation failed: %s", e, exc_info=True)
        return MapResponse(status=500, message=f"Failed: {str(e)}")


@router.get("/api/v1/maps/{map_id}/export/xlsx")
async def export_map_xlsx(map_id: int):
    map_req = await load_map_request(map_id)
    fname, content = export_map_to_xlsx(map_req, map_id)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/v1/maps/{map_id}/polygons", response_model=PolygonListResponse)
async def list_map_polygons(map_id: int):
    map_data = await asyncio.to_thread(get_map_data, map_id)
    if not map_data:
        raise HTTPException(404, "Map not found")
    polygons = await asyncio.to_thread(list_polygons_for_map, map_id)
    return {"polygons": polygons}


@router.post("/api/v1/maps/{map_id}/polygons", response_model=PolygonRecord)
async def create_map_polygon(map_id: int, payload: PolygonCreateRequest):
    map_data = await asyncio.to_thread(get_map_data, map_id)
    if not map_data:
        raise HTTPException(404, "Map not found")
    pid = await asyncio.to_thread(save_polygon, map_id, payload.coordinates)
    return {"id": pid, "coordinates": payload.coordinates}


@router.delete("/api/v1/maps/{map_id}/polygons/{polygon_id}")
async def delete_map_polygon(map_id: int, polygon_id: int):
    success = await asyncio.to_thread(delete_polygon, map_id, polygon_id)
    if not success:
        raise HTTPException(404, "Polygon not found")
    return {"status": "ok"}
