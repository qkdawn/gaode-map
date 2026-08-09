import logging
import asyncio
import aiohttp
import json
from typing import Awaitable, Callable, List, Dict, Optional, Tuple
from core.config import settings
import time
import random
import math
import re
import unicodedata
from numbers import Number
from pathlib import Path
from urllib.parse import urlencode

from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from core.spatial import polygon_from_payload
from modules.poi.records import poi_semantics
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84, wgs84_to_gcj02

logger = logging.getLogger(__name__)

AMAP_POLYGON_URL = "https://restapi.amap.com/v3/place/polygon"
LOCAL_POLYGON_ENDPOINT = "/place/polygon"
AMAP_POLYGON_MAX_QUERY_LEN = 4300
AMAP_POLYGON_MIN_VERTEX_COUNT = 3
AMAP_POLYGON_PAGE_SIZE = 25
AMAP_POLYGON_RETRIEVABLE_RESULT_LIMIT = 900
AMAP_POLYGON_SATURATION_THRESHOLD = 850
AMAP_TILE_MAX_DEPTH = 7
AMAP_TILE_MIN_SIZE_DEG = 0.0012
AMAP_TILE_MAX_REQUESTS_PER_TYPE = 160
AMAP_POI_MAX_PAGES_PER_TILE = 4
AMAP_POI_MAX_API_CALLS_PER_YEAR = 400
AMAP_POI_CALLS_PER_SECOND = 10
AMAP_QPS_BACKOFF_BASE_SECONDS = 1.5
AMAP_QPS_BACKOFF_MAX_SECONDS = 12.0
AMAP_PAGE_RETRY_COUNT = 2
AMAP_REQUEST_TIMEOUT_SECONDS = 3.0
PARKING_TYPE_PREFIX = "1509"
POI_DEDUP_GRID_SIZE_M = 120.0
POI_DEDUP_DISTANCE_M = 90.0
POI_DEDUP_LOC_PRECISION = 6
POI_ENTRY_EXIT_SUFFIX_RE = re.compile(
    r"(停车场)?(出入口|入口|出口|东门|西门|南门|北门|[A-Za-z]口|[0-9]+号口)$"
)

class AmapPoiFetchError(RuntimeError):
    """Raised when AMap returns an explicit failed response for a POI query."""


def _new_poi_fetch_diagnostics(mode: str = "polygon") -> Dict:
    return {
        "mode": mode,
        "tile_count": 0,
        "request_count": 0,
        "api_call_count": 0,
        "dedup_removed": 0,
        "saturated_queries": 0,
        "request_budget_exceeded": False,
        "api_budget_exceeded": False,
        "incomplete_tiles": [],
        "failed_queries": [],
        "expanded_type_queries": 0,
    }


def _format_amap_error(data: Dict, fallback: str = "AMap polygon query failed") -> str:
    status = data.get("status")
    info = data.get("info")
    infocode = data.get("infocode")
    details = []
    if status is not None:
        details.append(f"status={status}")
    if info:
        details.append(f"info={info}")
    if infocode:
        details.append(f"infocode={infocode}")
    return f"{fallback} ({', '.join(details)})" if details else fallback


class KeyManager:
    """Manages multiple API keys with rotation and exhaustion tracking"""
    def __init__(self, key_string: str):
        self.keys = [k.strip() for k in key_string.split(",") if k.strip()]
        self.current_index = 0
        self.exhausted_indices = set()
        self.lock = asyncio.Lock()
        logger.info(f"KeyManager initialized with {len(self.keys)} keys.")

    def get_current_key(self) -> Optional[str]:
        if len(self.exhausted_indices) >= len(self.keys):
            return None
        start_index = self.current_index
        while self.current_index in self.exhausted_indices:
            self.current_index = (self.current_index + 1) % len(self.keys)
            if self.current_index == start_index: return None
        return self.keys[self.current_index]

    async def report_limit_reached(self):
        async with self.lock:
            if len(self.exhausted_indices) >= len(self.keys): return
            logger.warning(f"Key {self.keys[self.current_index][:6]}... exhausted. Rotating.")
            self.exhausted_indices.add(self.current_index)
            self.current_index = (self.current_index + 1) % len(self.keys)
    
    def rotate(self):
        self.current_index = (self.current_index + 1) % len(self.keys)

class RateLimiter:
    """Token bucket rate limiter + Global smart backoff"""
    def __init__(self, calls_per_second=20):
        self.rate = calls_per_second
        self.tokens = calls_per_second
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()
        self._backoff_until = 0.0

    async def set_rate(self, calls_per_second: int):
        async with self.lock:
            next_rate = max(1, int(calls_per_second or 1))
            if next_rate == self.rate:
                return
            self.rate = next_rate
            self.tokens = min(float(next_rate), float(self.tokens))
            self.last_update = time.monotonic()

    async def acquire(self):
        async with self.lock:
            # Check global backoff
            now = time.monotonic()
            if self._backoff_until > now:
                await asyncio.sleep(self._backoff_until - now)
                now = time.monotonic()

            # Refill tokens
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
                self.last_update = time.monotonic()
            
            self.tokens -= 1

    async def trigger_backoff(self, seconds=5.0):
        """Pause all requests for `seconds`"""
        async with self.lock:
            # Only extend if not already backed off further
            target = time.monotonic() + seconds
            if target > self._backoff_until:
                self._backoff_until = target
                logger.warning(f"Global Rate Limit Triggered! Pausing all requests for {seconds}s")


