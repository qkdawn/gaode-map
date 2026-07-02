from fastapi import APIRouter

from modules.h3.arcgis_bridge import run_arcgis_h3_export
from modules.isochrone.core import get_isochrone_polygon
from modules.isochrone.service import (
    _build_scope_sample_points,
    build_debug_isochrone_samples as _build_debug_isochrone_samples,
)
from modules.road.core import analyze_road_syntax
from router.domains import (
    agent_router,
    charting_router,
    documents_router,
    evidence_retrieval_router,
    export_router,
    gwr_router,
    h3_router,
    history_router,
    isochrone_router,
    jobs_router,
    map_router,
    nightlight_router,
    poi_router,
    population_router,
    ppt_planning_router,
    ppt_web_source_router,
    road_router,
    system_router,
    timeseries_router,
    tools_router,
)

router = APIRouter()
router.include_router(system_router)
router.include_router(agent_router)
router.include_router(charting_router)
router.include_router(documents_router)
router.include_router(evidence_retrieval_router)
router.include_router(jobs_router)
router.include_router(map_router)
router.include_router(poi_router)
router.include_router(population_router)
router.include_router(ppt_planning_router)
router.include_router(ppt_web_source_router)
router.include_router(nightlight_router)
router.include_router(timeseries_router)
router.include_router(tools_router)
router.include_router(export_router)
router.include_router(gwr_router)
router.include_router(history_router)
router.include_router(h3_router)
router.include_router(road_router)
router.include_router(isochrone_router)


async def debug_isochrone_samples(payload):
    import modules.isochrone.service as isochrone_service

    original_builder = isochrone_service._build_scope_sample_points
    original_get_isochrone_polygon = isochrone_service.get_isochrone_polygon
    try:
        isochrone_service._build_scope_sample_points = _build_scope_sample_points
        isochrone_service.get_isochrone_polygon = get_isochrone_polygon
        return await _build_debug_isochrone_samples(payload)
    finally:
        isochrone_service._build_scope_sample_points = original_builder
        isochrone_service.get_isochrone_polygon = original_get_isochrone_polygon
