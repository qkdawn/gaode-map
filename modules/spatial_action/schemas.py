from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceState = Literal[
    "measured",
    "proxy",
    "inference",
    "recommendation",
    "experimental_assumption",
]


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


class LocalPatternAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cells: list[LocalizedPatternInputCell]
    alpha: float = Field(default=0.05, gt=0.0, le=1.0)
