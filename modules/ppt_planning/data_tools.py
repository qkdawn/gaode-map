from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from shapely.geometry import Point, shape
from shapely.prepared import prep

from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled
from modules.population.service import get_population_grid
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from store.analysis_artifact_repo import analysis_artifact_repo
from store.history_repo import history_repo

from .schemas import (
    PptDataPackageRequest,
    PptDataPackageResponse,
    PptDataSourceSummary,
    PptEvidenceIntentGroup,
    PptEvidenceIntentPlan,
    PptEvidenceQuery,
    PptPoiNearbyRequest,
    PptPoiPoint,
    PptPoiQueryRequest,
    PptPoiQueryResponse,
    PptSource,
)


class PptDataAreaNotFound(RuntimeError):
    pass


class PptDataSourceNotFound(RuntimeError):
    pass


class PptDataIntentLlmUnavailable(RuntimeError):
    pass


class PptDataInvalidIntentPlan(RuntimeError):
    pass


SYSTEM_SOURCE_TITLES = {
    "system:scope": "当前等时圈范围",
    "system:poi": "POI 基础数据",
    "system:h3": "H3 / 共享网格",
    "system:population": "人口结构分析",
    "system:nightlight": "夜光强度分析",
    "system:road-syntax": "路网与可达性分析",
}

ARTIFACT_SOURCE_TYPES = {
    "system:h3": "poi_h3_grid",
    "system:population": "population",
    "system:nightlight": "nightlight",
    "system:road-syntax": "road_syntax",
}

TYPE_MAP_PATH = Path(__file__).resolve().parents[2] / "share" / "type_map.json"
_TYPE_CODE_LABELS: Dict[str, Dict[str, str]] | None = None
DEFAULT_EVIDENCE_INTENT = "为 PPT 指令生成整理当前区域代表性 POI 资料"
NIGHTLIFE_EVIDENCE_INTENT = "整理夜生活与夜间消费相关 POI，并与夜光格子对应"
NIGHTLIFE_QUERY_TERMS = [
    "酒吧",
    "夜店",
    "KTV",
    "影院",
    "电影院",
    "剧场",
    "夜宵",
    "烧烤",
    "火锅",
    "餐吧",
    "茶馆",
    "咖啡",
    "娱乐",
    "网吧",
    "足浴",
    "按摩",
]
NIGHTLIFE_CATEGORY_LABELS = ["餐饮", "体育", "购物", "生活服务"]
NIGHTLIFE_CORE_TYPECODES = ["080300", "080500", "080600", "050500", "050600", "050700", "061000", "060200"]
NIGHTLIFE_STRONG_TERMS = [
    "酒吧",
    "夜店",
    "KTV",
    "ktv",
    "影院",
    "电影院",
    "影城",
    "剧场",
    "夜宵",
    "烧烤",
    "烤肉",
    "火锅",
    "餐吧",
    "清吧",
    "茶馆",
    "茶艺",
    "茶饮",
    "奶茶",
    "咖啡",
    "网吧",
    "棋牌",
    "桌游",
    "足浴",
    "按摩",
    "24小时",
    "24h",
]
NIGHTLIFE_EXCLUDED_TERMS = [
    "五金",
    "建材",
    "批发",
    "专卖店",
    "土鸡土鸭",
    "大闸蟹",
    "生鲜",
    "菜市场",
    "综合市场",
    "超级市场",
]
NIGHTLIFE_NEAREST_CELL_TOLERANCE_M = 30.0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _normalize_type_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _typecode_matches(point_typecode: Any, filter_typecode: Any) -> bool:
    point_code = _normalize_type_code(point_typecode)
    filter_code = _normalize_type_code(filter_typecode)
    if not point_code or not filter_code:
        return False
    if point_code.startswith(filter_code):
        return True
    if len(filter_code) == 6 and filter_code.endswith("00"):
        return point_code.startswith(filter_code[:4])
    return False


