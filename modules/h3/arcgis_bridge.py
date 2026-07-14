import json
import logging
import math
import uuid
import base64
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ArcGISBridgeError(RuntimeError):
    pass


def _cleanup_old_arcgis_previews(output_root: Path, ttl_hours: int) -> None:
    """Best-effort cleanup for stale ArcGIS preview snapshots."""
    try:
        keep_seconds = max(1, int(ttl_hours)) * 3600
    except Exception:
        keep_seconds = 168 * 3600
    now_ts = datetime.now().timestamp()
    if not output_root.exists() or not output_root.is_dir():
        return

    for path in output_root.glob("arcgis_h3_preview_*.svg"):
        try:
            age_seconds = now_ts - float(path.stat().st_mtime)
            if age_seconds >= keep_seconds:
                path.unlink(missing_ok=True)
        except Exception:
            continue


def _svg_to_data_uri(svg_text: str) -> str:
    # In-memory snapshot, no disk persistence.
    # Use base64 to avoid malformed URI caused by unescaped '%' in raw SVG (e.g. "100%").
    raw = str(svg_text or "").encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:
            return None
        return f
    except Exception:
        return None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _quantile(sorted_values: List[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    ratio = _clamp(float(q), 0.0, 1.0)
    pos = ratio * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    lv = float(sorted_values[lo])
    hv = float(sorted_values[hi])
    frac = pos - lo
    return lv + (hv - lv) * frac


def _mix_hex_color(from_hex: str, to_hex: str, ratio: float) -> str:
    r = _clamp(float(ratio), 0.0, 1.0)
    f = str(from_hex or "#000000").lstrip("#")
    t = str(to_hex or "#000000").lstrip("#")
    if len(f) != 6 or len(t) != 6:
        return from_hex or "#000000"
    try:
        fr, fg, fb = int(f[0:2], 16), int(f[2:4], 16), int(f[4:6], 16)
        tr, tg, tb = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    except Exception:
        return from_hex or "#000000"
    rr = round(fr + (tr - fr) * r)
    rg = round(fg + (tg - fg) * r)
    rb = round(fb + (tb - fb) * r)
    return f"#{rr:02x}{rg:02x}{rb:02x}"


def _extract_outer_ring(feature: Dict[str, Any]) -> List[List[float]]:
    geometry = (feature or {}).get("geometry") or {}
    if str(geometry.get("type") or "") != "Polygon":
        return []
    coordinates = geometry.get("coordinates") or []
    if not coordinates:
        return []
    ring = coordinates[0] or []
    result: List[List[float]] = []
    for pt in ring:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            result.append([float(pt[0]), float(pt[1])])
        except Exception:
            continue
    return result


def _resolve_lisa_render_meta(cell_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    values: List[float] = []
    for item in (cell_map or {}).values():
        v = _safe_float((item or {}).get("lisa_i"))
        if v is None:
            continue
        values.append(float(v))
    if not values:
        return {
            "mean": 0.0,
            "std": 0.0,
            "clip_min": 0.0,
            "clip_max": 0.0,
            "degraded": True,
        }
    sorted_values = sorted(values)
    n = float(len(sorted_values))
    mean = sum(values) / n
    variance = sum((v - mean) * (v - mean) for v in values) / n
    std = variance ** 0.5
    min_v = sorted_values[0]
    max_v = sorted_values[-1]
    p10 = _quantile(sorted_values, 0.10)
    p90 = _quantile(sorted_values, 0.90)
    degraded = std <= 1e-12
    if degraded:
        return {
            "mean": mean,
            "std": std,
            "clip_min": mean,
            "clip_max": mean,
            "degraded": True,
        }
    std_clip_min = mean - 2.0 * std
    std_clip_max = mean + 2.0 * std
    clip_min_raw = max(v for v in [std_clip_min, p10, min_v] if v is not None and math.isfinite(v))
    clip_max_raw = min(v for v in [std_clip_max, p90, max_v] if v is not None and math.isfinite(v))
    if clip_max_raw <= clip_min_raw:
        clip_min_raw = p10 if p10 is not None else min_v
        clip_max_raw = p90 if p90 is not None else max_v
    if clip_max_raw <= clip_min_raw:
        clip_min_raw = min_v
        clip_max_raw = max_v
    if clip_max_raw <= clip_min_raw:
        clip_min_raw = mean - 2.0 * std
        clip_max_raw = mean + 2.0 * std
    return {
        "mean": mean,
        "std": std,
        "clip_min": clip_min_raw,
        "clip_max": clip_max_raw,
        "degraded": False,
    }


def _resolve_gi_z_style(z_value: Optional[float]) -> Dict[str, Any]:
    z = _safe_float(z_value)
    if z is None:
        return {"fill": "#000000", "fill_opacity": 0.0}
    min_v, max_v, center = -3.0, 3.0, 0.0
    vv = _clamp(z, min_v, max_v)
    min_opacity, max_opacity = 0.06, 0.42
    threshold = 0.2
    if vv >= center:
        span = max(1e-9, max_v - center)
        ratio = (vv - center) / span
        fill = _mix_hex_color("#f8fafc", "#b91c1c", ratio)
    else:
        span = max(1e-9, center - min_v)
        ratio = (center - vv) / span
        fill = _mix_hex_color("#f8fafc", "#1d4ed8", ratio)
    if abs(vv - center) < threshold:
        return {"fill": fill, "fill_opacity": min_opacity * 0.6}
    fill_opacity = min_opacity + (max_opacity - min_opacity) * _clamp(ratio, 0.0, 1.0)
    return {"fill": fill, "fill_opacity": fill_opacity}


def _resolve_lisa_i_style(lisa_i: Optional[float], lisa_meta: Dict[str, Any]) -> Dict[str, Any]:
    v = _safe_float(lisa_i)
    if v is None:
        return {"fill": "#000000", "fill_opacity": 0.0}
    if bool((lisa_meta or {}).get("degraded")):
        return {"fill": "#cbd5e1", "fill_opacity": 0.06}
    mean = _safe_float((lisa_meta or {}).get("mean")) or 0.0
    clip_min = _safe_float((lisa_meta or {}).get("clip_min"))
    clip_max = _safe_float((lisa_meta or {}).get("clip_max"))
    if clip_min is None or clip_max is None or clip_max <= clip_min:
        return {"fill": "#cbd5e1", "fill_opacity": 0.10}
    vv = _clamp(v, clip_min, clip_max)
    min_opacity, max_opacity = 0.06, 0.38
    if vv >= mean:
        span = max(1e-9, clip_max - mean)
        ratio = (vv - mean) / span
        fill = _mix_hex_color("#f8fafc", "#f97316", ratio)
    else:
        span = max(1e-9, mean - clip_min)
        ratio = (mean - vv) / span
        fill = _mix_hex_color("#f8fafc", "#0f766e", ratio)
    fill_opacity = min_opacity + (max_opacity - min_opacity) * _clamp(ratio, 0.0, 1.0)
    return {"fill": fill, "fill_opacity": fill_opacity}


def _render_preview_svg_from_rows(
    rows: List[Dict[str, Any]],
    cell_map: Dict[str, Dict[str, Any]],
    mode: str = "gi_z",
    width: int = 920,
    height: int = 920,
) -> str:
    all_pts: List[List[float]] = []
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows or []:
        h3_id = str((row or {}).get("h3_id") or "")
        ring = (row or {}).get("ring") or []
        if not h3_id or len(ring) < 3:
            continue
        clean_ring: List[List[float]] = []
        for pt in ring:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                continue
            x = _safe_float(pt[0])
            y = _safe_float(pt[1])
            if x is None or y is None:
                continue
            clean_ring.append([x, y])
        if len(clean_ring) < 3:
            continue
        all_pts.extend(clean_ring)
        normalized_rows.append({"h3_id": h3_id, "ring": clean_ring})

    if not normalized_rows or not all_pts:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="240">'
            '<text x="16" y="36" font-size="16" fill="#374151">ArcGIS structure preview is empty</text>'
            '</svg>'
        )

    xs = [pt[0] for pt in all_pts]
    ys = [pt[1] for pt in all_pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = max(1e-9, max_x - min_x)
    span_y = max(1e-9, max_y - min_y)
    pad = 22.0
    draw_w = width - 2 * pad
    draw_h = height - 2 * pad

    def to_svg_xy(lng: float, lat: float) -> List[float]:
        x = pad + ((lng - min_x) / span_x) * draw_w
        y = pad + ((max_y - lat) / span_y) * draw_h
        return [x, y]

    view_mode = "lisa_i" if str(mode or "").lower() == "lisa_i" else "gi_z"
    lisa_meta = _resolve_lisa_render_meta(cell_map) if view_mode == "lisa_i" else {}

    lines: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
    ]
    for row in normalized_rows:
        meta = cell_map.get(row["h3_id"]) or {}
        if view_mode == "lisa_i":
            style = _resolve_lisa_i_style(_safe_float(meta.get("lisa_i")), lisa_meta)
        else:
            style = _resolve_gi_z_style(_safe_float(meta.get("gi_z_score")))
        fill = style["fill"]
        fill_opacity = float(style["fill_opacity"])
        stroke = "#2c6ecb"
        pts = [to_svg_xy(pt[0], pt[1]) for pt in row["ring"]]
        if not pts:
            continue
        path_d = "M " + " L ".join(f"{p[0]:.2f} {p[1]:.2f}" for p in pts) + " Z"
        lines.append(
            f'<path d="{path_d}" fill="{fill}" fill-opacity="{fill_opacity:.3f}" '
            f'stroke="{stroke}" stroke-width="1.2" stroke-opacity="0.95"/>'
        )

    lines.extend(
        [
            '<rect x="16" y="16" width="292" height="96" rx="8" fill="#ffffff" fill-opacity="0.88" stroke="#d1d5db"/>',
            '<text x="28" y="38" font-size="12" fill="#111827">ArcGIS bridge preview</text>',
            '<text x="28" y="58" font-size="11" fill="#374151">'
            + ('Fill: LMiIndex (stddev continuous)' if view_mode == "lisa_i" else 'Fill: GiZScore (continuous)')
            + '</text>',
            '<text x="28" y="76" font-size="11" fill="#374151">Stroke: unified grid border (#2c6ecb)</text>',
            f'<text x="28" y="94" font-size="10" fill="#6b7280">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</text>',
        ]
    )
    lines.append("</svg>")
    return "\n".join(lines)


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
    export_image: bool = True,
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
        "export_image": bool(export_image),
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

    image_url = None
    image_url_gi = None
    image_url_lisa = None
    if export_image:
        gi_svg = _render_preview_svg_from_rows(rows, cell_map, mode="gi_z")
        lisa_svg = _render_preview_svg_from_rows(rows, cell_map, mode="lisa_i")
        image_url_gi = _svg_to_data_uri(gi_svg)
        image_url_lisa = _svg_to_data_uri(lisa_svg)
        image_url = image_url_gi

    if trace_id:
        status_text = f"{status_text} (trace_id={trace_id})"

    return {
        "cells": cells,
        "global_moran": global_moran,
        "status": status_text,
        "image_url": image_url,
        "image_url_gi": image_url_gi,
        "image_url_lisa": image_url_lisa,
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
