from __future__ import annotations

import logging
import secrets
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from core.config import settings

from modules.spatial_strategy import (
    KnowledgeBaseIngestAccepted,
    KnowledgeBaseIngestRequest,
    SpatialStrategyGatewayError,
    SpatialStrategyRunAccepted,
    SpatialStrategyRunDetail,
    SpatialStrategyRunRequest,
    SpatialStrategyProjectContextRequest,
    SpatialStrategyProjectDataRequest,
    SpatialStrategyHarnessUnitRequest,
    SpatialStrategyHarnessVisualRequest,
    SpatialStrategyVisualRequest,
    SpatialStrategyReportFinalizeRequest,
    SpatialStrategyReportDeliveryRequest,
    compose_spatial_strategy_report,
    deliver_spatial_strategy_report,
    finalize_spatial_strategy_report,
    get_project_context_for_run,
    get_project_data_for_step,
    build_spatial_strategy_visuals,
    get_spatial_strategy_run,
    ingest_document_to_knowledge_base,
    normalize_access_groups,
    SpatialStrategyHarnessError,
    analyze_strategy_unit,
    design_strategy_visuals,
    resume_spatial_strategy_run,
    submit_spatial_strategy_run,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/analysis", tags=["spatial-strategy"])


def _tenant_id(raw_value: str) -> str:
    tenant_id = str(raw_value or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="x_tenant_id_required")
    return tenant_id


def _raise_gateway_error(exc: SpatialStrategyGatewayError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _require_n8n_client(raw_value: str) -> None:
    expected = str(settings.n8n_webhook_api_key or "").strip()
    supplied = str(raw_value or "").strip()
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="n8n_client_authentication_failed")
@router.post(
    "/spatial-strategy/runs",
    response_model=SpatialStrategyRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_spatial_strategy_run(
    payload: SpatialStrategyRunRequest,
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-Id")],
    x_access_groups: Annotated[str, Header(alias="X-Access-Groups")] = "",
) -> SpatialStrategyRunAccepted:
    try:
        return await submit_spatial_strategy_run(
            payload,
            tenant_id=_tenant_id(x_tenant_id),
            access_groups=normalize_access_groups(x_access_groups),
        )
    except SpatialStrategyGatewayError as exc:
        _raise_gateway_error(exc)


@router.get("/spatial-strategy/runs/{run_id}", response_model=SpatialStrategyRunDetail)
async def read_spatial_strategy_run(
    run_id: UUID,
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-Id")],
) -> SpatialStrategyRunDetail:
    try:
        return await get_spatial_strategy_run(
            run_id,
            tenant_id=_tenant_id(x_tenant_id),
        )
    except SpatialStrategyGatewayError as exc:
        _raise_gateway_error(exc)



@router.post(
    "/spatial-strategy/runs/{run_id}/resume",
    response_model=SpatialStrategyRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_failed_spatial_strategy_run(
    run_id: UUID,
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-Id")],
) -> SpatialStrategyRunAccepted:
    try:
        return await resume_spatial_strategy_run(
            run_id,
            tenant_id=_tenant_id(x_tenant_id),
        )
    except SpatialStrategyGatewayError as exc:
        _raise_gateway_error(exc)


@router.post("/spatial-strategy/project-data/context")
async def read_spatial_strategy_project_context(
    payload: SpatialStrategyProjectContextRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await run_in_threadpool(get_project_context_for_run, payload.history_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="project_data_source_unavailable") from exc


@router.post("/spatial-strategy/project-data/step")
async def read_spatial_strategy_project_data(
    payload: SpatialStrategyProjectDataRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await run_in_threadpool(
            get_project_data_for_step,
            history_id=payload.history_id,
            step_key=payload.step_key,
            project_context=payload.project_context,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="project_data_source_unavailable") from exc


@router.post("/spatial-strategy/harness/analyze-unit")
async def analyze_spatial_strategy_unit_with_harness(
    payload: SpatialStrategyHarnessUnitRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await run_in_threadpool(
            analyze_strategy_unit,
            run_id=str(payload.run_id),
            history_id=payload.history_id,
            project_question=payload.project_question,
            decision_unit=payload.decision_unit,
        )
    except SpatialStrategyHarnessError as exc:
        logger.warning(
            "Spatial strategy unit failed: run_id=%s unit_id=%s error=%s",
            payload.run_id,
            str(payload.decision_unit.get("unit_id") or ""),
            exc,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/spatial-strategy/harness/design-visuals")
async def design_spatial_strategy_visuals_with_harness(
    payload: SpatialStrategyHarnessVisualRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await run_in_threadpool(
            design_strategy_visuals,
            run_id=str(payload.run_id),
            project_question=payload.project_question,
            visual_task=payload.visual_task,
        )
    except SpatialStrategyHarnessError as exc:
        logger.warning(
            "Spatial strategy visual design failed: run_id=%s error=%s",
            payload.run_id,
            exc,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/spatial-strategy/visuals")
async def create_spatial_strategy_visuals(
    payload: SpatialStrategyVisualRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await run_in_threadpool(
            build_spatial_strategy_visuals,
            run_id=str(payload.run_id),
            history_id=payload.history_id,
            project_context=payload.project_context,
            visual_plan=payload.visual_plan,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="project_visual_source_unavailable") from exc


@router.post("/spatial-strategy/reports/compose")
async def compose_spatial_strategy_run_report(
    payload: SpatialStrategyReportFinalizeRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await compose_spatial_strategy_report(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/spatial-strategy/reports/deliver")
async def deliver_spatial_strategy_run_report(
    payload: SpatialStrategyReportDeliveryRequest,
    x_n8n_client_key: Annotated[str, Header(alias="X-N8N-Client-Key")],
) -> dict:
    _require_n8n_client(x_n8n_client_key)
    try:
        return await deliver_spatial_strategy_report(payload)
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/knowledge-base/documents",
    response_model=KnowledgeBaseIngestAccepted,
)
async def publish_document_to_knowledge_base(
    payload: KnowledgeBaseIngestRequest,
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-Id")],
    x_access_groups: Annotated[str, Header(alias="X-Access-Groups")] = "",
) -> KnowledgeBaseIngestAccepted:
    try:
        tenant_id = _tenant_id(x_tenant_id)
        return await ingest_document_to_knowledge_base(
            payload,
            tenant_id=tenant_id,
            access_groups=normalize_access_groups(x_access_groups),
        )
    except SpatialStrategyGatewayError as exc:
        _raise_gateway_error(exc)
