from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.ops import transform


EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class LocalMetricProjection:
    """Small-area metric projection owned by the road analysis boundary."""

    lon0: float
    lat0: float

    @classmethod
    def for_geometry(cls, geometry: Any) -> "LocalMetricProjection":
        if geometry is None or geometry.is_empty:
            raise ValueError("projection_requires_non_empty_geometry")
        center = geometry.centroid
        return cls(lon0=float(center.x), lat0=float(center.y))

    def forward_xy(self, lon: float, lat: float) -> tuple[float, float]:
        latitude_scale = math.cos(math.radians(self.lat0))
        x = EARTH_RADIUS_M * math.radians(float(lon) - self.lon0) * latitude_scale
        y = EARTH_RADIUS_M * math.radians(float(lat) - self.lat0)
        return x, y

    def inverse_xy(self, x: float, y: float) -> tuple[float, float]:
        latitude_scale = math.cos(math.radians(self.lat0))
        if abs(latitude_scale) <= 1e-12:
            raise ValueError("projection_undefined_near_pole")
        lon = self.lon0 + math.degrees(float(x) / (EARTH_RADIUS_M * latitude_scale))
        lat = self.lat0 + math.degrees(float(y) / EARTH_RADIUS_M)
        return lon, lat

    def forward_geometry(self, geometry: Any) -> Any:
        return transform(self.forward_xy, geometry)

    def inverse_geometry(self, geometry: Any) -> Any:
        return transform(self.inverse_xy, geometry)

    def buffer_wgs84(self, geometry: Any, distance_m: float) -> Any:
        metric_geometry = self.forward_geometry(geometry)
        return self.inverse_geometry(metric_geometry.buffer(max(0.0, float(distance_m))))

    def project_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        x1, y1 = self.forward_xy(float(edge["x1"]), float(edge["y1"]))
        x2, y2 = self.forward_xy(float(edge["x2"]), float(edge["y2"]))
        return {**edge, "x1": x1, "y1": y1, "x2": x2, "y2": y2}

    def inverse_result_row(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            lon1, lat1 = self.inverse_xy(float(row["x1"]), float(row["y1"]))
            lon2, lat2 = self.inverse_xy(float(row["x2"]), float(row["y2"]))
        except (KeyError, TypeError, ValueError):
            return dict(row)
        return {**row, "x1": lon1, "y1": lat1, "x2": lon2, "y2": lat2}
