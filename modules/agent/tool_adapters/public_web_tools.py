from __future__ import annotations

from typing import Any, Dict, Iterable, List

from modules.ppt_planning.schemas import PptWebSourceSearchRequest
from modules.ppt_web_source.service import preview_ppt_web_source

from ..schemas import AnalysisSnapshot, ToolResult


DEFAULT_CATEGORIES = [
    "统计",
    "政策规划",
    "文保档案",
    "片区供给",
    "直接及区域竞品",
    "文化机构或机构采购",
    "公开价格与活动",
]
DEFAULT_SOURCE_MODES = ["trusted", "market"]


def _history_id(arguments: Dict[str, Any], snapshot: AnalysisSnapshot) -> str:
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    return str(arguments.get("area_id") or arguments.get("history_id") or context.get("history_id") or "").strip()


def _text_list(value: Any, *, default: Iterable[str]) -> List[str]:
    values = value if isinstance(value, list) else []
    normalized: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized or list(default)


def _usable_item(item: Any) -> bool:
    if not isinstance(item, dict) or not str(item.get("url") or "").strip():
        return False
    if str(item.get("parse_status") or "").strip() != "parsed":
        return False
    return bool(_source_excerpt(item))


def _source_excerpt(item: Dict[str, Any]) -> str:
    for node in item.get("web_evidence_nodes") or []:
        if not isinstance(node, dict):
            continue
        excerpt = str(node.get("content") or node.get("text") or node.get("summary") or "").strip()
        if excerpt:
            return excerpt
    return str(item.get("markdown_excerpt") or "").strip()


def _normalize_source_item(
    item: Dict[str, Any],
    *,
    category: str,
    round_number: int,
    request: PptWebSourceSearchRequest,
) -> Dict[str, Any]:
    """Expose a stable research-source contract independent of the PPT fetcher."""
    normalized = dict(item)
    attempt = {
        "round": round_number,
        "phase": ("原始查询", "行政区+主题重组", "机构/来源替代")[round_number - 1],
        "region_name": request.region_name,
        "topic": request.topic,
        "intent": request.intent,
    }
    normalized.update(
        {
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "publisher": str(item.get("publisher") or item.get("source_name") or item.get("source_domain") or "unknown").strip(),
            "publication_date": str(item.get("publication_date") or item.get("published_at") or "unknown").strip(),
            "access_date": str(item.get("access_date") or item.get("accessed_at") or "unknown").strip(),
            "query": " ".join(part for part in (request.region_name, request.topic, request.intent) if str(part or "").strip()),
            "research_category": category,
            "original_excerpt": _source_excerpt(item),
            "applicable_scope": str(item.get("applicable_scope") or item.get("applicability") or "仅适用于来源页面明确陈述的地区、对象与时间范围"),
            "inference_boundary": str(item.get("inference_boundary") or item.get("inference_limit") or "不得由公开页面直接推导项目级客流、支付、成本、许可或实施承诺"),
            "search_attempt": attempt,
        }
    )
    # Keep the earlier names while this result is inside the search service;
    # downstream research code consumes the stable aliases above.
    normalized["applicability"] = normalized["applicable_scope"]
    normalized["inference_limit"] = normalized["inference_boundary"]
    return normalized


def _request_for_round(
    *,
    round_number: int,
    area_id: str,
    region_name: str,
    administrative_area: str,
    topic: str,
    intent: str,
    category: str,
    source_modes: List[str],
    urls: List[str],
    limit: int,
) -> PptWebSourceSearchRequest:
    if round_number == 1:
        round_region, round_topic, round_intent = region_name, topic, intent
    elif round_number == 2:
        # Use the administrative scope as the search anchor when the project-name query misses.
        round_region = administrative_area or region_name
        round_topic = " ".join(part for part in [topic, category] if part)
        round_intent = "行政区与主题重组：" + (intent or category)
    else:
        round_region = administrative_area or region_name
        round_topic = " ".join(part for part in [topic, category, "机构 原始来源"] if part)
        round_intent = "机构与来源替代：政府、档案、文博、统计、行业机构"
    return PptWebSourceSearchRequest(
        area_id=area_id,
        region_name=round_region or "当前项目区域",
        administrative_area=administrative_area,
        topic=round_topic or "公开资料",
        intent=round_intent or "项目关联的公开资料、政策、历史、市场与机构信息",
        categories=[category],
        source_modes=source_modes,
        urls=urls if round_number == 1 else [],
        limit=limit,
    )


