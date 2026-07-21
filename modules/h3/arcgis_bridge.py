import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ArcGISBridgeError(RuntimeError):
    pass


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _extract_outer_ring(feature: Dict[str, Any]) -> List[List[float]]:
    geometry = (feature or {}).get("geometry") or {}
    if str(geometry.get("type") or "") != "Polygon":
        return []
    coordinates = geometry.get("coordinates") or []
    if not coordinates:
        return []
    ring: List[List[float]] = []
    for point in coordinates[0] or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        longitude = _safe_float(point[0])
        latitude = _safe_float(point[1])
        if longitude is not None and latitude is not None:
            ring.append([longitude, latitude])
    return ring


def _build_rows(features: List[Dict[str, Any]], stats_by_cell: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for feature in features:
        props = (feature or {}).get("properties") or {}
        h3_id = str(props.get("h3_id") or "")
        if not h3_id:
            continue
        ring = _extract_outer_ring(feature)
        if len(ring) < 3:
            continue
        density = _safe_float((stats_by_cell.get(h3_id) or {}).get("density_poi_per_km2"))
        rows.append({
            "h3_id": h3_id,
            "value": density or 0.0,
            "ring": ring,
        })
    return rows


def run_arcgis_h3_analysis(
    features: List[Dict[str, Any]],
    stats_by_cell: Dict[str, Dict[str, Any]],
    knn_neighbors: int = 8,
    timeout_sec: int = 240,
) -> Dict[str, Any]:
    if not settings.arcgis_bridge_enabled:
        raise ArcGISBridgeError("ArcGIS bridge is disabled by ARCGIS_BRIDGE_ENABLED")

    if not features:
        raise ArcGISBridgeError("Grid is empty, cannot run ArcGIS bridge")

    token = str(settings.arcgis_bridge_token or "").strip()
    if not token:
        raise ArcGISBridgeError("ARCGIS_BRIDGE_TOKEN is not configured")

    rows = _build_rows(features, stats_by_cell)
    if not rows:
        raise ArcGISBridgeError("No valid H3 rows to submit ArcGIS bridge")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    bridge_timeout = max(int(settings.arcgis_bridge_timeout_s or 300), int(timeout_sec or 240))
    payload: Dict[str, Any] = {
        "rows": rows,
        "knn_neighbors": int(max(1, min(64, int(knn_neighbors)))),
        "timeout_sec": int(max(30, int(timeout_sec))),
        "run_id": run_id,
    }
    configured_python_path = str(settings.arcgis_python_path or "").strip()
    if configured_python_path:
        payload["arcgis_python_path"] = configured_python_path

    endpoint = str(settings.arcgis_bridge_base_url or "").rstrip("/") + "/v1/arcgis/h3/analyze"
    headers = {
        "X-ArcGIS-Token": token,
        "Content-Type": "application/json",
    }

    logger.info("[ArcGISBridge] request %s rows=%d run_id=%s", endpoint, len(rows), run_id)

    try:
        with httpx.Client(timeout=float(bridge_timeout), trust_env=False) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ArcGISBridgeError(f"ArcGIS bridge timeout after {bridge_timeout}s") from exc
    except httpx.RequestError as exc:
        raise ArcGISBridgeError(f"ArcGIS bridge unreachable: {exc}") from exc

    try:
        body = resp.json()
    except Exception:
        body = {}

    if resp.status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        raise ArcGISBridgeError(f"ArcGIS bridge HTTP {resp.status_code}: {detail or resp.text[:300]}")

    if not isinstance(body, dict) or not body.get("ok"):
        err = body.get("error") if isinstance(body, dict) else None
        status = body.get("status") if isinstance(body, dict) else None
        raise ArcGISBridgeError(f"ArcGIS bridge failed: {err or status or 'unknown error'}")

    cells = body.get("cells") or []
    global_moran = body.get("global_moran") or {}
    trace_id = str(body.get("trace_id") or "")
    status_text = str(body.get("status") or "ok")

    cell_map: Dict[str, Dict[str, Any]] = {}
    for item in cells:
        h3_id = str((item or {}).get("h3_id") or "")
        if h3_id:
            cell_map[h3_id] = item

    if trace_id:
        status_text = f"{status_text} (trace_id={trace_id})"

    return {
        "cells": cells,
        "global_moran": global_moran,
        "status": status_text,
    }


def _parse_content_disposition_filename(content_disposition: str) -> Optional[str]:
    text = str(content_disposition or "").strip()
    if not text:
        return None
    # RFC 5987 format
    if "filename*=" in text:
        part = text.split("filename*=", 1)[1].split(";", 1)[0].strip().strip('"')
        if "''" in part:
            _, encoded = part.split("''", 1)
            return unquote(encoded)
        return unquote(part)
    if "filename=" in text:
        part = text.split("filename=", 1)[1].split(";", 1)[0].strip().strip('"')
        return part or None
    return None


def run_arcgis_h3_export(
    export_format: str,
    include_poi: bool,
    style_mode: str,
    grid_features: List[Dict[str, Any]],
    poi_features: Optional[List[Dict[str, Any]]] = None,
    style_meta: Optional[Dict[str, Any]] = None,
    timeout_sec: int = 300,
) -> Dict[str, Any]:
    if not settings.arcgis_bridge_enabled:
        raise ArcGISBridgeError("ArcGIS bridge is disabled by ARCGIS_BRIDGE_ENABLED")

    token = str(settings.arcgis_bridge_token or "").strip()
    if not token:
        raise ArcGISBridgeError("ARCGIS_BRIDGE_TOKEN is not configured")

    normalized_format = "arcgis_package" if str(export_format or "") == "arcgis_package" else "gpkg"
    normalized_style_mode = str(style_mode or "density").strip().lower()
    if normalized_style_mode not in {"density", "gi_z", "lisa_i"}:
        normalized_style_mode = "density"

    feature_list = list(grid_features or [])
    if not feature_list:
        raise ArcGISBridgeError("Grid feature list is empty, cannot export")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    bridge_timeout = max(
        int(settings.arcgis_bridge_timeout_s or 300),
        int(getattr(settings, "arcgis_export_timeout_s", 600) or 600),
        int(timeout_sec or 300),
    )
    payload: Dict[str, Any] = {
        "format": normalized_format,
        "include_poi": bool(include_poi),
        "style_mode": normalized_style_mode,
        "grid_features": feature_list,
        "poi_features": list(poi_features or []),
        "style_meta": dict(style_meta or {}),
        "timeout_sec": int(max(30, int(timeout_sec or 300))),
        "run_id": run_id,
    }
    configured_python_path = str(settings.arcgis_python_path or "").strip()
    if configured_python_path:
        payload["arcgis_python_path"] = configured_python_path

    endpoint = str(settings.arcgis_bridge_base_url or "").rstrip("/") + "/v1/arcgis/h3/export"
    headers = {
        "X-ArcGIS-Token": token,
        "Content-Type": "application/json",
    }

    logger.info(
        "[ArcGISBridge] export request %s format=%s grids=%d poi=%d run_id=%s",
        endpoint,
        normalized_format,
        len(feature_list),
        len(payload["poi_features"]),
        run_id,
    )

    try:
        with httpx.Client(timeout=float(bridge_timeout), trust_env=False) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ArcGISBridgeError(f"ArcGIS export timeout after {bridge_timeout}s") from exc
    except httpx.RequestError as exc:
        raise ArcGISBridgeError(f"ArcGIS bridge unreachable: {exc}") from exc

    if resp.status_code != 200:
        detail = ""
        try:
            parsed = resp.json()
            if isinstance(parsed, dict):
                detail = str(parsed.get("detail") or parsed.get("error") or "")
            else:
                detail = str(parsed)
        except Exception:
            detail = str(resp.text or "")
        raise ArcGISBridgeError(f"ArcGIS bridge HTTP {resp.status_code}: {detail[:500]}")

    content = resp.content or b""
    if not content:
        raise ArcGISBridgeError("ArcGIS export returned empty file content")

    max_mb = max(16, int(getattr(settings, "arcgis_export_max_mb", 512) or 512))
    max_bytes = max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ArcGISBridgeError(f"ArcGIS export file is too large ({len(content)} bytes > {max_bytes} bytes)")

    content_type = str(resp.headers.get("content-type") or "application/octet-stream").strip()
    filename = _parse_content_disposition_filename(resp.headers.get("content-disposition"))
    if not filename:
        suffix = ".zip" if normalized_format == "arcgis_package" else ".gpkg"
        filename = f"h3_analysis_{run_id}{suffix}"

    return {
        "filename": filename,
        "content_type": content_type,
        "content": content,
    }
