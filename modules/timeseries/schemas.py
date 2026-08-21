from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class TimeseriesBaseRequest(BaseModel):
    polygon: list = Field(..., description="Polygon ring or multi-ring polygon coordinates")
    coord_type: Literal["gcj02", "wgs84"] = Field("gcj02", description="Input coordinate system")


class TimeseriesPopulationRequest(TimeseriesBaseRequest):
    period: str = Field("2024-2026", description="Comparison period, for example 2024-2026")
    layer_view: Literal["population_delta", "population_rate", "density_delta", "age_shift"] = Field("population_delta")


class TimeseriesNightlightRequest(TimeseriesBaseRequest):
    period: str = Field("2023-2025", description="Comparison period, for example 2023-2025")
    layer_view: Literal["radiance_delta", "radiance_rate", "hotspot_shift", "lit_change"] = Field("radiance_delta")


class TimeseriesJointRequest(TimeseriesBaseRequest):
    period: str = Field("2024-2025", description="Joint comparison period; currently 2024-2025")


class TimeseriesMetaResponse(BaseModel):
    population_years: List[str] = Field(default_factory=list)
    nightlight_years: List[int] = Field(default_factory=list)
    common_years: List[int] = Field(default_factory=list)
    population_periods: List[Dict[str, Any]] = Field(default_factory=list)
    nightlight_periods: List[Dict[str, Any]] = Field(default_factory=list)
    joint_periods: List[Dict[str, Any]] = Field(default_factory=list)
    default_population_period: str = "2024-2026"
    default_nightlight_period: str = "2023-2025"
    default_joint_period: str = "2024-2025"


class TimeseriesResponse(BaseModel):
    series: List[Dict[str, Any]] = Field(default_factory=list)
    method: Dict[str, Any] = Field(default_factory=dict)
    periods: List[Dict[str, Any]] = Field(default_factory=list)
    layer: Dict[str, Any] = Field(default_factory=dict)
    insights: List[Dict[str, Any]] = Field(default_factory=list)
