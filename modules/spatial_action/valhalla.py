from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import requests
from shapely.geometry import LineString, mapping

from core.config import settings


class ValhallaRouteBlocked(RuntimeError):
    """A real pedestrian route could not be produced; callers must not fabricate one."""


@dataclass(frozen=True)
class ValhallaRoute:
    geometry: dict[str, Any]
    distance_m: float
    duration_s: float


def _decode_polyline6(encoded: str) -> list[list[float]]:
    index = 0
    lat = 0
    lon = 0
    coordinates: list[list[float]] = []
    while index < len(encoded):
        values: list[int] = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    raise ValhallaRouteBlocked("invalid_valhalla_shape")
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            values.append(~(result >> 1) if result & 1 else result >> 1)
        lat += values[0]
        lon += values[1]
        coordinates.append([lon / 1_000_000.0, lat / 1_000_000.0])
    return coordinates


class ValhallaRouteAdapter:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_s: int | None = None,
        post: Callable[..., Any] | None = None,
    ) -> None:
        self._base_url = (base_url or settings.valhalla_base_url).rstrip("/")
        self._timeout_s = int(timeout_s or settings.valhalla_timeout_s)
        self._post = post or requests.post

    def route(self, origin: tuple[float, float], destination: tuple[float, float]) -> ValhallaRoute:
        payload = {
            "locations": [
                {"lon": float(origin[0]), "lat": float(origin[1])},
                {"lon": float(destination[0]), "lat": float(destination[1])},
            ],
            "costing": "pedestrian",
            "units": "kilometers",
            "directions_options": {"units": "kilometers"},
        }
        try:
            response = self._post(f"{self._base_url}/route", json=payload, timeout=self._timeout_s)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ValhallaRouteBlocked(f"valhalla_unavailable:{exc}") from exc
        trip = data.get("trip") if isinstance(data, dict) else None
        legs = trip.get("legs") if isinstance(trip, dict) else None
        summary = trip.get("summary") if isinstance(trip, dict) else None
        if not isinstance(legs, list) or not legs or not isinstance(summary, dict):
            raise ValhallaRouteBlocked("valhalla_route_missing")
        shape = legs[0].get("shape") if isinstance(legs[0], dict) else None
        if not isinstance(shape, str) or not shape:
            raise ValhallaRouteBlocked("valhalla_shape_missing")
        coords = _decode_polyline6(shape)
        if len(coords) < 2:
            raise ValhallaRouteBlocked("valhalla_shape_too_short")
        try:
            distance_m = float(summary["length"]) * 1000.0
            duration_s = float(summary["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValhallaRouteBlocked("valhalla_summary_invalid") from exc
        if distance_m <= 0 or duration_s < 0:
            raise ValhallaRouteBlocked("valhalla_summary_invalid")
        return ValhallaRoute(
            geometry=mapping(LineString(coords)),
            distance_m=distance_m,
            duration_s=duration_s,
        )
