from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class SharedGridRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    polygon: list = Field(default_factory=list)
    coord_type: str = "gcj02"
    pois: List[Dict[str, Any]] = Field(default_factory=list)
    poi_coord_type: str = "gcj02"
    poi_year: int | None = None
    poi_ready: bool = False
    population_year: str = Field(..., min_length=1)
    nightlight_year: int = Field(..., gt=0)
    road_features: List[Dict[str, Any]] = Field(default_factory=list)
    road_ready: bool = False
    categories: List[Any] = Field(default_factory=list)


class SharedGridResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidence_version: str
    join_key: str
    grid: Dict[str, Any]
    summary: Dict[str, Any]
    source_versions: Dict[str, Any]
    source_readiness: Dict[str, Any]
    limitations: List[str] = Field(default_factory=list)
