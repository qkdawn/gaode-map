"""
Reverse geocoding helper using the Gaode regeo API.
"""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.config import settings

logger = logging.getLogger(__name__)


def reverse_geocode(
    lng: float,
    lat: float,
    api_key: Optional[str] = None,
    mock_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if mock_response is not None:
        payload = mock_response
    else:
        key = (api_key or settings.amap_web_service_key or "").split(",", 1)[0].strip()
        if not key:
            raise ValueError("Gaode Web 服务 key 未配置")
        params = {
            "key": key,
            "location": f"{float(lng):.6f},{float(lat):.6f}",
            "extensions": "base",
            "radius": 1000,
            "roadlevel": 0,
        }
        payload = _request_json(f"https://restapi.amap.com/v3/geocode/regeo?{urlencode(params)}")
    logger.debug("Gaode regeo response: %s", payload)
    if str(payload.get("status") or "") not in {"1", "true", "True"}:
        raise ValueError(f"Gaode regeo failed: {payload.get('info') or payload.get('infocode') or 'unknown'}")
    regeocode = payload.get("regeocode")
    if not isinstance(regeocode, dict):
        raise ValueError("Gaode regeo returned no regeocode")
    return regeocode


def _request_json(url: str) -> Dict[str, Any]:
    req = Request(url, headers={"User-Agent": "gaode-map-plugin/1.0"})
    ssl_context = ssl._create_unverified_context()
    with urlopen(req, timeout=15, context=ssl_context) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))
