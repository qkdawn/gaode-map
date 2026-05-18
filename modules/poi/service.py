from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from modules.history import service as history_service
from store.history_repo import history_repo

from .aggregation import (
    build_category_summary,
    build_summary_by_year,
    deduplicate_pois,
    normalize_type_code,
    normalize_years,
    select_display_year,
)
from .fetcher import fetch_pois_for_source, fetch_pois_for_source_with_diagnostics, resolve_source_for_year
from .schemas import (
    HistoryPoiYearResult,
    HistorySaveRequest,
    PoiMultiYearRequest,
    PoiRequest,
)


async def fetch_single_year_pois(payload: PoiRequest) -> List[Dict[str, Any]]:
    source = (payload.source or "local").strip().lower()
    if source not in ("gaode", "local"):
        source = "local"
    return await fetch_pois_for_source(
        polygon=payload.polygon,
        source=source,  # type: ignore[arg-type]
        year=payload.year,
        keywords=payload.keywords,
        types=payload.types,
        max_count=payload.max_count,
    )


async def fetch_single_year_pois_with_diagnostics(payload: PoiRequest) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    source = (payload.source or "local").strip().lower()
    if source not in ("gaode", "local"):
        source = "local"
    return await fetch_pois_for_source_with_diagnostics(
        polygon=payload.polygon,
        source=source,  # type: ignore[arg-type]
        year=payload.year,
        keywords=payload.keywords,
        types=payload.types,
        max_count=payload.max_count,
    )


def save_single_year_history(payload: PoiRequest, results: List[Dict[str, Any]], source: str) -> Any:
    if not payload.save_history:
        return None
    request = HistorySaveRequest(
        center=payload.center or [],
        polygon=payload.polygon,
        pois=results,
        keywords=payload.keywords,
        mode=payload.mode or "walking",
        time_min=payload.time_min or 15,
        year=payload.year,
        years=[int(payload.year)] if payload.year is not None else [],
        poi_results_by_year=[HistoryPoiYearResult(source=source, year=payload.year, pois=results)],
        location_name=payload.location_name,
        source=source,  # type: ignore[arg-type]
    )
    return history_service.save_history_request(request, history_repo).get("history_id")


async def fetch_multi_year_pois(payload: PoiMultiYearRequest) -> Dict[str, Any]:
    final_result: Optional[Dict[str, Any]] = None
    async for event in stream_fetch_multi_year_pois(payload):
        if event.get("type") == "final":
            final_result = dict(event.get("result") or {})
    return final_result or {
        "years": [],
        "selected_year": None,
        "display_pois": [],
        "results_by_year": [],
        "summary_by_year": [],
        "category_summary": [],
        "errors": [],
        "history_id": None,
    }