async def search_public_web(*, arguments: Dict[str, Any], snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], question: str) -> ToolResult:
    del artifacts, question
    area_id = _history_id(arguments, snapshot)
    if not area_id:
        return ToolResult(tool_name="search_public_web", status="failed", error="history_id_required", warnings=["公开网页检索需要 history_id 作为项目区域标识"])

    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    region_name = str(arguments.get("region_name") or context.get("project_name") or context.get("region_name") or "当前项目区域").strip()
    administrative_area = str(arguments.get("administrative_area") or context.get("administrative_area") or "").strip()
    topic = str(arguments.get("topic") or "公开资料").strip()
    intent = str(arguments.get("intent") or "项目关联的公开资料、政策、历史、市场与机构信息").strip()
    categories = _text_list(arguments.get("categories"), default=DEFAULT_CATEGORIES)
    source_modes = _text_list(arguments.get("source_modes"), default=DEFAULT_SOURCE_MODES)
    urls = _text_list(arguments.get("urls"), default=[])
    limit = max(1, min(int(arguments.get("limit") or 8), 20))

    all_items: List[Dict[str, Any]] = []
    evidence_refs: List[str] = []
    warnings: List[str] = []
    attempts: List[Dict[str, Any]] = []
    category_coverage: List[Dict[str, Any]] = []
    for category in categories:
        category_items: List[Dict[str, Any]] = []
        usable_items: List[Dict[str, Any]] = []
        for round_number in range(1, 4):
            request = _request_for_round(
                round_number=round_number,
                area_id=area_id,
                region_name=region_name,
                administrative_area=administrative_area,
                topic=topic,
                intent=intent,
                category=category,
                source_modes=source_modes,
                urls=urls,
                limit=limit,
            )
            try:
                response = await preview_ppt_web_source(request)
            except Exception as exc:
                return ToolResult(
                    tool_name="search_public_web",
                    status="failed",
                    error=str(exc),
                    warnings=[*warnings, "公开网页检索服务异常，本轮必须保留网页证据缺口"],
                    result={
                        "summary": "公开网页检索服务异常，未能完成全部类别。",
                        "items": _dedupe_by_url([item for item in all_items if _usable_item(item)]),
                        "evidence_refs": _dedupe_text(evidence_refs),
                        "coverage_status": "failed",
                        "attempts": attempts,
                        "category_coverage": category_coverage,
                    },
                )
            items = []
            for raw_item in list(response.items or []):
                if not isinstance(raw_item, dict):
                    continue
                item = _normalize_source_item(
                    raw_item,
                    category=category,
                    round_number=round_number,
                    request=request,
                )
                items.append(item)
            usable = [item for item in items if _usable_item(item)]
            phase = ("原始查询", "行政区+主题重组", "机构/来源替代")[round_number - 1]
            attempts.append({
                "category": category,
                "round": round_number,
                "phase": phase,
                "region_name": request.region_name,
                "topic": request.topic,
                "intent": request.intent,
                "item_count": len(items),
                "usable_source_count": len(usable),
                "outcome": "usable_source_found" if usable else "no_usable_source",
            })
            category_items.extend(items)
            usable_items.extend(usable)
            warnings.extend(list(response.warnings or []))
            evidence_refs.extend(str(reference) for reference in list(response.evidence_refs or []) if str(reference).strip())
            # A failed page is not enough to close a category; only usable evidence stops retries.
            if usable:
                break
        unique_usable = _dedupe_by_url(usable_items)
        all_items.extend(category_items)
        category_coverage.append({
            "category": category,
            "coverage_status": "usable_sources_found" if unique_usable else "searched_no_usable_source",
            "attempt_count": sum(1 for attempt in attempts if attempt["category"] == category),
            "usable_source_count": len(unique_usable),
        })

    usable_sources = _dedupe_by_url([item for item in all_items if _usable_item(item)])
    coverage_status = "usable_sources_found" if usable_sources else "searched_no_usable_source"
    result = {
        "summary": f"已完成 {len(categories)} 个公开资料类别的检索；{len(usable_sources)} 条可用来源。",
        "items": usable_sources,
        "evidence_refs": _dedupe_text(evidence_refs),
        "coverage_status": coverage_status,
        "attempts": attempts,
        "category_coverage": category_coverage,
    }
    return ToolResult(
        tool_name="search_public_web",
        status="success",
        result=result,
        evidence=[{"field": "public_web.usable_source_count", "value": len(usable_sources)}],
        warnings=_dedupe_text(warnings),
        artifacts={"public_web_sources": result},
    )


def _dedupe_by_url(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for item in items:
        key = str(item.get("url") or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _dedupe_text(items: Iterable[Any]) -> List[str]:
    unique: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in unique:
            unique.append(text)
    return unique
