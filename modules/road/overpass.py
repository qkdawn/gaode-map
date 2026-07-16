from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import requests

from core.config import settings

OVERPASS_USER_AGENT = "gaode-map-dev/0.1"

OverpassMode = Literal["walking", "bicycling", "driving"]
HighwayFilter = Literal["mode", "all", "major"]

MODE_HIGHWAY_REGEX: Dict[OverpassMode, str] = {
    "walking": (
        "footway|path|pedestrian|living_street|residential|unclassified|service|track|steps|"
        "cycleway|tertiary|secondary|primary"
    ),
    "bicycling": (
        "cycleway|path|living_street|residential|unclassified|service|track|"
        "tertiary|secondary|primary"
    ),
    "driving": (
        "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service"
    ),
}
MAJOR_HIGHWAY_REGEX = (
    "motorway|motorway_link|trunk|trunk_link|primary|primary_link|"
    "secondary|secondary_link"
)

_OVERPASS_CACHE_LOCK = threading.Lock()
_OVERPASS_QUERY_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def build_overpass_query(
    bbox: Tuple[float, float, float, float],
    mode: OverpassMode,
    highway_filter: HighwayFilter = "mode",
    query_timeout_s: int = 25,
) -> str:
    south, west, north, east = bbox
    timeout_value = max(10, int(query_timeout_s or 25))
    if highway_filter == "all":
        return f"""
[out:json][timeout:{timeout_value}];
(
  way["highway"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});
);
out body geom;
"""
    if highway_filter == "major":
        return f"""
[out:json][timeout:{timeout_value}];
(
  way["highway"~"{MAJOR_HIGHWAY_REGEX}"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});
);
out body geom;
"""
    regex = MODE_HIGHWAY_REGEX.get(mode, MODE_HIGHWAY_REGEX["walking"])
    return f"""
[out:json][timeout:{timeout_value}];
(
  way["highway"~"{regex}"]({south:.7f},{west:.7f},{north:.7f},{east:.7f});
);
out body geom;
"""


def resolve_overpass_endpoint() -> str:
    return resolve_overpass_endpoints()[0]


def resolve_overpass_endpoints() -> List[str]:
    primary = str(getattr(settings, "overpass_endpoint", "") or "").strip()
    fallback_raw = str(getattr(settings, "overpass_fallback_endpoints", "") or "").strip()
    candidates = [primary, *re.split(r"[,;\s]+", fallback_raw)]
    endpoints: List[str] = []
    for candidate in candidates:
        endpoint = str(candidate or "").strip().rstrip("/")
        if endpoint and endpoint not in endpoints:
            endpoints.append(endpoint)
    if not endpoints:
        raise RuntimeError("OVERPASS_ENDPOINT 未配置，请设置本地 Overpass 地址。")
    return endpoints


def _is_retryable_overpass_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    text = str(exc).lower()
    retryable_markers = (
        "http 408",
        "http 429",
        "http 5",
        "timeout",
        "timed out",
        "runtime error",
        "connection refused",
        "connection aborted",
        "connection reset",
        "empty response body",
        "non-json response",
        "invalid json payload",
    )
    return any(marker in text for marker in retryable_markers)


def get_overpass_cache(query: str, ttl_s: int) -> Optional[List[Dict[str, Any]]]:
    if ttl_s <= 0:
        return None
    now = time.time()
    with _OVERPASS_CACHE_LOCK:
        item = _OVERPASS_QUERY_CACHE.get(query)
        if not item:
            return None
        ts, cached = item
        if now - ts > ttl_s:
            _OVERPASS_QUERY_CACHE.pop(query, None)
            return None
        return cached


def set_overpass_cache(query: str, elements: List[Dict[str, Any]], ttl_s: int, max_entries: int) -> None:
    if ttl_s <= 0:
        return
    now = time.time()
    max_allowed = max(1, int(max_entries or 16))
    with _OVERPASS_CACHE_LOCK:
        _OVERPASS_QUERY_CACHE[query] = (now, elements)
        if len(_OVERPASS_QUERY_CACHE) <= max_allowed:
            return
        expired_keys = [key for key, (ts, _) in _OVERPASS_QUERY_CACHE.items() if now - ts > ttl_s]
        for key in expired_keys:
            _OVERPASS_QUERY_CACHE.pop(key, None)
        if len(_OVERPASS_QUERY_CACHE) <= max_allowed:
            return
        sorted_items = sorted(_OVERPASS_QUERY_CACHE.items(), key=lambda kv: kv[1][0])
        extra = len(_OVERPASS_QUERY_CACHE) - max_allowed
        for key, _ in sorted_items[:extra]:
            _OVERPASS_QUERY_CACHE.pop(key, None)


def fetch_overpass_elements(query: str) -> List[Dict[str, Any]]:
    endpoints = resolve_overpass_endpoints()
    cache_ttl_s = max(0, int(getattr(settings, "overpass_cache_ttl_s", 45) or 0))
    cache_max_entries = max(1, int(getattr(settings, "overpass_cache_max_entries", 16) or 16))
    cached = get_overpass_cache(query, cache_ttl_s)
    if cached is not None:
        return cached

    retry_count = max(0, int(getattr(settings, "overpass_retry_count", 1) or 0))
    read_timeout_s = max(20, int(getattr(settings, "overpass_http_timeout_s", 90) or 90))
    connect_timeout_s = min(15, max(3, read_timeout_s // 8))

    attempt_count = max(len(endpoints), retry_count + 1)
    failures: List[str] = []
    last_error: Optional[Exception] = None
    for attempt in range(attempt_count):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": OVERPASS_USER_AGENT},
                timeout=(connect_timeout_s, read_timeout_s),
            )
            if response.status_code != 200:
                preview = (response.text or "").strip().replace("\n", " ")[:280]
                raise RuntimeError(f"HTTP {response.status_code}, body={preview}")
            raw = (response.text or "").strip()
            if not raw:
                raise RuntimeError("empty response body")
            if raw[:1] != "{":
                preview = raw.replace("\n", " ")[:320]
                if "runtime error" in raw.lower() or "timed out" in raw.lower():
                    raise RuntimeError(f"Overpass query timeout/error: {preview}")
                raise RuntimeError(f"non-JSON response: {preview}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("invalid JSON payload")
            elements = payload.get("elements") or []
            set_overpass_cache(query, elements, cache_ttl_s, cache_max_entries)
            return elements
        except Exception as exc:
            last_error = exc
            failures.append(f"{endpoint}: {exc}")
            can_retry = attempt + 1 < attempt_count and _is_retryable_overpass_error(exc)
            if not can_retry:
                break
            time.sleep(0.8 + attempt * 0.7)

    detail = " | ".join(failures)
    raise RuntimeError(
        f"Overpass query timeout/error after {len(failures)} endpoint attempt(s): {detail}"
    ) from last_error


def normalize_label(radius_m: int) -> str:
    return f"r{int(radius_m)}"


def radius_label_from_header(header: str) -> str:
    match = re.search(r"\bR(\d+(?:\.\d+)?)\b", header or "", flags=re.IGNORECASE)
    if not match:
        return "global"
    value = float(match.group(1))
    if value.is_integer():
        return f"r{int(value)}"
    return "r" + str(value).replace(".", "_")


def build_radius_arg(radii_m: List[int]) -> str:
    cleaned = sorted({int(r) for r in radii_m if int(r) > 0})
    if not cleaned:
        return "n"
    return ",".join([str(v) for v in cleaned] + ["n"])
