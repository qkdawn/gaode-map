from __future__ import annotations

from typing import Any, Dict, List, Optional

from modules.history import service as history_service
from store.history_repo import history_repo

from .aggregation import (
    build_category_summary,
    build_summary_by_year,
    deduplicate_pois,
    normalize_years,
    select_display_year,
)
from .fetcher import fetch_pois_for_source, resolve_source_for_year
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
    years = normalize_years(payload.years)
    categories = list(payload.categories or [])
    results_by_year: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for year in years:
        source = resolve_source_for_year(year)
        year_pois: List[Dict[str, Any]] = []
        for category in categories:
            try:
                fetched = await fetch_pois_for_source(
                    polygon=payload.polygon,
                    source=source,
                    year=year,
                    keywords="",
                    types=str(category.types or ""),
                    max_count=payload.max_count,
                )
            except Exception as exc:
                errors.append(
                    {
                        "year": year,
                        "source": source,
                        "category": category.name or category.id,
                        "error": str(exc),
                    }
                )
                continue
            year_pois.extend(fetched)

        year_pois = deduplicate_pois(year_pois)
        results_by_year.append(
            {
                "year": year,
                "source": source,
                "pois": year_pois,
                "count": len(year_pois),
            }
        )

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

    return {
        "years": available_years,
        "selected_year": selected_year,
        "display_pois": display_pois,
        "results_by_year": results_by_year,
        "summary_by_year": build_summary_by_year(results_by_year, categories),
        "category_summary": build_category_summary(display_pois, categories),
        "errors": errors,
        "history_id": history_id,
    }


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