async def stream_fetch_multi_year_pois(payload: PoiMultiYearRequest) -> AsyncIterator[Dict[str, Any]]:
    years = normalize_years(payload.years)
    categories = list(payload.categories or [])
    results_by_year: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    total_units = max(1, len(years) * max(1, len(categories)))
    completed_units = 0

    yield {
        "type": "start",
        "years": years,
        "category_count": len(categories),
        "total_units": total_units,
    }

    for year in years:
        source = resolve_source_for_year(year)
        year_pois: List[Dict[str, Any]] = []
        year_diagnostics: List[Dict[str, Any]] = []
        if source == "gaode" and int(year) == 2026:
            async for event in _stream_fetch_gaode_year_combined(
                payload=payload,
                year=year,
                source=source,
                categories=categories,
                completed_units=completed_units,
                total_units=total_units,
                errors=errors,
            ):
                if event.get("type") == "_year_result":
                    year_pois = list(event.get("pois") or [])
                    year_diagnostics = list(event.get("diagnostics") or [])
                    completed_units = int(event.get("completed_units") or completed_units)
                    continue
                yield event
            row = {
                "year": year,
                "source": source,
                "pois": year_pois,
                "count": len(year_pois),
            }
            if year_diagnostics:
                row["diagnostics"] = year_diagnostics
            results_by_year.append(row)
            yield {
                "type": "year_complete",
                "year": year,
                "source": source,
                "count": len(year_pois),
                "completed_units": completed_units,
                "total_units": total_units,
                "progress": round(completed_units / total_units * 100),
            }
            continue
        for category_index, category in enumerate(categories, start=1):
            category_label = category.name or category.id
            progress_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

            async def publish_fetch_progress(progress: Dict[str, Any]) -> None:
                await progress_queue.put(
                    {
                        "type": "category_progress",
                        "year": year,
                        "source": source,
                        "category": category_label,
                        "category_index": category_index,
                        "category_count": len(categories),
                        "completed_units": completed_units,
                        "total_units": total_units,
                        **(progress or {}),
                    }
                )

            yield {
                "type": "category_start",
                "year": year,
                "source": source,
                "category": category_label,
                "category_index": category_index,
                "category_count": len(categories),
                "completed_units": completed_units,
                "total_units": total_units,
            }
            try:
                fetch_task = asyncio.create_task(
                    fetch_pois_for_source_with_diagnostics(
                        polygon=payload.polygon,
                        source=source,
                        year=year,
                        keywords="",
                        types=str(category.types or ""),
                        max_count=payload.max_count,
                        progress_callback=publish_fetch_progress,
                    )
                )
                while not fetch_task.done():
                    try:
                        yield await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                while not progress_queue.empty():
                    yield progress_queue.get_nowait()
                fetched, diagnostics = await fetch_task
            except Exception as exc:
                error_row = {
                    "year": year,
                    "source": source,
                    "category": category_label,
                    "error": str(exc),
                }
                errors.append(error_row)
                completed_units += 1
                yield {
                    "type": "category_complete",
                    "status": "failed",
                    "year": year,
                    "source": source,
                    "category": category_label,
                    "count": 0,
                    "error": error_row,
                    "completed_units": completed_units,
                    "total_units": total_units,
                    "progress": round(completed_units / total_units * 100),
                }
                continue
            year_pois.extend(fetched)
            if diagnostics:
                diagnostic_row = {
                    "category": category_label,
                    **diagnostics,
                }
                year_diagnostics.append(diagnostic_row)
                errors.extend(
                    _build_gaode_diagnostic_errors(
                        year=year,
                        source=source,
                        category=str(category_label or ""),
                        diagnostics=diagnostics,
                    )
                )
            completed_units += 1
            yield {
                "type": "category_complete",
                "status": "ready",
                "year": year,
                "source": source,
                "category": category_label,
                "count": len(fetched),
                "year_count": len(year_pois),
                "diagnostics": diagnostics or {},
                "completed_units": completed_units,
                "total_units": total_units,
                "progress": round(completed_units / total_units * 100),
            }

        before_cross_dedup = len(year_pois)
        year_pois = deduplicate_pois(year_pois)
        cross_category_dedup_removed = max(0, before_cross_dedup - len(year_pois))
        if cross_category_dedup_removed and year_diagnostics:
            for row in year_diagnostics:
                row["cross_category_dedup_removed"] = cross_category_dedup_removed
                row["final_count"] = len(year_pois)
        row = {
            "year": year,
            "source": source,
            "pois": year_pois,
            "count": len(year_pois),
        }
        if year_diagnostics:
            row["diagnostics"] = year_diagnostics
        results_by_year.append(row)
        yield {
            "type": "year_complete",
            "year": year,
            "source": source,
            "count": len(year_pois),
            "completed_units": completed_units,
            "total_units": total_units,
            "progress": round(completed_units / total_units * 100),
        }

    selected_year = select_display_year(results_by_year)
    display_pois = []
    if selected_year is not None:
        for item in results_by_year:
            if int(item.get("year")) == int(selected_year):
                display_pois = list(item.get("pois") or [])
                break

    available_years = [
        int(item["year"])
        for item in results_by_year
        if int(item.get("count") or 0) > 0
    ]

    history_id: Optional[str] = None
    if payload.save_history and payload.center:
        history_id = save_multi_year_history(
            payload=payload,
            results_by_year=results_by_year,
            display_pois=display_pois,
            selected_year=selected_year,
            years=available_years,
        )

    result = {
        "years": available_years,
        "selected_year": selected_year,
        "display_pois": display_pois,
        "results_by_year": results_by_year,
        "summary_by_year": build_summary_by_year(results_by_year, categories),
        "category_summary": build_category_summary(display_pois, categories),
        "errors": errors,
        "history_id": history_id,
    }
    yield {"type": "final", "result": result, "progress": 100}


