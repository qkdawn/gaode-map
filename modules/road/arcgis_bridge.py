import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ArcGISRoadSyntaxBridgeError(RuntimeError):
    pass


def _normalize_metric_field(metric_field: Optional[str]) -> str:
    field = str(metric_field or "").strip()
    if not field:
        return "accessibility_score"
    return field


def _normalize_coord_type(coord_type: Optional[str]) -> str:
    text = str(coord_type or "").strip().lower()
    if text not in {"gcj02", "wgs84"}:
        return "gcj02"
    return text


def _normalize_feature_collection(value: Any) -> Dict[str, Any]:
    fc = value if isinstance(value, dict) else {}
    features = fc.get("features") if isinstance(fc.get("features"), list) else []
    count = int(fc.get("count")) if isinstance(fc.get("count"), int) else len(features)
    return {
        "type": "FeatureCollection",
        "features": features,
        "count": max(0, count),
    }


def run_arcgis_road_syntax_webgl(
    road_features: List[Dict[str, Any]],
    metric_field: Optional[str] = None,
    target_coord_type: Optional[str] = "gcj02",
    timeout_sec: int = 300,
) -> Dict[str, Any]:
    if not settings.arcgis_bridge_enabled:
        raise ArcGISRoadSyntaxBridgeError("ArcGIS bridge is disabled by ARCGIS_BRIDGE_ENABLED")

    token = str(settings.arcgis_bridge_token or "").strip()
    if not token:
        raise ArcGISRoadSyntaxBridgeError("ARCGIS_BRIDGE_TOKEN is not configured")

    feature_list = list(road_features or [])
    if not feature_list:
        raise ArcGISRoadSyntaxBridgeError("Road feature list is empty, cannot run ArcGIS road-syntax bridge")

    normalized_metric_field = _normalize_metric_field(metric_field)
    normalized_coord_type = _normalize_coord_type(target_coord_type)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    bridge_timeout = int(max(5, int(timeout_sec or settings.arcgis_bridge_timeout_s or 300)))

    payload: Dict[str, Any] = {
        "roads_features": feature_list,
        "metric_field": normalized_metric_field,
        "target_coord_type": normalized_coord_type,
        "timeout_sec": int(max(5, int(timeout_sec or 300))),
        "run_id": run_id,
    }
    configured_python_path = str(settings.arcgis_python_path or "").strip()
    if configured_python_path:
        payload["arcgis_python_path"] = configured_python_path

    endpoint = str(settings.arcgis_bridge_base_url or "").rstrip("/") + "/v1/arcgis/road-syntax/webgl"
    headers = {
        "X-ArcGIS-Token": token,
        "Content-Type": "application/json",
    }

    logger.info(
        "[ArcGISRoadSyntaxBridge] request %s features=%d metric=%s run_id=%s",
        endpoint,
        len(feature_list),
        normalized_metric_field,
        run_id,
    )

    try:
        with httpx.Client(timeout=float(bridge_timeout), trust_env=False) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ArcGISRoadSyntaxBridgeError(f"ArcGIS road-syntax bridge timeout after {bridge_timeout}s") from exc
    except httpx.RequestError as exc:
        raise ArcGISRoadSyntaxBridgeError(f"ArcGIS bridge unreachable: {exc}") from exc

    try:
        body = resp.json()
    except Exception:
        body = {}

    if resp.status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        raise ArcGISRoadSyntaxBridgeError(f"ArcGIS bridge HTTP {resp.status_code}: {detail or resp.text[:300]}")

    if not isinstance(body, dict) or not body.get("ok"):
        err = body.get("error") if isinstance(body, dict) else None
        status = body.get("status") if isinstance(body, dict) else None
        raise ArcGISRoadSyntaxBridgeError(f"ArcGIS bridge failed: {err or status or 'unknown error'}")

    roads_fc = _normalize_feature_collection(body.get("roads"))
    return {
        "status": str(body.get("status") or "ok"),
        "metric_field": str(body.get("metric_field") or normalized_metric_field),
        "coord_type": str(body.get("coord_type") or normalized_coord_type),
        "elapsed_ms": float(body.get("elapsed_ms") or 0.0),
        "roads": roads_fc,
    }