def _load_type_code_labels() -> Dict[str, Dict[str, str]]:
    global _TYPE_CODE_LABELS
    if _TYPE_CODE_LABELS is not None:
        return _TYPE_CODE_LABELS
    labels: Dict[str, Dict[str, str]] = {}
    try:
        payload = json.loads(TYPE_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        _TYPE_CODE_LABELS = labels
        return labels
    for group in _safe_list(_safe_dict(payload).get("groups")):
        group_payload = _safe_dict(group)
        category = _clean_text(group_payload.get("title"))
        for item in _safe_list(group_payload.get("items")):
            item_payload = _safe_dict(item)
            subcategory = _clean_text(item_payload.get("label"))
            for raw_code in _clean_text(item_payload.get("types")).replace("|", ",").split(","):
                code = _normalize_type_code(raw_code)
                if code:
                    labels[code] = {
                        "category": category,
                        "subcategory": subcategory,
                    }
    _TYPE_CODE_LABELS = labels
    return labels


def _resolve_type_labels(typecode: str) -> Dict[str, str]:
    normalized = _normalize_type_code(typecode)
    if not normalized:
        return {}
    labels = _load_type_code_labels()
    if normalized in labels:
        return labels[normalized]
    for code, payload in labels.items():
        if normalized.startswith(code) or normalized[:2] == code[:2]:
            return payload
    return {}


def _available_category_payload() -> Dict[str, List[str]]:
    labels = _load_type_code_labels()
    categories = sorted({payload.get("category", "") for payload in labels.values() if payload.get("category")})
    subcategories = sorted({payload.get("subcategory", "") for payload in labels.values() if payload.get("subcategory")})
    return {
        "categories": categories,
        "subcategories": subcategories,
    }


def _normalize_taxonomy_values(values: List[str], available_values: List[str]) -> tuple[List[str], List[Dict[str, str]]]:
    available = [_clean_text(item) for item in available_values if _clean_text(item)]
    normalized: List[str] = []
    repairs: List[Dict[str, str]] = []
    for raw_value in values:
        value = _clean_text(raw_value)
        if not value:
            continue
        match = next((item for item in available if item == value), "")
        if not match:
            match = next((item for item in available if item in value or value in item), "")
        if match:
            if match not in normalized:
                normalized.append(match)
            if match != value:
                repairs.append({"from": value, "to": match})
    return normalized, repairs


def _haversine_meters(a: List[float], b: List[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return math.inf
    lng1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lng2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lng = lng2 - lng1
    d_lat = lat2 - lat1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _load_history_detail(area_id: str) -> Dict[str, Any]:
    normalized = _clean_text(area_id)
    if not normalized:
        raise PptDataAreaNotFound("area_id_required")
    detail = history_repo.get_detail(normalized, include_pois=False)
    if not detail:
        raise PptDataAreaNotFound("area_not_found")
    return detail


def _load_history_pois(area_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    normalized = _clean_text(area_id)
    if not normalized:
        raise PptDataAreaNotFound("area_id_required")
    payload = history_repo.get_pois(normalized, year=year)
    if not payload:
        raise PptDataAreaNotFound("area_not_found")
    return payload


def _latest_artifact_payload(area_id: str, artifact_type: str) -> Dict[str, Any]:
    artifacts = analysis_artifact_repo.list(area_id, artifact_type=artifact_type)
    if not artifacts:
        return {}
    return _safe_dict(artifacts[0].get("payload"))


def _artifact_ready(area_id: str, source_id: str) -> bool:
    artifact_type = ARTIFACT_SOURCE_TYPES.get(source_id)
    if not artifact_type:
        return False
    return bool(analysis_artifact_repo.list(area_id, artifact_type=artifact_type))


def _source_label(source_id: str, ready: bool, count: int = 0) -> str:
    if source_id == "system:poi" and count:
        return f"POI {count} 条"
    return "已生成" if ready else "待生成"


def list_ppt_sources(area_id: str) -> List[PptDataSourceSummary]:
    detail = _load_history_detail(area_id)
    poi_payload = _load_history_pois(area_id)
    poi_count = int(poi_payload.get("count") or len(_safe_list(poi_payload.get("pois"))))
    params = _safe_dict(detail.get("params"))
    scope_ready = bool(detail.get("polygon") or params.get("drawn_polygon") or params.get("center"))

    sources: List[PptDataSourceSummary] = []
    for source_id, title in SYSTEM_SOURCE_TITLES.items():
        if source_id == "system:scope":
            ready = scope_ready
            count = 1 if ready else 0
        elif source_id == "system:poi":
            ready = poi_count > 0
            count = poi_count
        else:
            ready = _artifact_ready(area_id, source_id)
            count = 1 if ready else 0
        sources.append(
            PptDataSourceSummary(
                id=source_id,
                type="data",
                title=title,
                status="ready" if ready else "pending",
                summary=_source_label(source_id, ready, count),
                count=count,
                meta={
                    "label": _source_label(source_id, ready, count),
                    "sourceKind": "system",
                    "areaId": _clean_text(area_id),
                },
            )
        )
    return sources


def read_ppt_source_summary(area_id: str, source_id: str) -> PptDataSourceSummary:
    normalized_source = _clean_text(source_id)
    summaries = {item.id: item for item in list_ppt_sources(area_id)}
    if normalized_source not in summaries:
        raise PptDataSourceNotFound("source_not_found")
    return summaries[normalized_source]


def _first_text(poi: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        value = poi.get(key)
        if value is not None and _clean_text(value):
            return _clean_text(value)
    return ""


def _parse_location(value: Any, poi: Dict[str, Any]) -> List[float]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) >= 2:
            try:
                return [float(parts[0]), float(parts[1])]
            except (TypeError, ValueError):
                return []
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return []
    lng = poi.get("lng", poi.get("longitude", poi.get("lon")))
    lat = poi.get("lat", poi.get("latitude"))
    if lng is not None and lat is not None:
        try:
            return [float(lng), float(lat)]
        except (TypeError, ValueError):
            return []
    return []


def _normalize_poi(poi: Any, index: int, *, year: Optional[int], source: str) -> PptPoiPoint:
    item = _safe_dict(poi)
    name = _first_text(item, ["name", "title", "名称"])
    raw_type = _first_text(item, ["type"])
    raw_typecode = _first_text(item, ["typecode", "type_code"])
    typecode = raw_typecode or (raw_type if raw_type.replace(";", "").replace("|", "").isdigit() else "")
    type_labels = _resolve_type_labels(typecode)
    category = _first_text(item, ["category", "type_name", "类别", "中类", "大类"]) or _clean_text(type_labels.get("category"))
    subcategory = _first_text(item, ["subcategory", "sub_category", "小类"]) or _clean_text(type_labels.get("subcategory"))
    if not category and raw_type and not typecode:
        category = raw_type
    return PptPoiPoint(
        id=_first_text(item, ["id", "uid", "poiid"]) or f"poi-{index + 1}",
        name=name or f"POI {index + 1}",
        location=_parse_location(item.get("location"), item),
        address=_first_text(item, ["address", "addr", "地址", "adname"]),
        category=category,
        subcategory=subcategory,
        typecode=typecode,
        year=year if year is not None else item.get("year"),
        source=source or _clean_text(item.get("source")),
    )


def _poi_matches(point: PptPoiPoint, query: str, filters: Dict[str, Any]) -> bool:
    normalized_query = _clean_text(query).lower()
    query_terms = [
        _clean_text(item).lower()
        for item in _safe_list(filters.get("query_terms"))
        if _clean_text(item)
    ]
    if normalized_query:
        query_terms.append(normalized_query)
    category = _clean_text(filters.get("category")).lower()
    if category and category not in point.category.lower():
        return False
    categories = [
        _clean_text(item).lower()
        for item in _safe_list(filters.get("categories"))
        if _clean_text(item)
    ]
    if categories and not any(item in point.category.lower() or point.category.lower() in item for item in categories):
        return False
    subcategory = _clean_text(filters.get("subcategory")).lower()
    if subcategory and subcategory not in point.subcategory.lower():
        return False
    subcategories = [
        _clean_text(item).lower()
        for item in _safe_list(filters.get("subcategories"))
        if _clean_text(item)
    ]
    if subcategories and not any(item in point.subcategory.lower() or point.subcategory.lower() in item for item in subcategories):
        return False
    typecode = _normalize_type_code(filters.get("typecode"))
    if typecode and not _typecode_matches(point.typecode, typecode):
        return False
    typecodes = [
        _normalize_type_code(item)
        for item in _safe_list(filters.get("typecodes"))
        if _normalize_type_code(item)
    ]
    if typecodes and not any(_typecode_matches(point.typecode, item) for item in typecodes):
        return False
    if not query_terms:
        return True
    haystack = " ".join([point.name, point.address, point.category, point.subcategory, point.typecode]).lower()
    return any(item in haystack for item in query_terms)


def _filtered_poi_points(area_id: str, filters: Dict[str, Any]) -> tuple[List[PptPoiPoint], Dict[str, Any], List[str]]:
    filters = _safe_dict(filters)
    year = filters.get("year")
    try:
        normalized_year = int(year) if year is not None and _clean_text(year) else None
    except (TypeError, ValueError):
        normalized_year = None
    poi_payload = _load_history_pois(area_id, year=normalized_year)
    raw_pois = _safe_list(poi_payload.get("pois"))
    selected_year = poi_payload.get("selected_year")
    source = _clean_text(_safe_dict(poi_payload.get("params")).get("source"))
    query = _clean_text(filters.get("query"))
    points = [
        _normalize_poi(poi, index, year=selected_year, source=source)
        for index, poi in enumerate(raw_pois)
    ]
    filtered = [point for point in points if _poi_matches(point, query, filters)]
    warnings: List[str] = []
    if not raw_pois:
        warnings.append("当前区域没有可用 POI 明细。")
    elif not filtered:
        warnings.append("没有匹配筛选条件的 POI。")
    return filtered, poi_payload, warnings


def query_poi_points(request: PptPoiQueryRequest) -> PptPoiQueryResponse:
    filters = _safe_dict(request.filters)
    filtered, poi_payload, warnings = _filtered_poi_points(request.area_id, filters)
    selected_year = poi_payload.get("selected_year")
    start = min(max(0, request.offset), len(filtered))
    end = min(len(filtered), start + request.limit)
    return PptPoiQueryResponse(
        area_id=_clean_text(request.area_id),
        coordinate_system="WGS84",
        items=filtered[start:end],
        total=len(filtered),
        limit=request.limit,
        offset=request.offset,
        available_years=[int(item) for item in _safe_list(poi_payload.get("available_years")) if isinstance(item, int)],
        selected_year=selected_year,
        warnings=warnings,
    )


def query_nearby_poi_points(request: PptPoiNearbyRequest) -> PptPoiQueryResponse:
    center = request.center if isinstance(request.center, list) else []
    if len(center) < 2:
        return PptPoiQueryResponse(
            area_id=_clean_text(request.area_id),
            coordinate_system="WGS84",
            limit=request.limit,
            warnings=["nearby 查询缺少中心点。"],
        )
    points, poi_payload, warnings = _filtered_poi_points(request.area_id, request.filters)
    matched: List[PptPoiPoint] = []
    for point in points:
        distance = _haversine_meters(center, point.location)
        if math.isfinite(distance) and distance <= request.radius_m:
            matched.append(point.model_copy(update={"distance_m": round(distance, 2)}))
    matched.sort(key=lambda item: float(item.distance_m or 0))
    if not matched and not warnings:
        warnings.append("中心点半径范围内没有匹配 POI。")
    return PptPoiQueryResponse(
        area_id=_clean_text(request.area_id),
        coordinate_system="WGS84",
        items=matched[:request.limit],
        total=len(matched),
        limit=request.limit,
        offset=0,
        available_years=[int(item) for item in _safe_list(poi_payload.get("available_years")) if isinstance(item, int)],
        selected_year=poi_payload.get("selected_year"),
        warnings=warnings,
    )


def _category_summary(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for item in items:
        category = _clean_text(item.get("category")) or "未分类"
        counts[category] = counts.get(category, 0) + 1
    return [
        {"category": category, "count": count}
        for category, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    ]


def _subcategory_summary(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for item in items:
        subcategory = _clean_text(item.get("subcategory")) or "未分类"
        counts[subcategory] = counts.get(subcategory, 0) + 1
    return [
        {"subcategory": subcategory, "count": count}
        for subcategory, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    ]


def _point_key(point: PptPoiPoint) -> str:
    return _clean_text(point.id) or f"{point.name}:{point.location}"


def _diverse_sample_points(points: List[PptPoiPoint], target_count: int, *, excluded: Optional[set[str]] = None) -> List[PptPoiPoint]:
    target = max(1, int(target_count or 1))
    excluded = excluded or set()
    subcategory_cap = max(1, math.ceil(target / 3))
    selected: List[PptPoiPoint] = []
    selected_keys: set[str] = set()
    subcategory_counts: Dict[str, int] = {}

    for point in points:
        key = _point_key(point)
        if key in excluded or key in selected_keys:
            continue
        subcategory = _clean_text(point.subcategory) or "未分类"
        if subcategory_counts.get(subcategory, 0) >= subcategory_cap:
            continue
        selected.append(point)
        selected_keys.add(key)
        subcategory_counts[subcategory] = subcategory_counts.get(subcategory, 0) + 1
        if len(selected) >= target:
            return selected

    for point in points:
        key = _point_key(point)
        if key in excluded or key in selected_keys:
            continue
        selected.append(point)
        selected_keys.add(key)
        if len(selected) >= target:
            return selected

    return selected


def _is_nightlife_point(point: PptPoiPoint) -> bool:
    haystack = " ".join([
        point.name,
        point.address,
        point.category,
        point.subcategory,
        point.typecode,
    ]).lower()
    if any(_clean_text(term).lower() in haystack for term in NIGHTLIFE_EXCLUDED_TERMS):
        return False
    if any(_clean_text(term).lower() in haystack for term in NIGHTLIFE_STRONG_TERMS):
        return True
    return any(_typecode_matches(point.typecode, typecode) for typecode in NIGHTLIFE_CORE_TYPECODES)


def _nightlife_evidence_plan(limit: int) -> PptEvidenceIntentPlan:
    target = max(1, min(50, int(limit or 50)))
    base = max(1, target // 4)
    remainder = max(0, target - base * 4)

    def count(index: int) -> int:
        return base + (1 if index < remainder else 0)

    return PptEvidenceIntentPlan(
        package_title="夜生活 POI × 夜光格子资料包",
        selection_reason="按夜间社交娱乐、夜宵轻餐、夜间商业节点和夜间生活配套分组整理代表性 POI，并与夜光格子对齐。",
        evidence_groups=[
            PptEvidenceIntentGroup(
                name="夜间社交娱乐",
                purpose="识别晚上停留和社交活动的核心场所。",
                categories=["体育"],
                subcategories=["娱乐场所", "休闲场所", "影剧院"],
                query_terms=["酒吧", "KTV", "影院", "影城", "剧场", "棋牌", "桌游", "网吧", "娱乐"],
                typecodes=["080300", "080500", "080600"],
                target_count=count(0),
            ),
            PptEvidenceIntentGroup(
                name="夜宵与轻餐饮",
                purpose="识别更可能承载夜间消费的餐饮点位。",
                target_count=count(1),
                queries=[
                    PptEvidenceQuery(
                        name="夜宵关键词",
                        categories=["餐饮"],
                        query_terms=["夜宵", "烧烤", "烤肉", "火锅", "餐吧", "清吧"],
                        target_count=max(1, count(1) // 2),
                    ),
                    PptEvidenceQuery(
                        name="轻餐茶饮",
                        categories=["餐饮"],
                        subcategories=["休闲餐饮场所", "咖啡厅", "茶艺馆", "冷饮店", "甜品店"],
                        typecodes=["050400", "050500", "050600", "050700", "050900"],
                        target_count=max(1, count(1) - max(1, count(1) // 2)),
                    ),
                ],
            ),
            PptEvidenceIntentGroup(
                name="夜间商业节点",
                purpose="识别夜间可形成聚集感的商业街区和复合消费节点。",
                categories=["购物"],
                subcategories=["特色商业街", "商场"],
                query_terms=["商业街", "夜市", "街区", "广场", "mall", "购物中心"],
                typecodes=["061000", "060100"],
                target_count=count(2),
            ),
            PptEvidenceIntentGroup(
                name="夜间生活配套",
                purpose="识别可能支撑晚间停留的即时消费与服务点位。",
                categories=["购物", "生活服务"],
                subcategories=["便民商店/便利店"],
                query_terms=["便利店", "24小时", "24h", "足浴", "按摩"],
                typecodes=["060200"],
                target_count=count(3),
            ),
        ],
    )


def _point_gcj02_candidates(point: PptPoiPoint) -> List[Point]:
    if len(point.location) < 2:
        return []
    try:
        lng = float(point.location[0])
        lat = float(point.location[1])
    except (TypeError, ValueError):
        return []
    candidates = [Point(lng, lat)]
    try:
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        if abs(gcj_lng - lng) > 1e-9 or abs(gcj_lat - lat) > 1e-9:
            candidates.append(Point(gcj_lng, gcj_lat))
    except Exception:
        pass
    return candidates


def _history_polygon_gcj02(detail: Dict[str, Any]) -> List[Any]:
    params = _safe_dict(detail.get("params"))
    polygon = detail.get("polygon") or params.get("polygon") or params.get("drawn_polygon")
    return _safe_list(polygon)


def _load_shared_grid_features(area_id: str, detail: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    poi_raster_payload = _latest_artifact_payload(area_id, "poi_raster_grid")
    grid = _safe_dict(poi_raster_payload.get("grid"))
    features = _safe_list(grid.get("features"))
    if features:
        return features, warnings
    polygon = _history_polygon_gcj02(detail)
    if not polygon:
        return [], ["缺少范围 polygon，无法把 POI 精确对应到夜光格子。"]
    try:
        population_grid = get_population_grid(polygon, "gcj02")
        features = _safe_list(population_grid.get("features"))
        return features, warnings
    except Exception:
        return [], ["共享格子加载失败，夜生活 POI 只能作为点位证据使用。"]


def _prepared_grid_cells(features: List[Dict[str, Any]]) -> List[tuple[str, Any, Any]]:
    cells: List[tuple[str, Any, Any]] = []
    for feature in features:
        props = _safe_dict(_safe_dict(feature).get("properties"))
        cell_id = _clean_text(props.get("cell_id") or props.get("h3_id"))
        if not cell_id:
            continue
        try:
            geom = shape(_safe_dict(feature).get("geometry") or {})
        except Exception:
            continue
        if geom.is_empty:
            continue
        cells.append((cell_id, geom, prep(geom)))
    return cells


def _approx_distance_meters(a: Point, b: Point) -> float:
    lat = math.radians((float(a.y) + float(b.y)) / 2)
    dx = (float(a.x) - float(b.x)) * 111320 * math.cos(lat)
    dy = (float(a.y) - float(b.y)) * 111320
    return math.hypot(dx, dy)


def _match_point_cell(point: PptPoiPoint, prepared_cells: List[tuple[str, Any, Any]]) -> Dict[str, Any]:
    candidate_points = _point_gcj02_candidates(point)
    if not candidate_points:
        return {"cell_id": "", "status": "unmatched", "distance_m": None}
    nearest: Dict[str, Any] = {"cell_id": "", "status": "unmatched", "distance_m": None}
    for cell_id, geom, prepared in prepared_cells:
        for gcj02_point in candidate_points:
            if prepared.contains(gcj02_point) or geom.touches(gcj02_point):
                return {"cell_id": cell_id, "status": "matched_cell", "distance_m": 0.0}
            nearest_points = geom.boundary.interpolate(geom.boundary.project(gcj02_point))
            distance_m = _approx_distance_meters(gcj02_point, nearest_points)
            if nearest["distance_m"] is None or distance_m < float(nearest["distance_m"]):
                nearest = {"cell_id": cell_id, "status": "matched_nearest_cell", "distance_m": round(distance_m, 2)}
    if nearest["cell_id"] and float(nearest["distance_m"] or 0) <= NIGHTLIFE_NEAREST_CELL_TOLERANCE_M:
        return nearest
    return {"cell_id": "", "status": "unmatched", "distance_m": nearest["distance_m"]}


def _latest_nightlight_cells(area_id: str) -> Dict[str, Dict[str, Any]]:
    payload = _latest_artifact_payload(area_id, "nightlight")
    cells = _safe_list(payload.get("layer_cells"))
    return {
        _clean_text(cell.get("cell_id")): _safe_dict(cell)
        for cell in cells
        if isinstance(cell, dict) and _clean_text(cell.get("cell_id"))
    }


def _nightlight_value(cell: Dict[str, Any]) -> float:
    for key in ("display_value", "value", "raw_value", "radiance", "mean_radiance"):
        try:
            number = float(cell.get(key))
            if math.isfinite(number):
                return number
        except (TypeError, ValueError):
            continue
    return 0.0


def _build_nightlife_poi_nightlight_package(
    *,
    request: PptDataPackageRequest,
    selected_sources: set[str],
    plan: PptEvidenceIntentPlan,
    group_payloads: List[Dict[str, Any]],
    repaired_groups: List[tuple[PptEvidenceIntentGroup, List[Dict[str, str]]]],
) -> PptDataPackageResponse:
    detail = _load_history_detail(request.area_id)
    selected_points_by_key: Dict[str, PptPoiPoint] = {}
    for group_payload in group_payloads:
        for item in _safe_list(group_payload.get("items")):
            point = PptPoiPoint(**_safe_dict(item))
            key = _point_key(point)
            if key and key not in selected_points_by_key and _is_nightlife_point(point):
                selected_points_by_key[key] = point
    nightlife_points = list(selected_points_by_key.values())
    features, grid_warnings = _load_shared_grid_features(request.area_id, detail)
    prepared_cells = _prepared_grid_cells(features)
    nightlight_by_cell = _latest_nightlight_cells(request.area_id)

    aligned_items: List[Dict[str, Any]] = []
    for point in nightlife_points:
        match = _match_point_cell(point, prepared_cells)
        cell_id = _clean_text(match.get("cell_id"))
        nightlight_cell = nightlight_by_cell.get(cell_id) if cell_id else {}
        item = point.model_dump(mode="json")
        item["cell_id"] = cell_id
        item["cell_match_distance_m"] = match.get("distance_m")
        item["nightlight_cell"] = {
            "cell_id": cell_id,
            "radiance": round(_nightlight_value(nightlight_cell), 6),
            "class_key": _clean_text(nightlight_cell.get("class_key")),
            "class_label": _clean_text(nightlight_cell.get("class_label") or nightlight_cell.get("label")),
            "has_data": bool(nightlight_cell.get("has_data")) if nightlight_cell else False,
            "label": _clean_text(nightlight_cell.get("label")),
        } if cell_id else {}
        if cell_id and nightlight_cell:
            item["alignment_status"] = _clean_text(match.get("status")) or "matched_cell"
        elif cell_id:
            item["alignment_status"] = "matched_grid_without_nightlight"
        else:
            item["alignment_status"] = "unmatched"
        aligned_items.append(item)

    aligned_items.sort(key=lambda item: (
        0 if item.get("alignment_status") == "matched_cell" else (1 if item.get("alignment_status") == "matched_nearest_cell" else 2),
        -float(_safe_dict(item.get("nightlight_cell")).get("radiance") or 0),
        _clean_text(item.get("name")),
    ))
    limited_items = aligned_items[: request.limit]
    matched_items = [item for item in limited_items if item.get("alignment_status") in {"matched_cell", "matched_nearest_cell"}]
    strict_matched_items = [item for item in limited_items if item.get("alignment_status") == "matched_cell"]
    nearest_matched_items = [item for item in limited_items if item.get("alignment_status") == "matched_nearest_cell"]
    evidence_refs = [
        f"poi_nightlight:{item.get('id') or index + 1}:{item.get('cell_id') or 'unmatched'}"
        for index, item in enumerate(limited_items)
    ]
    filters = {
        "intent_type": "nightlife_poi_nightlight_alignment",
        "evidence_groups": [
            {
                "name": group.name,
                "queries": [_query_filters(query) for query in _group_queries(group)],
            }
            for group, _repairs in repaired_groups
        ],
        "query_terms": NIGHTLIFE_QUERY_TERMS,
        "categories": NIGHTLIFE_CATEGORY_LABELS,
        "typecodes": NIGHTLIFE_CORE_TYPECODES,
        "cell_id_source": "population_nightlight_shared_cell_id",
    }
    package_payload = {
        "area_id": _clean_text(request.area_id),
        "source_ids": sorted(selected_sources),
        "package_mode": "evidence",
        "intent": _clean_text(request.intent) or NIGHTLIFE_EVIDENCE_INTENT,
        "filters": filters,
        "limit": request.limit,
        "items": limited_items,
        "alignment": {
            "grid_type": "shared_raster",
            "join_key": "cell_id",
            "grid_cell_count": len(features),
            "nightlight_cell_count": len(nightlight_by_cell),
            "matched_item_count": len(matched_items),
            "strict_matched_item_count": len(strict_matched_items),
            "nearest_matched_item_count": len(nearest_matched_items),
            "nearest_match_tolerance_m": NIGHTLIFE_NEAREST_CELL_TOLERANCE_M,
            "alignment_level": "cell_id_overlap" if matched_items else "poi_only_or_missing_nightlight_cells",
        },
    }
    package_id = f"package:poi-nightlife:{_stable_hash(package_payload)}"
    summary = f"已整理 {len(limited_items)} 个夜生活 POI，其中 {len(matched_items)} 个已对应夜光格子。"
    warnings = [
        warning
        for group_payload in group_payloads
        for warning in _safe_list(group_payload.get("warnings"))
        if _clean_text(warning)
    ] + list(grid_warnings)
    if not limited_items:
        warnings.append("按夜生活意图分组后没有找到高置信 POI，未使用普通餐饮/超市兜底。")
    if not nightlight_by_cell:
        warnings.append("未读取到夜光格子 artifact，已保留 POI 与共享格子的对应状态。")
    package_meta = {
        "id": package_id,
        "title": "夜生活 POI × 夜光格子资料包",
        "summary": summary,
        "coordinate_system": "WGS84",
        "package_mode": "evidence",
        "intent": _clean_text(request.intent) or NIGHTLIFE_EVIDENCE_INTENT,
        "source_ids": sorted(selected_sources),
        "filters": filters,
        "total": len(nightlife_points),
        "items": limited_items,
        "alignment": package_payload["alignment"],
        "category_summary": _category_summary(limited_items),
        "evidence_refs": evidence_refs,
        "intent_plan": plan.model_dump(mode="json"),
        "selection_reason": _clean_text(plan.selection_reason),
        "groups": group_payloads,
        "warnings": warnings,
    }
    source = PptSource(
        id=package_id,
        type="package",
        title="夜生活 POI × 夜光格子资料包",
        status="ready",
        selected=True,
        meta={
            "label": f"POI {len(limited_items)} 条 / 夜光格 {len({item.get('cell_id') for item in matched_items if item.get('cell_id')})} 个",
            "sourceKind": "package",
            "package": package_meta,
        },
    )
    return PptDataPackageResponse(
        source=source,
        summary=summary,
        items=limited_items,
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def _group_filters(group: PptEvidenceIntentGroup) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if group.query_terms:
        filters["query_terms"] = list(group.query_terms)
    if group.categories:
        filters["categories"] = list(group.categories)
    if group.subcategories:
        filters["subcategories"] = list(group.subcategories)
    if group.typecodes:
        filters["typecodes"] = list(group.typecodes)
    return filters


def _query_filters(query: PptEvidenceQuery) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if query.query_terms:
        filters["query_terms"] = list(query.query_terms)
    if query.categories:
        filters["categories"] = list(query.categories)
    if query.subcategories:
        filters["subcategories"] = list(query.subcategories)
    if query.typecodes:
        filters["typecodes"] = list(query.typecodes)
    return filters


def _repair_evidence_query(query: PptEvidenceQuery, available_categories: Dict[str, List[str]]) -> tuple[PptEvidenceQuery, List[Dict[str, str]]]:
    categories, category_repairs = _normalize_taxonomy_values(query.categories, available_categories.get("categories", []))
    subcategories, subcategory_repairs = _normalize_taxonomy_values(query.subcategories, available_categories.get("subcategories", []))
    repairs = [
        {"field": "categories", **repair}
        for repair in category_repairs
    ] + [
        {"field": "subcategories", **repair}
        for repair in subcategory_repairs
    ]
    repaired = query.model_copy(update={
        "categories": categories,
        "subcategories": subcategories,
    })
    return repaired, repairs


def _group_queries(group: PptEvidenceIntentGroup) -> List[PptEvidenceQuery]:
    if group.queries:
        return list(group.queries)
    return [
        PptEvidenceQuery(
            name=_clean_text(group.name) or "POI 子查询",
            purpose=_clean_text(group.purpose),
            query_terms=list(group.query_terms),
            categories=list(group.categories),
            subcategories=list(group.subcategories),
            typecodes=list(group.typecodes),
            nearby_required=bool(group.nearby_required),
            radius_m=group.radius_m,
            target_count=group.target_count,
        )
    ]


def _repair_evidence_group(group: PptEvidenceIntentGroup, available_categories: Dict[str, List[str]]) -> tuple[PptEvidenceIntentGroup, List[Dict[str, str]]]:
    repaired_queries: List[PptEvidenceQuery] = []
    repairs: List[Dict[str, str]] = []
    for query in _group_queries(group):
        repaired_query, query_repairs = _repair_evidence_query(query, available_categories)
        repaired_queries.append(repaired_query)
        repairs.extend([
            {"query": _clean_text(query.name), **repair}
            for repair in query_repairs
        ])
    return group.model_copy(update={"queries": repaired_queries}), repairs


def _plan_groups(plan: PptEvidenceIntentPlan, fallback_limit: int) -> List[PptEvidenceIntentGroup]:
    groups = list(plan.evidence_groups or [])
    if groups:
        limit = max(1, int(fallback_limit or len(groups)))
        if sum(int(group.target_count or 0) for group in groups) <= limit:
            return groups
        base = max(1, limit // len(groups))
        remainder = max(0, limit - base * len(groups))
        adjusted: List[PptEvidenceIntentGroup] = []
        for index, group in enumerate(groups):
            target_count = base + (1 if index < remainder else 0)
            adjusted.append(group.model_copy(update={"target_count": target_count}))
        return adjusted
    return [
        PptEvidenceIntentGroup(
            name=_clean_text(plan.package_title) or "POI 证据",
            purpose=_clean_text(plan.selection_reason),
            query_terms=list(plan.query_terms),
            categories=list(plan.categories),
            subcategories=list(plan.subcategories),
            typecodes=list(plan.typecodes),
            nearby_required=bool(plan.nearby_required),
            radius_m=plan.radius_m,
            target_count=max(1, min(50, int(fallback_limit or 6))),
        )
    ]


def _execute_evidence_group(
    *,
    request: PptDataPackageRequest,
    group: PptEvidenceIntentGroup,
    excluded_keys: set[str],
    repairs: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    query_payloads: List[Dict[str, Any]] = []
    candidates_by_key: Dict[str, PptPoiPoint] = {}
    total = 0
    warnings: List[str] = []
    for query in _group_queries(group):
        query_payload = _execute_evidence_query(request=request, query=query)
        query_payloads.append(query_payload)
        total += int(query_payload.get("total") or 0)
        warnings.extend([_clean_text(item) for item in _safe_list(query_payload.get("warnings")) if _clean_text(item)])
        for item in _safe_list(query_payload.get("candidates")):
            point = PptPoiPoint(**_safe_dict(item))
            key = _point_key(point)
            if key and key not in candidates_by_key:
                candidates_by_key[key] = point
    candidates = list(candidates_by_key.values())
    selected = _diverse_sample_points(candidates, group.target_count, excluded=excluded_keys)
    for point in selected:
        excluded_keys.add(_point_key(point))
    selected_items = [item.model_dump(mode="json") for item in selected]
    candidate_items = [item.model_dump(mode="json") for item in candidates]
    return {
        "name": _clean_text(group.name) or "POI 证据",
        "purpose": _clean_text(group.purpose),
        "filters": {"queries": [_query_filters(query) for query in _group_queries(group)]},
        "queries": [
            {
                key: value
                for key, value in query_payload.items()
                if key != "candidates"
            }
            for query_payload in query_payloads
        ],
        "target_count": group.target_count,
        "plan_repair": repairs or [],
        "total": total,
        "unique_total": len(candidates),
        "category_summary": _category_summary(candidate_items),
        "subcategory_summary": _subcategory_summary(candidate_items),
        "items": selected_items,
        "warnings": warnings,
    }


def _execute_evidence_query(*, request: PptDataPackageRequest, query: PptEvidenceQuery) -> Dict[str, Any]:
    filters = _query_filters(query)
    if query.nearby_required and request.center:
        result = query_nearby_poi_points(
            PptPoiNearbyRequest(
                area_id=request.area_id,
                center=list(request.center),
                radius_m=query.radius_m or request.radius_m or 1000,
                filters=filters,
                limit=200,
            )
        )
        candidates = list(result.items)
    else:
        candidates, poi_payload, warnings = _filtered_poi_points(request.area_id, filters)
        result = PptPoiQueryResponse(
            area_id=_clean_text(request.area_id),
            coordinate_system="WGS84",
            total=len(candidates),
            limit=200,
            offset=0,
            available_years=[int(item) for item in _safe_list(poi_payload.get("available_years")) if isinstance(item, int)],
            selected_year=poi_payload.get("selected_year"),
            warnings=warnings,
        )
    return {
        "name": _clean_text(query.name) or "POI 子查询",
        "purpose": _clean_text(query.purpose),
        "filters": filters,
        "nearby_required": bool(query.nearby_required),
        "radius_m": query.radius_m,
        "target_count": query.target_count,
        "total": result.total,
        "category_summary": _category_summary([item.model_dump(mode="json") for item in candidates]),
        "subcategory_summary": _subcategory_summary([item.model_dump(mode="json") for item in candidates]),
        "candidates": [item.model_dump(mode="json") for item in candidates[:200]],
        "warnings": list(result.warnings),
    }


async def parse_ppt_evidence_intent_with_llm(
    *,
    intent: str,
    available_categories: Dict[str, List[str]],
    area_context: Dict[str, Any],
) -> PptEvidenceIntentPlan:
    if not is_llm_enabled():
        raise PptDataIntentLlmUnavailable("ppt_data_intent_llm_unavailable")
    raw = await _invoke_json_role(
        system_prompt=(
            "你是城市空间分析 PPT 的资料检索规划器。"
            "你的任务是把用户的 PPT 页面资料意图解析成 POI 检索计划。"
            "只输出 JSON，不要输出解释。"
            "不得编造 POI 数据；只选择检索关键词、分类和半径等条件。"
        ),
        user_payload={
            "task": "ppt_poi_evidence_intent_parse",
            "intent": _clean_text(intent) or DEFAULT_EVIDENCE_INTENT,
            "available_categories": available_categories,
            "area_context": area_context,
            "output_schema": {
                "package_title": "资料包标题",
                "selection_reason": "为什么这样检索",
                "evidence_groups": [
                    {
                        "name": "证据组名称，例如餐饮密度",
                        "purpose": "这组证据服务的 PPT 论点",
                        "target_count": 6,
                        "queries": [
                            {
                                "name": "子查询名称，例如酒吧/KTV/娱乐",
                                "purpose": "这个子查询服务的证据角度",
                                "query_terms": ["关键词"],
                                "categories": ["中文大类"],
                                "subcategories": ["中文小类"],
                                "typecodes": ["POI typecode"],
                                "nearby_required": False,
                                "radius_m": 1000,
                                "target_count": 3,
                            }
                        ],
                    }
                ],
            },
        },
        emit=None,
        phase="ppt_poi_evidence_intent_parse",
        title="解析 PPT POI 资料意图",
        reasoning_id="ppt-poi-evidence-intent-parse",
    )
    if not isinstance(raw, dict):
        raise PptDataInvalidIntentPlan("ppt_data_invalid_intent_plan")
    plan = PptEvidenceIntentPlan(**raw)
    valid_groups = [
        group for group in plan.evidence_groups
        if group.query_terms or group.categories or group.subcategories or group.typecodes or group.nearby_required or any(
            query.query_terms or query.categories or query.subcategories or query.typecodes or query.nearby_required
            for query in group.queries
        )
    ]
    if plan.evidence_groups and not valid_groups:
        raise PptDataInvalidIntentPlan("ppt_data_empty_intent_plan")
    if not (
        plan.query_terms
        or plan.categories
        or plan.subcategories
        or plan.typecodes
        or plan.nearby_required
        or valid_groups
    ):
        raise PptDataInvalidIntentPlan("ppt_data_empty_intent_plan")
    if valid_groups != plan.evidence_groups:
        plan = plan.model_copy(update={"evidence_groups": valid_groups})
    return plan


def _build_poi_package_response(
    *,
    request: PptDataPackageRequest,
    poi_result: PptPoiQueryResponse,
    selected_sources: set[str],
    package_mode: str,
    filters: Dict[str, Any],
    title: str,
    intent: str = "",
    intent_plan: Optional[PptEvidenceIntentPlan] = None,
    selection_reason: str = "",
    package_groups: Optional[List[Dict[str, Any]]] = None,
) -> PptDataPackageResponse:
    items = [item.model_dump(mode="json") for item in poi_result.items]
    package_payload = {
        "area_id": _clean_text(request.area_id),
        "coordinate_system": "WGS84",
        "source_ids": sorted(selected_sources),
        "package_mode": package_mode,
        "intent": _clean_text(intent),
        "query": _clean_text(request.query),
        "limit": request.limit,
        "filters": filters,
        "center": list(request.center),
        "radius_m": request.radius_m,
        "intent_plan": intent_plan.model_dump(mode="json") if intent_plan else None,
        "total": poi_result.total,
        "items": items,
        "groups": package_groups or [],
    }
    package_id = f"package:poi:{_stable_hash(package_payload)}"
    item_count = len(items)
    summary = f"已整理 {item_count} 条 POI 样例，共 {poi_result.total} 条匹配结果。"
    evidence_refs = [f"poi:{item.get('id') or index + 1}" for index, item in enumerate(items)]
    package_meta = {
        "id": package_id,
        "title": title,
        "summary": summary,
        "coordinate_system": "WGS84",
        "package_mode": package_mode,
        "intent": _clean_text(intent),
        "query": _clean_text(request.query),
        "source_ids": sorted(selected_sources),
        "filters": filters,
        "center": list(request.center),
        "radius_m": request.radius_m,
        "total": poi_result.total,
        "category_summary": _category_summary(items),
        "items": items,
        "groups": package_groups or [],
        "evidence_refs": evidence_refs,
        "warnings": list(poi_result.warnings),
    }
    if intent_plan:
        package_meta["intent_plan"] = intent_plan.model_dump(mode="json")
    if selection_reason:
        package_meta["selection_reason"] = selection_reason
    source = PptSource(
        id=package_id,
        type="package",
        title=title,
        status="ready",
        selected=True,
        meta={
            "label": f"POI {item_count} 条",
            "sourceKind": "package",
            "package": package_meta,
        },
    )
    return PptDataPackageResponse(
        source=source,
        summary=summary,
        items=items,
        evidence_refs=evidence_refs,
        warnings=list(poi_result.warnings),
    )


def _build_evidence_filters(plan: PptEvidenceIntentPlan) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if plan.query_terms:
        filters["query_terms"] = list(plan.query_terms)
    if plan.categories:
        filters["categories"] = list(plan.categories)
    if plan.subcategories:
        filters["subcategories"] = list(plan.subcategories)
    if plan.typecodes:
        filters["typecodes"] = list(plan.typecodes)
    return filters


async def create_ppt_data_package(request: PptDataPackageRequest) -> PptDataPackageResponse:
    selected_sources = {_clean_text(item) for item in request.source_ids if _clean_text(item)}
    include_poi = not selected_sources or "system:poi" in selected_sources
    intent_text = _clean_text(request.intent)
    include_nightlight = "system:nightlight" in selected_sources
    wants_nightlife_alignment = include_nightlight and any(
        keyword in intent_text
        for keyword in ("夜生活", "夜间消费", "夜间活力", "夜光格子", "夜光")
    )
    if not include_poi:
        poi_result = PptPoiQueryResponse(area_id=request.area_id, warnings=["第一版资料包仅支持 POI 来源。"])
        return _build_poi_package_response(
            request=request,
            poi_result=poi_result,
            selected_sources=selected_sources,
            package_mode=_clean_text(request.package_mode) or "query",
            filters={},
            title="资料包",
        )

    package_mode = (_clean_text(request.package_mode) or "evidence").lower()
    filters = dict(_safe_dict(request.filters))
    if request.query:
        filters["query"] = request.query

    if package_mode == "nearby":
        poi_result = query_nearby_poi_points(
            PptPoiNearbyRequest(
                area_id=request.area_id,
                center=list(request.center),
                radius_m=request.radius_m or 1000,
                filters=filters,
                limit=request.limit,
            )
        )
        return _build_poi_package_response(
            request=request,
            poi_result=poi_result,
            selected_sources=selected_sources,
            package_mode="nearby",
            filters=filters,
            title="附近 POI 资料包",
        )

    if package_mode == "evidence":
        detail = _load_history_detail(request.area_id)
        params = _safe_dict(detail.get("params"))
        area_context = {
            "area_id": _clean_text(request.area_id),
            "center": params.get("center"),
            "time_min": params.get("time_min") or params.get("duration") or params.get("minutes"),
            "source_ids": sorted(selected_sources),
        }
        available_categories = _available_category_payload()
        plan = _nightlife_evidence_plan(request.limit) if wants_nightlife_alignment else await parse_ppt_evidence_intent_with_llm(
            intent=request.intent,
            available_categories=available_categories,
            area_context=area_context,
        )
        raw_groups = _plan_groups(plan, request.limit)
        repaired_groups: List[tuple[PptEvidenceIntentGroup, List[Dict[str, str]]]] = [
            _repair_evidence_group(group, available_categories)
            for group in raw_groups
        ]
        excluded_keys: set[str] = set()
        group_payloads = [
            _execute_evidence_group(request=request, group=group, excluded_keys=excluded_keys, repairs=repairs)
            for group, repairs in repaired_groups
        ]
        if wants_nightlife_alignment:
            return _build_nightlife_poi_nightlight_package(
                request=request,
                selected_sources=selected_sources,
                plan=plan,
                group_payloads=group_payloads,
                repaired_groups=repaired_groups,
            )
        flat_items = [
            item
            for group_payload in group_payloads
            for item in _safe_list(group_payload.get("items"))
        ]
        poi_result = PptPoiQueryResponse(
            area_id=_clean_text(request.area_id),
            coordinate_system="WGS84",
            items=[PptPoiPoint(**item) for item in flat_items[: request.limit]],
            total=sum(int(group_payload.get("total") or 0) for group_payload in group_payloads),
            limit=request.limit,
            offset=0,
            warnings=[
                warning
                for group_payload in group_payloads
                for warning in _safe_list(group_payload.get("warnings"))
                if _clean_text(warning)
            ],
        )
        return _build_poi_package_response(
            request=request,
            poi_result=poi_result,
            selected_sources=selected_sources,
            package_mode="evidence",
            filters={
                "evidence_groups": [
                    {
                        "name": group.name,
                        "queries": [_query_filters(query) for query in _group_queries(group)],
                    }
                    for group, _repairs in repaired_groups
                ]
            },
            title=_clean_text(plan.package_title) or "POI 资料包",
            intent=_clean_text(request.intent) or DEFAULT_EVIDENCE_INTENT,
            intent_plan=plan,
            selection_reason=_clean_text(plan.selection_reason),
            package_groups=group_payloads,
        )

    poi_result = query_poi_points(
        PptPoiQueryRequest(
            area_id=request.area_id,
            filters=filters,
            limit=request.limit,
            offset=0,
        )
    )
    return _build_poi_package_response(
        request=request,
        poi_result=poi_result,
        selected_sources=selected_sources,
        package_mode="query",
        filters=filters,
        title="POI 资料包",
    )
