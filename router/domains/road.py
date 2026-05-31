from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from modules.road import analyze_road_syntax
from modules.road.progress import get_road_syntax_progress, update_road_syntax_progress
from modules.road.schemas import RoadSyntaxRequest, RoadSyntaxResponse

router = APIRouter()


@router.post("/api/v1/analysis/road-syntax", response_model=RoadSyntaxResponse)
async def analyze_road_syntax_api(payload: RoadSyntaxRequest):
    run_id = str(payload.run_id or "").strip() or uuid.uuid4().hex
    update_road_syntax_progress(
        run_id,
        status="running",
        stage="queued",
        message="已接收请求，等待开始计算",
        step=0,
        total=9,
        extra={},
    )

    def _progress_callback(snapshot: Dict[str, Any]) -> None:
        update_road_syntax_progress(
            run_id,
            status="running",
            stage=str(snapshot.get("stage") or ""),
            message=str(snapshot.get("message") or ""),
            step=snapshot.get("step"),
            total=snapshot.get("total"),
            extra=snapshot.get("extra") if isinstance(snapshot.get("extra"), dict) else {},
        )

    try:
        result = await asyncio.to_thread(
            analyze_road_syntax,
            polygon=payload.polygon,
            coord_type=payload.coord_type,
            mode=payload.mode,
            graph_model=payload.graph_model,
            highway_filter=payload.highway_filter,
            include_geojson=payload.include_geojson,
            max_edge_features=payload.max_edge_features,
            merge_geojson_edges=payload.merge_geojson_edges,
            merge_bucket_step=payload.merge_bucket_step,
            radii_m=payload.radii_m,
            metric=payload.metric,
            tulip_bins=payload.tulip_bins,
            use_arcgis_webgl=payload.use_arcgis_webgl,
            arcgis_timeout_sec=payload.arcgis_timeout_sec,
            arcgis_metric_field=payload.arcgis_metric_field,
            progress_callback=_progress_callback,
        )
    except RuntimeError as exc:
        update_road_syntax_progress(
            run_id,
            status="failed",
            stage="failed",
            message=str(exc),
            extra={},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    update_road_syntax_progress(
        run_id,
        status="success",
        stage="completed",
        message="计算完成",
        step=9,
        total=9,
        extra={},
    )
    return result


@router.get("/api/v1/analysis/road-syntax/progress")
async def get_road_syntax_progress(run_id: str = Query(..., description="Road syntax run id")):
    payload = get_road_syntax_progress(run_id)
    if not payload:
        now_ts = float(time.time())
        return {
            "run_id": str(run_id or "").strip(),
            "status": "running",
            "stage": "queued",
            "message": "任务已提交，等待进度同步",
            "step": 0,
            "total": 9,
            "started_at": now_ts,
            "updated_at": now_ts,
            "elapsed_sec": 0.0,
            "extra": {
                "missing_progress_record": True,
            },
        }
    return payload
