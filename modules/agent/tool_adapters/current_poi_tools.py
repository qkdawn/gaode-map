from __future__ import annotations

from typing import Any, Dict, List

from modules.scope_datasets import ScopeDatasetService

from ..schemas import AnalysisSnapshot, ToolResult

_CURRENT_POI_DATASET_WARNING = "结果来自保存的当前范围 POI 数据集，不代表完整城市 POI 数据库。"
_NO_CURRENT_POI_WARNING = "当前范围没有保存的 POI 数据集；请先执行并保存 POI 分析。"
_HISTORY_ID_REQUIRED_WARNING = "query_current_pois 需要 history_id 才能查询保存的当前范围 POI 数据集。"
_DATASET_PAGE_SIZE = 100
_DATASET_SCAN_LIMIT = 10000
_SCHOOL_ALIASES = (
    "学校",
    "小学",
    "中学",
    "大学",
    "学院",
    "幼儿园",
    "高等院校",
    "教育培训",
    "科教文化",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _contains_any(text: str, needles: List[str]) -> bool:
    haystack = text.casefold()
    return any(needle.casefold() in haystack for needle in needles if needle)


def _query_terms(keyword: str, category: str) -> List[str]:
    terms = [keyword, category]
    encoded = " ".join(term for term in terms if term)
    if "学校" in encoded:
        terms.extend(_SCHOOL_ALIASES)
    return [term for term in terms if term]


def _poi_search_text(poi: Dict[str, Any]) -> str:
    values = [
        poi.get("name"),
        poi.get("title"),
        poi.get("type"),
        poi.get("type_label"),
        poi.get("category"),
        poi.get("category_label"),
        poi.get("address"),
        poi.get("adname"),
        poi.get("district"),
    ]
    return " ".join(_text(value) for value in values if _text(value))


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row(index: int, poi: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "index": index,
        "name": _text(poi.get("name") or poi.get("title")),
        "type": _text(poi.get("type") or poi.get("type_label")),
        "category": _text(poi.get("category") or poi.get("category_label")),
        "address": _text(poi.get("address")),
        "lng": _number(poi.get("lng") if poi.get("lng") is not None else poi.get("longitude")),
        "lat": _number(poi.get("lat") if poi.get("lat") is not None else poi.get("latitude")),
    }


def _history_id(arguments: Dict[str, Any], snapshot: AnalysisSnapshot) -> str:
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    return _text(
        arguments.get("history_id")
        or arguments.get("historyId")
        or context.get("history_id")
        or context.get("historyId")
    )


def _poi_from_scope_record(record: Dict[str, Any]) -> Dict[str, Any]:
    props = record.get("properties") if isinstance(record.get("properties"), dict) else {}
    return {
        **dict(props),
        "id": _text(props.get("id") or record.get("record_id")),
        "name": _text(props.get("name") or record.get("title")),
        "type": _text(props.get("type") or props.get("category")),
        "category": _text(props.get("category") or props.get("type")),
        "address": _text(props.get("address")),
    }


def _match_pois(pois: List[Dict[str, Any]], terms: List[str]) -> List[tuple[int, Dict[str, Any]]]:
    return [
        (index, poi)
        for index, poi in enumerate(pois)
        if not terms or _contains_any(_poi_search_text(poi), terms)
    ]


def _query_saved_poi_dataset(*, history_id: str, year: Any = None) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    offset = 0
    while offset < _DATASET_SCAN_LIMIT:
        payload = ScopeDatasetService().query_scope_dataset(
            history_id=history_id,
            source_id="current:dataset:poi",
            limit=_DATASET_PAGE_SIZE,
            offset=offset,
            year=year,
        )
        page = payload.get("records") if isinstance(payload, dict) else []
        records.extend([dict(item) for item in page if isinstance(item, dict)])
        warnings.extend(str(item) for item in (payload.get("warnings") or []) if str(item).strip())
        if not payload.get("has_more") or not page:
            break
        offset += _DATASET_PAGE_SIZE
    if offset + _DATASET_PAGE_SIZE >= _DATASET_SCAN_LIMIT:
        warnings.append(f"当前 POI 数据集超过扫描上限 {_DATASET_SCAN_LIMIT} 条，请缩小范围或增加过滤条件。")
    return {"pois": [_poi_from_scope_record(record) for record in records], "warnings": warnings}


async def query_current_pois(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
    ) -> ToolResult:
    del artifacts, question
    keyword = _text(arguments.get("keyword"))
    category = _text(arguments.get("category") or arguments.get("type"))
    limit = max(1, min(200, int(arguments.get("limit") or 50)))
    offset = max(0, int(arguments.get("offset") or 0))
    history_id = _history_id(arguments, snapshot)
    data_source = "scope_dataset"

    if not history_id:
        payload = {"total": 0, "limit": limit, "offset": offset, "has_more": False, "rows": [], "data_source": data_source}
        return ToolResult(
            tool_name="query_current_pois",
            status="success",
            result=payload,
            evidence=[{"field": "current_poi_query.total", "value": 0}],
            warnings=[_HISTORY_ID_REQUIRED_WARNING],
            artifacts={"current_poi_query": payload},
        )

    dataset = _query_saved_poi_dataset(history_id=history_id, year=arguments.get("year"))
    pois = dataset.get("pois") if isinstance(dataset.get("pois"), list) else []
    dataset_warnings = [str(item) for item in (dataset.get("warnings") or []) if str(item).strip()]

    if not pois:
        payload = {"total": 0, "limit": limit, "offset": offset, "has_more": False, "rows": [], "data_source": data_source}
        return ToolResult(
            tool_name="query_current_pois",
            status="success",
            result=payload,
            evidence=[{"field": "current_poi_query.total", "value": 0}],
            warnings=[_NO_CURRENT_POI_WARNING, *dataset_warnings],
            artifacts={"current_poi_query": payload},
        )

    terms = _query_terms(keyword, category)
    matched = _match_pois(pois, terms)
    page = matched[offset : offset + limit]
    payload = {
        "total": len(matched),
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < len(matched),
        "data_source": data_source,
        "rows": [_row(index, poi) for index, poi in page],
    }
    return ToolResult(
        tool_name="query_current_pois",
        status="success",
        result=payload,
        evidence=[
            {"field": "current_poi_query.total", "value": len(matched)},
            {"field": "current_poi_query.returned", "value": len(page)},
        ],
        warnings=[_CURRENT_POI_DATASET_WARNING, *dataset_warnings],
        artifacts={"current_poi_query": payload},
    )
