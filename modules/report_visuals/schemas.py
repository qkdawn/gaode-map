"""Typed contracts for restricted, evidence-led report visuals."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DIRECTION_ORDER = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRECTION_LABELS = {"N": "北", "NE": "东北", "E": "东", "SE": "东南", "S": "南", "SW": "西南", "W": "西", "NW": "西北"}
DISTANCE_BANDS = ("0-500m", "500-1000m", "1000-1600m")
DISTANCE_BAND_LABELS = {"0-500m": "0–500m", "500-1000m": "500–1000m", "1000-1600m": "1000–1600m"}
AGE_BANDS = ("0–14", "15–24", "25–44", "45–59", "60+")
ReportVisualTemplateId = Literal[
    "population_age_structure",
    "population_supply_context",
    "directional_action_priority_matrix",
    "focused_poi_walking_route_map",
    "poi_supply_structure",
]


class EditorialAction(BaseModel):
    """A reviewed action declaration, not an algorithmic score."""

    direction: str
    distance_band: str
    action: Literal["导向验证", "通达诊断", "夜间联动测试"]
    evidence_label: str = Field(min_length=1, max_length=24)
    required_evidence: list[Literal["population", "poi", "nightlight", "road", "low_road_coverage", "low_road_integration"]] = Field(min_length=1)

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, value: object) -> str:
        text = str(value).strip().upper()
        aliases = {label: key for key, label in DIRECTION_LABELS.items()}
        text = aliases.get(text, text)
        if text not in DIRECTION_ORDER:
            raise ValueError("direction must be one of the eight approved directions")
        return text

    @field_validator("distance_band", mode="before")
    @classmethod
    def normalize_distance_band(cls, value: object) -> str:
        text = str(value).strip().replace("–", "-").replace("—", "-").replace(" ", "")
        if text not in DISTANCE_BANDS:
            raise ValueError("distance_band must be one of 0-500m, 500-1000m, 1000-1600m")
        return text


class VisualPlanItem(BaseModel):
    """One editorially selected approved template, never a free Vega spec."""

    model_config = ConfigDict(extra="forbid")

    template_id: ReportVisualTemplateId
    chapter_anchor: str = Field(min_length=1)
    # ``statement_ref`` keeps the editor's semantic placement rationale auditable.
    # The current renderer still resolves the approved Markdown anchor itself.
    statement_ref: str | None = Field(default=None, min_length=1)
    metric_ids: list[str] = Field(min_length=1)
    # Public renderer callers may omit this for the local script.  The MCP
    # boundary requires it for every planned visual and resolves values server-side.
    metric_result_ids: list[str] = Field(default_factory=list)
    supports_judgment: str = Field(min_length=1)
    does_not_prove: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)
    status: Literal["planned", "omitted"] = "planned"
    omission_reason: str | None = None
    template_input: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def omitted_plan_needs_reason(self) -> "VisualPlanItem":
        if self.status == "omitted" and not str(self.omission_reason or "").strip():
            raise ValueError("omitted visual plan items require omission_reason")
        return self


class VisualPlan(BaseModel):
    """Auditable output of the Wave 5 visual-evidence editor."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["report-visual-plan.v1"] = "report-visual-plan.v1"
    run_id: str = Field(min_length=1)
    items: list[VisualPlanItem]

    @field_validator("items")
    @classmethod
    def one_asset_per_approved_template(cls, items: list[VisualPlanItem]) -> list[VisualPlanItem]:
        template_ids = [item.template_id for item in items]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("a report visual plan may select each template at most once")
        return items


class ReportVisualRequest(BaseModel):
    """Only reviewed visual plans and structured metrics reach the renderer."""

    run_id: str = Field(min_length=1)
    report_path: Path
    visual_plan: VisualPlan
    age_structure: dict[str, Any] | None = None
    directional_evidence_matrix: dict[str, Any] | None = None
    poi_supply_structure: dict[str, Any] | None = None
    focused_poi_accessibility: dict[str, Any] | None = None
    # Kept only to deserialize older run payloads. New execution reads actions
    # exclusively from VisualPlanItem.template_input.
    editorial_actions: list[EditorialAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def plan_must_match_report_run(self) -> "ReportVisualRequest":
        if self.visual_plan.run_id != self.run_id:
            raise ValueError("visual_plan.run_id must match report run_id")
        return self


class VisualManifestItem(BaseModel):
    template_id: ReportVisualTemplateId
    template_version: str
    status: Literal["generated", "omitted"]
    chapter_anchor: str
    metric_ids: list[str]
    title: str
    caption: str
    supports_judgment: str
    does_not_prove: str
    asset_path: str | None = None
    spec_path: str | None = None
    omission_reason: str | None = None
    data_scope: dict[str, Any] = Field(default_factory=dict)


class VisualManifest(BaseModel):
    schema_version: Literal["report-visuals.v1"] = "report-visuals.v1"
    run_id: str
    items: list[VisualManifestItem]
