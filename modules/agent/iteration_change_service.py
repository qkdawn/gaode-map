from __future__ import annotations

from typing import Any, Dict, List

from modules.spatial_factor_engine import build_subcategory_spatial_trends

from .providers.llm_provider import _invoke_json_role, is_llm_enabled
from .prompt_registry import build_prompt_snapshot, get_prompt_config


_REQUIRED_FIELDS = ("headline", "trend_summary", "hotspot_migration", "risk_or_opportunity")


def _clean_text(value: Any, max_len: int = 360) -> str:
    if isinstance(value, dict):
        category = _clean_text(value.get("category"), max_len=80)
        subcategory = _clean_text(value.get("subcategory"), max_len=80)
        area = _clean_text(value.get("area") or value.get("region"), max_len=80)
        parts: List[str] = []
        if category:
            parts.append(f"大类：{category}")
        if subcategory:
            suffix = f"（{category}）" if category and category not in subcategory else ""
            parts.append(f"小类：{subcategory}{suffix}")
        if area:
            parts.append(f"区域：{area}")
        for key, label in (
            ("delta", "变化"),
            ("change", "变化"),
            ("count", "数量"),
            ("ratio", "占比"),
            ("evidence", "证据"),
        ):
            raw = value.get(key)
            if raw not in (None, ""):
                parts.append(f"{label}：{raw}")
        text = "；".join(parts) if parts else "；".join(
            f"{key}：{item}" for key, item in value.items() if item not in (None, "")
        )
    elif isinstance(value, list):
        text = "；".join(_clean_text(item, max_len=max_len) for item in value)
    else:
        text = str(value or "").strip()
    if not text:
        return ""
    return text[:max_len]


