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
        "请基于多年 POI 总量、一级业态结构、小类业态结构、区域分布、变化指标和空间因子生成解释。"
        "必须先概括一级业态和关键小类数量变化，再使用 spatial_factors 与 subcategory_spatial_trend_rows 说明小类位置变化。"
        "位置判断只能来自 spatial_factors、subcategory_spatial_trend_rows 和 evidence 中已有区域字段，"
        "不得凭坐标或想象地图编造方向、商圈、道路名、地标或百分比。"
        "emerging_area 优先结合小类增长、方位、圈层、重心迁移、热点网格和区域字段。"
        "只输出 JSON 对象，字段必须为 summary_points, fastest_growth, declining_category, emerging_area, structure_judgement。"
        "summary_points 必须是 2 到 4 条中文短句；其余字段必须是中文字符串，不要返回对象或数组。"
        "不要把小类当成独立大类，不要编造 evidence 中没有出现的行业、小类、区域、商圈或道路。"
        "证据不足时明确说明趋势信号有限。不要输出 markdown。"
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
    if not is_llm_enabled():
        return {"status": "failed", "ai_summary": [], "ai_insights": {}, "error": "llm_unavailable", **spatial_fields}
    try:
        raw = await _invoke_json_role(
            system_prompt=_poi_iteration_prompt(),
            user_payload={"task": "poi_iteration_change", "evidence": enriched_evidence},
            emit=None,
            phase="poi_iteration_change",
            title="生成 POI 多年变化解析",
            reasoning_id="poi-iteration-change",
        )
        analysis = _validate_poi_ai_analysis(raw)
        if not analysis:
            return {"status": "failed", "ai_summary": [], "ai_insights": {}, "error": "invalid_ai_analysis", **spatial_fields}
        return {
            "status": "ready",
            "ai_summary": analysis["summary_points"],
            "ai_insights": {
                "fastest_growth": analysis["fastest_growth"],
                "declining_category": analysis["declining_category"],
                "emerging_area": analysis["emerging_area"],
                "structure_judgement": analysis["structure_judgement"],
            },
            "error": "",
            **spatial_fields,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "ai_summary": [],
            "ai_insights": {},
            "error": f"{exc.__class__.__name__}: {exc}",
            **spatial_fields,
        }