def _setting_number(name: str, default, *, minimum=None, cast=float):
    raw_value = getattr(settings, name, default)
    if not isinstance(raw_value, (str, Number)):
        return default
    try:
        value = cast(raw_value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return minimum
    return value


def _amap_poi_calls_per_second() -> int:
    return int(_setting_number("amap_poi_calls_per_second", AMAP_POI_CALLS_PER_SECOND, minimum=1, cast=int))


def _amap_tile_max_requests_per_type() -> int:
    return int(_setting_number("amap_tile_max_requests_per_type", AMAP_TILE_MAX_REQUESTS_PER_TYPE, minimum=1, cast=int))


def _amap_poi_max_pages_per_tile() -> int:
    return int(_setting_number("amap_poi_max_pages_per_tile", AMAP_POI_MAX_PAGES_PER_TILE, minimum=1, cast=int))


def _amap_poi_max_api_calls_per_year() -> int:
    return int(_setting_number("amap_poi_max_api_calls_per_year", AMAP_POI_MAX_API_CALLS_PER_YEAR, minimum=1, cast=int))


def _amap_page_retry_count() -> int:
    return int(_setting_number("amap_poi_page_retry_count", AMAP_PAGE_RETRY_COUNT, minimum=1, cast=int))


def _amap_request_timeout_seconds() -> float:
    return float(_setting_number("amap_poi_request_timeout_s", AMAP_REQUEST_TIMEOUT_SECONDS, minimum=0.5, cast=float))


def _amap_qps_backoff_base_seconds() -> float:
    return float(_setting_number("amap_poi_qps_backoff_base_s", AMAP_QPS_BACKOFF_BASE_SECONDS, minimum=0.1, cast=float))


def _amap_qps_backoff_max_seconds() -> float:
    return float(_setting_number("amap_poi_qps_backoff_max_s", AMAP_QPS_BACKOFF_MAX_SECONDS, minimum=0.1, cast=float))


def _qps_backoff_seconds(attempt: int) -> float:
    return min(
        _amap_qps_backoff_max_seconds(),
        _amap_qps_backoff_base_seconds() * (2 ** max(0, int(attempt))) + random.random(),
    )

# Global rate limiter to stay within AMap QPS limits across parallel requests.
global_limiter = RateLimiter(calls_per_second=_amap_poi_calls_per_second())


async def _sync_amap_rate_limiter_from_settings():
    await global_limiter.set_rate(_amap_poi_calls_per_second())


def _is_api_budget_exceeded(diagnostics: Optional[Dict], api_budget: Optional[Dict]) -> bool:
    if diagnostics is not None and diagnostics.get("api_budget_exceeded"):
        return True
    if not api_budget:
        return False
    max_calls = int(api_budget.get("max") or 0)
    if max_calls <= 0:
        return False
    current = int((diagnostics or {}).get("api_call_count") or 0)
    return current >= max_calls


def _mark_api_budget_if_needed(diagnostics: Optional[Dict], api_budget: Optional[Dict]) -> bool:
    if diagnostics is None or not api_budget:
        return False
    max_calls = int(api_budget.get("max") or 0)
    if max_calls <= 0:
        return False
    if int(diagnostics.get("api_call_count") or 0) >= max_calls:
        diagnostics["api_budget_exceeded"] = True
        diagnostics["request_budget_exceeded"] = True
        return True
    return False


def _is_coord_pair(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    )


def _normalize_polygon_rings_input(polygon: list) -> List[List[List[float]]]:
    if not isinstance(polygon, list) or not polygon:
        return []
    if _is_coord_pair(polygon[0]):
        ring = _ensure_polygon_closed(_normalize_polygon_points(polygon))
        return [ring] if len(ring) >= AMAP_POLYGON_MIN_VERTEX_COUNT + 1 else []

    rings: List[List[List[float]]] = []
    for item in polygon:
        ring_source = None
        if isinstance(item, list) and item and _is_coord_pair(item[0]):
            ring_source = item
        elif isinstance(item, list) and item and isinstance(item[0], list) and item[0] and _is_coord_pair(item[0][0]):
            ring_source = item[0]
        if ring_source is None:
            continue
        ring = _ensure_polygon_closed(_normalize_polygon_points(ring_source))
        if len(ring) >= AMAP_POLYGON_MIN_VERTEX_COUNT + 1:
            rings.append(ring)
    return rings


async def _fetch_pois_by_single_polygon(
    polygon: List[List[float]],
    keywords: str,
    types: str = "",
) -> List[Dict]:
    await _sync_amap_rate_limiter_from_settings()
    raw_keys = settings.amap_web_service_key
    if not raw_keys:
        raise ValueError("AMap Web Service Key is missing in settings")

    key_manager = KeyManager(raw_keys)
    normalized_polygon = _normalize_polygon_points(polygon)
    if len(normalized_polygon) < AMAP_POLYGON_MIN_VERTEX_COUNT:
        logger.error("Invalid polygon input")
        return []
    normalized_polygon = _ensure_polygon_closed(normalized_polygon)

    sample_key = key_manager.keys[0] if key_manager.keys else ""
    split_base_polygon = _fit_polygon_to_query_limit(
        normalized_polygon,
        keywords,
        types,
        sample_key,
    )
    type_batches = _split_types_by_query_limit(
        split_base_polygon,
        keywords,
        types,
        sample_key,
    )

    all_pois: List[Dict] = []
    async with aiohttp.ClientSession() as session:
        for batch_index, batch_types in enumerate(type_batches, start=1):
            request_polygon = _fit_polygon_to_query_limit(
                split_base_polygon,
                keywords,
                batch_types,
                sample_key,
            )
            count, first_page_pois = await _fetch_amap_page_one(
                request_polygon,
                keywords,
                batch_types,
                key_manager,
                global_limiter,
                session,
            )
            all_pois.extend(first_page_pois)
            if count > len(first_page_pois):
                remaining = await _fetch_remaining_pages(
                    request_polygon,
                    keywords,
                    batch_types,
                    key_manager,
                    count,
                    global_limiter,
                    session,
                )
                all_pois.extend(remaining)
    return all_pois


async def _fetch_pois_by_single_polygon_with_stats(
    polygon: List[List[float]],
    keywords: str,
    types: str = "",
    *,
    key_manager: KeyManager,
    session,
    max_pages: Optional[int] = None,
    diagnostics: Optional[Dict] = None,
    api_budget: Optional[Dict] = None,
) -> Tuple[int, List[Dict], bool, str]:
    normalized_polygon = _ensure_polygon_closed(_normalize_polygon_points(polygon))
    if len(normalized_polygon) < AMAP_POLYGON_MIN_VERTEX_COUNT + 1:
        return 0, [], False, "invalid polygon"

    sample_key = key_manager.keys[0] if key_manager.keys else ""
    query_len = _estimate_amap_polygon_query_len(
        normalized_polygon,
        keywords,
        types,
        sample_key,
    )
    if query_len > AMAP_POLYGON_MAX_QUERY_LEN:
        return 0, [], False, f"polygon query too long: {query_len}"

    if _is_api_budget_exceeded(diagnostics, api_budget):
        return 0, [], False, "api budget exceeded"
    before_page_one_calls = int((diagnostics or {}).get("api_call_count") or 0)
    count, first_page_pois = await _fetch_amap_page_one(
        normalized_polygon,
        keywords,
        types,
        key_manager,
        global_limiter,
        session,
        diagnostics=diagnostics,
        api_budget=api_budget,
    )
    if diagnostics is not None and int(diagnostics.get("api_call_count") or 0) == before_page_one_calls:
        # Some tests monkeypatch _fetch_amap_page_one with a stub that does not
        # receive diagnostics. Count that stubbed first page as one API call.
        diagnostics["api_call_count"] = int(diagnostics.get("api_call_count") or 0) + 1
        _mark_api_budget_if_needed(diagnostics, api_budget)
    all_pois = list(first_page_pois)
    fetch_complete = True
    error = ""
    if _is_amap_count_saturated(count):
        return int(count or 0), all_pois, False, "query saturated; skipped remaining pages"
    if max_pages is not None and _calculate_amap_page_count(count, AMAP_POLYGON_PAGE_SIZE) > max_pages:
        return int(count or 0), all_pois, False, f"query exceeded tile page budget: {max_pages}"
    if count > len(first_page_pois):
        try:
            remaining = await _fetch_remaining_pages(
                normalized_polygon,
                keywords,
                types,
                key_manager,
                count,
                global_limiter,
                session,
                max_pages=max_pages,
                diagnostics=diagnostics,
                api_budget=api_budget,
            )
            all_pois.extend(remaining)
        except AmapPoiFetchError as exc:
            fetch_complete = False
            error = str(exc)
    if int(count or 0) > len(all_pois):
        fetch_complete = False
    return int(count or 0), all_pois, fetch_complete, error


async def _fetch_local_pois_by_single_polygon(
    polygon: List[List[float]],
    types: str = "",
    year: Optional[int] = None,
) -> List[Dict]:
    normalized_polygon = _normalize_polygon_points(polygon)
    if len(normalized_polygon) < 3:
        logger.error("Invalid local polygon input")
        return []

    request_polygon = _to_local_query_polygon(normalized_polygon)
    polygon_str = ";".join(f"{p[0]:.8f},{p[1]:.8f}" for p in request_polygon)

    base_url = str(settings.local_query_base_url or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("LOCAL_QUERY_BASE_URL 未配置")

    payload: Dict[str, object] = {
        "polygon": polygon_str,
        "types": str(types or ""),
        "pageSize": -1,
    }
    if year is not None:
        payload["year"] = int(year)

    url = f"{base_url}{LOCAL_POLYGON_ENDPOINT}"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(url, json=payload) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Local query HTTP {resp.status}: {body[:200]}")
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Local query request failed: {exc}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Local query response is not JSON: {body[:200]}") from exc

    status = str(data.get("status") or "")
    if status and status != "1":
        raise ValueError(
            "Local query failed: "
            f"status={status}, info={data.get('info')}, infocode={data.get('infocode')}"
        )

    normalized = _normalize_pois(data.get("pois") or [])
    if settings.local_query_coord_system == "wgs84":
        for poi in normalized:
            coords = _extract_poi_location(poi)
            if not coords:
                continue
            gx, gy = wgs84_to_gcj02(coords[0], coords[1])
            poi["location"] = [gx, gy]
    return normalized

async def fetch_pois_by_polygon(
    polygon: list,
    keywords: str,
    types: str = "",
    max_count: int = 0
) -> List[Dict]:
    all_pois: List[Dict] = []
    polygon_rings = _normalize_polygon_rings_input(polygon)
    for ring in polygon_rings:
        ring_pois = await _fetch_pois_by_single_polygon(ring, keywords, types)
        all_pois.extend(ring_pois)
    before_dedup = len(all_pois)
    all_pois = _dedupe_polygon_pois(all_pois)
    if max_count > 0:
        all_pois = all_pois[:max_count]
    after_dedup = len(all_pois)
    logger.info(
        "Fetch Complete. Total POIs: %s (dedup removed=%s)",
        after_dedup,
        max(0, before_dedup - after_dedup),
    )
    return all_pois


async def fetch_pois_by_polygon_tiled(
    polygon: list,
    keywords: str,
    types: str = "",
    max_count: int = 0,
    progress_callback: Optional[Callable[[Dict], Awaitable[None]]] = None,
    fetch_strategy: str = "gaode_tiled_polygon",
    selected_category_count: Optional[int] = None,
) -> Tuple[List[Dict], Dict]:
    await _sync_amap_rate_limiter_from_settings()
    diagnostics = _new_poi_fetch_diagnostics("gaode_tiled_polygon")
    diagnostics["fetch_strategy"] = str(fetch_strategy or "gaode_tiled_polygon")
    if selected_category_count is not None:
        diagnostics["selected_category_count"] = int(selected_category_count)
    raw_keys = settings.amap_web_service_key
    if not raw_keys:
        raise ValueError("AMap Web Service Key is missing in settings")

    scope_geom = polygon_from_payload(polygon)
    if scope_geom.is_empty:
        return [], diagnostics
    scope_geom = scope_geom.buffer(0)
    if scope_geom.is_empty:
        return [], diagnostics

    children_by_parent = _load_type_children_by_parent()
    key_manager = KeyManager(raw_keys)
    api_budget = {"max": _amap_poi_max_api_calls_per_year()}
    sample_key = key_manager.keys[0] if key_manager.keys else ""
    type_queries = _initial_type_queries_for_tiled_fetch(
        types,
        keywords=keywords,
        sample_key=sample_key,
        sample_polygon=_tile_request_polygon(box(*scope_geom.bounds)),
    )
    all_pois: List[Dict] = []

    async with aiohttp.ClientSession() as session:
        for type_code in type_queries:
            type_pois = await _fetch_tiled_type_query(
                scope_geom=scope_geom,
                keywords=keywords,
                type_code=type_code,
                key_manager=key_manager,
                session=session,
                diagnostics=diagnostics,
                children_by_parent=children_by_parent,
                progress_callback=progress_callback,
                api_budget=api_budget,
            )
            if diagnostics.get("api_budget_exceeded"):
                break
            all_pois.extend(type_pois)

    before_filter = len(all_pois)
    all_pois = _filter_pois_to_geometry(all_pois, scope_geom)
    filtered_out = max(0, before_filter - len(all_pois))
    before_dedup = len(all_pois)
    all_pois = _dedupe_polygon_pois(all_pois)
    if max_count > 0:
        all_pois = all_pois[:max_count]
    diagnostics["dedup_removed"] = max(0, before_dedup - len(all_pois))
    diagnostics["filtered_outside_scope"] = filtered_out
    diagnostics["type_query_count"] = len(type_queries)
    diagnostics["merged_type_count"] = len(type_queries)
    logger.info(
        "Tiled Gaode POI fetch complete: total=%s type_queries=%s tiles=%s requests=%s dedup_removed=%s saturated=%s incomplete=%s failed=%s",
        len(all_pois),
        len(type_queries),
        diagnostics.get("tile_count"),
        diagnostics.get("request_count"),
        diagnostics.get("dedup_removed"),
        diagnostics.get("saturated_queries"),
        len(diagnostics.get("incomplete_tiles") or []),
        len(diagnostics.get("failed_queries") or []),
    )
    return all_pois, diagnostics


async def fetch_local_pois_by_polygon(
    polygon: list,
    types: str = "",
    year: Optional[int] = None,
    max_count: int = 0,
) -> List[Dict]:
    normalized: List[Dict] = []
    polygon_rings = _normalize_polygon_rings_input(polygon)
    for ring in polygon_rings:
        ring_pois = await _fetch_local_pois_by_single_polygon(ring, types=types, year=year)
        normalized.extend(ring_pois)

    before_dedup = len(normalized)
    normalized = _dedupe_polygon_pois(normalized)
    if max_count > 0:
        normalized = normalized[:max_count]
    logger.info(
        "Local polygon fetch complete: total=%s dedup_removed=%s",
        len(normalized),
        max(0, before_dedup - len(normalized)),
    )
    return normalized


def _normalize_polygon_points(polygon: List[List[float]]) -> List[List[float]]:
    points: List[List[float]] = []
    for point in polygon or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            lng = float(point[0])
            lat = float(point[1])
            points.append([lng, lat])
        except (TypeError, ValueError):
            continue
    return points


def _ensure_polygon_closed(polygon: List[List[float]]) -> List[List[float]]:
    if not polygon:
        return []
    if len(polygon) == 1:
        return [polygon[0], polygon[0]]
    first = polygon[0]
    last = polygon[-1]
    if first[0] == last[0] and first[1] == last[1]:
        return polygon
    return polygon + [first]


def _split_type_codes(types: str) -> List[str]:
    seen = set()
    codes: List[str] = []
    for raw in str(types or "").split("|"):
        code = re.sub(r"\D", "", raw.strip())
        if len(code) >= 6:
            code = code[:6]
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def _estimate_amap_polygon_query_len(
    polygon: List[List[float]],
    keywords: str,
    types: str,
    key: str,
) -> int:
    polygon_str = ";".join(f"{p[0]:.6f},{p[1]:.6f}" for p in polygon)
    params = {
        "key": str(key or ""),
        "polygon": polygon_str,
        "keywords": str(keywords or ""),
        "types": str(types or ""),
        "offset": 25,
        "page": 1,
        "extensions": "base",
    }
    return len(f"{AMAP_POLYGON_URL}?{urlencode(params)}")


def _split_types_by_query_limit(
    polygon: List[List[float]],
    keywords: str,
    types: str,
    key: str,
    max_query_len: int = AMAP_POLYGON_MAX_QUERY_LEN,
) -> List[str]:
    codes = _split_type_codes(types)
    if not codes:
        return [""]

    batches: List[str] = []
    current_batch: List[str] = []

    for code in codes:
        candidate = current_batch + [code]
        candidate_types = "|".join(candidate)
        candidate_len = _estimate_amap_polygon_query_len(
            polygon, keywords, candidate_types, key
        )
        if current_batch and candidate_len > max_query_len:
            batches.append("|".join(current_batch))
            current_batch = [code]
            continue
        current_batch = candidate

    if current_batch:
        batches.append("|".join(current_batch))

    return batches


def _expand_type_queries_for_tiled_fetch(types: str) -> List[str]:
    codes = _split_type_codes(types)
    if not codes:
        return [""]

    children_by_parent = _load_type_children_by_parent()
    expanded: List[str] = []
    seen = set()
    for code in codes:
        candidates = _leaf_type_codes_for_parent(code, children_by_parent)
        candidates = candidates or [code]
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded or [""]


def _initial_type_queries_for_tiled_fetch(
    types: str,
    *,
    keywords: str = "",
    sample_key: str = "",
    sample_polygon: Optional[List[List[float]]] = None,
) -> List[str]:
    codes = _split_type_codes(types)
    if not codes:
        return [""]
    polygon = sample_polygon or [[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]
    return _split_types_by_query_limit(polygon, keywords, "|".join(codes), sample_key)


def _leaf_type_codes_for_parent(code: str, children_by_parent: Dict[str, List[str]]) -> List[str]:
    normalized = re.sub(r"\D", "", str(code or ""))[:6]
    if len(normalized) != 6:
        return []
    child_codes = [child for child in children_by_parent.get(normalized, []) if child != normalized]
    if not child_codes:
        return []

    child_set = set(child_codes)
    leaf_codes: List[str] = []
    for child in child_codes:
        descendants = [
            descendant
            for descendant in children_by_parent.get(child, [])
            if descendant != child and descendant in child_set
        ]
        if descendants:
            continue
        leaf_codes.append(child)
    return leaf_codes or child_codes


_TYPE_CHILDREN_CACHE: Optional[Dict[str, List[str]]] = None


def _load_type_children_by_parent() -> Dict[str, List[str]]:
    global _TYPE_CHILDREN_CACHE
    if _TYPE_CHILDREN_CACHE is not None:
        return _TYPE_CHILDREN_CACHE

    children: Dict[str, set] = {}
    try:
        path = Path(__file__).resolve().parents[2] / "share" / "type_map.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to load type_map.json for POI type expansion: %s", exc)
        _TYPE_CHILDREN_CACHE = {}
        return _TYPE_CHILDREN_CACHE

    def collect(item):
        if isinstance(item, dict):
            raw_types = str(item.get("types") or "")
            for code in _split_type_codes(raw_types):
                if len(code) != 6:
                    continue
                children.setdefault(code[:2] + "0000", set()).add(code)
                children.setdefault(code[:4] + "00", set()).add(code)
            for value in item.values():
                collect(value)
        elif isinstance(item, list):
            for value in item:
                collect(value)

    collect(data)
    _TYPE_CHILDREN_CACHE = {
        parent: sorted(value)
        for parent, value in children.items()
        if len(value) > 1
    }
    return _TYPE_CHILDREN_CACHE


def _downsample_polygon_vertices(polygon: List[List[float]]) -> List[List[float]]:
    if len(polygon) <= AMAP_POLYGON_MIN_VERTEX_COUNT + 1:
        return polygon

    open_ring = polygon[:-1]
    reduced = open_ring[::2]
    if len(reduced) < AMAP_POLYGON_MIN_VERTEX_COUNT:
        reduced = open_ring[:AMAP_POLYGON_MIN_VERTEX_COUNT]
    return _ensure_polygon_closed(reduced)


def _fit_polygon_to_query_limit(
    polygon: List[List[float]],
    keywords: str,
    types: str,
    key: str,
    max_query_len: int = AMAP_POLYGON_MAX_QUERY_LEN,
) -> List[List[float]]:
    fitted = _ensure_polygon_closed(_normalize_polygon_points(polygon))
    if len(fitted) < AMAP_POLYGON_MIN_VERTEX_COUNT + 1:
        return fitted

    query_len = _estimate_amap_polygon_query_len(fitted, keywords, types, key)
    while query_len > max_query_len and len(fitted) > AMAP_POLYGON_MIN_VERTEX_COUNT + 1:
        fitted = _downsample_polygon_vertices(fitted)
        query_len = _estimate_amap_polygon_query_len(fitted, keywords, types, key)

    if query_len > max_query_len:
        logger.warning(
            "AMap polygon query remains long after downsample: query_len=%s points=%s",
            query_len,
            len(fitted),
        )

    return fitted


async def _fetch_tiled_type_query(
    *,
    scope_geom: BaseGeometry,
    keywords: str,
    type_code: str,
    key_manager: KeyManager,
    session,
    diagnostics: Dict,
    children_by_parent: Optional[Dict[str, List[str]]] = None,
    progress_callback: Optional[Callable[[Dict], Awaitable[None]]] = None,
    api_budget: Optional[Dict] = None,
) -> List[Dict]:
    minx, miny, maxx, maxy = scope_geom.bounds
    root_tile = box(minx, miny, maxx, maxy)
    stack: List[Tuple[BaseGeometry, int]] = [(root_tile, 0)]
    pois: List[Dict] = []
    type_request_count = 0

    while stack:
        tile_geom, depth = stack.pop()
        if tile_geom.is_empty or not tile_geom.intersects(scope_geom):
            continue

        if _is_api_budget_exceeded(diagnostics, api_budget):
            diagnostics["api_budget_exceeded"] = True
            diagnostics["request_budget_exceeded"] = True
            diagnostics.setdefault("incomplete_tiles", []).append(
                _tile_diagnostic_row(tile_geom, depth, type_code, "year_api_budget_exceeded")
            )
            break

        clipped = tile_geom.intersection(scope_geom)
        if clipped.is_empty:
            continue

        max_requests_per_type = _amap_tile_max_requests_per_type()
        if type_request_count >= max_requests_per_type:
            diagnostics["request_budget_exceeded"] = True
            diagnostics.setdefault("incomplete_tiles", []).append(
                _tile_diagnostic_row(tile_geom, depth, type_code, "tile_request_budget_exceeded")
            )
            for remaining_tile, remaining_depth in stack:
                if remaining_tile.is_empty or not remaining_tile.intersects(scope_geom):
                    continue
                diagnostics.setdefault("incomplete_tiles", []).append(
                    _tile_diagnostic_row(
                        remaining_tile,
                        remaining_depth,
                        type_code,
                        "tile_request_budget_exceeded",
                    )
                )
            break

        request_polygon = _tile_request_polygon(tile_geom)
        type_request_count += 1
        diagnostics["tile_count"] = int(diagnostics.get("tile_count") or 0) + 1
        diagnostics["request_count"] = int(diagnostics.get("request_count") or 0) + 1
        await _emit_tiled_fetch_progress(
            progress_callback,
            diagnostics=diagnostics,
            type_code=type_code,
            depth=depth,
            stage="tile_request",
            force=diagnostics["request_count"] == 1,
        )
        try:
            count, tile_pois, fetch_complete, fetch_error = await _fetch_pois_by_single_polygon_with_stats(
                request_polygon,
                keywords,
                type_code,
                key_manager=key_manager,
                session=session,
                max_pages=_amap_poi_max_pages_per_tile(),
                diagnostics=diagnostics,
                api_budget=api_budget,
            )
        except Exception as exc:
            diagnostics.setdefault("failed_queries", []).append(
                _tile_diagnostic_row(tile_geom, depth, type_code, str(exc))
            )
            continue

        is_saturated = _is_tile_query_saturated(count, len(tile_pois), fetch_complete)
        if is_saturated:
            diagnostics["saturated_queries"] = int(diagnostics.get("saturated_queries") or 0) + 1
            if _can_subdivide_tile(tile_geom, depth):
                stack.extend((child, depth + 1) for child in _subdivide_tile(tile_geom))
                continue
            child_type_codes = _leaf_type_codes_for_parent(type_code, children_by_parent or {})
            if child_type_codes:
                diagnostics["expanded_type_queries"] = int(diagnostics.get("expanded_type_queries") or 0) + len(child_type_codes)
                for child_type_code in child_type_codes:
                    child_pois = await _fetch_tiled_type_query(
                        scope_geom=tile_geom.intersection(scope_geom),
                        keywords=keywords,
                        type_code=child_type_code,
                        key_manager=key_manager,
                        session=session,
                        diagnostics=diagnostics,
                        children_by_parent=children_by_parent,
                        progress_callback=progress_callback,
                        api_budget=api_budget,
                    )
                    pois.extend(child_pois)
                    if diagnostics.get("api_budget_exceeded"):
                        break
                continue
            diagnostics.setdefault("incomplete_tiles", []).append(
                _tile_diagnostic_row(tile_geom, depth, type_code, fetch_error or "query remained saturated")
            )

        pois.extend(tile_pois)

    return pois


async def _emit_tiled_fetch_progress(
    progress_callback: Optional[Callable[[Dict], Awaitable[None]]],
    *,
    diagnostics: Dict,
    type_code: str,
    depth: int,
    stage: str,
    force: bool = False,
) -> None:
    if progress_callback is None:
        return
    request_count = int(diagnostics.get("request_count") or 0)
    if not force and request_count % 10 != 0:
        return
    await progress_callback(
        {
            "stage": stage,
            "type_code": str(type_code or ""),
            "depth": int(depth),
            "tile_count": int(diagnostics.get("tile_count") or 0),
            "request_count": request_count,
            "api_call_count": int(diagnostics.get("api_call_count") or 0),
            "saturated_queries": int(diagnostics.get("saturated_queries") or 0),
            "expanded_type_queries": int(diagnostics.get("expanded_type_queries") or 0),
        }
    )


def _tile_request_polygon(tile_geom: BaseGeometry) -> List[List[float]]:
    minx, miny, maxx, maxy = tile_geom.bounds
    return [
        [float(minx), float(miny)],
        [float(maxx), float(miny)],
        [float(maxx), float(maxy)],
        [float(minx), float(maxy)],
        [float(minx), float(miny)],
    ]


def _subdivide_tile(tile_geom: BaseGeometry) -> List[BaseGeometry]:
    minx, miny, maxx, maxy = tile_geom.bounds
    midx = (minx + maxx) / 2.0
    midy = (miny + maxy) / 2.0
    return [
        box(minx, miny, midx, midy),
        box(midx, miny, maxx, midy),
        box(minx, midy, midx, maxy),
        box(midx, midy, maxx, maxy),
    ]


def _can_subdivide_tile(tile_geom: BaseGeometry, depth: int) -> bool:
    if depth >= AMAP_TILE_MAX_DEPTH:
        return False
    minx, miny, maxx, maxy = tile_geom.bounds
    return (maxx - minx) > AMAP_TILE_MIN_SIZE_DEG and (maxy - miny) > AMAP_TILE_MIN_SIZE_DEG


def _is_tile_query_saturated(count: int, fetched_count: int, fetch_complete: bool) -> bool:
    if _is_amap_count_saturated(count):
        return True
    if not fetch_complete:
        try:
            total = int(count or 0)
        except (TypeError, ValueError):
            total = 0
        return total > fetched_count
    return False


def _is_amap_count_saturated(count: int) -> bool:
    try:
        total = int(count or 0)
    except (TypeError, ValueError):
        total = 0
    if total >= AMAP_POLYGON_SATURATION_THRESHOLD:
        return True
    if total >= AMAP_POLYGON_RETRIEVABLE_RESULT_LIMIT:
        return True
    return False


def _tile_diagnostic_row(tile_geom: BaseGeometry, depth: int, type_code: str, reason: str) -> Dict:
    minx, miny, maxx, maxy = tile_geom.bounds
    return {
        "type": str(type_code or ""),
        "depth": int(depth),
        "bounds": [round(float(minx), 6), round(float(miny), 6), round(float(maxx), 6), round(float(maxy), 6)],
        "reason": str(reason or ""),
    }


def _filter_pois_to_geometry(pois: List[Dict], scope_geom: BaseGeometry) -> List[Dict]:
    if not pois or scope_geom.is_empty:
        return []
    prepared = prep(scope_geom)
    filtered: List[Dict] = []
    for poi in pois:
        coords = _extract_poi_location(poi)
        if not coords:
            continue
        point = Point(coords[0], coords[1])
        if prepared.contains(point) or scope_geom.touches(point):
            filtered.append(poi)
    return filtered


def _to_local_query_polygon(polygon_gcj02: List[List[float]]) -> List[List[float]]:
    if settings.local_query_coord_system != "wgs84":
        return polygon_gcj02
    converted: List[List[float]] = []
    for lng, lat in polygon_gcj02:
        wx, wy = gcj02_to_wgs84(lng, lat)
        converted.append([wx, wy])
    return converted


async def _fetch_amap_page_one(
    polygon,
    keywords,
    types,
    key_manager,
    limiter,
    session,
    diagnostics: Optional[Dict] = None,
    api_budget: Optional[Dict] = None,
):
    """Fetch page 1 to get total count and first batch"""
    poly_str = ";".join([f"{p[0]:.6f},{p[1]:.6f}" for p in polygon])
    last_error = ""
    
    # Retry loop for key rotation
    for key_attempt in range(len(key_manager.keys) + 1):
        current_key = key_manager.get_current_key()
        if not current_key:
             message = "AMap API keys exhausted or unavailable"
             if last_error:
                 message = f"{message}; last_error={last_error}"
             logger.error(message)
             raise AmapPoiFetchError(message)

        params = {
            "key": current_key, "polygon": poly_str, "keywords": keywords, "types": types,
            "offset": 25, "page": 1, "extensions": "base"
        }

        # Request loop (network retries)
        for attempt in range(_amap_page_retry_count()):
            if _is_api_budget_exceeded(diagnostics, api_budget):
                raise AmapPoiFetchError("api budget exceeded")
            await limiter.acquire()
            if diagnostics is not None:
                diagnostics["api_call_count"] = int(diagnostics.get("api_call_count") or 0) + 1
                _mark_api_budget_if_needed(diagnostics, api_budget)
            try:
                async with session.get(AMAP_POLYGON_URL, params=params, timeout=_amap_request_timeout_seconds()) as resp:
                    if resp.status != 200:
                        last_error = f"HTTP {resp.status}"
                        logger.warning(last_error)
                        continue
                    
                    data = await resp.json()
                    status = data.get("status")
                    
                    if status == "1":
                        count = int(data.get("count", 0))
                        pois = _normalize_pois(data.get("pois", []))
                        key_manager.rotate() # Success, rotate for load balancing
                        return count, pois
                    elif status == "0" and data.get("infocode") == "10003":
                        # QPS Limit
                        last_error = _format_amap_error(data, "AMap QPS limit")
                        await limiter.trigger_backoff(_qps_backoff_seconds(attempt))
                        continue # Retry same key
                    elif status == "0" and data.get("infocode") == "10044":
                        # DAILY LIMIT - Switch Key!
                        last_error = _format_amap_error(data, "AMap daily quota limit")
                        logger.warning(f"Daily limit reached for key {current_key[:6]}... Switching...")
                        await key_manager.report_limit_reached()
                        break # Break retry loop to outer key loop
                    else:
                        last_error = _format_amap_error(data)
                        logger.warning(f"Key {current_key[:6]}... Error: {last_error}")
                        raise AmapPoiFetchError(last_error)
            except Exception as e:
                if isinstance(e, AmapPoiFetchError):
                    raise
                last_error = str(e)
                logger.warning(f"Fetch page 1 error: {e}")
                await asyncio.sleep(min(4.0, 0.8 * (attempt + 1)))
        else:
            # If we exhausted attempts without switching keys (e.g. network error), return
            # But if we broke out due to 10044, we continue to next key
            pass

    raise AmapPoiFetchError(last_error or "AMap page 1 fetch failed after retries")

async def _fetch_remaining_pages(
    polygon,
    keywords,
    types,
    key_manager,
    total_count,
    limiter,
    session,
    max_pages: Optional[int] = None,
    diagnostics: Optional[Dict] = None,
    api_budget: Optional[Dict] = None,
):
    """Fetch pages 2..N"""
    poly_str = ";".join([f"{p[0]:.6f},{p[1]:.6f}" for p in polygon])
    all_pois = []
    page_size = AMAP_POLYGON_PAGE_SIZE
    calculated_pages = _calculate_amap_page_count(total_count, page_size)
    max_pages = min(calculated_pages, int(max_pages or calculated_pages))
    last_error = ""
    
    # Start from page 2
    for page in range(2, max_pages + 1):
        if _is_api_budget_exceeded(diagnostics, api_budget):
            raise AmapPoiFetchError("api budget exceeded")
        # Key Rotation Loop for EACH page
        success = False
        for key_attempt in range(len(key_manager.keys) + 1):
            current_key = key_manager.get_current_key()
            if not current_key:
                last_error = "AMap API keys exhausted or unavailable"
                break

            params = {
                "key": current_key, "polygon": poly_str, "keywords": keywords, "types": types,
                "offset": page_size, "page": page, "extensions": "base"
            }
            
            # Network Attempt Loop
            for attempt in range(_amap_page_retry_count()):
                if _is_api_budget_exceeded(diagnostics, api_budget):
                    raise AmapPoiFetchError("api budget exceeded")
                await limiter.acquire()
                try:
                    async with session.get(AMAP_POLYGON_URL, params=params, timeout=_amap_request_timeout_seconds()) as resp:
                        if diagnostics is not None:
                            diagnostics["api_call_count"] = int(diagnostics.get("api_call_count") or 0) + 1
                            _mark_api_budget_if_needed(diagnostics, api_budget)
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == "1":
                                pois = _normalize_pois(data.get("pois", []))
                                key_manager.rotate()
                                if not pois:
                                    return all_pois
                                all_pois.extend(pois)
                                success = True
                                break
                            elif data.get("infocode") == "10003":
                                last_error = _format_amap_error(data, "AMap QPS limit")
                                await limiter.trigger_backoff(_qps_backoff_seconds(attempt))
                            elif data.get("infocode") == "10044":
                                 last_error = _format_amap_error(data, "AMap daily quota limit")
                                 logger.warning(f"Daily limit (page fetch) for key {current_key[:6]}... Switching...")
                                 await key_manager.report_limit_reached()
                                 break # Break network loop, retry with new key
                            else:
                                last_error = _format_amap_error(data)
                        else:
                            last_error = f"HTTP {resp.status}"
                except Exception as exc:
                    last_error = str(exc)
                    await asyncio.sleep(min(4.0, 0.8 * (attempt + 1)))
            
            if success: break # Page fetched, move to next page
        
        if not success:
            message = (
                f"AMap page {page} fetch failed after retries"
                f"; fetched {len(all_pois)} of estimated {total_count}"
            )
            if last_error:
                message = f"{message}; last_error={last_error}"
            logger.warning(message)
            raise AmapPoiFetchError(message)
            
    return all_pois


def _calculate_amap_page_count(total_count, page_size: int = 25) -> int:
    try:
        total = max(0, int(total_count or 0))
    except (TypeError, ValueError):
        total = 0
    page_size = max(1, int(page_size or 1))
    return max(1, math.ceil(total / page_size))

def _normalize_pois(raw_list: List[Dict]) -> List[Dict]:
    results = []
    for p in raw_list:
        try:
            loc_str = p.get("location")
            if not loc_str or isinstance(loc_str, list): continue
            lng, lat = map(float, loc_str.split(","))
            
            semantics = poi_semantics(p)
            
            address = p.get("address")
            if isinstance(address, list): address = str(address[0]) if address else ""
            if address is None: address = ""
            
            # Simple lines extraction
            lines = []
            if "路" in str(address) or "线" in str(address):
                lines = [address] 
            
            results.append({
                "id": str(p.get("id", "")),
                "poi_id": str(p.get("id", "")),
                "name": str(p.get("name", "未命名")),
                "location": [lng, lat],
                "address": str(address),
                "type": semantics["typecode"],
                **semantics,
                "adname": str(p.get("adname", "")),
                "year": _safe_int(p.get("year")),
                "source": str(p.get("source") or ""),
                "lines": lines
            })
        except:
            continue
    return results


def _safe_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dedupe_polygon_pois(pois: List[Dict]) -> List[Dict]:
    """
    Two-stage dedupe for polygon POI results:
    1) exact dedupe: id or (normalized name + rounded location)
    2) semantic-spatial dedupe for parking entry/exit variants
    """
    if not pois:
        return []

    exact_seen = set()
    exact_deduped: List[Dict] = []
    for poi in pois:
        key = _build_poi_exact_key(poi)
        if key in exact_seen:
            continue
        exact_seen.add(key)
        exact_deduped.append(poi)

    cell_size_deg = POI_DEDUP_GRID_SIZE_M / 111_000.0
    parking_bucket: Dict[Tuple[int, int], List[Dict]] = {}
    kept: List[Dict] = []

    for poi in exact_deduped:
        if not _is_parking_like_poi(poi):
            kept.append(poi)
            continue

        coords = _extract_poi_location(poi)
        if not coords:
            kept.append(poi)
            continue

        canonical_name = _canonical_parking_name(str(poi.get("name") or ""))
        if not canonical_name:
            kept.append(poi)
            continue

        cell_x = int(math.floor(coords[0] / cell_size_deg))
        cell_y = int(math.floor(coords[1] / cell_size_deg))
        is_duplicate = False

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbors = parking_bucket.get((cell_x + dx, cell_y + dy), [])
                for other in neighbors:
                    if other.get("canonical_name") != canonical_name:
                        continue
                    other_coords = other.get("coords")
                    if not other_coords:
                        continue
                    if _haversine_m(coords, other_coords) <= POI_DEDUP_DISTANCE_M:
                        is_duplicate = True
                        break
                if is_duplicate:
                    break
            if is_duplicate:
                break

        if is_duplicate:
            continue

        kept.append(poi)
        parking_bucket.setdefault((cell_x, cell_y), []).append(
            {"canonical_name": canonical_name, "coords": coords}
        )

    return kept


def _build_poi_exact_key(poi: Dict) -> str:
    poi_id = str(poi.get("id") or "").strip()
    if poi_id:
        return f"id:{poi_id}"

    name = _normalize_text(str(poi.get("name") or ""))
    coords = _extract_poi_location(poi)
    if coords:
        return "name_loc:{name}|{lng:.{p}f},{lat:.{p}f}".format(
            name=name,
            lng=coords[0],
            lat=coords[1],
            p=POI_DEDUP_LOC_PRECISION,
        )
    return f"name_only:{name}"


def _normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"\s+", "", value)
    return value.strip()


def _extract_poi_location(poi: Dict) -> Optional[Tuple[float, float]]:
    raw = poi.get("location")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        parts = raw.split(",")
        if len(parts) < 2:
            return None
        try:
            return float(parts[0]), float(parts[1])
        except (TypeError, ValueError):
            return None
    return None


def _is_parking_like_poi(poi: Dict) -> bool:
    raw_type = str(poi.get("type") or poi.get("typecode") or "").strip()
    type_digits = re.sub(r"\D", "", raw_type)
    if type_digits.startswith(PARKING_TYPE_PREFIX):
        return True
    name = str(poi.get("name") or "")
    return "停车" in name


def _canonical_parking_name(name: str) -> str:
    if not name:
        return ""
    value = _normalize_text(name)
    value = POI_ENTRY_EXIT_SUFFIX_RE.sub("", value)
    value = value.replace("停车场出入口", "停车场")
    value = value.replace("停车场入口", "停车场")
    value = value.replace("停车场出口", "停车场")
    return value.strip("-_")


def _haversine_m(
    a: Tuple[float, float],
    b: Tuple[float, float],
) -> float:
    lng1, lat1 = a
    lng2, lat2 = b
    lng1, lat1, lng2, lat2 = map(math.radians, (lng1, lat1, lng2, lat2))
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * 6_371_000.0 * math.asin(math.sqrt(x))
