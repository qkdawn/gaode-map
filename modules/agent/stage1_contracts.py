from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VerificationStatus = Literal[
    "verified",
    "cross_checked",
    "inferred",
    "hypothesis",
    "blocked",
    "fieldwork_required",
]
VerificationExecutor = Literal["agent", "fieldwork", "manual_authority"]
TemporalStatus = Literal[
    "not_applicable",
    "current",
    "completed",
    "overdue",
    "current_status_unknown",
    "cancelled",
    "superseded",
]


class VerificationTask(BaseModel):
    """A concrete unresolved check, with enough information to execute it."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    status: Literal["blocked", "fieldwork_required"]
    missing_input: str
    blocking_reason: str
    executor: VerificationExecutor
    next_action: str


class VerificationSummary(BaseModel):
    """Evidence gate result consumed by Stage 1 orchestration and the UI."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "passed_with_gaps", "failed"]
    report_allowed: bool
    as_of_date: str
    status_counts: dict[str, int] = Field(default_factory=dict)
    tasks: list[VerificationTask] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)


class _FlexibleObject(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProjectIdentity(_FlexibleObject):
    project_id: str
    name: str
    location: str = ""
    analysis_date: str = ""
    source_cutoff_date: str = ""


class PreferredPositioning(_FlexibleObject):
    option_id: str = ""
    statement: str
    target_users: list[Any] = Field(min_length=1)
    problems_to_solve: list[Any] = Field(min_length=1)
    success_conditions: list[Any] = Field(min_length=1)
    prerequisites: list[Any] = Field(default_factory=list)
    fallback_option: str = ""


class ProgramContract(_FlexibleObject):
    must_have: list[Any] = Field(min_length=1)
    should_have: list[Any] = Field(default_factory=list)
    optional: list[Any] = Field(default_factory=list)
    excluded: list[Any] = Field(default_factory=list)
    area_ranges: list[Any] = Field(default_factory=list)
    shared_space_rules: list[Any] = Field(default_factory=list)


class SpatialStrategyContract(_FlexibleObject):
    zones: list[Any] = Field(min_length=1)
    anchors: list[Any] = Field(default_factory=list)
    connections: list[Any] = Field(default_factory=list)
    public_interfaces: list[Any] = Field(default_factory=list)
    day_night_requirements: list[Any] = Field(default_factory=list)


class RenewalPrinciples(_FlexibleObject):
    retain: list[Any] = Field(default_factory=list)
    adapt: list[Any] = Field(default_factory=list)
    replace: list[Any] = Field(default_factory=list)
    temporary_use: list[Any] = Field(default_factory=list)


class OperationalRequirements(_FlexibleObject):
    hours: list[Any] = Field(default_factory=list)
    service_flows: list[Any] = Field(default_factory=list)
    back_of_house: list[Any] = Field(default_factory=list)
    event_modes: list[Any] = Field(default_factory=list)
    operator_assumptions: list[Any] = Field(default_factory=list)


class DesignHandoffContract(BaseModel):
    """Stable Stage 1 → Stage 2 contract aligned with the offline Skill schema."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["v1"]
    project_identity: ProjectIdentity
    preferred_positioning: PreferredPositioning
    program: ProgramContract
    spatial_strategy: SpatialStrategyContract
    renewal_principles: RenewalPrinciples
    operational_requirements: OperationalRequirements
    hard_constraints: list[Any] = Field(default_factory=list)
    open_design_questions: list[Any] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    items_requiring_survey_or_approval: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_evidence_refs(self) -> "DesignHandoffContract":
        normalized = [str(item).strip() for item in self.evidence_refs if str(item).strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence_refs must be unique")
        self.evidence_refs = normalized
        return self


_DATE_PATTERN = re.compile(r"(?P<year>20\d{2})\s*年(?:\s*(?P<month>\d{1,2})\s*月)?")
_FUTURE_PLAN_PATTERN = re.compile(r"(计划|拟于|预计|将于|力争|月底前|年底前).{0,28}(完成|启动|开展|实现|建成|交付)")


def historical_plan_date(text: str, *, as_of: date) -> bool:
    """Return true when text still phrases a past calendar plan as a future action."""

    if not _FUTURE_PLAN_PATTERN.search(text):
        return False
    for match in _DATE_PATTERN.finditer(text):
        year = int(match.group("year"))
        month = int(match.group("month") or 12)
        if (year, month) < (as_of.year, as_of.month):
            return True
    return False


def verification_status_counts(ledger: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("status") or "") for item in ledger)
    return dict(sorted((key, value) for key, value in counts.items() if key))
