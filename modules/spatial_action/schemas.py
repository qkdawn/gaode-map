from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceState = Literal[
    "measured",
    "proxy",
    "inference",
    "recommendation",
    "experimental_assumption",
]
EntranceSourceType = Literal["existing_observed", "project_planned", "inferred_candidate"]
DestinationType = Literal["internal_program", "transit", "poi_hotspot", "local_hotspot"]


class LocalizedPatternInputCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str
    metric_id: str
    value: float
    geometry: dict[str, Any]
    statistic: float | None = None
    z_score: float | None = None
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    adjusted_p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    cluster_type: str = ""
    neighbor_ids: list[str] = Field(default_factory=list)


class LocalizedPatternCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str
    metric_id: str
    value: float
    statistic: float | None = None
    z_score: float | None = None
    p_value: float | None = None
    adjusted_p_value: float | None = None
    cluster_type: str
    zone_id: str


class LocalizedPatternZone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str
    pattern_type: str
    cell_ids: list[str]
    geometry: dict[str, Any]
    source_metric_ids: list[str]
    significance_method: str


class LocalizedPatternResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_state: EvidenceState
    pattern_label: str
    cells: list[LocalizedPatternCell]
    zones: list[LocalizedPatternZone]
    diagnostics: list[str] = Field(default_factory=list)


class EntranceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrance_id: str
    geometry: dict[str, Any]
    label: str = ""
    source_type: EntranceSourceType
    source_ref: str = ""


class DestinationAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: str
    geometry: dict[str, Any]
    destination_type: DestinationType
    source_ref: str = ""


class RoadSegmentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    geometry: dict[str, Any]
    integration: float | None = None
    choice: float | None = None
    connectivity: float | None = None
    walkable: bool = True


class EntranceRelationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrance_id: str
    geometry: dict[str, Any]
    source_type: EntranceSourceType
    evidence_state: EvidenceState
    snapped_road_segment_id: str = ""
    snap_distance_m: float | None = None
    target_road_distances_m: dict[str, float] = Field(default_factory=dict)
    catchment_ids: list[str] = Field(default_factory=list)
    nearby_hotspot_zone_ids: list[str] = Field(default_factory=list)
    local_integration: float | None = None
    local_choice: float | None = None
    demand_exposure_metrics: dict[str, float] = Field(default_factory=dict)
    directional_exposure: dict[str, float] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)


class PathRelationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    entrance_id: str
    destination_id: str
    geometry: dict[str, Any]
    road_segment_ids: list[str] = Field(default_factory=list)
    network_distance_m: float = Field(ge=0)
    duration_s: float = Field(ge=0)
    straight_line_distance_m: float = Field(ge=0)
    detour_ratio: float | None = None
    high_choice_overlap_ratio: float | None = None
    high_integration_overlap_ratio: float | None = None
    low_access_segment_ids: list[str] = Field(default_factory=list)
    barrier_or_break_points: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_detour_ratio(self):
        if self.straight_line_distance_m > 0 and self.detour_ratio is None:
            raise ValueError("route with non-zero straight-line distance requires detour_ratio")
        return self

class LocalPatternAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cells: list[LocalizedPatternInputCell]
    alpha: float = Field(default=0.05, gt=0.0, le=1.0)


class EntranceRelationAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrances: list[EntranceAnchor] = Field(default_factory=list)
    road_segments: list[RoadSegmentRef]
    project_boundary: dict[str, Any] | None = None
    hotspot_zones: list[LocalizedPatternZone] = Field(default_factory=list)
    catchments: list[dict[str, Any]] = Field(default_factory=list)
    demand_features: list[dict[str, Any]] = Field(default_factory=list)
    directional_exposure: dict[str, dict[str, float]] = Field(default_factory=dict)
    target_road_segment_ids: list[str] = Field(default_factory=list)
    nearby_radius_m: float = Field(default=250.0, gt=0.0)
    dedupe_tolerance_m: float = Field(default=8.0, gt=0.0)

    @model_validator(mode="after")
    def _validate_anchor_source(self):
        if not self.entrances and not self.project_boundary:
            raise ValueError("entrances or project_boundary is required")
        return self


class OriginDestinationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrance_id: str
    destination_id: str


class PathRelationAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrances: list[EntranceAnchor]
    destinations: list[DestinationAnchor]
    pairs: list[OriginDestinationPair]
    road_segments: list[RoadSegmentRef] | None = None
    match_tolerance_m: float = Field(default=12.0, gt=0.0)

    @model_validator(mode="after")
    def _validate_pairs(self):
        if not self.pairs:
            raise ValueError("at least one entrance-destination pair is required")
        return self
