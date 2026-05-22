from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from modules.history import service as history_service
from modules.poi.schemas import HistorySaveRequest
from store.history_repo import history_repo

router = APIRouter()


@router.post("/api/v1/analysis/history/save")
async def save_history_manually(payload: HistorySaveRequest):
    return history_service.save_history_request(payload, history_repo)


@router.get("/api/v1/analysis/history")
async def get_history_list(limit: int = Query(100, ge=0, le=500)):
    return await run_in_threadpool(history_service.get_history_list_payload, limit, history_repo)


@router.get("/api/v1/analysis/history/{id}/pois")
async def get_history_pois(id: str, year: int | None = None):
    return history_service.get_history_pois_payload(id, history_repo, year=year)


@router.get("/api/v1/analysis/history/{id}")
async def get_history_detail(id: str, include_pois: bool = Query(True), year: int | None = None):
    return history_service.get_history_detail_payload_for_year(id, include_pois, year, history_repo)


@router.delete("/api/v1/analysis/history/{id}")
async def delete_history(id: str):
    return history_service.delete_history_record(id, history_repo)
