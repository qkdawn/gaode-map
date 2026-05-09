from __future__ import annotations

from typing import Any, Dict, List

from modules.spatial_factor_engine import build_subcategory_spatial_trends

from .providers.llm_provider import _invoke_json_role, is_llm_enabled


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


def _validate_poi_ai_analysis(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    summary_points = _clean_text_list(raw.get("summary_points"), max_items=4, max_len=180)
    insights = {
        "fastest_growth": _clean_text(raw.get("fastest_growth"), max_len=160),
        "declining_category": _clean_text(raw.get("declining_category"), max_len=160),
        "emerging_area": _clean_text(raw.get("emerging_area"), max_len=160),
        "structure_judgement": _clean_text(raw.get("structure_judgement"), max_len=220),
    }
    if not summary_points or not all(insights.values()):
        return {}
    return {"summary_points": summary_points, **insights}


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
    if not is_llm_enabled():
        return {"status": "failed", "ai_analysis": {}, "error": "llm_unavailable"}
    try:
        raw = await _invoke_json_role(
            system_prompt=_nightlight_iteration_prompt(),
            user_payload={"task": "nightlight_iteration_change", "evidence": evidence or {}},
            emit=None,
            phase="nightlight_iteration_change",
            title="生成夜光多年变化解析",
            reasoning_id="nightlight-iteration-change",
        )
        analysis = _validate_ai_analysis(raw)
        if not analysis:
            return {"status": "failed", "ai_analysis": {}, "error": "invalid_ai_analysis"}
        return {"status": "ready", "ai_analysis": analysis, "error": ""}
    except Exception as exc:
        return {"status": "failed", "ai_analysis": {}, "error": f"{exc.__class__.__name__}: {exc}"}


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
    prompt = _poi_iteration_prompt()
    prompt_note = _poi_iteration_prompt_payload_note()
    if not is_llm_enabled():
        return {
            "status": "failed",
            "ai_summary": [],
            "ai_insights": {},
            "error": "llm_unavailable",
            "ai_prompt": prompt,
            "ai_prompt_payload_note": prompt_note,
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
                **spatial_fields,
            }
        growth_area = _normalize_growth_area_insight(
            analysis["emerging_area"],
            llm_evidence.get("growth_area_signal"),
        )
        return {
            "status": "ready",
            "ai_summary": analysis["summary_points"],
            "ai_insights": {
                "fastest_growth": analysis["fastest_growth"],
                "declining_category": analysis["declining_category"],
                "emerging_area": growth_area,
                "structure_judgement": analysis["structure_judgement"],
            },
            "ai_prompt": prompt,
            "ai_prompt_payload_note": prompt_note,
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
            "error": f"{exc.__class__.__name__}: {exc}",
            **spatial_fields,
        }
