from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from core.config import settings
from .schemas import (
    KnowledgeBaseIngestAccepted,
    KnowledgeBaseIngestRequest,
    SpatialStrategyRunAccepted,
    SpatialStrategyRunDetail,
    SpatialStrategyRunRequest,
)
from .project_data import read_project_context, read_step_project_data
from .reader_result import project_run_accepted, project_run_detail


class SpatialStrategyGatewayError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 503) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def normalize_access_groups(raw_value: str) -> list[str]:
    return list(
        dict.fromkeys(
            item.strip()
            for item in str(raw_value or "").split(",")
            if item.strip()
        )
    )


def _gateway_config() -> tuple[str, dict[str, str], float]:
    base_url = settings.n8n_webhook_base_url
    api_key = str(settings.n8n_webhook_api_key or "").strip()
    if not base_url or not api_key:
        raise SpatialStrategyGatewayError("n8n_spatial_strategy_not_configured")
    return (
        base_url,
        {"X-N8N-Client-Key": api_key},
        float(settings.n8n_webhook_timeout_s),
    )


async def _request_n8n(
    method: str,
    path: str,
    *,
    tenant_id: str,
    access_groups: list[str] | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    base_url, headers, timeout_s = _gateway_config()
    headers["X-Tenant-Id"] = tenant_id
    if access_groups:
        headers["X-Access-Groups"] = ",".join(access_groups)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s), trust_env=False
        ) as client:
            response = await client.request(
                method,
                f"{base_url}/{path.lstrip('/')}",
                headers=headers,
                json=json,
                params=params,
            )
    except httpx.TimeoutException as exc:
        raise SpatialStrategyGatewayError(
            "n8n_spatial_strategy_timeout", status_code=504
        ) from exc
    except httpx.RequestError as exc:
        raise SpatialStrategyGatewayError(
            "n8n_spatial_strategy_unavailable", status_code=503
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise SpatialStrategyGatewayError(
            "n8n_spatial_strategy_invalid_response", status_code=502
        ) from exc

    if response.status_code == 404:
        raise SpatialStrategyGatewayError(
            str(payload.get("detail") or "analysis_run_not_found"), status_code=404
        )
    if response.status_code >= 400:
        detail = payload.get("detail") or payload.get("message") or "n8n_spatial_strategy_rejected"
        raise SpatialStrategyGatewayError(str(detail), status_code=502)
    if not isinstance(payload, dict):
        raise SpatialStrategyGatewayError(
            "n8n_spatial_strategy_invalid_response", status_code=502
        )
    return payload


async def submit_spatial_strategy_run(
    request: SpatialStrategyRunRequest,
    *,
    tenant_id: str,
    access_groups: list[str],
) -> SpatialStrategyRunAccepted:
    payload = request.model_dump(mode="json")
    response = await _request_n8n(
        "POST",
        "api/v1/n8n/spatial-strategy",
        tenant_id=tenant_id,
        access_groups=access_groups,
        json=payload,
    )
    return project_run_accepted(response)


async def resume_spatial_strategy_run(
    run_id: UUID,
    *,
    tenant_id: str,
) -> SpatialStrategyRunAccepted:
    response = await _request_n8n(
        "POST",
        "api/v1/n8n/spatial-strategy",
        tenant_id=tenant_id,
        json={"resume_run_id": str(run_id)},
    )
    return project_run_accepted(response)


async def get_spatial_strategy_run(
    run_id: UUID,
    *,
    tenant_id: str,
) -> SpatialStrategyRunDetail:
    response = await _request_n8n(
        "GET",
        "api/v1/n8n/spatial-strategy/status",
        tenant_id=tenant_id,
        params={"run_id": str(run_id)},
    )
    return project_run_detail(response)


def get_project_context_for_run(history_id: str = "") -> dict[str, Any]:
    return read_project_context(history_id)


def get_project_data_for_step(
    *,
    history_id: str = "",
    step_key: str,
    project_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return read_step_project_data(
        history_id=history_id,
        step_key=step_key,
        project_context=project_context,
    )


async def ingest_document_to_knowledge_base(
    request: KnowledgeBaseIngestRequest,
    *,
    tenant_id: str,
    access_groups: list[str],
) -> KnowledgeBaseIngestAccepted:
    payload = request.model_dump(mode="json")
    response = await _request_n8n(
        "POST",
        "api/v1/n8n/kb/ingest",
        tenant_id=tenant_id,
        access_groups=access_groups,
        json=payload,
    )
    return KnowledgeBaseIngestAccepted.model_validate(response)
