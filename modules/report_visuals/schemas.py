"""Typed contracts for restricted, evidence-led report visuals."""
from __future__ import annotations

import re
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
    "poi_distance_band_supply_structure",
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
    # Optional editor-declared expectation. The trusted renderer compares this
    # against the persisted result provenance before producing an asset.
    scope_year: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def omitted_plan_needs_reason(self) -> "VisualPlanItem":
        if self.status == "omitted" and not str(self.omission_reason or "").strip():
            raise ValueError("omitted visual plan items require omission_reason")
        if self.status == "planned" and not self.metric_result_ids:
            raise ValueError("planned visual items require current metric_result_ids")
        if self.status == "planned" and not self.scope_year:
            raise ValueError("planned visual items require an explicit current scope_year expectation")
        if self.status == "planned" and not str(self.statement_ref or "").strip():
            raise ValueError("planned visual items require a statement_ref")
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
    history_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    # The MCP boundary supplies this from same-history immutable results. It is
    # intentionally not accepted as a template input.
    metric_result_provenance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    age_structure: dict[str, Any] | None = None
    directional_evidence_matrix: dict[str, Any] | None = None
    poi_supply_structure: dict[str, Any] | None = None
    poi_distance_band_supply_structure: dict[str, Any] | None = None
    focused_poi_accessibility: dict[str, Any] | None = None
    # Kept only to deserialize older run payloads. New execution reads actions
    # exclusively from VisualPlanItem.template_input.
    editorial_actions: list[EditorialAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def plan_must_match_report_run(self) -> "ReportVisualRequest":
        if self.visual_plan.run_id != self.run_id:
            raise ValueError("visual_plan.run_id must match report run_id")
        for item in self.visual_plan.items:
            if item.status != "planned":
                continue
            for result_id in item.metric_result_ids:
                provenance = self.metric_result_provenance.get(result_id)
                if not isinstance(provenance, dict):
                    raise ValueError(f"visual metric result provenance missing: {result_id}")
                if str(provenance.get("tool_id") or "") not in item.metric_ids:
                    raise ValueError(f"visual metric result tool mismatch: {result_id}")
                if not isinstance(provenance.get("time_scope"), dict) or not provenance["time_scope"]:
                    raise ValueError(f"visual metric result time scope missing: {result_id}")
                if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("result_sha256") or "")):
                    raise ValueError(f"visual metric result checksum missing: {result_id}")
        return self


class VisualManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: str = ""
    report_id: str = ""
    run_id: str = ""
    template_id: ReportVisualTemplateId
    template_version: str
    status: Literal["generated", "omitted"]
    chapter_anchor: str
    metric_ids: list[str]
    metric_result_ids: list[str] = Field(default_factory=list)
    title: str
    caption: str
    supports_judgment: str
    does_not_prove: str
    asset_path: str | None = None
    spec_path: str | None = None
    omission_reason: str | None = None
    data_scope: dict[str, Any] = Field(default_factory=dict)
    asset_sha256: str | None = None
    spec_sha256: str | None = None
    scope_year_fingerprint: str = ""
    statement_ref: str | None = None
    asset_id: str | None = None
    resource_uri: str | None = None


class VisualManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["report-visuals.v2"] = "report-visuals.v2"
    history_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    run_id: str
    metric_result_ids: list[str] = Field(default_factory=list)
    visual_plan_sha256: str = ""
    report_markdown_sha256: str = ""
    report_resource_uri: str | None = None
    visual_plan_resource_uri: str | None = None
    items: list[VisualManifestItem]

    @model_validator(mode="after")
    def every_item_belongs_to_this_run(self) -> "VisualManifest":
        for item in self.items:
            if (item.history_id, item.report_id, item.run_id) != (self.history_id, self.report_id, self.run_id):
                raise ValueError(f"visual item {item.template_id} does not belong to this manifest run")
            if item.status == "generated" and not item.metric_result_ids:
                raise ValueError(f"generated visual {item.template_id} has no current metric result")
        return self
