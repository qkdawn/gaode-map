from __future__ import annotations

from typing import Awaitable, Callable, Dict, List, Literal, Optional

from .core import fetch_local_pois_by_polygon, fetch_pois_by_polygon, fetch_pois_by_polygon_tiled


PoiSource = Literal["gaode", "local"]


def resolve_source_for_year(year: int) -> PoiSource:
    return "gaode" if int(year) == 2026 else "local"


async def fetch_pois_for_source(
    *,
    polygon: list,
    source: PoiSource,
    year: Optional[int],
    keywords: str = "",
    types: str = "",
    max_count: int = 0,
) -> List[Dict]:
    results, _ = await fetch_pois_for_source_with_diagnostics(
        polygon=polygon,
        source=source,
        year=year,
        keywords=keywords,
        types=types,
        max_count=max_count,
    )
    return results


async def fetch_pois_for_source_with_diagnostics(
    *,
    polygon: list,
    source: PoiSource,
    year: Optional[int],
    keywords: str = "",
    types: str = "",
    max_count: int = 0,
    progress_callback: Optional[Callable[[Dict], Awaitable[None]]] = None,
    fetch_strategy: str = "gaode_tiled_polygon",
    selected_category_count: Optional[int] = None,
) -> tuple[List[Dict], Dict]:
    if source == "local":
        results = await fetch_local_pois_by_polygon(
            polygon,
            types=types,
            year=year,
            max_count=max_count,
        )
        return results, {"mode": "local_polygon"}

    if year is not None and int(year) == 2026:
        results, diagnostics = await fetch_pois_by_polygon_tiled(
            polygon,
            keywords,
            types,
            max_count=max_count,
            progress_callback=progress_callback,
            fetch_strategy=fetch_strategy,
            selected_category_count=selected_category_count,
        )
    else:
        results = await fetch_pois_by_polygon(
            polygon,
            keywords,
            types,
            max_count=max_count,
        )
        diagnostics = {"mode": "gaode_polygon"}
    if year is not None:
        for poi in results:
            poi["year"] = int(year)
    return results, diagnostics
