from __future__ import annotations

import json
import logging
from time import perf_counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from core.spatial import transform_geojson_coordinates, transform_nested_coords, transform_polygon_payload_coords
from modules.poi.schemas import HistorySaveRequest
from modules.poi.records import PoiRecordContractError, complete_poi_record
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84, wgs84_to_gcj02

logger = logging.getLogger(__name__)


def coerce_extracted_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, int, float)):
        return value
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    try:
        return json.loads(text)
    except Exception:
        return value


def _normalize_years(values: Any) -> List[int]:
    result: List[int] = []
    for item in values or []:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted({item for item in result})


def build_lightweight_list_params(row: Any) -> Dict[str, Any]:
    years = coerce_extracted_json_value(getattr(row, "years", None))
    return {
        "center": coerce_extracted_json_value(getattr(row, "center", None)),
        "time_min": coerce_extracted_json_value(getattr(row, "time_min", None)),
        "keywords": coerce_extracted_json_value(getattr(row, "keywords", None)),
        "mode": coerce_extracted_json_value(getattr(row, "mode", None)),
        "source": coerce_extracted_json_value(getattr(row, "source", None)),
        "year": coerce_extracted_json_value(getattr(row, "year", None)),
        "years": _normalize_years(years),
    }


def build_list_params_from_params(raw_params: Dict[str, Any]) -> Dict[str, Any]:
    params = raw_params if isinstance(raw_params, dict) else {}
    return {
        "center": params.get("center"),
        "time_min": params.get("time_min"),
        "keywords": params.get("keywords"),
        "mode": params.get("mode"),
        "source": params.get("source"),
        "year": params.get("year"),
        "years": _normalize_years(params.get("years")),
    }


def _build_year_key(params: Dict[str, Any]) -> str:
    years = _normalize_years(params.get("years"))
    if years:
        return ",".join(str(item) for item in years)
    year = params.get("year")
    return str(year if year is not None else "")


def build_history_list_dedupe_key(description: str, params: Dict[str, Any]) -> str:
    params = params if isinstance(params, dict) else {}
    center = params.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            center_key = f"{float(center[0]):.6f},{float(center[1]):.6f}"
        except Exception:
            center_key = str(center)
    else:
        center_key = ""
    time_min = str(params.get("time_min") if params.get("time_min") is not None else "")
    mode = str(params.get("mode") or "").strip().lower()
    source = str(params.get("source") or "").strip().lower()
    year = _build_year_key(params)
    keywords = str(params.get("keywords") or "").strip()
    desc_key = str(description or "").strip()
    return "||".join([center_key, time_min, mode, source, year, keywords, desc_key])


def build_history_overwrite_key(params: Dict[str, Any]) -> str:
    params = params if isinstance(params, dict) else {}
    center = params.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            center_key = f"{float(center[0]):.6f},{float(center[1]):.6f}"
        except Exception:
            center_key = str(center)
    else:
        center_key = ""
    time_min = str(params.get("time_min") if params.get("time_min") is not None else "")
    mode = str(params.get("mode") or "").strip().lower()
    source = str(params.get("source") or "").strip().lower()
    year = _build_year_key(params)
    keywords = str(params.get("keywords") or "").strip()
    return "||".join([center_key, time_min, mode, source, year, keywords])