async def _stream_fetch_gaode_year_combined(
    *,
    payload: PoiMultiYearRequest,
    year: int,
    source: str,
    categories: List[Any],
    completed_units: int,
    total_units: int,
    errors: List[Dict[str, Any]],
) -> AsyncIterator[Dict[str, Any]]:
    category_label = "all selected categories"
    merged_types = _merge_category_types(categories)
    progress_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    category_count = len(categories)
    category_units = max(1, category_count)

    async def publish_fetch_progress(progress: Dict[str, Any]) -> None:
        await progress_queue.put(
            {
                "type": "category_progress",
                "year": year,
                "source": source,
                "category": category_label,
                "category_index": 1,
                "category_count": 1,
                "completed_units": completed_units,
                "total_units": total_units,
                **(progress or {}),
            }
        )

    yield {
        "type": "category_start",
        "year": year,
        "source": source,
        "category": category_label,
        "category_index": 1,
        "category_count": 1,
        "completed_units": completed_units,
        "total_units": total_units,
    }
    try:
        fetch_task = asyncio.create_task(
            fetch_pois_for_source_with_diagnostics(
                polygon=payload.polygon,
                source="gaode",
                year=year,
                keywords="",
                types=merged_types,
                max_count=payload.max_count,
                progress_callback=publish_fetch_progress,
                fetch_strategy="year_combined_types",
                selected_category_count=category_count,
            )
        )
        while not fetch_task.done():
            try:
                yield await asyncio.wait_for(progress_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
        while not progress_queue.empty():
            yield progress_queue.get_nowait()
        fetched, diagnostics = await fetch_task
    except Exception as exc:
        error_row = {
            "year": year,
            "source": source,
            "category": category_label,
            "error": str(exc),
        }
        errors.append(error_row)
        completed_units += category_units
        yield {
            "type": "category_complete",
            "status": "failed",
            "year": year,
            "source": source,
            "category": category_label,
            "count": 0,
            "error": error_row,
            "completed_units": completed_units,
            "total_units": total_units,
            "progress": round(completed_units / total_units * 100),
        }
        yield {
            "type": "_year_result",
            "pois": [],
            "diagnostics": [],
            "completed_units": completed_units,
        }
        return

    for poi in fetched:
        poi["year"] = int(year)
    fetched = deduplicate_pois(fetched)
    diagnostics = dict(diagnostics or {})
    diagnostics.update(
        {
            "category": category_label,
            "fetch_strategy": "year_combined_types",
            "selected_category_count": category_count,
            "merged_type_count": len(_split_merged_types(merged_types)),
            "final_count": len(fetched),
        }
    )
    year_diagnostics = [diagnostics]
    errors.extend(
        _build_gaode_diagnostic_errors(
            year=year,
            source=source,
            category=category_label,
            diagnostics=diagnostics,
        )
    )
    completed_units += category_units
    yield {
        "type": "category_complete",
        "status": "ready",
        "year": year,
        "source": source,
        "category": category_label,
        "count": len(fetched),
        "year_count": len(fetched),
        "diagnostics": diagnostics,
        "completed_units": completed_units,
        "total_units": total_units,
        "progress": round(completed_units / total_units * 100),
    }
    yield {
        "type": "_year_result",
        "pois": fetched,
        "diagnostics": year_diagnostics,
        "completed_units": completed_units,
    }


def _merge_category_types(categories: List[Any]) -> str:
    seen = set()
    codes: List[str] = []
    for category in categories or []:
        for raw in str(getattr(category, "types", "") or "").split("|"):
            code = normalize_type_code(raw)
            if not code or code in seen:
                continue
            seen.add(code)
            codes.append(code)
    return "|".join(codes)


def _split_merged_types(types: str) -> List[str]:
    return [code for code in (normalize_type_code(raw) for raw in str(types or "").split("|")) if code]


def _build_gaode_diagnostic_errors(
    *,
    year: int,
    source: str,
    category: str,
    diagnostics: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if source != "gaode" or not isinstance(diagnostics, dict):
        return []

    errors: List[Dict[str, Any]] = []
    if diagnostics.get("failed_queries"):
        errors.append(
            {
                "year": year,
                "source": source,
                "category": category,
                "error": "gaode_tiled_query_failed",
                "detail": _summarize_poi_diagnostic_block(diagnostics.get("failed_queries")),
                "reason_type": _classify_poi_diagnostic_reason(diagnostics.get("failed_queries")),
            }
        )
    if diagnostics.get("incomplete_tiles"):
        errors.append(
            {
                "year": year,
                "source": source,
                "category": category,
                "error": "gaode_tiled_fetch_incomplete",
                "detail": _summarize_poi_diagnostic_block(diagnostics.get("incomplete_tiles")),
                "reason_type": _classify_poi_diagnostic_reason(diagnostics.get("incomplete_tiles")),
            }
        )
    if diagnostics.get("request_budget_exceeded"):
        errors.append(
            {
                "year": year,
                "source": source,
                "category": category,
                "error": "gaode_tiled_year_api_budget_exceeded" if diagnostics.get("api_budget_exceeded") else "gaode_tiled_request_budget_exceeded",
                "detail": {
                    "request_count": int(diagnostics.get("request_count") or 0),
                    "api_call_count": int(diagnostics.get("api_call_count") or 0),
                    "type_query_count": int(diagnostics.get("type_query_count") or 0),
                },
                "reason_type": "request_budget",
            }
        )
    return errors


def _summarize_poi_diagnostic_block(value: Any) -> Dict[str, Any]:
    rows = value if isinstance(value, list) else []
    return {
        "count": len(rows),
        "samples": rows[:3],
    }


def _classify_poi_diagnostic_reason(value: Any) -> str:
    rows = value if isinstance(value, list) else []
    text = " ".join(str((row or {}).get("reason") or row) for row in rows).lower()
    if "10003" in text or "qps" in text or "limit" in text and "daily" not in text:
        return "qps_limit"
    if "10044" in text or "daily quota" in text or "quota" in text or "exhausted" in text:
        return "quota_limit"
    if "tile_request_budget_exceeded" in text:
        return "request_budget"
    if "http" in text or "timeout" in text or "network" in text or "connect" in text:
        return "network_or_http"
    if "saturated" in text or "page cap" in text:
        return "result_cap"
    return "unknown"


def save_multi_year_history(
    *,
    payload: PoiMultiYearRequest,
    results_by_year: List[Dict[str, Any]],
    display_pois: List[Dict[str, Any]],
    selected_year: Optional[int],
    years: List[int],
) -> Optional[str]:
    if not payload.center:
        return None

    selected_categories = ", ".join(
        str(category.name or category.id)
        for category in payload.categories
        if str(category.name or category.id).strip()
    )
    snapshots = [
        HistoryPoiYearResult(
            source=item.get("source") or "local",
            year=int(item.get("year")),
            pois=list(item.get("pois") or []),
        )
        for item in results_by_year
        if int(item.get("count") or 0) > 0
    ]
    if not snapshots:
        return None

    request = HistorySaveRequest(
        history_id=payload.history_id,
        center=payload.center,
        polygon=payload.polygon,
        pois=display_pois,
        keywords=selected_categories,
        mode=payload.mode or "walking",
        time_min=payload.time_min or 15,
        year=selected_year,
        years=years,
        poi_results_by_year=snapshots,
        location_name=payload.location_name,
        source=resolve_source_for_year(selected_year) if selected_year is not None else "local",
    )
    return history_service.save_history_request(request, history_repo).get("history_id")
