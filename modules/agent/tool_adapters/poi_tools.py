from __future__ import annotations

from typing import Any, Dict

from modules.poi.core import fetch_local_pois_by_polygon, fetch_pois_by_polygon

from ..schemas import AnalysisSnapshot, ToolResult


async def fetch_pois_in_scope(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del question
    polygon = artifacts.get("scope_polygon") or []
    if not polygon:
        return ToolResult(
            tool_name="fetch_pois_in_scope",
            status="failed",
            warnings=["缺少分析范围，无法抓取 POI"],
            error="missing_scope_polygon",
        )

    source = str(
        arguments.get("source")
        or snapshot.current_filters.get("poi_source")
        or snapshot.context.get("source")
        or "local"
    ).strip().lower()
    if source not in {"local", "gaode"}:
        source = "local"
    types = str(arguments.get("types") or "")
    keywords = str(arguments.get("keywords") or "")
    max_count = int(arguments.get("max_count") or 0)

    if source == "gaode":
        pois = await fetch_pois_by_polygon(
            polygon,
            keywords=keywords or str(arguments.get("keywords") or ""),
            types=types,
            max_count=max_count,
        )
    else:
        year = arguments.get("year")
        pois = await fetch_local_pois_by_polygon(
            polygon,
            types=types,
            year=int(year) if isinstance(year, int) else None,
            max_count=max_count,
        )

    return ToolResult(
        tool_name="fetch_pois_in_scope",
        status="success",
        result={
            "poi_count": len(pois),
            "source": source,
            "types": types,
            "keywords": keywords,
        },
        evidence=[
            {"field": "poi.count", "value": len(pois)},
            {"field": "poi.source", "value": source},
        ],
        warnings=[] if pois else ["当前范围未命中 POI 数据"],
        artifacts={
            "current_pois": pois,
            "current_poi_summary": {
                "total": len(pois),
                "source": source,
                "types": types,
                "keywords": keywords,
            },
        },
    )
