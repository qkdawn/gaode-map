from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from modules.history.service import get_history_pois_payload


_TYPE_MAP_PATH = Path(__file__).resolve().parents[2] / "share" / "type_map.json"
_TYPE_CONFIG: Dict[str, Any] = json.loads(_TYPE_MAP_PATH.read_text(encoding="utf-8"))


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _to_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _normalize_type_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _build_type_indexes() -> Dict[str, Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_label: Dict[str, Dict[str, Any]] = {}
    by_typecode: Dict[str, Dict[str, Any]] = {}
    for group in _TYPE_CONFIG.get("groups") or []:
        group_title = _as_text(group.get("title")) or _as_text(group.get("id")) or "未分类"
        for item in group.get("items") or []:
            row = {
                "id": _as_text(item.get("id")),
                "label": _as_text(item.get("label")),
                "parent": group_title,
            }
            if row["id"]:
                by_id[row["id"]] = row
            if row["label"]:
                by_label[row["label"]] = row
            for raw_code in _as_text(item.get("types")).split("|"):
                code = _normalize_type_code(raw_code)
                if code:
                    by_typecode[code] = row
    return {"by_id": by_id, "by_label": by_label, "by_typecode": by_typecode}


_TYPE_INDEXES = _build_type_indexes()


def _resolve_poi_type(poi: Dict[str, Any]) -> Dict[str, str]:
    raw_type = _as_text(poi.get("type") or poi.get("typecode") or poi.get("type_code"))
    typecode = _normalize_type_code(poi.get("typecode") or poi.get("type_code") or raw_type)
    item = (
        _TYPE_INDEXES["by_id"].get(raw_type)
        or _TYPE_INDEXES["by_label"].get(raw_type)
        or _TYPE_INDEXES["by_typecode"].get(typecode)
    )
    if item:
        return {
            "category": item["parent"] or "未分类",
            "subcategory": item["label"] or "未分类小类",
            "subcategory_id": item["id"],
            "raw_type": raw_type,
        }
    labels = [part.strip() for part in raw_type.replace("，", ";").replace(",", ";").replace("/", ";").split(";") if part.strip()]
    return {
        "category": labels[0] if labels else "未分类",
        "subcategory": (labels[1] if len(labels) > 1 else (labels[0] if labels else "未分类小类")),
        "subcategory_id": "",
        "raw_type": raw_type,
    }


def _sort_count_rows(counter: Counter, total: int, extra=None) -> List[Dict[str, Any]]:
    total = max(1, int(total or 0))
    extra = extra or (lambda _name, _count: {})
    rows = [
        {"name": name, "count": int(count), "ratio": int(count) / total, **extra(name, int(count))}
        for name, count in counter.items()
    ]
    return sorted(rows, key=lambda item: (-int(item["count"]), _as_text(item["name"])))


def summarize_iteration_pois(pois: Iterable[Dict[str, Any]], year: Optional[int] = None) -> Dict[str, Any]:
    poi_list = [item for item in pois or [] if isinstance(item, dict)]
    category_counts: Counter[str] = Counter()
    subcategory_counts: Counter[str] = Counter()
    subcategory_parent: Dict[str, str] = {}
    category_to_subcategory: Dict[str, Counter[str]] = defaultdict(Counter)
    area_counts: Counter[str] = Counter()
    points: List[Dict[str, Any]] = []

    for poi in poi_list:
        type_info = _resolve_poi_type(poi)
        category = type_info["category"] or "未分类"
        subcategory = type_info["subcategory"] or "未分类小类"
        category_counts[category] += 1
        subcategory_counts[subcategory] += 1
        subcategory_parent.setdefault(subcategory, category)
        category_to_subcategory[category][subcategory] += 1
        area = _as_text(poi.get("adname") or poi.get("cityname") or poi.get("pname") or poi.get("area")) or "未知区域"
        area_counts[area] += 1
        location = poi.get("location")
        if isinstance(location, (list, tuple)) and len(location) >= 2:
            lng = _to_number(location[0])
            lat = _to_number(location[1])
            if lng is not None and lat is not None:
                points.append({"lng": lng, "lat": lat, "category": category, "subcategory": subcategory, "area": area})

    total = len(poi_list)
    category_to_subcategory_mix = {}
    for category, child_counter in category_to_subcategory.items():
        category_total = max(1, int(category_counts.get(category) or 0))
        category_to_subcategory_mix[category] = sorted(
            [
                {"name": name, "parent": category, "count": int(count), "ratio": int(count) / category_total}
                for name, count in child_counter.items()
            ],
            key=lambda item: (-int(item["count"]), _as_text(item["name"])),
        )[:6]

    return {
        "year": int(year) if year is not None else None,
        "count": total,
        "category_count": len(category_counts),
        "subcategory_count": len(subcategory_counts),
        "top_categories": _sort_count_rows(category_counts, total)[:5],
        "top_subcategories": _sort_count_rows(
            subcategory_counts,
            total,
            lambda name, _count: {"parent": subcategory_parent.get(name) or "未分类"},
        )[:8],
        "top_areas": _sort_count_rows(area_counts, total)[:5],
        "category_counts": dict(category_counts),
        "subcategory_counts": dict(subcategory_counts),
        "category_to_subcategory_mix": category_to_subcategory_mix,
        "area_counts": dict(area_counts),
        "points": points,
    }


def build_category_stack(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if item.get("category_counts")], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    totals: Counter[str] = Counter()
    for summary in sorted_summaries:
        totals.update({name: int(count or 0) for name, count in (summary.get("category_counts") or {}).items()})
    top_names = [name for name, _count in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:5]]
    rows = []
    for summary in sorted_summaries:
        counts = summary.get("category_counts") or {}
        total = max(1, int(summary.get("count") or 0))
        segments = [{"name": name, "count": int(counts.get(name) or 0), "ratio": int(counts.get(name) or 0) / total} for name in top_names]
        known = sum(int(item["count"]) for item in segments)
        other = max(0, int(summary.get("count") or 0) - known)
        if other:
            segments.append({"name": "其他", "count": other, "ratio": other / total})
        rows.append({"year": summary.get("year"), "total": int(summary.get("count") or 0), "segments": segments})
    return rows


