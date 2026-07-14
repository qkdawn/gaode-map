from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ArcGISGwrBridgeError(RuntimeError):
    pass


def run_arcgis_gwr_analysis(
    *,
    rows: List[Dict[str, Any]],
    variables: List[Dict[str, str]],
    timeout_sec: int = 240,
) -> Dict[str, Any]:
    if not settings.arcgis_bridge_enabled:
        raise ArcGISGwrBridgeError("ArcGIS bridge is disabled by ARCGIS_BRIDGE_ENABLED")
    token = str(settings.arcgis_bridge_token or "").strip()
    if not token:
        raise ArcGISGwrBridgeError("ARCGIS_BRIDGE_TOKEN is not configured")
    if not rows:
        raise ArcGISGwrBridgeError("GWR row list is empty")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    bridge_timeout = max(int(settings.arcgis_bridge_timeout_s or 300), int(timeout_sec or 240))
    payload: Dict[str, Any] = {
        "rows": rows,
        "dependent_variable": "nightlight_radiance",
        "variables": variables,
        "timeout_sec": int(max(30, int(timeout_sec or 240))),
        "run_id": run_id,
    }
    configured_python_path = str(settings.arcgis_python_path or "").strip()
    if configured_python_path:
        payload["arcgis_python_path"] = configured_python_path

    endpoint = str(settings.arcgis_bridge_base_url or "").rstrip("/") + "/v1/arcgis/gwr/analyze"
    headers = {"X-ArcGIS-Token": token, "Content-Type": "application/json"}
    logger.info("[ArcGISGWRBridge] request %s rows=%d run_id=%s", endpoint, len(rows), run_id)

    try:
        with httpx.Client(timeout=float(bridge_timeout), trust_env=False) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ArcGISGwrBridgeError(f"ArcGIS GWR bridge timeout after {bridge_timeout}s") from exc
    except httpx.RequestError as exc:
        raise ArcGISGwrBridgeError(f"ArcGIS bridge unreachable: {exc}") from exc

    try:
        body = resp.json()
    except Exception:
        body = {}
    if resp.status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        raise ArcGISGwrBridgeError(f"ArcGIS bridge HTTP {resp.status_code}: {detail or resp.text[:300]}")
    if not isinstance(body, dict) or not body.get("ok"):
        raise ArcGISGwrBridgeError(f"ArcGIS bridge failed: {body.get('error') or body.get('status') or 'unknown error'}")
    return body
