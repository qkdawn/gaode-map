from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _identifier_for_plan(value: Any, field: str) -> str:
    identifier = _text(value, field)
    if any(token in identifier for token in ("/", "\\", "://")):
        raise ValueError(f"{field}_must_be_stable_id")
    return identifier


class VisualPlanItem(BaseModel):
    """Chief-analyst visual intent. It carries decision semantics, never GIS implementation."""

    model_config = ConfigDict(extra="forbid")
    visual_id: str
    owner: Literal["chief_analyst"] = "chief_analyst"
    chapter_id: str | None = None
    placement: str
    decision_question: str
    purpose: str
    visual_semantics: Literal["thematic_map", "bar", "line", "scatter", "timeline", "diagram"]
    required_result_ids: list[str] = Field(default_factory=list)
    input_snapshot_ids: list[str] = Field(default_factory=list)
    required_source_ids: list[str] = Field(default_factory=list)
    selection_rule: str
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["planned", "approved", "generated", "unavailable", "omitted"] = "planned"
    asset_id: str | None = None
    # Reader-facing map guidance is part of the semantic visual plan, not a
    # compiler-generated professional conclusion.  Keeping these fields on the
    # plan lets the same explanation survive unavailable/retry states.
    what_it_shows: str = ""
    how_to_read: str = ""
    supports_judgment: str = ""
    does_not_prove: str = ""
    next_validation: str = ""

    @model_validator(mode="after")
    def validate_visual_plan(self):
        self.visual_id = _identifier_for_plan(self.visual_id, "visual_id")
        self.placement = _text(self.placement, "visual_plan.placement")
        self.decision_question = _text(self.decision_question, "visual_plan.decision_question")
        self.purpose = _text(self.purpose, "visual_plan.purpose")
        self.selection_rule = _text(self.selection_rule, "visual_plan.selection_rule")
        for field_name in ("what_it_shows", "how_to_read", "supports_judgment", "does_not_prove", "next_validation"):
            value = getattr(self, field_name)
            if value:
                setattr(self, field_name, _text(value, f"visual_plan.{field_name}"))
        identifiers = [*self.required_result_ids, *self.input_snapshot_ids, *self.required_source_ids]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("visual_plan_dependency_ids_must_be_unique")
        for identifier in identifiers:
            _identifier_for_plan(identifier, "visual_plan dependency")
        forbidden = ("arcgis", "arcpy", "template", "renderer", "geojson", "bridge", "token", "field", "path", "mxd")
        corpus = " ".join([self.placement, self.decision_question, self.purpose, self.selection_rule]).lower()
        if any(token in corpus for token in forbidden):
            raise ValueError("visual_plan_must_not_expose_gis_implementation")
        if self.status == "generated" and not self.asset_id:
            raise ValueError("generated_visual_plan_requires_asset_id")
        if self.status != "generated" and self.asset_id:
            raise ValueError("only_generated_visual_plan_may_reference_asset")
        return self
