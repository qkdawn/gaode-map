from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from core.config import settings
from modules.evidence_retrieval import EvidenceNode, evidence_node_payloads_from_nodes
from modules.ppt_planning.schemas import (
    PptDataPackageResponse,
    PptWebSourceCommitRequest,
    PptWebSourceLocationDefaultRequest,
    PptWebSourceLocationDefaultResponse,
    PptWebSourceSearchRequest,
    PptSource,
)
from modules.providers.amap.regeo import reverse_geocode
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from modules.web_crawler import WebCrawlerUnavailable, crawl_web_page
from modules.web_crawler.crawler import clean_visible_text, is_noise_text
from modules.ppt_database.service import build_database_data_package
from store.analysis_artifact_repo import analysis_artifact_repo
from store.history_repo import history_repo

logger = logging.getLogger(__name__)

PPT_WEB_SOURCE_ARTIFACT_TYPE = "ppt_web_source"
FALLBACK_REGION_NAME = "当前分析区域"
DEFAULT_WEB_SOURCE_CATEGORIES = ["政策背景", "区域概况", "产业商业", "文旅案例", "竞品项目", "周边房租"]
GENERIC_WEB_SOURCE_TOPICS = {"地区资料", "区域资料", "资料搜索", "AI 搜索地区资料", "AI搜索地区资料"}
WEB_SOURCE_CATEGORY_BUCKETS = {
    "政策背景": {
        "queries": ["政策", "规划", "统计 公报"],
        "keywords": ("政策", "规划", "统计", "公报", "公告", "通知", "政策背景"),
    },
    "区域概况": {
        "queries": ["概况", "城市介绍", "片区 介绍"],
        "keywords": ("概况", "介绍", "简介", "区情", "区位", "基础情况"),
    },
    "产业商业": {
        "queries": ["产业", "商业", "招商"],
        "keywords": ("产业", "商业", "招商", "园区", "楼宇", "载体"),
    },
    "周边房租": {
        "queries": ["房租 58同城", "租房 58同城", "租金 房源"],
        "keywords": ("房租", "租金", "租房", "出租", "公寓", "房源"),
    },
    "文旅案例": {
        "queries": ["文旅", "旅游 案例", "文旅 案例"],
        "keywords": ("文旅", "旅游", "案例", "景区", "消费", "文旅案例"),
    },
    "竞品项目": {
        "queries": ["竞品 项目", "参考 项目", "项目 案例"],
        "keywords": ("竞品", "参考", "项目", "样板", "案例", "对标"),
    },
}
TRUSTED_SOURCES = [
    {"name": "地方政府公开信息", "domain": "changsha.gov.cn", "site": "changsha.gov.cn", "confidence": "high", "source_tier": "trusted"},
    {"name": "区县政府公开信息", "domain": "yuelu.gov.cn", "site": "yuelu.gov.cn", "confidence": "high", "source_tier": "trusted"},
    {"name": "政府网站", "domain": "gov.cn", "site": "gov.cn", "confidence": "high", "source_tier": "trusted"},
    {"name": "统计公开信息", "domain": "stats.gov.cn", "site": "stats.gov.cn", "confidence": "medium", "source_tier": "trusted"},
    {"name": "文旅公开信息", "domain": "mct.gov.cn", "site": "mct.gov.cn", "confidence": "medium", "source_tier": "trusted"},
    {"name": "官方媒体", "domain": "people.com.cn", "site": "people.com.cn", "confidence": "medium", "source_tier": "trusted"},
]
RENTAL_MARKET_SOURCES = [
    {"name": "58同城租房", "domain": "58.com", "site": "58.com", "confidence": "medium", "source_tier": "market"},
]
COMMUNITY_SOURCES = [
    {"name": "知乎", "domain": "zhihu.com", "site": "zhihu.com", "confidence": "low", "source_tier": "community"},
    {"name": "百家号", "domain": "baijiahao.baidu.com", "site": "baijiahao.baidu.com", "confidence": "low", "source_tier": "community"},
    {"name": "贴吧", "domain": "tieba.baidu.com", "site": "tieba.baidu.com", "confidence": "low", "source_tier": "community"},
    {"name": "B站", "domain": "bilibili.com", "site": "bilibili.com", "confidence": "low", "source_tier": "community"},
    {"name": "抖音", "domain": "douyin.com", "site": "douyin.com", "confidence": "low", "source_tier": "community"},
    {"name": "快手", "domain": "kuaishou.com", "site": "kuaishou.com", "confidence": "low", "source_tier": "community"},
    {"name": "小红书", "domain": "xiaohongshu.com", "site": "xiaohongshu.com", "confidence": "low", "source_tier": "community"},
    {"name": "微博", "domain": "weibo.com", "site": "weibo.com", "confidence": "low", "source_tier": "community"},
]
RENTAL_CATEGORY_KEYWORDS = ("房租", "租金", "租房", "出租", "公寓")
SOURCE_MODES = {"trusted", "market", "community"}
DEFAULT_SOURCE_MODES = ["trusted", "market"]
LOW_TRUST_DOMAINS = (
    "zhihu.com",
    "baijiahao.baidu.com",
    "tieba.baidu.com",
    "bilibili.com",
    "douyin.com",
    "kuaishou.com",
    "xiaohongshu.com",
    "weibo.com",
)
WEB_SOURCE_MARKDOWN_EXCERPT_CHARS = 3600


class PptWebSourceAreaNotFound(RuntimeError):
    pass


class PptWebSourceSearchUnavailable(RuntimeError):
    pass


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_web_source_text(value: Any) -> str:
    return clean_visible_text(value)


def _is_web_source_noise(value: Any) -> bool:
    return is_noise_text(value)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value if isinstance(value, list) else []


def _ai_payload_evidence_count(ai_payload: Dict[str, Any]) -> int:
    payload = _safe_dict(ai_payload)
    evidence_nodes = _safe_list(payload.get("evidence_nodes") or payload.get("evidenceNodes"))
    return len(evidence_nodes)


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _normalize_lng_lat_pair(value: Any) -> List[float]:
    if isinstance(value, dict):
        value = [value.get("lng"), value.get("lat")]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return []
    try:
        lng = float(value[0])
        lat = float(value[1])
    except (TypeError, ValueError):
        return []
    if not math.isfinite(lng) or not math.isfinite(lat):
        return []
    if lng < -180 or lng > 180 or lat < -90 or lat > 90:
        return []
    return [lng, lat]


def _polygon_centroid(points: Any) -> List[float]:
    ring = points if isinstance(points, list) else []
    coords = [_normalize_lng_lat_pair(item) for item in ring]
    coords = [item for item in coords if item]
    if not coords:
        return []
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    if not coords:
        return []
    return [
        sum(item[0] for item in coords) / len(coords),
        sum(item[1] for item in coords) / len(coords),
    ]