def build_subcategory_stack(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if item.get("subcategory_counts")], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    totals: Counter[str] = Counter()
    parent_by_name: Dict[str, str] = {}
    for summary in sorted_summaries:
        for item in summary.get("top_subcategories") or []:
            if isinstance(item, dict) and item.get("name"):
                parent_by_name.setdefault(_as_text(item.get("name")), _as_text(item.get("parent")))
        totals.update({name: int(count or 0) for name, count in (summary.get("subcategory_counts") or {}).items()})
    top_names = [name for name, _count in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:6]]
    rows = []
    for summary in sorted_summaries:
        counts = summary.get("subcategory_counts") or {}
        total = max(1, int(summary.get("count") or 0))
        segments = [
            {
                "name": name,
                "parent": parent_by_name.get(name, ""),
                "count": int(counts.get(name) or 0),
                "ratio": int(counts.get(name) or 0) / total,
            }
            for name in top_names
        ]
        known = sum(int(item["count"]) for item in segments)
        other = max(0, int(summary.get("count") or 0) - known)
        if other:
            segments.append({"name": "其他小类", "parent": "", "count": other, "ratio": other / total})
        rows.append({"year": summary.get("year"), "total": int(summary.get("count") or 0), "segments": segments})
    return rows


def build_area_heatmaps(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if item.get("points")], key=lambda item: int(item.get("year") or 0))
    all_points = [point for summary in sorted_summaries for point in (summary.get("points") or [])]
    lngs = [float(point["lng"]) for point in all_points if _to_number(point.get("lng")) is not None]
    lats = [float(point["lat"]) for point in all_points if _to_number(point.get("lat")) is not None]
    if not lngs or not lats:
        return []
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    span_lng = max(max_lng - min_lng, 1e-9)
    span_lat = max(max_lat - min_lat, 1e-9)
    rows = []
    for summary in sorted_summaries:
        points = []
        for point in summary.get("points") or []:
            lng = _to_number(point.get("lng"))
            lat = _to_number(point.get("lat"))
            if lng is None or lat is None:
                continue
            points.append(
                {
                    "x": max(4, min(96, 4 + ((lng - min_lng) / span_lng) * 92)),
                    "y": max(4, min(96, 96 - ((lat - min_lat) / span_lat) * 92)),
                    "area": _as_text(point.get("area")),
                    "category": _as_text(point.get("category")),
                    "subcategory": _as_text(point.get("subcategory")),
                }
            )
        rows.append(
            {
                "year": summary.get("year"),
                "points": points[:260],
                "point_count": len(points),
                "top_area": ((summary.get("top_areas") or [{}])[0] or {}).get("name") or "",
            }
        )
    return rows


