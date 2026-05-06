from __future__ import annotations

from typing import Dict, List, Literal, Optional

from .core import fetch_local_pois_by_polygon, fetch_pois_by_polygon


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
    if source == "local":
        return await fetch_local_pois_by_polygon(
            polygon,
            types=types,
            year=year,
            max_count=max_count,
        )

    results = await fetch_pois_by_polygon(
        polygon,
        keywords,
        types,
        max_count=max_count,
    )
    if year is not None:
        for poi in results:
            poi["year"] = int(year)
    return results