def _history_center(detail: Dict[str, Any]) -> List[float]:
    params = _safe_dict(detail.get("params"))
    candidates = [
        params.get("center"),
        params.get("center_gcj02"),
        params.get("centerGcj02"),
        detail.get("center"),
        detail.get("selected_point"),
        detail.get("selectedPoint"),
    ]
    for candidate in candidates:
        center = _normalize_lng_lat_pair(candidate)
        if center:
            return center
    polygon = detail.get("polygon") or params.get("drawn_polygon") or params.get("drawnPolygon")
    return _polygon_centroid(polygon)


def _load_history_detail(area_id: str) -> Dict[str, Any]:
    normalized = _clean_text(area_id)
    if not normalized:
        raise PptWebSourceAreaNotFound("area_id_required")
    detail = history_repo.get_detail(normalized, include_pois=False)
    if not detail:
        raise PptWebSourceAreaNotFound("area_not_found")
    return detail


def _first_component(value: Any) -> str:
    if isinstance(value, list):
        return _clean_text(value[0]) if value else ""
    return _clean_text(value)


def _regeo_address_component(regeocode: Dict[str, Any]) -> Dict[str, str]:
    component = _safe_dict(regeocode.get("addressComponent"))
    township = _first_component(component.get("township"))
    neighborhood = _safe_dict(component.get("neighborhood"))
    building = _safe_dict(component.get("building"))
    pois = _safe_list(regeocode.get("pois"))
    nearby_poi = ""
    if pois:
        nearby_poi = _clean_text(_safe_dict(pois[0]).get("name"))
    return {
        "province": _first_component(component.get("province")),
        "city": _first_component(component.get("city")),
        "district": _first_component(component.get("district")),
        "township": township,
        "neighborhood": _clean_text(neighborhood.get("name")),
        "building": _clean_text(building.get("name")),
        "nearby_poi": nearby_poi,
        "adcode": _clean_text(component.get("adcode")),
        "formatted_address": _clean_text(regeocode.get("formatted_address")),
    }


def _region_name_from_component(component: Dict[str, str]) -> str:
    district = _clean_text(component.get("district"))
    fine = (
        _clean_text(component.get("township"))
        or _clean_text(component.get("neighborhood"))
        or _clean_text(component.get("building"))
        or _clean_text(component.get("nearby_poi"))
    )
    return " ".join(part for part in [district, fine] if part).strip()


def _administrative_area_from_component(component: Dict[str, str]) -> str:
    return " ".join(
        part
        for part in [
            _clean_text(component.get("province")),
            _clean_text(component.get("city")),
            _clean_text(component.get("district")),
        ]
        if part
    ).strip()