def build_trend_rows(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if "count" in item], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    first, last = sorted_summaries[0], sorted_summaries[-1]
    first_counts = first.get("category_counts") or {}
    last_counts = last.get("category_counts") or {}
    names = sorted(set(first_counts) | set(last_counts))
    deltas = sorted(
        [{"name": name, "delta": int(last_counts.get(name) or 0) - int(first_counts.get(name) or 0)} for name in names],
        key=lambda item: (-abs(int(item["delta"])), item["name"]),
    )
    top_increase = next((item for item in deltas if item["delta"] > 0), None)
    top_decrease = next((item for item in deltas if item["delta"] < 0), None)
    total_delta = int(last.get("count") or 0) - int(first.get("count") or 0)
    return [
        {"key": "years", "label": "覆盖年份", "value": f"{first.get('year') or '-'}-{last.get('year') or '-'}"},
        {"key": "total_delta", "label": "POI 首尾变化", "value": f"{'+' if total_delta >= 0 else ''}{total_delta}"},
        {"key": "category_delta", "label": "业态类型变化", "value": f"{'+' if int(last.get('category_count') or 0) - int(first.get('category_count') or 0) >= 0 else ''}{int(last.get('category_count') or 0) - int(first.get('category_count') or 0)}"},
        {"key": "top_increase", "label": "增长最明显业态", "value": f"{top_increase['name']} +{top_increase['delta']}" if top_increase else "-"},
        {"key": "top_decrease", "label": "减少最明显业态", "value": f"{top_decrease['name']} {top_decrease['delta']}" if top_decrease else "-"},
        {"key": "latest_top", "label": "末年第一业态", "value": ((last.get("top_categories") or [{}])[0] or {}).get("name") or "-"},
    ]


