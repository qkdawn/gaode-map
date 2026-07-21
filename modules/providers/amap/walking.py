"""AMap Web Service pedestrian-route adapter for report evidence.

The adapter owns provider-specific coordinate normalization, throttling, request
validation and error translation.  It returns only distance and duration; route
geometry and API details do not escape into report or MCP payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any, Callable

import requests

from core.config import settings
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02


class AMapWalkingRouteBlocked(RuntimeError):
    """Raised when AMap cannot provide a usable pedestrian route."""


@dataclass(frozen=True)
class AMapWalkingRoute:
    distance_m: float
    duration_s: float


class AMapWalkingRouteAdapter:
    """Call AMap's Web Service walking-route endpoint from WGS84 inputs."""

    _ENDPOINT = "https://restapi.amap.com/v5/direction/walking"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout_s: float | None = None,
        min_interval_s: float | None = None,
        get: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else settings.amap_web_service_key).split(",", 1)[0].strip()
        self._endpoint = endpoint or self._ENDPOINT
        self._timeout_s = float(timeout_s if timeout_s is not None else settings.amap_route_timeout_s)
        self._min_interval_s = max(0.0, float(min_interval_s if min_interval_s is not None else settings.amap_route_min_interval_s))
        self._get = get or requests.get
        self._clock = clock or monotonic
        self._sleep = sleeper or sleep
        self._last_request_at: float | None = None

    def route(self, origin: tuple[float, float], destination: tuple[float, float]) -> AMapWalkingRoute:
        if not self._api_key:
            raise AMapWalkingRouteBlocked("amap_web_service_key_missing")
        origin_wgs84 = _coordinate(origin, "origin")
        destination_wgs84 = _coordinate(destination, "destination")
        origin_gcj02 = wgs84_to_gcj02(*origin_wgs84)
        destination_gcj02 = wgs84_to_gcj02(*destination_wgs84)
        self._throttle()
        try:
            response = self._get(
                self._endpoint,
                params={
                    "key": self._api_key,
                    "origin": _location(origin_gcj02),
                    "destination": _location(destination_gcj02),
                    "show_fields": "cost",
                },
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise AMapWalkingRouteBlocked("amap_walking_unavailable") from exc
        finally:
            self._last_request_at = self._clock()
        return _parse_walking_route(payload)

    def _throttle(self) -> None:
        if self._last_request_at is None or self._min_interval_s <= 0:
            return
        remaining = self._min_interval_s - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)


def _coordinate(value: tuple[float, float], label: str) -> tuple[float, float]:
    try:
        lng, lat = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise AMapWalkingRouteBlocked(f"amap_{label}_invalid") from exc
    if not -180 <= lng <= 180 or not -90 <= lat <= 90:
        raise AMapWalkingRouteBlocked(f"amap_{label}_invalid")
    return lng, lat


def _location(coordinate: tuple[float, float]) -> str:
    return f"{coordinate[0]:.6f},{coordinate[1]:.6f}"


def _parse_walking_route(payload: Any) -> AMapWalkingRoute:
    if not isinstance(payload, dict):
        raise AMapWalkingRouteBlocked("amap_walking_response_invalid")
    if str(payload.get("status") or "") not in {"1", "true", "True"}:
        raise AMapWalkingRouteBlocked("amap_walking_rejected")
    route = payload.get("route")
    paths = route.get("paths") if isinstance(route, dict) else None
    first = paths[0] if isinstance(paths, list) and paths and isinstance(paths[0], dict) else None
    if first is None:
        raise AMapWalkingRouteBlocked("amap_walking_route_missing")
    try:
        distance_m = float(first["distance"])
        duration_s = float(first["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AMapWalkingRouteBlocked("amap_walking_measurements_invalid") from exc
    if distance_m <= 0 or duration_s <= 0:
        raise AMapWalkingRouteBlocked("amap_walking_measurements_invalid")
    return AMapWalkingRoute(distance_m=distance_m, duration_s=duration_s)