def _validate_ai_analysis(raw: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized = {key: _clean_text(raw.get(key)) for key in _REQUIRED_FIELDS}
    if not all(normalized.values()):
        return {}
    return normalized


def _build_output_validation_result(config: Any, output: Any, *, checks: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    return {
        "source": "backend",
        "prompt_key": getattr(config, "prompt_key", ""),
        "evidence_version": getattr(config, "evidence_version", ""),
        "status": "passed" if output else "failed",
        "output_schema": getattr(config, "output_schema", {}) or {},
        "validated_output": output or {},
        "checks": checks or [],
        "note": "该验证结果由后端本次生成链路写入，展示内容与实际采用的输出一致。",
    }


def _required_field_checks(output: Dict[str, Any], required: List[str]) -> List[Dict[str, Any]]:
    source = output if isinstance(output, dict) else {}
    return [
        {
            "key": f"required.{field}",
            "label": f"必填字段 {field}",
            "passed": bool(source.get(field)),
        }
        for field in required
    ]


def _clean_text_list(value: Any, *, max_items: int = 4, max_len: int = 180) -> List[str]:
    source = value if isinstance(value, list) else [value]
    rows: List[str] = []
    for item in source:
        text = _clean_text(item, max_len=max_len)
        if text:
            rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


def _clean_long_text(value: Any, *, max_len: int = 12000) -> str:
    if isinstance(value, (dict, list)):
        return ""
    text = str(value or "").strip()
    return text[:max_len] if text else ""


def _clean_string_map(value: Any, *, allowed_keys: List[str] | None = None, max_len: int = 360) -> Dict[str, str]:
    source = value if isinstance(value, dict) else {"interpretation": value}
    result: Dict[str, str] = {}
    for key in allowed_keys or list(source.keys()):
        text = _clean_text(source.get(key), max_len=max_len)
        if text:
            result[key] = text
    return result


def _clean_string_map_list(value: Any, *, allowed_keys: List[str], max_items: int = 5, max_len: int = 360) -> List[Dict[str, str]]:
    rows = value if isinstance(value, list) else []
    result: List[Dict[str, str]] = []
    for item in rows:
        row = _clean_string_map(item, allowed_keys=allowed_keys, max_len=max_len)
        if row:
            result.append(row)
        if len(result) >= max_items:
            break
    return result


def _insight_text(value: Any) -> str:
    if isinstance(value, dict):
        return "；".join(str(item) for item in value.values() if item)
    if isinstance(value, list):
        return "；".join(_insight_text(item) for item in value if item)
    return str(value or "")


def _validate_poi_ai_analysis(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    summary_points = _clean_text_list(raw.get("summary_points"), max_items=5, max_len=80)
    insights = {
        "fastest_growth": _clean_string_map(
            raw.get("fastest_growth"),
            allowed_keys=["name", "evidence", "interpretation", "category", "subcategory", "delta", "change", "count"],
            max_len=360,
        ),
        "declining_category": _clean_string_map(
            raw.get("declining_category"),
            allowed_keys=["name", "evidence", "interpretation", "category", "subcategory", "delta", "change", "count"],
            max_len=360,
        ),
        "emerging_area": _clean_string_map(
            raw.get("emerging_area"),
            allowed_keys=["area_signal", "evidence", "interpretation", "area", "region", "direction", "ring"],
            max_len=360,
        ),
        "structure_judgement": _clean_string_map(
            raw.get("structure_judgement"),
            allowed_keys=["current_structure", "trend", "reason", "interpretation"],
            max_len=420,
        ),
    }
    if not summary_points or not all(_insight_text(value) for value in insights.values()):
        return {}
    driver_analysis = _clean_string_map_list(
        raw.get("driver_analysis"),
        allowed_keys=["driver", "evidence", "confidence", "explanation"],
        max_items=4,
        max_len=420,
    )
    planning_implications = _clean_string_map_list(
        raw.get("planning_implications"),
        allowed_keys=["implication", "evidence", "suggested_direction"],
        max_items=5,
        max_len=420,
    )
    if not driver_analysis or not planning_implications:
        return {}
    return {
        "summary_points": summary_points,
        **insights,
        "driver_analysis": driver_analysis,
        "planning_implications": planning_implications,
    }


def _growth_area_fallback_text(growth_signal: Dict[str, Any] | None) -> str:
    signal = growth_signal if isinstance(growth_signal, dict) else {}
    rows = [row for row in signal.get("growth_rows") or [] if isinstance(row, dict)]
    if not rows:
        return "未形成可命名增长片区；当前空间增量信号有限。"
    parts = []
    for row in rows[:3]:
        name = _clean_text(row.get("name"), max_len=40)
        delta = _as_int(row.get("delta"), 0)
        direction = _clean_text(row.get("dominant_direction") or row.get("centroid_shift_direction"), max_len=20)
        ring = _clean_text(row.get("dominant_ring"), max_len=20)
        hotspot = _as_int(row.get("hotspot_grid_count"), 0)
        row_parts = [name or "新增小类"]
        if delta > 0:
            row_parts.append(f"+{delta}")
        if direction:
            row_parts.append(f"偏{direction}")
        if ring:
            row_parts.append(ring)
        if hotspot:
            row_parts.append(f"热点{hotspot}格")
        parts.append("，".join(row_parts))
    return f"未形成可命名增长片区；新增 POI 主要表现为{'；'.join(parts)}。"


def _normalize_growth_area_insight(text: str, growth_signal: Dict[str, Any] | None) -> str:
    value = _clean_text(text, max_len=180)
    if not value:
        return _growth_area_fallback_text(growth_signal)
    old_area_terms = ("新兴区域", "新兴片区")
    weak_negative = "未发现明显" in value or "没有明显" in value or "暂无明显" in value
    if any(term in value for term in old_area_terms):
        fallback = _growth_area_fallback_text(growth_signal)
        if weak_negative:
            return fallback
        value = value.replace("新兴区域", "增长片区").replace("新兴片区", "增长片区")
    return value


def _normalize_growth_area_value(value: Any, growth_signal: Dict[str, Any] | None) -> Any:
    if not isinstance(value, dict):
        return _normalize_growth_area_insight(value, growth_signal)
    result = dict(value)
    target_key = "area_signal" if _clean_text(result.get("area_signal"), max_len=180) else "interpretation"
    normalized = _normalize_growth_area_insight(result.get(target_key), growth_signal)
    if normalized:
        result[target_key] = normalized
    return result


def enrich_poi_iteration_spatial_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(evidence or {})
    if payload.get("spatial_factors") and payload.get("subcategory_spatial_trend_rows"):
        return payload
    spatial = build_subcategory_spatial_trends(
        payload.get("summaries") or [],
        center=payload.get("center") or payload.get("center_gcj02"),
    )
    payload.update(spatial)
    return payload


def _limit_list(value: Any, limit: int) -> List[Any]:
    if not isinstance(value, list):
        return []
    return value[: max(0, limit)]


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_category_mix(value: Any, *, group_limit: int = 10, item_limit: int = 12) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    rows: Dict[str, Any] = {}
    for idx, (category, items) in enumerate(value.items()):
        if idx >= group_limit:
            break
        rows[str(category)] = _limit_list(items, item_limit)
    return rows


def _summary_count(summary: Dict[str, Any], key: str, name: str) -> int:
    source = summary.get(key)
    if not isinstance(source, dict):
        return 0
    return _as_int(source.get(name), 0)


def _ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 6)


def _change_rate(first_count: int, last_count: int) -> float | None:
    if first_count <= 0:
        return None
    return round((last_count - first_count) / first_count, 6)


def _is_low_base_change(first_count: int, last_count: int) -> bool:
    return max(first_count, last_count) < 10


def _change_rows(
    first: Dict[str, Any],
    last: Dict[str, Any],
    count_key: str,
    *,
    parent_lookup: Dict[str, str] | None = None,
    spatial_names: set[str] | None = None,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    first_counts = first.get(count_key) if isinstance(first.get(count_key), dict) else {}
    last_counts = last.get(count_key) if isinstance(last.get(count_key), dict) else {}
    names = sorted({str(name) for name in [*first_counts.keys(), *last_counts.keys()] if str(name)})
    first_total = max(0, _as_int(first.get("count"), 0))
    last_total = max(0, _as_int(last.get("count"), 0))
    parent_lookup = parent_lookup or {}
    spatial_names = spatial_names or set()
    rows = []
    for name in names:
        first_count = _as_int(first_counts.get(name), 0)
        last_count = _as_int(last_counts.get(name), 0)
        row = {
            "name": name,
            "first_count": first_count,
            "last_count": last_count,
            "delta": last_count - first_count,
            "rate": _change_rate(first_count, last_count),
            "first_ratio": _ratio(first_count, first_total),
            "last_ratio": _ratio(last_count, last_total),
            "is_low_base": _is_low_base_change(first_count, last_count),
        }
        if parent_lookup.get(name):
            row["parent"] = parent_lookup[name]
        if name in spatial_names:
            row["has_spatial_signal"] = True
        rows.append(row)
    rows.sort(
        key=lambda row: (
            1 if row.get("has_spatial_signal") else 0,
            abs(_as_int(row.get("delta"), 0)),
            _as_number(row.get("last_ratio"), 0.0),
            _as_int(row.get("last_count"), 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _material_change_rows(rows: List[Dict[str, Any]], direction: str, limit: int = 5) -> List[Dict[str, Any]]:
    sign = 1 if direction == "growth" else -1
    source = [
        row for row in rows
        if isinstance(row, dict) and (_as_int(row.get("delta"), 0) * sign) > 0
    ]
    source.sort(
        key=lambda row: (
            abs(_as_int(row.get("delta"), 0)),
            0 if row.get("is_low_base") else 1,
            _as_number(row.get("last_ratio"), 0.0),
            _as_int(row.get("last_count"), 0),
        ),
        reverse=True,
    )
    return source[:limit]


def _low_base_change_rows(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    source = [
        row for row in rows
        if isinstance(row, dict) and row.get("is_low_base") and _as_int(row.get("delta"), 0) > 0
    ]
    source.sort(
        key=lambda row: (
            _as_number(row.get("rate"), 0.0),
            abs(_as_int(row.get("delta"), 0)),
        ),
        reverse=True,
    )
    return source[:limit]


def _material_change_highlights(
    category_changes: List[Dict[str, Any]],
    subcategory_changes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "ranking_policy": "primary_rank_by_absolute_delta_then_last_ratio_and_last_count; percentage_rate_is_secondary",
        "category_growth": _material_change_rows(category_changes, "growth", 5),
        "category_decline": _material_change_rows(category_changes, "decline", 5),
        "subcategory_growth": _material_change_rows(subcategory_changes, "growth", 8),
        "subcategory_decline": _material_change_rows(subcategory_changes, "decline", 8),
        "low_base_growth_watchlist": _low_base_change_rows(category_changes + subcategory_changes, 8),
    }


def _growth_area_signal(spatial_trends: List[Dict[str, Any]], limit: int = 5) -> Dict[str, Any]:
    growth_rows = [
        row for row in spatial_trends
        if isinstance(row, dict) and _as_int(row.get("delta"), 0) > 0
    ]
    growth_rows.sort(
        key=lambda row: (
            _as_int(row.get("delta"), 0),
            _as_number(row.get("centroid_shift_m"), 0.0),
            _as_int(row.get("hotspot_grid_count"), 0),
        ),
        reverse=True,
    )
    compact = []
    for row in growth_rows[:limit]:
        compact.append({
            "name": row.get("name"),
            "parent": row.get("parent"),
            "delta": row.get("delta"),
            "dominant_direction": row.get("dominant_direction"),
            "secondary_direction": row.get("secondary_direction"),
            "dominant_ring": row.get("dominant_ring"),
            "centroid_shift_direction": row.get("centroid_shift_direction"),
            "centroid_shift_m": row.get("centroid_shift_m"),
            "hotspot_grid_count": row.get("hotspot_grid_count"),
            "hotspot_grid_count_delta": row.get("hotspot_grid_count_delta"),
            "top_area": row.get("top_area"),
        })
    return {
        "label": "growth_area_direction",
        "interpretation_policy": "describe internal growth direction/ring/hotspots inside the isochrone; do not require an administrative new area name",
        "has_named_area": False,
        "growth_rows": compact,
    }


def _subcategory_parent_lookup(summaries: List[Dict[str, Any]]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for summary in summaries:
        for item in _limit_list(summary.get("top_subcategories"), 200):
            if isinstance(item, dict) and item.get("name") and item.get("parent"):
                lookup[str(item["name"])] = str(item["parent"])
        mix = summary.get("category_to_subcategory_mix")
        if isinstance(mix, dict):
            for category, rows in mix.items():
                for item in _limit_list(rows, 200):
                    if isinstance(item, dict) and item.get("name"):
                        lookup.setdefault(str(item["name"]), str(item.get("parent") or category))
    return lookup


def _compact_poi_year_summary(summary: Any) -> Dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    return {
        "year": summary.get("year"),
        "poi_count": summary.get("count"),
        "category_count": summary.get("category_count"),
        "top_categories": _limit_list(summary.get("top_categories"), 8),
        "subcategory_count": summary.get("subcategory_count"),
        "top_subcategories": _limit_list(summary.get("top_subcategories"), 12),
        "top_areas": _limit_list(summary.get("top_areas"), 8),
    }


def _compact_area_distribution(row: Any) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    cells = row.get("cells") if isinstance(row.get("cells"), list) else []
    sorted_cells = sorted(
        cells,
        key=lambda cell: float((cell or {}).get("intensity") or 0) if isinstance(cell, dict) else 0.0,
        reverse=True,
    )[:12]
    top_cells = []
    for idx, cell in enumerate(sorted_cells, start=1):
        if not isinstance(cell, dict):
            continue
        top_cells.append({
            "rank": idx,
            "intensity": cell.get("intensity"),
            "poi_count": cell.get("count") or cell.get("poi_count") or cell.get("point_count"),
        })
    return {
        "year": row.get("year"),
        "point_count": row.get("point_count"),
        "top_area": row.get("top_area"),
        "hotspot_cell_count": len(cells),
        "top_cells": top_cells,
    }


def _scope_from_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    summaries = _limit_list(evidence.get("summaries"), 8)
    top_area = ""
    for summary in reversed(summaries):
        if isinstance(summary, dict):
            area = _limit_list(summary.get("top_areas"), 1)
            if area and isinstance(area[0], dict) and area[0].get("name"):
                top_area = str(area[0]["name"])
                break
    polygon = evidence.get("area_heatmap_polygon")
    return {
        "center": evidence.get("center") or evidence.get("center_gcj02"),
        "area_name": top_area,
        "scope_type": "history_polygon" if isinstance(polygon, list) and polygon else "point_bounds",
        "polygon_point_count": len(polygon) if isinstance(polygon, list) else 0,
    }


def _compact_spatial_trends(rows: Any, limit: int = 30) -> List[Dict[str, Any]]:
    source = rows if isinstance(rows, list) else []
    def score(row: Any) -> tuple[int, int, int, int, int]:
        if not isinstance(row, dict):
            return (0, 0, 0, 0, 0)
        return (
            1 if row.get("dominant_direction") else 0,
            1 if _as_number(row.get("centroid_shift_m"), 0.0) > 0 else 0,
            1 if _as_number(row.get("hotspot_grid_count"), 0.0) > 0 else 0,
            1 if row.get("top_area") else 0,
            abs(_as_int(row.get("delta"), 0)),
        )
    compact = []
    for row in sorted(source, key=score, reverse=True)[:limit]:
        if not isinstance(row, dict):
            continue
        compact.append({
            "name": row.get("name"),
            "parent": row.get("parent"),
            "delta": row.get("delta"),
            "dominant_direction": row.get("dominant_direction"),
            "secondary_direction": row.get("secondary_direction"),
            "dominant_ring": row.get("dominant_ring"),
            "centroid_shift_direction": row.get("centroid_shift_direction"),
            "centroid_shift_m": row.get("centroid_shift_m"),
            "hotspot_grid_count": row.get("hotspot_grid_count"),
            "hotspot_grid_count_delta": row.get("hotspot_grid_count_delta"),
            "top_area": row.get("top_area"),
        })
    return compact


def _compact_h3_evidence(value: Any, cell_limit: int = 240, row_limit: int = 40) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cells = value.get("cells") if isinstance(value.get("cells"), list) else []
    compact_cells: List[Dict[str, Any]] = []
    for cell in cells[:cell_limit]:
        if not isinstance(cell, dict):
            continue
        h3_id = str(cell.get("h3_id") or "").strip()
        if not h3_id:
            continue
        compact_cells.append(
            {
                "h3_id": h3_id,
                "poi_count": cell.get("poi_count"),
                "density_poi_per_km2": cell.get("density_poi_per_km2"),
                "local_entropy": cell.get("local_entropy"),
                "neighbor_mean_density": cell.get("neighbor_mean_density"),
                "neighbor_mean_entropy": cell.get("neighbor_mean_entropy"),
                "neighbor_count": cell.get("neighbor_count"),
                "category_counts": cell.get("category_counts") or {},
                "gi_star_z_score": cell.get("gi_star_z_score"),
                "gi_star_value": cell.get("gi_star_value"),
                "lisa_i": cell.get("lisa_i"),
                "lisa_z_score": cell.get("lisa_z_score"),
            }
        )

    derived = value.get("derived_stats") if isinstance(value.get("derived_stats"), dict) else {}

    def compact_rows(section_key: str) -> List[Dict[str, Any]]:
        rows = derived.get(section_key)
        if isinstance(rows, list):
            return _limit_list(rows, row_limit)
        return []

    def compact_summary(section_key: str) -> Dict[str, Any]:
        source = derived.get(section_key)
        if isinstance(source, dict):
            return source
        return {}

    return {
        "evidence_version": value.get("evidence_version") or "poi_h3_evidence_v1",
        "grid_type": value.get("grid_type") or "h3",
        "usage": value.get("usage") or "POI-only H3 spatial structure evidence",
        "params": value.get("params") or {},
        "counts": value.get("counts") or {},
        "metrics": value.get("metrics") or {},
        "summary": value.get("summary") or {},
        "charts": value.get("charts") or {},
        "ui": value.get("ui") or {},
        "category_meta": _limit_list(value.get("category_meta"), 80),
        "cells": compact_cells,
        "omitted": value.get("omitted") or {
            "cells_total": ((value.get("counts") or {}).get("cell_count") if isinstance(value.get("counts"), dict) else len(cells)),
            "cells_included": len(compact_cells),
            "geometry_removed": True,
        },
        "derived_stats": {
            "structure_rows": compact_rows("structure_rows"),
            "typing_rows": compact_rows("typing_rows"),
            "lq_rows": compact_rows("lq_rows"),
            "gap_rows": compact_rows("gap_rows"),
            "structure_summary": compact_summary("structure_summary"),
            "typing_summary": compact_summary("typing_summary"),
            "lq_summary": compact_summary("lq_summary"),
            "gap_summary": compact_summary("gap_summary"),
        },
        "constraints": {
            "poi_only": True,
            "do_not_use_for_population_nightlight_coupling": True,
        },
    }


def _compact_raster_grid_evidence(value: Any, row_limit: int = 24) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    counts = value.get("counts") if isinstance(value.get("counts"), dict) else {}
    top_cells = summary.get("top_cells") if isinstance(summary.get("top_cells"), list) else value.get("top_cells")
    return {
        "evidence_version": value.get("evidence_version") or "poi_raster_grid_evidence_v1",
        "grid_type": value.get("grid_type") or "raster",
        "params": value.get("params") or {},
        "counts": counts,
        "summary": {
            key: val
            for key, val in summary.items()
            if key != "top_cells"
        },
        "top_cells": _limit_list(top_cells, row_limit),
    }


def _compact_yearly_grid_evidence(value: Any, year_limit: int = 8) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    items = []
    for item in _limit_list(value.get("items"), year_limit):
        if not isinstance(item, dict):
            continue
        items.append({
            "year": item.get("year"),
            "status": item.get("status") or "ready",
            "error": item.get("error") or "",
            "grid_scope": item.get("grid_scope") or value.get("grid_scope") or "poi_iteration_h3_per_year",
            "h3_evidence": _compact_h3_evidence(item.get("h3_evidence"), cell_limit=80, row_limit=20),
        })
    return {
        "evidence_version": value.get("evidence_version") or "poi_iteration_yearly_grid_evidence_v1",
        "grid_scope": value.get("grid_scope") or "poi_iteration_h3_per_year",
        "grid_type": value.get("grid_type") or "h3",
        "years": _limit_list(value.get("years"), year_limit),
        "latest_year": value.get("latest_year"),
        "latest_h3_evidence": _compact_h3_evidence(value.get("latest_h3_evidence"), cell_limit=80, row_limit=20),
        "items": items,
        "constraints": {
            "per_year_grid": True,
            "use_for_spatial_evolution": True,
        },
    }


def build_poi_iteration_evidence_pack_v1(enriched_evidence: Dict[str, Any]) -> Dict[str, Any]:
    evidence = enriched_evidence if isinstance(enriched_evidence, dict) else {}
    summaries = [
        summary for summary in _limit_list(evidence.get("summaries"), 8)
        if isinstance(summary, dict)
    ]
    first = summaries[0] if summaries else {}
    last = summaries[-1] if summaries else {}
    spatial_trends = _compact_spatial_trends(evidence.get("subcategory_spatial_trend_rows"), 30)
    spatial_names = {
        str(row.get("name"))
        for row in spatial_trends
        if isinstance(row, dict) and row.get("name")
    }
    parent_lookup = _subcategory_parent_lookup(summaries)
    category_changes = _change_rows(first, last, "category_counts", limit=12)
    subcategory_changes = _change_rows(
        first,
        last,
        "subcategory_counts",
        parent_lookup=parent_lookup,
        spatial_names=spatial_names,
        limit=24,
    )
    return {
        "task": "poi_iteration_change",
        "evidence_version": "poi_iteration_v1",
        "years": _limit_list(evidence.get("years"), 8),
        "scope": _scope_from_evidence(evidence),
        "year_summaries": [
            row for row in (_compact_poi_year_summary(summary) for summary in summaries) if row
        ],
        "trend_metrics": _limit_list(evidence.get("trend_rows"), 16),
        "category_changes": category_changes,
        "subcategory_changes": subcategory_changes,
        "material_change_highlights": _material_change_highlights(category_changes, subcategory_changes),
        "spatial_factors": evidence.get("spatial_factors") or {},
        "subcategory_spatial_trends": spatial_trends,
        "growth_area_signal": _growth_area_signal(spatial_trends),
        "h3_evidence": _compact_h3_evidence(evidence.get("h3_evidence")),
        "yearly_grid_evidence": _compact_yearly_grid_evidence(evidence.get("yearly_grid_evidence")),
        "area_distribution": [
            row for row in (_compact_area_distribution(heatmap) for heatmap in _limit_list(evidence.get("area_heatmaps"), 8)) if row
        ],
        "rule_insights": evidence.get("rule_insights") or {},
        "constraints": {
            "no_invented_places": True,
            "no_coordinate_reasoning": True,
            "no_low_base_rate_as_primary": True,
            "growth_ranking_policy": "use material_change_highlights; rank by absolute delta before percentage rate",
            "output_language": "zh-CN",
        },
    }


def build_poi_iteration_llm_evidence(enriched_evidence: Dict[str, Any]) -> Dict[str, Any]:
    return build_poi_iteration_evidence_pack_v1(enriched_evidence)


def _nightlight_iteration_prompt() -> str:
    return (
        "你是商业地理与夜光遥感分析助手。"
        "请基于近三年夜光序列、热点迁移分类和年度快照元信息，判断区域夜间经济活动的热点变化和迁移趋势。"
        "只输出 JSON 对象，字段必须为 headline, trend_summary, hotspot_migration, risk_or_opportunity。"
        "不要编造未给出的方向、道路或商圈名称；证据不足时明确说明趋势信号有限。不要输出 markdown。"
    )


def _poi_iteration_prompt() -> str:
    return (
        "你是商业地理与 POI 多年变化分析助手。"
        "请基于 poi_iteration_v1 证据包中的 year_summaries、trend_metrics、category_changes、"
        "subcategory_changes、area_distribution、spatial_factors、subcategory_spatial_trends 和 growth_area_signal 生成解释。"
        "必须先概括 POI 总量、一级业态和关键小类数量变化，再使用 spatial_factors 与 subcategory_spatial_trends 说明小类位置变化。"
        "位置判断只能来自 spatial_factors、subcategory_spatial_trends、area_distribution 和 evidence 中已有区域字段，"
        "不得凭坐标或想象地图编造方向、商圈、道路名、地标或百分比。"
        "emerging_area 字段表示增长片区/空间增量方向，不是行政区新区域；优先使用 growth_area_signal，说明增长小类、方位、圈层、重心迁移和热点格。如果没有可命名片区，不要写“未发现明显新兴区域”，应写“未形成可命名片区，但新增 POI 主要表现为...方向/...圈层补点”。"
        "fastest_growth 和 declining_category 必须优先使用 material_change_highlights；排序按绝对增减量、末年占比、末年数量，百分比增速只能作为补充。"
        "first_count/last_count 均小于 10 的低基数项不得作为主导增长行业，只能作为小基数提示。"
        "只输出 JSON 对象，字段必须为 summary_points, fastest_growth, declining_category, emerging_area, structure_judgement。"
        "summary_points 必须是 2 到 4 条中文短句；其余字段必须是中文字符串，不要返回对象或数组。"
        "不要把小类当成独立大类，不要编造 evidence 中没有出现的行业、小类、区域、商圈或道路。"
        "证据不足时明确说明趋势信号有限。不要输出 markdown。"
    )


def _poi_iteration_prompt_payload_note() -> str:
    return (
        "User payload: {\"task\":\"poi_iteration_change\",\"evidence\": poi_iteration_v1 证据包}。"
        "evidence 只包含年摘要、趋势指标、业态/小类变化、空间因子、小类空间信号、增长片区信号和区域分布摘要；"
        "不包含全量 POI 点、图片 base64、底图、完整热力格或前端 UI 状态。"
    )


async def generate_nightlight_iteration_analysis(evidence: Dict[str, Any]) -> Dict[str, Any]:
    config = get_prompt_config("nightlight_iteration")
    snapshot = build_prompt_snapshot(config)
    if not is_llm_enabled():
        return {
            "status": "failed",
            "ai_analysis": {},
            "error": "llm_unavailable",
            "ai_prompt": config.system_prompt,
            "ai_prompt_payload_note": config.payload_note,
            "prompt_snapshot": snapshot,
            "prompt_snapshots": {"nightlight_iteration": snapshot},
        }
    try:
        raw = await _invoke_json_role(
            system_prompt=config.system_prompt,
            user_payload={"task": "nightlight_iteration_change", "evidence": evidence or {}},
            emit=None,
            phase="nightlight_iteration_change",
            title="生成夜光多年变化解析",
            reasoning_id="nightlight-iteration-change",
        )
        analysis = _validate_ai_analysis(raw)
        if not analysis:
            return {
                "status": "failed",
                "ai_analysis": {},
                "error": "invalid_ai_analysis",
                "ai_prompt": config.system_prompt,
                "ai_prompt_payload_note": config.payload_note,
                "prompt_snapshot": snapshot,
                "prompt_snapshots": {"nightlight_iteration": snapshot},
            }
        return {
            "status": "ready",
            "ai_analysis": analysis,
            "error": "",
            "ai_prompt": config.system_prompt,
            "ai_prompt_payload_note": config.payload_note,
            "prompt_snapshot": snapshot,
            "prompt_snapshots": {"nightlight_iteration": snapshot},
            "validation_results": {
                "nightlight_iteration": _build_output_validation_result(
                    config,
                    analysis,
                    checks=_required_field_checks(analysis, list(_REQUIRED_FIELDS)),
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "ai_analysis": {},
            "error": f"{exc.__class__.__name__}: {exc}",
            "ai_prompt": config.system_prompt,
            "ai_prompt_payload_note": config.payload_note,
            "prompt_snapshot": snapshot,
            "prompt_snapshots": {"nightlight_iteration": snapshot},
        }


def _poi_spatial_response_fields(enriched_evidence: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "spatial_factors": enriched_evidence.get("spatial_factors") or {},
        "subcategory_spatial_trend_rows": enriched_evidence.get("subcategory_spatial_trend_rows") or [],
        "subcategory_spatial_summary": enriched_evidence.get("subcategory_spatial_summary") or [],
    }


async def generate_poi_iteration_analysis(evidence: Dict[str, Any]) -> Dict[str, Any]:
    enriched_evidence = enrich_poi_iteration_spatial_evidence(evidence or {})
    spatial_fields = _poi_spatial_response_fields(enriched_evidence)
    llm_evidence = build_poi_iteration_llm_evidence(enriched_evidence)
    config = get_prompt_config("poi_iteration")
    prompt = config.system_prompt
    prompt_note = config.payload_note
    prompt_snapshot = build_prompt_snapshot(config)
    if not is_llm_enabled():
        return {
            "status": "failed",
            "ai_summary": [],
            "ai_insights": {},
            "error": "llm_unavailable",
            "ai_prompt": prompt,
            "ai_prompt_payload_note": prompt_note,
            "prompt_snapshot": prompt_snapshot,
            "prompt_snapshots": {"poi_iteration": prompt_snapshot},
            **spatial_fields,
        }
    try:
        raw = await _invoke_json_role(
            system_prompt=prompt,
            user_payload={"task": "poi_iteration_change", "evidence": llm_evidence},
            emit=None,
            phase="poi_iteration_change",
            title="生成 POI 多年变化解析",
            reasoning_id="poi-iteration-change",
        )
        analysis = _validate_poi_ai_analysis(raw)
        if not analysis:
            return {
                "status": "failed",
                "ai_summary": [],
                "ai_insights": {},
                "error": "invalid_ai_analysis",
                "ai_prompt": prompt,
                "ai_prompt_payload_note": prompt_note,
                "prompt_snapshot": prompt_snapshot,
                "prompt_snapshots": {"poi_iteration": prompt_snapshot},
                **spatial_fields,
            }
        growth_area = _normalize_growth_area_value(
            analysis["emerging_area"],
            llm_evidence.get("growth_area_signal"),
        )
        ai_insights = {
            "fastest_growth": analysis["fastest_growth"],
            "declining_category": analysis["declining_category"],
            "emerging_area": growth_area,
            "structure_judgement": analysis["structure_judgement"],
            "driver_analysis": analysis.get("driver_analysis") or [],
            "planning_implications": analysis.get("planning_implications") or [],
        }
        return {
            "status": "ready",
            "ai_summary": analysis["summary_points"],
            "ai_insights": ai_insights,
            "driver_analysis": analysis.get("driver_analysis") or [],
            "planning_implications": analysis.get("planning_implications") or [],
            "ai_prompt": prompt,
            "ai_prompt_payload_note": prompt_note,
            "prompt_snapshot": prompt_snapshot,
            "prompt_snapshots": {"poi_iteration": prompt_snapshot},
            "validation_results": {
                "poi_iteration": _build_output_validation_result(
                    config,
                    {
                        "summary_points": analysis["summary_points"],
                        "fastest_growth": analysis["fastest_growth"],
                        "declining_category": analysis["declining_category"],
                        "emerging_area": growth_area,
                        "structure_judgement": analysis["structure_judgement"],
                        "driver_analysis": analysis.get("driver_analysis") or [],
                        "planning_implications": analysis.get("planning_implications") or [],
                    },
                    checks=_required_field_checks(analysis, [
                        "summary_points",
                        "fastest_growth",
                        "declining_category",
                        "emerging_area",
                        "structure_judgement",
                        "driver_analysis",
                        "planning_implications",
                    ]),
                ),
            },
            "error": "",
            **spatial_fields,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "ai_summary": [],
            "ai_insights": {},
            "ai_prompt": prompt,
            "ai_prompt_payload_note": prompt_note,
            "prompt_snapshot": prompt_snapshot,
            "prompt_snapshots": {"poi_iteration": prompt_snapshot},
            "error": f"{exc.__class__.__name__}: {exc}",
            **spatial_fields,
        }