def serialize_created_at(value: datetime) -> str:
    if not isinstance(value, datetime):
        return str(value or "")
    dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def build_detail_payload(
    history: Any,
    *,
    pois: Optional[List[Dict[str, Any]]] = None,
    poi_summary: Optional[Dict[str, Any]] = None,
    poi_count: Optional[int] = None,
    available_years: Optional[List[int]] = None,
    selected_year: Optional[int] = None,
    pois_by_year: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = {
        "id": str(history.id or ""),
        "description": history.description,
        "created_at": serialize_created_at(history.created_at),
        "params": history.params,
        "polygon": history.result_polygon,
        "polygon_wgs84": history.result_polygon,
        "poi_summary": poi_summary or {},
        "available_years": list(available_years or []),
        "selected_year": int(selected_year) if selected_year is not None else None,
        "pois_by_year": list(pois_by_year or []),
    }
    if poi_count is not None:
        payload["poi_count"] = int(max(0, poi_count))
    if pois is not None:
        payload["pois"] = pois
    return payload


def _build_history_params_payload(payload: HistorySaveRequest) -> Dict[str, Any]:
    center = payload.center
    if center:
        wx, wy = gcj02_to_wgs84(center[0], center[1])
        center = [wx, wy]
    normalized_years = _normalize_years(payload.years)
    if payload.year is not None:
        normalized_years = _normalize_years(normalized_years + [payload.year])

    params_payload: Dict[str, Any] = {
        "center": center,
        "time_min": payload.time_min,
        "keywords": payload.keywords,
        "mode": payload.mode,
        "source": ((payload.source or "local").strip().lower() if payload.source else "local"),
        "year": payload.year,
        "years": normalized_years,
    }
    if params_payload["source"] not in ("gaode", "local"):
        params_payload["source"] = "local"
    if payload.drawn_polygon:
        transformed_drawn = transform_nested_coords(payload.drawn_polygon, gcj02_to_wgs84)
        if isinstance(transformed_drawn, list) and transformed_drawn:
            params_payload["drawn_polygon"] = transformed_drawn
    return params_payload


def _build_history_description(payload: HistorySaveRequest, params_payload: Dict[str, Any], poi_count: int) -> str:
    center = params_payload.get("center")
    display_title = payload.location_name
    if not display_title and center:
        display_title = f"{center[0]:.4f},{center[1]:.4f}"
    desc = f"{display_title} - {poi_count} POIs" if display_title else f"{payload.keywords} - {poi_count} POIs"
    if payload.time_min and "min" not in desc:
        desc = f"{payload.time_min}min - {desc}"
    return desc


def _complete_wgs84_poi(value: Dict[str, Any], *, source: str, year: Optional[int]) -> Dict[str, Any]:
    item = dict(value or {})
    if item.get("location"):
        lx, ly = item["location"]
        wx, wy = gcj02_to_wgs84(lx, ly)
        item["location"] = [wx, wy]
    return complete_poi_record(item, source=source, year=year)


def _normalize_poi_snapshot_rows(payload: HistorySaveRequest, params_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if payload.poi_results_by_year:
        result: List[Dict[str, Any]] = []
        for row in payload.poi_results_by_year:
            row_source = str(row.source or params_payload["source"]).strip().lower()
            row_year = int(row.year) if row.year is not None else None
            row_pois = [
                _complete_wgs84_poi(poi, source=row_source, year=row_year)
                for poi in row.pois
            ]
            result.append(
                {
                    "source": row_source,
                    "year": row_year,
                    "pois": row_pois,
                }
            )
        return result

    return [
        {
            "source": params_payload["source"],
            "year": payload.year,
            "pois": [
                _complete_wgs84_poi(poi, source=params_payload["source"], year=payload.year)
                for poi in payload.pois
            ],
        }
    ]


def save_history_request(payload: HistorySaveRequest, repo) -> Dict[str, Any]:
    params_payload = _build_history_params_payload(payload)
    preferred_history_id = str(payload.history_id or "").strip()
    polygon_wgs84 = (
        payload.polygon_wgs84
        if preferred_history_id and isinstance(payload.polygon_wgs84, list) and payload.polygon_wgs84
        else (transform_polygon_payload_coords(payload.polygon, gcj02_to_wgs84) if payload.polygon else [])
    )

    try:
        snapshots = _normalize_poi_snapshot_rows(payload, params_payload)
    except PoiRecordContractError as exc:
        raise HTTPException(status_code=422, detail=f"POI 记录不符合 spatial_records/v1: {exc}") from exc
    pois = next(
        (list(row["pois"]) for row in snapshots if row.get("year") == payload.year),
        list(snapshots[0]["pois"]) if snapshots else [],
    )
    desc = _build_history_description(payload, params_payload, len(pois))
    try:
        history_id = repo.create_record(
            params_payload,
            polygon_wgs84,
            pois,
            desc,
            preferred_history_id=preferred_history_id,
            poi_results_by_year=snapshots,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存历史失败: {exc}") from exc
    return {"status": "ok", "history_id": history_id, "count": len(pois)}


def get_history_list_payload(limit: int, repo) -> List[Dict[str, Any]]:
    try:
        return repo.get_list(limit)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="历史记录数据库不可用，请检查 MySQL 连接") from exc


def convert_history_detail_to_gcj02(res: Dict[str, Any], *, include_pois: bool) -> Dict[str, Any]:
    payload = dict(res or {})
    params = payload.get("params") or {}
    if params.get("center"):
        cx, cy = params["center"]
        nx, ny = wgs84_to_gcj02(cx, cy)
        params["center"] = [nx, ny]
    if params.get("drawn_polygon"):
        try:
            transformed = transform_nested_coords(params["drawn_polygon"], wgs84_to_gcj02)
            params["drawn_polygon"] = transformed if isinstance(transformed, list) else []
        except Exception:
            params["drawn_polygon"] = []
    if isinstance(params.get("h3_result"), dict):
        params["h3_result"] = transform_geojson_coordinates(params["h3_result"], wgs84_to_gcj02)
    if isinstance(params.get("road_result"), dict):
        params["road_result"] = transform_geojson_coordinates(params["road_result"], wgs84_to_gcj02)
    if payload.get("polygon"):
        polygon = payload["polygon"]

        def _convert_ring(ring):
            return [list(wgs84_to_gcj02(point[0], point[1])) for point in ring]

        if polygon and len(polygon) > 0:
            if isinstance(polygon[0][0], list):
                payload["polygon"] = [_convert_ring(ring) for ring in polygon]
            else:
                payload["polygon"] = _convert_ring(polygon)

    if include_pois and payload.get("pois"):
        for poi in payload["pois"]:
            if poi.get("location"):
                lx, ly = poi["location"]
                nlx, nly = wgs84_to_gcj02(lx, ly)
                poi["location"] = [nlx, nly]
    return payload


def convert_history_pois_to_gcj02(res: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(res or {})
    if payload.get("polygon"):
        polygon = payload["polygon"]

        def _convert_ring(ring):
            return [list(wgs84_to_gcj02(point[0], point[1])) for point in ring]

        if polygon and len(polygon) > 0:
            if isinstance(polygon[0][0], list):
                payload["polygon"] = [_convert_ring(ring) for ring in polygon]
            else:
                payload["polygon"] = _convert_ring(polygon)
    for poi in payload.get("pois") or []:
        if poi.get("location"):
            lx, ly = poi["location"]
            nlx, nly = wgs84_to_gcj02(lx, ly)
            poi["location"] = [nlx, nly]
    return payload


def _build_history_database_error_detail(exc: Exception) -> str:
    message = str(exc)
    normalized = message.lower()
    if "1038" in normalized or "sort memory" in normalized:
        return "数据库排序内存不足，POI 明细未恢复；已避免排序大字段后仍失败，请检查 MySQL sort_buffer_size"
    return f"历史数据库查询失败: {message[:300]}"


def get_history_detail_payload(history_id: str, include_pois: bool, repo) -> Dict[str, Any]:
    try:
        res = repo.get_detail(history_id, include_pois=include_pois)
    except SQLAlchemyError as exc:
        raise HTTPException(500, _build_history_database_error_detail(exc)) from exc
    if not res:
        raise HTTPException(404, "Record not found")
    return convert_history_detail_to_gcj02(res, include_pois=include_pois)


def get_history_detail_payload_for_year(history_id: str, include_pois: bool, year: Optional[int], repo) -> Dict[str, Any]:
    try:
        if year is None:
            res = repo.get_detail(history_id, include_pois=include_pois)
        else:
            res = repo.get_detail(history_id, include_pois=include_pois, year=year)
    except SQLAlchemyError as exc:
        raise HTTPException(500, _build_history_database_error_detail(exc)) from exc
    if not res:
        raise HTTPException(404, "Record not found")
    return convert_history_detail_to_gcj02(res, include_pois=include_pois)


def get_history_pois_payload(history_id: str, repo, year: Optional[int] = None) -> Dict[str, Any]:
    started_at = perf_counter()
    try:
        repo_started_at = perf_counter()
        if year is None:
            res = repo.get_pois(history_id)
        else:
            res = repo.get_pois(history_id, year=year)
        repo_ms = (perf_counter() - repo_started_at) * 1000
    except SQLAlchemyError as exc:
        raise HTTPException(500, _build_history_database_error_detail(exc)) from exc
    if not res:
        raise HTTPException(404, "Record not found")
    convert_started_at = perf_counter()
    payload = convert_history_pois_to_gcj02(res)
    convert_ms = (perf_counter() - convert_started_at) * 1000
    total_ms = (perf_counter() - started_at) * 1000
    logger.info(
        "history POI payload restored history_id=%s year=%s count=%s repo_ms=%.1f convert_ms=%.1f total_ms=%.1f",
        history_id,
        year,
        len(payload.get("pois") or []),
        repo_ms,
        convert_ms,
        total_ms,
    )
    return payload


def delete_history_record(history_id: str, repo) -> Dict[str, Any]:
    if not repo.delete_record(history_id):
        raise HTTPException(404, "Delete failed")
    return {"status": "success", "id": history_id}