def _looks_like_coordinate_text(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*[,，]\s*[-+]?\d+(?:\.\d+)?", text))


def build_web_source_location_default(request: PptWebSourceLocationDefaultRequest) -> PptWebSourceLocationDefaultResponse:
    area_id = _clean_text(request.area_id)
    warnings: List[str] = []
    center: List[float] = []
    try:
        detail = _load_history_detail(area_id)
        center = _history_center(detail)
    except RuntimeError:
        detail = {}
        warnings.append("未找到当前分析区域，已使用手动编辑默认值。")

    if not center:
        return PptWebSourceLocationDefaultResponse(
            area_id=area_id,
            region_name=FALLBACK_REGION_NAME,
            administrative_area="",
            center=[],
            confidence="fallback",
            warnings=warnings or ["当前分析区域缺少可用中心点，请手动输入地区名。"],
            meta={"source": "fallback"},
        )

    try:
        gcj_lng, gcj_lat = wgs84_to_gcj02(center[0], center[1])
        regeocode = reverse_geocode(float(gcj_lng), float(gcj_lat))
        component = _regeo_address_component(regeocode)
        region_name = _region_name_from_component(component)
        administrative_area = _administrative_area_from_component(component)
        if not region_name or _looks_like_coordinate_text(region_name):
            region_name = FALLBACK_REGION_NAME
            warnings.append("逆地理未返回可用地区名，请手动确认。")
            confidence = "fallback"
        else:
            confidence = "high" if administrative_area else "medium"
        return PptWebSourceLocationDefaultResponse(
            area_id=area_id,
            region_name=region_name,
            administrative_area=administrative_area,
            center=center,
            confidence=confidence,
            warnings=warnings,
            meta={"source": "amap_regeo", "address_component": component},
        )
    except Exception as exc:
        logger.info("PPT web source location default regeo failed", exc_info=exc)
        warnings.append("高德逆地理不可用，请手动确认地区名。")
        return PptWebSourceLocationDefaultResponse(
            area_id=area_id,
            region_name=FALLBACK_REGION_NAME,
            administrative_area="",
            center=center,
            confidence="fallback",
            warnings=warnings,
            meta={"source": "fallback", "error": type(exc).__name__},
        )


def _search_terms(request: PptWebSourceSearchRequest) -> List[str]:
    return _bucket_search_terms(request)


def _bucket_category(category: str) -> str:
    text = _clean_text(category)
    if not text:
        return "区域概况"
    if any(keyword in text for keyword in ("房租", "租金", "租房", "出租", "生活成本")):
        return "周边房租"
    if any(keyword in text for keyword in ("政策", "规划", "公示", "公告", "通知", "统计")):
        return "政策背景"
    if any(keyword in text for keyword in ("文旅", "旅游", "景区", "文创")):
        return "文旅案例"
    if any(keyword in text for keyword in ("竞品", "参考", "对标", "案例项目")):
        return "竞品项目"
    if any(keyword in text for keyword in ("产业", "商业", "招商", "园区", "楼宇")):
        return "产业商业"
    if text in WEB_SOURCE_CATEGORY_BUCKETS:
        return text
    return "区域概况"


def _bucket_search_terms(request: PptWebSourceSearchRequest) -> List[str]:
    region_name = _clean_text(request.region_name)
    administrative_area = _clean_text(request.administrative_area)
    topic = _clean_text(request.topic or request.intent)
    if topic in GENERIC_WEB_SOURCE_TOPICS:
        topic = ""
    categories = [_clean_text(item) for item in (request.categories or DEFAULT_WEB_SOURCE_CATEGORIES) if _clean_text(item)]
    base_parts: List[str] = []
    for part in " ".join(item for item in [administrative_area, region_name, topic] if item).split():
        if part and part not in base_parts:
            base_parts.append(part)
    base = " ".join(base_parts).strip()
    if not base:
        base = region_name or administrative_area or FALLBACK_REGION_NAME
    terms: List[str] = []
    for category in categories:
        bucket = _bucket_category(category)
        bucket_terms = WEB_SOURCE_CATEGORY_BUCKETS.get(bucket, {}).get("queries") or [bucket]
        for fragment in bucket_terms:
            term = " ".join(part for part in [base, fragment] if part).strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def _validate_search_region(request: PptWebSourceSearchRequest) -> str:
    region_name = _clean_text(request.region_name)
    if not region_name or _looks_like_coordinate_text(region_name):
        return FALLBACK_REGION_NAME
    return region_name


def _search_query_variants(term: str) -> List[str]:
    text = _clean_text(term)
    if not text:
        return []
    tokens = [part for part in text.split() if part]
    variants: List[str] = []

    def add(value: str) -> None:
        normalized = " ".join(part for part in _clean_text(value).split() if part)
        if normalized and normalized not in variants:
            variants.append(normalized)

    add(text)
    local_tokens = [part for part in tokens if not (part.endswith("省") or part.endswith("市"))]
    add(" ".join(local_tokens))
    if len(tokens) >= 3:
        add(" ".join(tokens[-3:]))
    add(text.replace("街道", "").replace("片区", ""))
    add(" ".join(local_tokens).replace("街道", "").replace("片区", ""))
    if _is_rental_term(text):
        rental_base = " ".join(part for part in local_tokens if part and part not in {"周边房租", "房租", "租金", "租房"})
        add(f"{rental_base or text} 58同城 租房")
        add(f"{rental_base or text} 房租 租金")
        add(f"{rental_base or text} 出租房源")
    return variants


def _is_rental_term(term: str) -> bool:
    text = _clean_text(term)
    return any(keyword in text for keyword in RENTAL_CATEGORY_KEYWORDS)


def _source_modes(request_or_modes: Any = None) -> List[str]:
    raw_modes = getattr(request_or_modes, "source_modes", request_or_modes)
    modes = [_clean_text(item).lower() for item in _safe_list(raw_modes)]
    if not modes:
        configured = getattr(settings, "research_source_modes", [])
        modes = [_clean_text(item).lower() for item in _safe_list(configured)]
    normalized = [mode for mode in modes if mode in SOURCE_MODES]
    return normalized or list(DEFAULT_SOURCE_MODES)


def _source_tier(source: Dict[str, str] | None = None, domain: str = "") -> str:
    explicit = _clean_text(_safe_dict(source).get("source_tier"))
    if explicit in SOURCE_MODES:
        return explicit
    text = _clean_text(domain or _safe_dict(source).get("domain")).lower()
    if any(item["domain"] in text for item in COMMUNITY_SOURCES):
        return "community"
    if any(item["domain"] in text for item in RENTAL_MARKET_SOURCES):
        return "market"
    return "trusted"


def _is_low_trust_domain(domain: str) -> bool:
    text = _clean_text(domain).lower()
    return any(blocked in text for blocked in LOW_TRUST_DOMAINS)


def _source_name_for_domain(domain: str, fallback: str = "开放网页搜索") -> str:
    text = _clean_text(domain).lower()
    for source in [*TRUSTED_SOURCES, *RENTAL_MARKET_SOURCES, *COMMUNITY_SOURCES]:
        if source["domain"] in text:
            return source["name"]
    return fallback


def _preferred_sources_for_term(term: str, index: int, source_modes: Any = None) -> List[Dict[str, str]]:
    modes = set(_source_modes(source_modes))
    if _is_rental_term(term):
        sources = RENTAL_MARKET_SOURCES if "market" in modes else []
        return sources + (COMMUNITY_SOURCES if "community" in modes else [])
    sources: List[Dict[str, str]] = []
    if "trusted" in modes:
        sources.extend(TRUSTED_SOURCES[index:] + TRUSTED_SOURCES[:index])
    if "market" in modes:
        sources.extend(RENTAL_MARKET_SOURCES)
    if "community" in modes:
        sources.extend(COMMUNITY_SOURCES)
    return sources or TRUSTED_SOURCES[index:] + TRUSTED_SOURCES[:index]


def _web_source_item_from_search_result(term: str, source: Dict[str, str], extracted: Dict[str, str]) -> Dict[str, Any]:
    snippet = _clean_text(extracted.get("snippet"))
    summary = snippet or f"围绕“{term}”在{source['name']}来源中检索到的地区资料线索。"
    tier = _source_tier(source)
    return {
        "title": _clean_text(extracted.get("title")) or term,
        "url": _clean_text(extracted.get("url")),
        "source_name": source["name"],
        "source_domain": source["domain"],
        "source_tier": tier,
        "published_at": "unknown",
        "accessed_at": datetime.now(timezone.utc).date().isoformat(),
        "summary": summary,
        "supported_claims": [summary],
        "category": _bucket_category(term),
        "confidence": "low" if tier == "community" else (source.get("confidence") or "medium"),
        "search_strategy": "trusted_site",
    }


def _domain_from_url(url: str) -> str:
    parsed = urlparse(_clean_text(url))
    return _clean_text(parsed.netloc).lower()


def _direct_urls(request: PptWebSourceSearchRequest) -> List[str]:
    urls: List[str] = []
    for raw_url in _safe_list(getattr(request, "urls", [])):
        url = _clean_text(raw_url)
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc and url not in urls:
            urls.append(url)
    return urls


def _source_for_domain(domain: str, fallback: Dict[str, str] | None = None) -> Dict[str, str]:
    text = _clean_text(domain).lower()
    for source in [*TRUSTED_SOURCES, *RENTAL_MARKET_SOURCES, *COMMUNITY_SOURCES]:
        if source["domain"] in text:
            return source
    fallback_source = _safe_dict(fallback)
    tier = _source_tier(fallback_source, text)
    return {
        "name": fallback_source.get("name") or _source_name_for_domain(text),
        "domain": fallback_source.get("domain") or text,
        "site": fallback_source.get("site") or text,
        "confidence": fallback_source.get("confidence") or ("low" if tier == "community" else "medium"),
        "source_tier": tier,
    }


def _searxng_url() -> str:
    base_url = _clean_text(getattr(settings, "searxng_base_url", ""))
    if not base_url:
        raise PptWebSourceSearchUnavailable("searxng_base_url_required")
    return f"{base_url.rstrip('/')}/search"


async def _search_searxng(query: str, *, limit: int) -> List[Dict[str, Any]]:
    params = {
        "q": query,
        "format": "json",
        "language": "zh-CN",
        "safesearch": 1,
    }
    timeout_s = max(1.0, int(getattr(settings, "searxng_timeout_ms", 8000) or 8000) / 1000)
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.get(_searxng_url(), params=params)
            response.raise_for_status()
            payload = response.json()
    except PptWebSourceSearchUnavailable:
        raise
    except Exception as exc:
        raise PptWebSourceSearchUnavailable("searxng_unavailable") from exc
    results = _safe_list(_safe_dict(payload).get("results"))
    return [_safe_dict(item) for item in results[: max(1, limit)]]


def _candidate_region_score(term: str, candidate: Dict[str, Any]) -> int:
    haystack = " ".join(
        _clean_text(candidate.get(key))
        for key in ("title", "content", "snippet", "url")
    )
    score = 0
    for token in [part for part in re.split(r"\s+", _clean_text(term)) if len(part) >= 2]:
        if token in haystack:
            score += 2 if token.endswith(("区", "县", "街道", "镇", "乡", "片区")) else 1
    return score


def _government_candidate_allowed(term: str, candidate: Dict[str, Any]) -> bool:
    domain = _domain_from_url(_clean_text(candidate.get("url")))
    if not (domain.endswith(".gov.cn") or ".gov.cn" in domain or domain == "gov.cn"):
        return True
    text = " ".join(_clean_text(candidate.get(key)) for key in ("title", "content", "snippet"))
    allowed_keywords = ("政策", "规划", "统计", "公报", "公告", "通知", "产业", "文旅", "更新", "概况")
    return any(keyword in text or keyword in term for keyword in allowed_keywords)


def _item_from_searxng_candidate(term: str, candidate: Dict[str, Any], source: Dict[str, str] | None = None) -> Dict[str, Any]:
    url = _clean_text(candidate.get("url"))
    domain = _domain_from_url(url)
    resolved_source = _source_for_domain(domain, source)
    tier = _source_tier(resolved_source, domain)
    snippet = _clean_text(candidate.get("content") or candidate.get("snippet"))
    summary = snippet or f"围绕“{term}”检索到的网页资料线索。"
    return {
        "title": _clean_text(candidate.get("title")) or term,
        "url": url,
        "source_name": resolved_source["name"],
        "source_domain": domain or resolved_source["domain"],
        "source_tier": tier,
        "published_at": _clean_text(candidate.get("publishedDate")) or "unknown",
        "accessed_at": datetime.now(timezone.utc).date().isoformat(),
        "summary": summary,
        "supported_claims": [summary] if summary else [],
        "category": _bucket_category(term),
        "confidence": "low" if tier == "community" else (resolved_source.get("confidence") or "medium"),
        "search_strategy": "searxng_site" if source else ("rental_market_open_web" if _is_rental_term(term) and tier == "market" else ("community_open_web" if tier == "community" else "open_web")),
        "search_score": _candidate_region_score(term, candidate),
    }


def _rank_searxng_candidates(term: str, candidates: List[Dict[str, Any]], *, source: Dict[str, str] | None = None, source_modes: Any = None) -> List[Dict[str, Any]]:
    modes = set(_source_modes(source_modes))
    ranked: List[tuple[int, Dict[str, Any]]] = []
    for candidate in candidates:
        url = _clean_text(candidate.get("url"))
        if not url.startswith(("http://", "https://")):
            continue
        domain = _domain_from_url(url)
        if source and _clean_text(source.get("domain")).lower() not in domain:
            continue
        item = _item_from_searxng_candidate(term, candidate, source)
        tier = _source_tier(item, domain)
        if tier not in modes:
            continue
        if _is_rental_term(term) and "58.com" not in domain:
            continue
        if tier == "community" and "community" not in modes:
            continue
        if _is_low_trust_domain(domain) and "community" not in modes:
            continue
        if not _government_candidate_allowed(term, candidate):
            continue
        tier_weight = {"trusted": 300, "market": 200, "community": 100}.get(tier, 0)
        if _is_rental_term(term) and "58.com" in domain:
            tier_weight += 400
        if source and _clean_text(source.get("domain")).lower() in domain:
            tier_weight += 200
        ranked.append((tier_weight + int(item.get("search_score") or 0), item))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return _dedupe_items([item for _, item in ranked])


async def _fetch_whitelisted_results_impl(term: str, source: Dict[str, str], *, limit: int = 4) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    search_top_k = max(limit, int(getattr(settings, "research_search_top_k", 8) or 8))
    for query_term in _search_query_variants(term):
        query = f"site:{source['site']} {query_term}"
        candidates = await _search_searxng(query, limit=search_top_k)
        items.extend(_rank_searxng_candidates(term, candidates, source=source, source_modes=[_source_tier(source)]))
        items = _dedupe_items(items)
        if len(items) >= limit:
            return items[:limit]
    return _dedupe_items(items)


async def _fetch_whitelisted_result(term: str, source: Dict[str, str]) -> Dict[str, Any]:
    items = await _fetch_whitelisted_results_impl(term, source, limit=1)
    if items:
        return items[0]
    summary = f"围绕“{term}”在{source['name']}来源中检索到的地区资料线索。"
    return {
        "title": term,
        "url": "",
        "source_name": source["name"],
        "source_domain": source["domain"],
        "source_tier": _source_tier(source),
        "published_at": "unknown",
        "accessed_at": datetime.now(timezone.utc).date().isoformat(),
        "summary": summary,
        "supported_claims": [summary],
        "category": term.rsplit(" ", 1)[-1] if " " in term else "区域概况",
        "confidence": "low" if _source_tier(source) == "community" else (source.get("confidence") or "medium"),
        "search_strategy": "trusted_site",
    }


_ORIGINAL_FETCH_WHITELISTED_RESULT = _fetch_whitelisted_result


async def _fetch_whitelisted_results(term: str, source: Dict[str, str], *, limit: int = 4) -> List[Dict[str, Any]]:
    if globals().get("_fetch_whitelisted_result") is not _ORIGINAL_FETCH_WHITELISTED_RESULT:
        candidate = await _fetch_whitelisted_result(term, source)
        return [candidate] if candidate else []
    return await _fetch_whitelisted_results_impl(term, source, limit=limit)


async def _fetch_open_search_results(term: str, *, limit: int = 4, source_modes: Any = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    modes = set(_source_modes(source_modes))
    rental_source = RENTAL_MARKET_SOURCES[0] if _is_rental_term(term) and "market" in modes else None
    allow_community = "community" in modes
    if _is_rental_term(term) and not rental_source and not allow_community:
        return []
    search_top_k = max(limit, int(getattr(settings, "research_search_top_k", 8) or 8))
    for query_term in _search_query_variants(term):
        candidates = await _search_searxng(query_term, limit=search_top_k)
        ranked = _rank_searxng_candidates(term, candidates, source=rental_source, source_modes=source_modes)
        if rental_source:
            ranked = [{**item, "search_strategy": "rental_market_open_web"} for item in ranked]
        items.extend(ranked)
        items = _dedupe_items(items)
        if len(items) >= limit:
            return items[:limit]
    return items


_ORIGINAL_FETCH_OPEN_SEARCH_RESULTS = _fetch_open_search_results


def _fallback_web_source_item(term: str, source: Dict[str, str]) -> Dict[str, Any]:
    tier = _source_tier(source)
    return {
        "title": f"{term}资料线索",
        "url": "",
        "source_name": source["name"],
        "source_domain": source["domain"],
        "source_tier": tier,
        "published_at": "unknown",
        "accessed_at": datetime.now(timezone.utc).date().isoformat(),
        "summary": f"当前未能实时获取网页结果；建议人工从{source['name']}核验“{term}”。",
        "supported_claims": [f"作为{term}方向的资料缺口提示，不作为事实引用。"],
        "category": _bucket_category(term),
        "confidence": "low",
    }


def _item_allowed_for_term(item: Dict[str, Any], term: str, source_modes: Any = None) -> bool:
    tier = _source_tier(None, _clean_text(item.get("source_domain") or item.get("url")))
    explicit_tier = _clean_text(item.get("source_tier"))
    if explicit_tier in SOURCE_MODES:
        tier = explicit_tier
    modes = set(_source_modes(source_modes))
    if tier == "community" and "community" not in modes:
        return False
    if tier == "market" and "market" not in modes:
        return False
    if tier == "trusted" and "trusted" not in modes:
        return False
    if _is_rental_term(term) and tier == "trusted":
        return False
    return True


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        url = _clean_text(item.get("url"))
        title = _clean_text(item.get("title"))
        key = url.lower() if url else re.sub(r"\s+", "", title.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _bucket_queries_for_category(request: PptWebSourceSearchRequest, category: str) -> List[str]:
    region_name = _clean_text(request.region_name)
    administrative_area = _clean_text(request.administrative_area)
    topic = _clean_text(request.topic or request.intent)
    if topic in GENERIC_WEB_SOURCE_TOPICS:
        topic = ""
    base_parts: List[str] = []
    for part in " ".join(item for item in [administrative_area, region_name, topic] if item).split():
        if part and part not in base_parts:
            base_parts.append(part)
    base = " ".join(base_parts).strip() or region_name or administrative_area or FALLBACK_REGION_NAME
    bucket = _bucket_category(category)
    fragments = WEB_SOURCE_CATEGORY_BUCKETS.get(bucket, {}).get("queries") or [bucket]
    terms: List[str] = []
    for fragment in fragments:
        term = " ".join(part for part in [base, fragment] if part).strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _bucket_quota_plan(categories: List[str], limit: int) -> List[tuple[str, int]]:
    normalized = [_bucket_category(item) for item in categories] or ["区域概况"]
    unique: List[str] = []
    for category in normalized:
        if category not in unique:
            unique.append(category)
    if not unique:
        unique = ["区域概况"]
    cap = max(1, min(int(limit or 8), 20))
    quotas = [1 for _ in unique]
    remaining = max(0, cap - len(unique))
    while remaining > 0:
        progressed = False
        for index, _category in enumerate(unique):
            if remaining <= 0:
                break
            if quotas[index] >= 3:
                continue
            quotas[index] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            break
    return list(zip(unique, quotas))


def _bucket_keywords(category: str) -> tuple[str, ...]:
    return tuple(WEB_SOURCE_CATEGORY_BUCKETS.get(_bucket_category(category), {}).get("keywords") or ())


def _bucket_item_score(item: Dict[str, Any], category: str, query_index: int = 0) -> int:
    tier = _clean_text(item.get("source_tier")) or _source_tier(None, _clean_text(item.get("source_domain") or item.get("url")))
    score = {"trusted": 300, "market": 260, "community": 120}.get(tier, 0)
    score += max(0, 80 - query_index * 10)
    if _clean_text(item.get("search_strategy")) == "rental_market_open_web":
        score += 120
    if _clean_text(item.get("search_strategy")) == "community_open_web":
        score += 40
    if _clean_text(item.get("search_strategy")) == "trusted_site":
        score += 60
    haystack = " ".join(
        _clean_text(item.get(key))
        for key in ("title", "summary", "source_name", "source_domain", "url")
    )
    for keyword in _bucket_keywords(category):
        if keyword and keyword in haystack:
            score += 30
    search_score = item.get("search_score")
    try:
        score += int(search_score or 0)
    except (TypeError, ValueError):
        pass
    return score


def _select_diverse_bucket_items(items: List[Dict[str, Any]], *, quota: int, max_per_domain: int = 3) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    domain_counts: Counter[str] = Counter()
    for item in items:
        if len(selected) >= quota:
            break
        url = _clean_text(item.get("url"))
        domain = _domain_from_url(url) or _clean_text(item.get("source_domain"))
        if domain and domain_counts[domain] >= max_per_domain:
            continue
        selected.append(item)
        if domain:
            domain_counts[domain] += 1
    return selected


async def _search_bucket_items(request: PptWebSourceSearchRequest, category: str, quota: int, source_modes: List[str]) -> List[Dict[str, Any]]:
    bucket_terms = _bucket_queries_for_category(request, category)
    category_bucket = _bucket_category(category)
    if category_bucket == "周边房租":
        bucket_terms = bucket_terms[:1]
    if not bucket_terms:
        return []
    collected: List[Dict[str, Any]] = []
    for query_index, term in enumerate(bucket_terms):
        if len(collected) >= quota:
            break
        preferred_sources = _preferred_sources_for_term(term, query_index, source_modes)
        if _clean_text(category_bucket) == "周边房租":
            preferred_sources = [source for source in preferred_sources if _clean_text(source.get("domain")) == "58.com"] or preferred_sources[:1]
        base_url_available = bool(_clean_text(getattr(settings, "searxng_base_url", "")))
        for source in preferred_sources:
            try:
                candidates = await _fetch_whitelisted_results(term, source, limit=max(1, quota - len(collected)))
            except PptWebSourceSearchUnavailable:
                raise
            except Exception as exc:
                logger.info("PPT web source bucket whitelist fetch failed", extra={"term": term, "source": source["domain"], "category": category_bucket}, exc_info=exc)
                continue
            for candidate in candidates:
                if not _clean_text(candidate.get("url")):
                    continue
                candidate = {**candidate, "category": category_bucket}
                if _item_allowed_for_term(candidate, term, source_modes):
                    collected.append(candidate)
                if len(collected) >= quota:
                    break
            if len(collected) >= quota:
                break
        collected = _dedupe_items(collected)
    if len(collected) < quota:
        if not base_url_available and globals().get("_fetch_open_search_results") is _ORIGINAL_FETCH_OPEN_SEARCH_RESULTS:
            return _select_diverse_bucket_items(
                sorted(collected, key=lambda item: _bucket_item_score(item, category_bucket, 0), reverse=True),
                quota=quota,
            )
        open_terms = bucket_terms[: max(1, len(bucket_terms))]
        for term in open_terms:
            if len(collected) >= quota:
                break
            try:
                open_items = await _fetch_open_search_results(term, limit=max(1, quota - len(collected)), source_modes=source_modes)
            except PptWebSourceSearchUnavailable:
                raise
            except Exception as exc:
                logger.info("PPT web source bucket open search failed", extra={"term": term, "category": category_bucket}, exc_info=exc)
                continue
            for candidate in open_items:
                candidate = {**candidate, "category": category_bucket}
                if _item_allowed_for_term(candidate, term, source_modes):
                    collected.append(candidate)
                if len(collected) >= quota:
                    break
            collected = _dedupe_items(collected)
    ranked = sorted(
        collected,
        key=lambda item: _bucket_item_score(item, category_bucket, 0),
        reverse=True,
    )
    return _select_diverse_bucket_items(ranked, quota=quota)


def _bucket_category_label(item: Dict[str, Any]) -> str:
    return _bucket_category(_clean_text(item.get("category")) or "区域概况")


def _item_summary(item: Dict[str, Any]) -> str:
    nodes = _safe_list(item.get("web_evidence_nodes"))
    node_text = " ".join(_clean_web_source_text(_safe_dict(node).get("summary") or _safe_dict(node).get("text")) for node in nodes[:2])
    return (_clean_web_source_text(node_text) or _clean_web_source_text(item.get("summary")))[:520]


def _search_snippet_nodes(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    summary = _clean_web_source_text(item.get("summary"))
    if not summary:
        return []
    title = _clean_web_source_text(item.get("title")) or "搜索结果摘要"
    return [
        {
            "node_id": f"search-snippet:{_stable_hash({'url': item.get('url'), 'title': title})}",
            "title": "搜索结果摘要",
            "summary": summary[:520],
            "text": summary[:520],
            "ordinal": 1,
            "source": "search_snippet",
        }
    ]


def _clean_web_evidence_nodes(nodes: Any) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for index, raw_node in enumerate(_safe_list(nodes), start=1):
        node = _safe_dict(raw_node)
        summary = _clean_web_source_text(node.get("summary") or node.get("text"))
        text = _clean_web_source_text(node.get("text") or summary)
        if len(summary or text) < 8:
            continue
        title = _clean_web_source_text(node.get("title")) or f"网页段落 {len(cleaned) + 1}"
        cleaned.append({
            **node,
            "title": title,
            "summary": (summary or text)[:520],
            "text": (text or summary)[:900],
            "ordinal": node.get("ordinal") or index,
        })
    return cleaned


def _clean_supported_claims(claims: Any) -> List[str]:
    cleaned: List[str] = []
    for claim in _safe_list(claims):
        text = _clean_web_source_text(claim)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _sanitize_web_source_item(item: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {**item}
    url = _clean_text(cleaned.get("url"))
    cleaned["source_tier"] = _clean_text(cleaned.get("source_tier")) or _source_tier(None, _clean_text(cleaned.get("source_domain") or url))
    cleaned["title"] = _clean_web_source_text(cleaned.get("title")) or url or _clean_text(cleaned.get("source_domain")) or "网页资料"
    cleaned["summary"] = _clean_web_source_text(cleaned.get("summary"))
    cleaned["supported_claims"] = _clean_supported_claims(cleaned.get("supported_claims"))
    cleaned["web_evidence_nodes"] = _clean_web_evidence_nodes(cleaned.get("web_evidence_nodes"))
    cleaned["markdown_excerpt"] = _clean_web_source_text(cleaned.get("markdown_excerpt"))[:WEB_SOURCE_MARKDOWN_EXCERPT_CHARS]
    if _clean_text(cleaned.get("parse_status")) == "parsed" and not cleaned["web_evidence_nodes"]:
        cleaned["parse_status"] = "parse_failed"
        cleaned["parse_error"] = _clean_text(cleaned.get("parse_error")) or "low_quality_markdown"
    return cleaned


def _web_source_ai_payload(source_id: str, title: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    evidence_nodes: List[EvidenceNode] = []
    for item in items:
        item_title = _clean_text(item.get("title"))
        item_url = _clean_text(item.get("url"))
        nodes = _safe_list(item.get("web_evidence_nodes"))
        node_rows = nodes[:6] if nodes else [{"title": item_title, "summary": _item_summary(item), "node_id": ""}]
        for index, node in enumerate(node_rows, start=1):
            node_dict = _safe_dict(node)
            text = _clean_text(node_dict.get("summary") or node_dict.get("text"))
            if not text:
                continue
            locator = item_url or f"web:{index}"
            node_id = _clean_text(node_dict.get("node_id")) or f"{_stable_hash({'url': item_url, 'title': item_title, 'index': index})}"
            evidence_nodes.append(
                EvidenceNode(
                    id=f"{source_id}:web:{node_id}",
                    source_id=source_id,
                    source_type="web",
                    title=_clean_text(node_dict.get("title")) or item_title or f"网页证据 {index}",
                    content=text,
                    summary=_clean_text(node_dict.get("summary") or text)[:260],
                    metadata={
                        "url": item_url,
                        "source_name": _clean_text(item.get("source_name")),
                        "source_domain": _clean_text(item.get("source_domain")),
                        "source_tier": _clean_text(item.get("source_tier")),
                        "published_at": _clean_text(item.get("published_at")) or "unknown",
                        "accessed_at": _clean_text(item.get("accessed_at")),
                        "category": _clean_text(item.get("category")),
                        "confidence": _clean_text(item.get("confidence")),
                        "parse_status": _clean_text(item.get("parse_status")),
                        "node_id": node_id,
                        "ordinal": node_dict.get("ordinal") or index,
                    },
                    locator=locator,
                    evidence_level="research_web_evidence",
                    citation=item_url or f"{_clean_text(item.get('source_name'))}（待人工核验）",
                )
            )
    evidence_node_payloads = evidence_node_payloads_from_nodes(evidence_nodes)
    return {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "sourceId": source_id,
        "title": title,
        "source_kind": "web",
        "sourceKind": "web",
        "included": ["evidence"] if evidence_node_payloads else [],
        "evidence_nodes": evidence_node_payloads,
        "evidenceNodes": evidence_node_payloads,
        "metrics": [],
        "metric_gaps": [],
        "visual_specs": [],
        "excluded": [{"type": "webpage_full_text", "reason": "不传网页全文，只传搜索结果摘要、关键段落和引用。"}],
        "counts": {"scope": 0, "metrics": 0, "metric_gaps": 0, "evidence": len(evidence_node_payloads), "visual_specs": 0},
        "policy": "联网资料仅作为外部背景、政策、案例和竞品支撑；不能覆盖当前地图分析指标或用户选择的项目来源事实。",
    }


def _web_source_id(area_id: str, request: PptWebSourceSearchRequest, items: List[Dict[str, Any]]) -> str:
    direct_urls = _direct_urls(request)
    if direct_urls:
        return f"web:{area_id}:{_stable_hash({'area_id': area_id, 'urls': direct_urls, 'topic': _clean_text(request.topic or request.intent)})}"
    region_name = _validate_search_region(request)
    administrative_area = _clean_text(request.administrative_area)
    topic = _clean_text(request.topic or request.intent) or "地区资料"
    hash_payload = {
        'area_id': area_id,
        'region_name': region_name,
        'administrative_area': administrative_area,
        'topic': topic,
        'categories': request.categories or DEFAULT_WEB_SOURCE_CATEGORIES,
        'source_modes': _source_modes(request),
    }
    return f"web:{area_id}:{_stable_hash(hash_payload)}"


def _web_source_title(request: PptWebSourceSearchRequest, items: List[Dict[str, Any]]) -> str:
    direct_urls = _direct_urls(request)
    if direct_urls:
        if len(direct_urls) == 1:
            item_title = _clean_web_source_text(_safe_dict(items[0] if items else {}).get("title"))
            return item_title or _clean_text(urlparse(direct_urls[0]).netloc) or "网页资料"
        return f"网页资料 {len(direct_urls)} 个"
    return f"{_validate_search_region(request)}地区资料"


def _web_locator_summary(items: List[Dict[str, Any]]) -> str:
    urls = [_clean_text(item.get("url")) for item in items if _clean_text(item.get("url"))]
    parsed_count = len([item for item in items if _clean_text(item.get("parse_status")) == "parsed"])
    if len(urls) == 1:
        return urls[0]
    if urls:
        return f"URL {len(urls)} 个 / 已解析 {parsed_count} 个"
    return f"网页条目 {len(items)} 个 / 已解析 {parsed_count} 个"


def _web_availability(evidence_count: int, items: List[Dict[str, Any]]) -> str:
    if evidence_count > 0:
        return "available"
    if items:
        return "empty_evidence:web_parse_empty"
    return "empty_evidence:web_empty"


def _persist_web_source(area_id: str, response: PptDataPackageResponse) -> None:
    source = response.source
    meta = _safe_dict(source.meta)
    web_source = _safe_dict(meta.get("web_source"))
    analysis_artifact_repo.upsert(
        history_id=area_id,
        artifact_type=PPT_WEB_SOURCE_ARTIFACT_TYPE,
        params={
            "region_name": web_source.get("region_name"),
            "administrative_area": web_source.get("administrative_area"),
            "topic": web_source.get("topic"),
            "categories": web_source.get("categories"),
            "source_modes": web_source.get("source_modes"),
        },
        payload=response.model_dump(mode="json"),
        summary={
            "id": source.id,
            "title": source.title,
            "label": meta.get("label"),
            "item_count": len(response.items),
        },
        data_version="v1",
    )


async def _enrich_item_with_web_parse(item: Dict[str, Any]) -> Dict[str, Any]:
    url = _clean_text(item.get("url"))
    if not url:
        return {
            **item,
            "parse_status": "not_available",
            "parse_error": "missing_url",
            "web_evidence_nodes": [],
            "markdown_excerpt": "",
        }
    try:
        parsed = await crawl_web_page(url, timeout_ms=20000)
    except WebCrawlerUnavailable:
        raise
    except Exception as exc:
        parsed = None
        error = type(exc).__name__
    else:
        error = parsed.error
    if parsed is None:
        return {
            **item,
            "parse_status": "parse_failed",
            "parse_error": error,
            "web_evidence_nodes": _search_snippet_nodes(item),
            "markdown_excerpt": "",
        }
    item_title = _clean_web_source_text(item.get("title"))
    parsed_title = _clean_web_source_text(parsed.title)
    title = parsed_title or item_title or _clean_text(item.get("url"))
    nodes = _clean_web_evidence_nodes(parsed.nodes)
    summary = _clean_web_source_text(parsed.summary) or _clean_web_source_text(item.get("summary"))
    if parsed.status != "parsed" and not nodes:
        nodes = _search_snippet_nodes({**item, "summary": summary})
    parse_status = parsed.status
    parse_error = _clean_text(parsed.error)
    if parsed.status == "parsed" and not nodes:
        parse_status = "parse_failed"
        parse_error = parse_error or "low_quality_markdown"
    supported_claims = _clean_supported_claims([_safe_dict(node).get("summary") for node in nodes[:3]]) or _clean_supported_claims(item.get("supported_claims"))
    return {
        **item,
        "title": title or item_title,
        "summary": summary,
        "parse_status": parse_status,
        "parse_error": parse_error,
        "web_evidence_nodes": nodes,
        "markdown_excerpt": _clean_web_source_text(parsed.markdown)[:WEB_SOURCE_MARKDOWN_EXCERPT_CHARS],
        "supported_claims": supported_claims,
    }


def _build_web_source_response(area_id: str, request: PptWebSourceSearchRequest, items: List[Dict[str, Any]], warnings: List[str]) -> PptDataPackageResponse:
    region_name = _validate_search_region(request)
    administrative_area = _clean_text(request.administrative_area)
    topic = _clean_text(request.topic or request.intent) or "地区资料"
    source_modes = _source_modes(request)
    direct_urls = _direct_urls(request)
    source_id = _web_source_id(area_id, request, items)
    title = _web_source_title(request, items)
    ai_payload = _web_source_ai_payload(source_id, title, items)
    evidence_count = _ai_payload_evidence_count(ai_payload)
    summary = f"已为“{region_name}”整理 {len(items)} 条网页证据。"
    source = PptSource(
        id=source_id,
        type="web",
        title=title,
        status="ready",
        selected=True,
        source_kind="web",
        summary=summary,
        evidence_count=evidence_count,
        locator_summary=_web_locator_summary(items),
        availability=_web_availability(evidence_count, items),
        meta={
            "label": f"网页证据 {len(items)} 条",
            "sourceKind": "web",
            "areaId": area_id,
            "web_source": {
                "region_name": region_name,
                "administrative_area": administrative_area,
                "topic": topic,
                "intent": _clean_text(request.intent),
                "categories": request.categories or DEFAULT_WEB_SOURCE_CATEGORIES,
                "source_modes": source_modes,
                "input_mode": "direct_url" if direct_urls else "regional_web_search",
                "urls": direct_urls,
                "trusted_sources": TRUSTED_SOURCES,
                "rental_sources": RENTAL_MARKET_SOURCES,
                "community_sources": COMMUNITY_SOURCES,
                "search_strategy": "direct_url_crawl4ai" if direct_urls else "tiered_sources_trusted_market_optional_community",
                "item_count": len(items),
                "parser": "crawl4ai",
                "source_kind": "web",
            },
            "aiPayload": ai_payload,
            "ai_payload": ai_payload,
        },
    )
    return PptDataPackageResponse(
        source=source,
        summary=summary,
        items=items,
        evidence_refs=[_clean_text(item.get("url")) for item in items if _clean_text(item.get("url"))],
        warnings=warnings,
    )


def _build_web_source_response_with_llamaindex(area_id: str, request: PptWebSourceSearchRequest, items: List[Dict[str, Any]], warnings: List[str]) -> PptDataPackageResponse:
    # 这里保留一个清晰的编排入口，后续可以把网页/数据库证据统一交给 LlamaIndex 做召回与重排。
    return _build_web_source_response(area_id, request, items, warnings)


async def preview_ppt_web_source(request: PptWebSourceSearchRequest) -> PptDataPackageResponse:
    area_id = _clean_text(request.area_id)
    if not area_id:
        raise PptWebSourceAreaNotFound("area_id_required")
    direct_urls = _direct_urls(request)
    if direct_urls:
        return await _preview_direct_web_sources(area_id, request, direct_urls)
    region_name = _validate_search_region(request)
    topic = _clean_text(request.topic or request.intent) or "地区资料"
    source_modes = _source_modes(request)
    normalized_request = request.model_copy(update={"region_name": region_name, "topic": topic, "source_modes": source_modes})
    warnings: List[str] = []
    max_items = max(1, min(int(request.limit or 8), 20))
    category_plan = _bucket_quota_plan(normalized_request.categories or DEFAULT_WEB_SOURCE_CATEGORIES, max_items)
    items: List[Dict[str, Any]] = []
    fallback_items: List[Dict[str, Any]] = []
    for category, quota in category_plan:
        if len(items) >= max_items:
            break
        target_quota = min(quota, max_items - len(items))
        category_items: List[Dict[str, Any]] = []
        try:
            category_items = await _search_bucket_items(normalized_request, category, target_quota, source_modes)
        except PptWebSourceSearchUnavailable:
            raise
        except Exception as exc:
            logger.info("PPT web source bucket search failed", extra={"category": category}, exc_info=exc)
            category_items = []
        if category_items:
            items.extend(category_items)
            continue
        fallback_source = None
        if category == "周边房租":
            fallback_source = RENTAL_MARKET_SOURCES[0]
        elif "trusted" in source_modes and TRUSTED_SOURCES:
            fallback_source = TRUSTED_SOURCES[0]
        elif "market" in source_modes and RENTAL_MARKET_SOURCES:
            fallback_source = RENTAL_MARKET_SOURCES[0]
        elif "community" in source_modes and COMMUNITY_SOURCES:
            fallback_source = COMMUNITY_SOURCES[0]
        if fallback_source:
            warnings.append(f"{category} 暂无可引用网页，已生成待核验线索。")
            fallback_items.append(_fallback_web_source_item(f"{region_name} {category}", fallback_source))
    items = _dedupe_items(items)[:max_items]
    if len(items) < max_items and fallback_items:
        items = _dedupe_items(items + fallback_items)[:max_items]
    if any(_clean_text(item.get("search_strategy")) == "open_web" for item in items):
        warnings.append("已补充开放网页搜索结果；非官方来源需人工核验，不能覆盖地图分析指标或上传资料事实。")
    if any(_clean_text(item.get("source_tier")) == "community" for item in items):
        warnings.append("已包含社媒/问答等低可信线索；仅可作为待核验参考。")
    enriched: List[Dict[str, Any]] = []
    crawler_unavailable = False
    crawl_limit = max(1, min(int(getattr(settings, "research_crawl_top_k", 5) or 5), max_items))
    for item in items[:crawl_limit]:
        try:
            enriched.append(await _enrich_item_with_web_parse(item))
        except WebCrawlerUnavailable:
            crawler_unavailable = True
            enriched.append(_sanitize_web_source_item({
                **item,
                "parse_status": "parse_failed",
                "parse_error": "crawl4ai_unavailable",
                "web_evidence_nodes": [],
                "markdown_excerpt": "",
            }))
    if crawler_unavailable:
        warnings.append("网页解析服务不可用，已保留搜索 URL 作为待核验线索。")
    enriched = [_sanitize_web_source_item(item) for item in enriched]
    for item in enriched:
        if _clean_text(item.get("url")) and _clean_text(item.get("parse_status")) != "parsed":
            warnings.append(f"{_clean_text(item.get('title')) or item.get('url')} 网页正文解析失败，已标记为待核验。")
    response = _build_web_source_response_with_llamaindex(area_id, normalized_request, enriched, warnings)
    return response


async def _preview_direct_web_sources(area_id: str, request: PptWebSourceSearchRequest, urls: List[str]) -> PptDataPackageResponse:
    warnings: List[str] = []
    items: List[Dict[str, Any]] = []
    for url in urls[: max(1, min(int(request.limit or 8), 20))]:
        domain = _domain_from_url(url)
        source = _source_for_domain(domain, {"name": domain or "网页", "domain": domain, "source_tier": "trusted"})
        item = {
            "title": "",
            "url": url,
            "source_name": source["name"],
            "source_domain": domain or source["domain"],
            "source_tier": _source_tier(source, domain),
            "published_at": "unknown",
            "accessed_at": datetime.now(timezone.utc).date().isoformat(),
            "summary": "",
            "supported_claims": [],
            "category": _clean_text(request.topic or request.intent) or "网页资料",
            "confidence": "medium" if _source_tier(source, domain) != "community" else "low",
            "search_strategy": "direct_url",
        }
        try:
            enriched = await _enrich_item_with_web_parse(item)
        except WebCrawlerUnavailable:
            raise
        except Exception as exc:
            logger.info("PPT direct web source parse failed", extra={"url": url}, exc_info=exc)
            enriched = {
                **item,
                "parse_status": "parse_failed",
                "parse_error": type(exc).__name__,
                "web_evidence_nodes": [],
                "markdown_excerpt": "",
            }
        enriched = _sanitize_web_source_item(enriched)
        if _clean_text(enriched.get("parse_status")) != "parsed":
            warnings.append(f"{_clean_text(enriched.get('title')) or url} 网页正文解析失败，已标记为待核验。")
        items.append(enriched)
    if not items:
        raise ValueError("web_url_required")
    return _build_web_source_response(area_id, request, items, warnings)


def commit_ppt_web_source(request: PptWebSourceCommitRequest) -> PptDataPackageResponse:
    area_id = _clean_text(request.area_id)
    if not area_id:
        raise PptWebSourceAreaNotFound("area_id_required")
    payload = _safe_dict(request.preview)
    if not payload:
        raise ValueError("web_source_preview_required")
    response = PptDataPackageResponse.model_validate(payload)
    _persist_web_source(area_id, response)
    return response


def list_persisted_web_sources(area_id: str) -> List[Any]:
    sources = []
    seen: set[str] = set()
    for artifact in analysis_artifact_repo.list(area_id, artifact_type=PPT_WEB_SOURCE_ARTIFACT_TYPE):
        payload = _safe_dict(artifact.get("payload"))
        source = _safe_dict(payload.get("source"))
        source_id = _clean_text(source.get("id"))
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        meta = _safe_dict(source.get("meta"))
        items = _safe_list(payload.get("items"))
        ai_payload = _safe_dict(meta.get("aiPayload") or meta.get("ai_payload"))
        evidence_count = _ai_payload_evidence_count(ai_payload) or int(source.get("evidence_count") or source.get("evidenceCount") or 0)
        sources.append(
            {
                "id": source_id,
                "type": _clean_text(source.get("type")) or "web",
                "source_kind": "web",
                "title": _clean_text(source.get("title")) or "地区资料",
                "status": "ready",
                "summary": _clean_text(payload.get("summary")) or _clean_text(meta.get("label")),
                "count": len(items),
                "evidence_count": evidence_count,
                "locator_summary": _clean_text(source.get("locator_summary") or source.get("locatorSummary")) or _web_locator_summary(items),
                "availability": _clean_text(source.get("availability")) or _web_availability(evidence_count, items),
                "meta": {
                    **meta,
                    "sourceKind": "web",
                    "areaId": area_id,
                    "persistedWebSource": True,
                },
            }
        )
    return sources


def build_ppt_database_package(area_id: str, *, title: str = "") -> PptDataPackageResponse:
    return build_database_data_package(area_id, title=title)
