from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from modules.spatial_projects.service import SpatialProjectService

router = APIRouter(prefix="/api/v1/spatial-projects", tags=["spatial-projects"])
service = SpatialProjectService()


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    scope: dict[str, Any] = Field(default_factory=dict)
    brief: dict[str, Any] = Field(default_factory=dict)


class SnapshotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: str = Field(min_length=1, max_length=96)


class UnitImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_collection: dict[str, Any]


def _translate_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 422, detail=str(exc))


@router.get("")
async def list_spatial_projects():
    return await run_in_threadpool(service.list_projects)


@router.post("")
async def create_spatial_project(payload: ProjectCreateRequest):
    try:
        return await run_in_threadpool(service.create_project, name=payload.name, scope=payload.scope, brief=payload.brief)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{project_id}/snapshots")
async def create_project_snapshot(project_id: str, payload: SnapshotCreateRequest):
    try:
        return await run_in_threadpool(service.build_snapshot, project_id=project_id, history_id=payload.history_id)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc


@router.get("/{project_id}/snapshots/{snapshot_id}")
async def read_project_snapshot(project_id: str, snapshot_id: str):
    try:
        return await run_in_threadpool(service.read_snapshot, project_id, snapshot_id)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc


@router.get("/{project_id}/snapshots/{snapshot_id}/datasets")
async def list_project_datasets(project_id: str, snapshot_id: str):
    try:
        return await run_in_threadpool(service.list_datasets, project_id, snapshot_id)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc


@router.get("/{project_id}/snapshots/{snapshot_id}/datasets/{source_id:path}")
async def query_project_dataset(project_id: str, snapshot_id: str, source_id: str, limit: int = 20, offset: int = 0):
    try:
        return await run_in_threadpool(service.query_dataset, project_id=project_id, snapshot_id=snapshot_id, source_id=source_id, limit=limit, offset=offset)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{project_id}/snapshots/{snapshot_id}/spatial-units")
async def import_project_units(project_id: str, snapshot_id: str, payload: UnitImportRequest):
    try:
        return await run_in_threadpool(service.import_units, project_id=project_id, snapshot_id=snapshot_id, feature_collection=payload.feature_collection)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc


@router.get("/{project_id}/snapshots/{snapshot_id}/spatial-units")
async def list_project_units(project_id: str, snapshot_id: str, status: str = "", limit: int = 50, offset: int = 0):
    try:
        return await run_in_threadpool(service.list_units, project_id=project_id, snapshot_id=snapshot_id, status=status, limit=limit, offset=offset)
    except (ValueError, LookupError) as exc:
        raise _translate_error(exc) from exc
