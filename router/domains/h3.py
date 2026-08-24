from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from core.config import settings
from modules.h3.analysis import analyze_h3_grid
from modules.h3.analysis_schemas import H3MetricsRequest, H3MetricsResponse
from modules.h3.core import build_h3_grid_feature_collection
from modules.h3.progress import get_h3_progress, update_h3_progress
from modules.h3.schemas import GridRequest, GridResponse

router = APIRouter()


def _normalize_boundary_ring(path: Any) -> List[List[float]]:
    ring: List[List[float]] = []
    for pt in path if isinstance(path, list) else []:
        if not isinstance(pt, list) or len(pt) < 2:
            continue
        try:
            lng = float(pt[0])
            lat = float(pt[1])
        except (TypeError, ValueError):
            continue
        ring.append([lng, lat])
    if len(ring) < 3:
        return []
    first = ring[0]
    last = ring[-1]
    if abs(first[0] - last[0]) > 1e-9 or abs(first[1] - last[1]) > 1e-9:
        ring.append([first[0], first[1]])
    return ring if len(ring) >= 4 else []


def _extract_boundary_rings(geometry: Dict[str, Any]) -> List[List[List[float]]]:
    if not isinstance(geometry, dict):
        return []
    geom_type = str(geometry.get("type") or "")
    coords = geometry.get("coordinates")
    rings: List[List[List[float]]] = []
    if geom_type == "Polygon" and isinstance(coords, list) and coords and isinstance(coords[0], list):
        ring = _normalize_boundary_ring(coords[0])
        if ring:
            rings.append(ring)
    elif geom_type == "MultiPolygon" and isinstance(coords, list):
        for polygon in coords:
            if not isinstance(polygon, list) or not polygon or not isinstance(polygon[0], list):
                continue
            ring = _normalize_boundary_ring(polygon[0])
            if ring:
                rings.append(ring)
    return rings


def _signed_ring_area(ring: List[List[float]]) -> float:
    if len(ring) < 4:
        return 0.0
    area = 0.0
    for i in range(len(ring) - 1):
        a = ring[i]
        b = ring[i + 1]
        area += (float(a[0]) * float(b[1])) - (float(b[0]) * float(a[1]))
    return area / 2.0


def _resolve_city_boundary_candidates(city_name: str) -> List[str]:
    city = (city_name or "").strip().lower()
    is_changsha = ("长沙" in city_name) or city in {"changsha", "changsha city", "cs"}
    if is_changsha:
        return [
            "changsha_boundary_gcj02.geojson",
            "changsha_boundary.geojson",
        ]
    return []


def _load_city_boundary_ring(city_name: str) -> Dict[str, Any]:
    candidates = _resolve_city_boundary_candidates(city_name)
    if not candidates:
        raise HTTPException(status_code=400, detail=f"暂不支持城市边界: {city_name}")

    boundary_dir = Path(settings.city_boundary_dir).expanduser()
    if not boundary_dir.exists() or not boundary_dir.is_dir():
        raise HTTPException(status_code=500, detail=f"城市边界目录不存在: {boundary_dir}")

    rings: List[List[List[float]]] = []
    used_file: Optional[Path] = None
    tried_paths: List[str] = []
    for filename in candidates:
        path = boundary_dir / filename
        tried_paths.append(str(path))
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"边界文件读取失败: {path} ({exc})") from exc

        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            for feature in payload.get("features") or []:
                if not isinstance(feature, dict):
                    continue
                rings.extend(_extract_boundary_rings(feature.get("geometry") or {}))
        elif isinstance(payload, dict) and payload.get("type") == "Feature":
            rings.extend(_extract_boundary_rings(payload.get("geometry") or {}))
        elif isinstance(payload, dict):
            rings.extend(_extract_boundary_rings(payload))

        if rings:
            used_file = path
            break

    if not rings:
        raise HTTPException(
            status_code=404,
            detail=f"未找到可用城市边界文件，请检查: {', '.join(tried_paths)}",
        )

    largest_ring = sorted(
        rings,
        key=lambda ring: (abs(_signed_ring_area(ring)), len(ring)),
        reverse=True,
    )[0]
    return {
        "city": city_name,
        "source_file": str(used_file) if used_file else "",
        "ring": largest_ring,
    }


@router.post("/api/v1/analysis/h3-grid", response_model=GridResponse)
async def build_h3_grid(payload: GridRequest):
    feature_collection = await asyncio.to_thread(
        build_h3_grid_feature_collection,
        payload.polygon,
        payload.resolution,
        payload.coord_type,
        payload.include_mode,
        payload.min_overlap_ratio,
    )
    return feature_collection


@router.get("/api/v1/analysis/city-boundary")
async def get_city_boundary(city: str = Query("长沙市", description="城市名称")):
    target_city = (city or "长沙市").strip() or "长沙市"
    return _load_city_boundary_ring(target_city)


@router.post("/api/v1/analysis/h3-metrics", response_model=H3MetricsResponse)
async def analyze_h3_metrics(payload: H3MetricsRequest):
    run_id = str(payload.run_id or "").strip()
    if run_id:
        update_h3_progress(
            run_id,
            status="running",
            stage="queued",
            message="已接收请求，等待开始计算",
            step=0,
            total=8,
            extra={
                "resolution": int(payload.resolution),
                "arcgis_enabled": True,
            },
        )

    def _progress_callback(snapshot: Dict[str, Any]) -> None:
        if not run_id:
            return
        update_h3_progress(
            run_id,
            status="running" if str(snapshot.get("stage") or "") != "completed" else "success",
            stage=str(snapshot.get("stage") or ""),
            message=str(snapshot.get("message") or ""),
            step=snapshot.get("step"),
            total=snapshot.get("total"),
            extra=snapshot.get("extra") if isinstance(snapshot.get("extra"), dict) else {},
        )

    poi_payload = [
        p.model_dump() if hasattr(p, "model_dump") else p.dict()
        for p in payload.pois
    ]
    try:
        result = await asyncio.to_thread(
            analyze_h3_grid,
            polygon=payload.polygon,
            resolution=payload.resolution,
            coord_type=payload.coord_type,
            include_mode=payload.include_mode,
            min_overlap_ratio=payload.min_overlap_ratio,
            pois=poi_payload,
            poi_coord_type=payload.poi_coord_type,
            use_arcgis=True,
            arcgis_timeout_sec=payload.arcgis_timeout_sec,
            progress_callback=_progress_callback,
        )
    except RuntimeError as exc:
        if run_id:
            update_h3_progress(
                run_id,
                status="failed",
                stage="failed",
                message=str(exc),
                step=8,
                total=8,
                extra={
                    "resolution": int(payload.resolution),
                    "arcgis_enabled": True,
                },
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.get("/api/v1/analysis/h3-metrics/progress")
async def get_h3_metrics_progress(run_id: str = Query(..., description="H3 metrics run id")):
    payload = get_h3_progress(run_id)
    if not payload:
        return {
            "run_id": str(run_id or "").strip(),
            "status": "running",
            "stage": "queued",
            "message": "任务已提交，等待进度同步",
            "step": 0,
            "total": 8,
            "started_at": 0.0,
            "updated_at": 0.0,
            "elapsed_sec": 0.0,
            "extra": {
                "missing_progress_record": True,
            },
        }
    return payload