def build_subcategory_trend_rows(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_summaries = sorted([item for item in summaries if "count" in item], key=lambda item: int(item.get("year") or 0))
    if len(sorted_summaries) < 2:
        return []
    first, last = sorted_summaries[0], sorted_summaries[-1]
    first_counts = first.get("subcategory_counts") or {}
    last_counts = last.get("subcategory_counts") or {}
    parent_by_name: Dict[str, str] = {}
    for item in list(first.get("top_subcategories") or []) + list(last.get("top_subcategories") or []):
        if isinstance(item, dict) and item.get("name"):
            parent_by_name.setdefault(_as_text(item.get("name")), _as_text(item.get("parent")))
    deltas = sorted(
        [
            {
                "name": name,
                "parent": parent_by_name.get(name, ""),
                "delta": int(last_counts.get(name) or 0) - int(first_counts.get(name) or 0),
            }
            for name in sorted(set(first_counts) | set(last_counts))
        ],
        key=lambda item: (-abs(int(item["delta"])), item["name"]),
    )
    top_increase = next((item for item in deltas if item["delta"] > 0), None)
    top_decrease = next((item for item in deltas if item["delta"] < 0), None)
    latest_top = (last.get("top_subcategories") or [{}])[0] or {}
    subcategory_delta = int(last.get("subcategory_count") or 0) - int(first.get("subcategory_count") or 0)
    increase_parent = f"（{top_increase['parent']}）" if top_increase and top_increase.get("parent") else ""
    decrease_parent = f"（{top_decrease['parent']}）" if top_decrease and top_decrease.get("parent") else ""
    latest_parent = f"（{latest_top.get('parent')}）" if latest_top.get("parent") else ""
    return [
        {"key": "subcategory_delta", "label": "小类类型变化", "value": f"{'+' if subcategory_delta >= 0 else ''}{subcategory_delta}"},
        {"key": "top_subcategory_increase", "label": "增长最明显小类", "value": f"{top_increase['name']}{increase_parent} +{top_increase['delta']}" if top_increase else "-"},
        {"key": "top_subcategory_decrease", "label": "减少最明显小类", "value": f"{top_decrease['name']}{decrease_parent} {top_decrease['delta']}" if top_decrease else "-"},
        {"key": "latest_top_subcategory", "label": "末年第一小类", "value": f"{latest_top.get('name')}{latest_parent}" if latest_top.get("name") else "-"},
    ]


def _format_metric(value: Any, digits: int = 0) -> str:
    number = _to_number(value)
    if number is None:
        return "0"
    return f"{number:.{digits}f}" if digits > 0 else str(int(round(number)))


def build_rule_insights(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    sorted_summaries = sorted([item for item in summaries if "count" in item], key=lambda item: int(item.get("year") or 0))
    latest = sorted_summaries[-1] if sorted_summaries else {}
    top_category = (latest.get("top_categories") or [{}])[0] or {}
    top_subcategory = (latest.get("top_subcategories") or [{}])[0] or {}
    top_area = (latest.get("top_areas") or [{}])[0] or {}
    top_subcategory_parts = []
    for item in (latest.get("top_subcategories") or [])[:3]:
        if item.get("name"):
            parent = f"（{item.get('parent')}）" if item.get("parent") else ""
            top_subcategory_parts.append(f"{item.get('name')}{parent}")
    top_subcategory_text = "、".join(top_subcategory_parts)
    single_structure_detail = f"，内部小类以{top_subcategory.get('name')}较突出" if top_subcategory.get("name") else ""
    structure_detail = f"，其下小类{top_subcategory.get('name')}表现突出" if top_subcategory.get("name") else ""
    if len(sorted_summaries) < 2:
        return {
            "summary": [
                f"当前POI规模为 {_format_metric(latest.get('count'), 0)}，一级主导业态为{top_category.get('name') or '未分类'}。",
                f"关键小类集中在{top_subcategory_text}。" if top_subcategory_text else "当前小类结构信号有限。",
                f"{top_area.get('name') or '主要区域'}为核心聚集区，呈现当前POI的主要空间承载。",
            ],
            "insights": {
                "fastest_growth": "当前只有一个年份，暂无法判断增长最快行业。",
                "declining_category": "当前只有一个年份，暂无法判断衰退行业。",
                "emerging_area": f"当前核心聚集区：{top_area.get('name')}" if top_area.get("name") else "当前缺少可识别的新兴区域信号。",
                "structure_judgement": f"一级业态以{top_category.get('name')}为主{single_structure_detail}。" if top_category.get("name") else "业态结构信号有限。",
            },
        }

    first, last = sorted_summaries[0], sorted_summaries[-1]
    total_delta = int(last.get("count") or 0) - int(first.get("count") or 0)
    top_ratio = (int(top_category.get("count") or 0) / int(last.get("count") or 1)) if int(last.get("count") or 0) > 0 else 0
    category_changes = _change_rows(first.get("category_counts") or {}, last.get("category_counts") or {})
    subcategory_changes = _change_rows(first.get("subcategory_counts") or {}, last.get("subcategory_counts") or {})
    fastest = next((item for item in sorted(category_changes, key=lambda item: (-item["rate"], -item["delta"])) if item["delta"] > 0), None)
    declining = next((item for item in sorted(category_changes, key=lambda item: (item["rate"], item["delta"])) if item["delta"] < 0), None)
    fastest_sub = next((item for item in sorted(subcategory_changes, key=lambda item: (-item["rate"], -item["delta"])) if item["delta"] > 0), None)
    declining_sub = next((item for item in sorted(subcategory_changes, key=lambda item: (item["rate"], item["delta"])) if item["delta"] < 0), None)
    growth_sub_detail = f"；小类增长最快为{fastest_sub['name']}，+{fastest_sub['delta']}" if fastest_sub else ""
    decline_sub_detail = f"；小类下降明显为{declining_sub['name']}，{declining_sub['delta']}" if declining_sub else ""
    emerging_area = next(
        (
            item
            for item in sorted(_change_rows(first.get("area_counts") or {}, last.get("area_counts") or {}), key=lambda item: -item["delta"])
            if item["delta"] > 0
        ),
        None,
    )
    return {
        "summary": [
            f"当前POI规模为 {_format_metric(last.get('count'), 0)}，较{first.get('year') or '首年'}{'增加' if total_delta >= 0 else '减少'} {_format_metric(abs(total_delta), 0)}。",
            f"{top_category.get('name') or '主导业态'}占比约 {top_ratio * 100:.1f}%，是当前一级主导业态。",
            f"小类层面以{top_subcategory_text}最为突出。" if top_subcategory_text else "小类层面暂未形成清晰主导。",
            f"{top_area.get('name') or '主要区域'}为核心聚集区，承担最多POI分布。",
            f"业态结构整体{'呈现较强主导业态特征' if top_ratio >= 0.25 else '较分散'}。",
        ],
        "insights": {
            "fastest_growth": f"{fastest['name']}大类增长较快（+{fastest['delta']}，+{fastest['rate'] * 100:.1f}%）{growth_sub_detail}" if fastest else "未发现明显增长行业。",
            "declining_category": f"{declining['name']}大类下降明显（{declining['delta']}，{declining['rate'] * 100:.1f}%）{decline_sub_detail}" if declining else "未发现明显衰退行业。",
            "emerging_area": f"{emerging_area['name']}（+{emerging_area['delta']}）" if emerging_area else "未发现明显新兴区域。",
            "structure_judgement": f"一级结构偏向{top_category.get('name')}主导{structure_detail}，需结合目标业态判断消费型/生产型属性。" if top_category.get("name") else "结构判断信号有限。",
        },
    }


def _change_rows(first_counts: Dict[str, Any], last_counts: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for name in sorted(set(first_counts) | set(last_counts)):
        before = int(first_counts.get(name) or 0)
        after = int(last_counts.get(name) or 0)
        delta = after - before
        rows.append({"name": name, "before": before, "after": after, "delta": delta, "rate": (delta / before) if before > 0 else (1 if after > 0 else 0)})
    return rows


def _normalize_years(years: Iterable[Any]) -> List[int]:
    result = []
    for item in years or []:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


async def _generate_poi_iteration_analysis(evidence: Dict[str, Any]) -> Dict[str, Any]:
    from modules.agent.iteration_change_service import generate_poi_iteration_analysis

    return await generate_poi_iteration_analysis(evidence)


async def build_agent_poi_iteration_payload(payload: Any, repo) -> Dict[str, Any]:
    history_id = _as_text(getattr(payload, "history_id", "") or (payload.get("history_id") if isinstance(payload, dict) else ""))
    years = _normalize_years(getattr(payload, "years", None) if not isinstance(payload, dict) else payload.get("years"))
    center = getattr(payload, "center", None) if not isinstance(payload, dict) else payload.get("center")
    if not history_id:
        raise HTTPException(status_code=400, detail="history_id is required")
    if len(years) < 2:
        raise HTTPException(status_code=400, detail="at least two years are required")

    summaries: List[Dict[str, Any]] = []
    for year in years:
        history_payload = get_history_pois_payload(history_id, repo, year=year)
        summaries.append(summarize_iteration_pois(history_payload.get("pois") or [], year))

    if not any(int(summary.get("count") or 0) > 0 for summary in summaries):
        raise HTTPException(status_code=404, detail="no POI data for requested years")

    rule = build_rule_insights(summaries)
    base_payload: Dict[str, Any] = {
        "status": "ready",
        "source": "history",
        "historyId": history_id,
        "years": years,
        "center": center,
        "summaries": summaries,
        "trend_rows": build_trend_rows(summaries),
        "total_series": [{"year": summary.get("year"), "value": int(summary.get("count") or 0)} for summary in summaries],
        "category_stack": build_category_stack(summaries),
        "subcategory_stack": build_subcategory_stack(summaries),
        "subcategory_trend_rows": build_subcategory_trend_rows(summaries),
        "area_heatmaps": build_area_heatmaps(summaries),
        "rule_summary": rule["summary"],
        "rule_insights": rule["insights"],
        "ai_summary": [],
        "ai_insights": {},
        "ai_error": "",
        "error": "",
    }

    ai_result = await _generate_poi_iteration_analysis(base_payload)
    return {
        **base_payload,
        "ai_summary": list(ai_result.get("ai_summary") or []),
        "ai_insights": dict(ai_result.get("ai_insights") or {}),
        "spatial_factors": dict(ai_result.get("spatial_factors") or {}),
        "subcategory_spatial_trend_rows": list(ai_result.get("subcategory_spatial_trend_rows") or []),
        "subcategory_spatial_summary": list(ai_result.get("subcategory_spatial_summary") or []),
        "ai_error": "" if ai_result.get("status") == "ready" else _as_text(ai_result.get("error")),
    }
