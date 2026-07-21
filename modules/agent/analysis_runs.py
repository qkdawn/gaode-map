from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from store.artifact_identity import content_digest

AnalysisRunStatus = Literal[
    "draft",
    "checking_inputs",
    "ready",
    "queued",
    "running",
    "waiting_for_user",
    "chapter_failed",
    "publication_blocked",
    "system_failed",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "stale",
]
AnalysisStageStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "waiting_for_user",
    "skipped",
]
AnalysisArtifactType = Literal[
    "structured_data",
    "map_layer",
    "table",
    "chart",
    "report",
    "report_chapter",
    "report_visual",
    "presentation",
    "evidence_nodes",
    "evidence_gates",
    "design_handoff",
    "export_file",
    "diagnostic_report",
    "editorial_review",
    "source_index",
    "analysis_plan",
]
MetricExecutionStatus = Literal["succeeded", "blocked", "not_applicable", "failed"]
MetricPlanRole = Literal["primary", "supporting", "diagnostic", "excluded"]
SpatialUnit = Literal[
    "scope",
    "sector",
    "distance_band",
    "catchment",
    "grid_cell",
    "hotspot_zone",
    "road_segment",
    "route",
    "origin_destination_pair",
]
MetricActivationType = Literal[
    "always",
    "if_primary_blocked",
    "if_quality_failed",
    "if_pattern_detected",
]
AnalysisScope = Literal["full_project", "focused_diagnostic"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AnalysisArtifactRef(BaseModel):
    """Stable artifact identity used by workbenches instead of runtime file paths."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: AnalysisArtifactType
    title: str
    version: str = "unversioned"
    filename: str = ""
    source_run_id: str = ""
    source_artifact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    content_digest: str = ""
    created_at: str = ""


class AnalysisStageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    title: str
    status: AnalysisStageStatus
    summary: str = ""
    diagnostics: list[str] = Field(default_factory=list)
    completed_at: str = ""


class AnalysisSourceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    year: int | None = None
    sha256: str
    scope_fingerprint: str = ""
    record_count: int | None = Field(default=None, ge=0)


class DecisionHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    statement: str
    disconfirming_condition: str


class DecisionQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    text: str
    decision_target: str
    hypotheses: list[DecisionHypothesis] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_content(self):
        if not self.question_id.strip():
            raise ValueError("decision question requires question_id")
        if not self.text.strip():
            raise ValueError("decision question requires text")
        if not self.decision_target.strip():
            raise ValueError("decision question requires decision_target")
        return self


class ProjectDecisionAgenda(BaseModel):
    """The decision agenda that frames analysis before any delivery profile is chosen.

    A complete project agenda keeps unanswered areas visible as evidence gaps instead
    of omitting them because a report template does not have a matching section.
    """

    model_config = ConfigDict(extra="forbid")

    agenda_id: str = ""
    user_question: str = ""
    analysis_scope: AnalysisScope = "focused_diagnostic"
    decision_questions: list[DecisionQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_questions(self):
        if not self.decision_questions:
            if self.analysis_scope == "full_project":
                raise ValueError("full project agenda requires decision_questions")
            if self.agenda_id or self.user_question:
                raise ValueError("project decision agenda metadata requires decision_questions")
            return self
        if not self.agenda_id.strip() or not self.user_question.strip():
            raise ValueError("project decision agenda requires agenda_id and user_question")
        question_ids = [item.question_id for item in self.decision_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("project decision agenda decision question ids must be unique")
        return self


class PlannedSpatialTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: SpatialUnit
    source: str
    runtime_parameters: list[str] = Field(default_factory=list)


class SpatialTargetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: SpatialUnit
    target_id: str


class MetricPlanActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MetricActivationType = "always"
    source_entry_ids: list[str] = Field(default_factory=list)
    rule: str = ""

    @model_validator(mode="after")
    def _validate_condition(self):
        if self.type == "always" and (self.source_entry_ids or self.rule):
            raise ValueError("always activation cannot declare condition sources or rule")
        if self.type != "always" and (not self.source_entry_ids or not self.rule.strip()):
            raise ValueError("conditional activation requires source_entry_ids and rule")
        return self


class MetricPlanEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_entry_id: str
    metric_id: str
    role: MetricPlanRole
    decision_question_id: str
    hypothesis_ids: list[str] = Field(default_factory=list)
    planned_spatial_target: PlannedSpatialTarget
    selection_reason: str = ""
    expected_decision_use: str = ""
    required_source_ids: list[str] = Field(default_factory=list)
    activation: MetricPlanActivation = Field(default_factory=MetricPlanActivation)
    exclusion_reason: str = ""

    @model_validator(mode="after")
    def _validate_role_fields(self):
        if self.role == "excluded":
            if not self.exclusion_reason.strip():
                raise ValueError("excluded metric plan entry requires exclusion_reason")
            if self.expected_decision_use.strip():
                raise ValueError("excluded metric plan entry cannot declare expected_decision_use")
        else:
            if not self.selection_reason.strip():
                raise ValueError("selected metric plan entry requires selection_reason")
            if not self.expected_decision_use.strip():
                raise ValueError("selected metric plan entry requires expected_decision_use")
            if self.exclusion_reason.strip():
                raise ValueError("selected metric plan entry cannot declare exclusion_reason")
        return self


class MetricPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str = "2.0.0"
    decision_questions: list[DecisionQuestion] = Field(default_factory=list)
    entries: list[MetricPlanEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_plan(self):
        if not self.decision_questions:
            if self.entries:
                raise ValueError("metric plan entries require decision_questions")
            return self
        question_ids = [item.question_id for item in self.decision_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("metric plan decision question ids must be unique")
        entry_ids = [item.plan_entry_id for item in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("metric plan entry ids must be unique")
        questions = {item.question_id: item for item in self.decision_questions}
        entries = {item.plan_entry_id: item for item in self.entries}
        for entry in self.entries:
            question = questions.get(entry.decision_question_id)
            if question is None:
                raise ValueError(f"metric plan entry references unknown question: {entry.decision_question_id}")
            hypothesis_ids = {item.hypothesis_id for item in question.hypotheses}
            unknown_hypotheses = sorted(set(entry.hypothesis_ids) - hypothesis_ids)
            if unknown_hypotheses:
                raise ValueError(f"metric plan entry references unknown hypotheses: {unknown_hypotheses}")
            unknown_sources = sorted(set(entry.activation.source_entry_ids) - set(entries))
            if unknown_sources:
                raise ValueError(f"metric plan activation references unknown entries: {unknown_sources}")
            if entry.plan_entry_id in entry.activation.source_entry_ids:
                raise ValueError("metric plan activation cannot reference itself")
        for question_id in question_ids:
            selected = [
                item
                for item in self.entries
                if item.decision_question_id == question_id and item.role != "excluded"
            ]
            if selected and not any(item.role == "primary" for item in selected):
                raise ValueError(f"metric plan question requires a primary metric: {question_id}")
        return self


class MetricAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_entry_id: str
    metric_id: str
    spatial_target: SpatialTargetRef
    execution_status: MetricExecutionStatus
    reason: str = ""
    evidence_node_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence_refs(self):
        if self.execution_status == "succeeded" and not self.evidence_node_ids:
            raise ValueError("succeeded metric attempt requires evidence_node_ids")
        if self.execution_status != "succeeded" and self.evidence_node_ids:
            raise ValueError("non-succeeded metric attempt cannot reference evidence nodes")
        if self.execution_status == "not_applicable" and not self.reason.strip():
            raise ValueError("not_applicable metric attempt requires reason")
        return self


class MetricPlanDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_counts: dict[str, int] = Field(default_factory=dict)
    blocked_primary_entry_ids: list[str] = Field(default_factory=list)
    missing_attempt_entry_ids: list[str] = Field(default_factory=list)
    unplanned_attempt_entry_ids: list[str] = Field(default_factory=list)
    excluded_entry_ids: list[str] = Field(default_factory=list)


class AnalysisRun(BaseModel):
    """Immutable snapshot of one capability execution and its artifact lineage."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    read_only: Literal[False] = False
    run_id: str
    capability_id: str
    manifest_sha256: str = ""
    catalog_version: str = "2.0.0"
    code_version: str = "unversioned"
    analysis_code_sha256: str = ""
    project_location: tuple[float, float] | None = None
    scope_origin: tuple[float, float] | None = None
    partition_origin: tuple[float, float] | None = None
    source_versions: list[AnalysisSourceVersion] = Field(default_factory=list)
    decision_agenda: ProjectDecisionAgenda = Field(default_factory=ProjectDecisionAgenda)
    metric_plan: MetricPlan = Field(default_factory=MetricPlan)
    metric_attempts: list[MetricAttempt] = Field(default_factory=list)
    project_context: dict[str, Any] = Field(default_factory=dict)
    configuration_snapshot: dict[str, Any] = Field(default_factory=dict)
    execution_profile: dict[str, Any] = Field(default_factory=dict)
    input_artifact_refs: list[AnalysisArtifactRef] = Field(default_factory=list)
    status: AnalysisRunStatus
    current_stage: str = ""
    stage_records: list[AnalysisStageRecord] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    stale_input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_refs: list[AnalysisArtifactRef] = Field(default_factory=list)
    created_at: str
    completed_at: str = ""

    def canonical_manifest_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        return content_digest(payload)

    @model_validator(mode="after")
    def _validate_metric_plan_alignment(self):
        if self.catalog_version != self.metric_plan.catalog_version:
            raise ValueError("analysis run catalog_version must match metric_plan.catalog_version")
        if self.decision_agenda.decision_questions != self.metric_plan.decision_questions:
            raise ValueError("analysis run decision_agenda must exactly match metric_plan decision_questions")
        entries = {item.plan_entry_id: item for item in self.metric_plan.entries}
        seen_attempt_keys: set[tuple[str, SpatialUnit, str]] = set()
        attempted_entry_ids: set[str] = set()
        for attempt in self.metric_attempts:
            attempt_key = (
                attempt.plan_entry_id,
                attempt.spatial_target.unit,
                attempt.spatial_target.target_id,
            )
            if attempt_key in seen_attempt_keys:
                raise ValueError(
                    "duplicate metric attempt for plan entry and spatial target: "
                    f"{attempt.plan_entry_id}/{attempt.spatial_target.unit}/{attempt.spatial_target.target_id}"
                )
            seen_attempt_keys.add(attempt_key)
            attempted_entry_ids.add(attempt.plan_entry_id)
            entry = entries.get(attempt.plan_entry_id)
            if entry is None:
                raise ValueError(f"metric attempt is not planned: {attempt.plan_entry_id}")
            if entry.role == "excluded":
                raise ValueError(f"excluded metric cannot be executed: {attempt.plan_entry_id}")
            if attempt.metric_id != entry.metric_id:
                raise ValueError(f"metric attempt id mismatch for plan entry: {attempt.plan_entry_id}")
            if attempt.spatial_target.unit != entry.planned_spatial_target.unit:
                raise ValueError(f"metric attempt spatial unit mismatch for plan entry: {attempt.plan_entry_id}")
        if self.status in {"completed", "completed_with_warnings"}:
            required = {item.plan_entry_id for item in self.metric_plan.entries if item.role != "excluded"}
            missing = sorted(required - attempted_entry_ids)
            if missing:
                raise ValueError(f"completed analysis run has unattempted metric plan entries: {missing}")
        return self

    @model_validator(mode="after")
    def _validate_manifest_digest(self):
        if self.manifest_sha256 and self.manifest_sha256 != self.canonical_manifest_sha256():
            raise ValueError("analysis_run_manifest_sha256_mismatch")
        return self




class AnalysisArtifactSnapshot(BaseModel):
    """Persisted artifact version with its immutable payload when available."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["input", "output"]
    artifact: AnalysisArtifactRef
    payload: Any = None


class AnalysisRunDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: str
    run: AnalysisRun
    artifacts: list[AnalysisArtifactSnapshot] = Field(default_factory=list)
    metric_plan_diagnostics: MetricPlanDiagnostics = Field(default_factory=MetricPlanDiagnostics)




class AnalysisRunRecorder:
    """Own mutable orchestration state while only exposing copied run snapshots."""

    def __init__(
        self,
        *,
        capability_id: str,
        project_context: dict[str, Any],
        configuration_snapshot: dict[str, Any],
        execution_profile: dict[str, Any],
        catalog_version: str = "2.0.0",
        code_version: str = "unversioned",
        analysis_code_sha256: str = "",
        project_location: tuple[float, float] | None = None,
        scope_origin: tuple[float, float] | None = None,
        partition_origin: tuple[float, float] | None = None,
        source_versions: list[AnalysisSourceVersion] | None = None,
        run_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self._metric_plan_locked = False
        self._run = AnalysisRun(
            run_id=run_id or f"run-{uuid4().hex}",
            capability_id=capability_id,
            catalog_version=catalog_version,
            code_version=code_version,
            analysis_code_sha256=analysis_code_sha256 or content_digest({"capability_id": capability_id, "execution_profile": execution_profile}),
            project_location=project_location,
            scope_origin=scope_origin,
            partition_origin=partition_origin,
            source_versions=list(source_versions or []),
            project_context=deepcopy(project_context),
            configuration_snapshot=deepcopy(configuration_snapshot),
            execution_profile=deepcopy(execution_profile),
            status="checking_inputs",
            current_stage="readiness",
            created_at=created_at or _utc_now(),
        )

    @property
    def run_id(self) -> str:
        return self._run.run_id

    def set_decision_agenda(self, agenda: ProjectDecisionAgenda) -> None:
        if self._metric_plan_locked or self._run.metric_attempts or self._run.status not in {"draft", "checking_inputs"}:
            raise ValueError("decision_agenda_locked")
        if self._run.metric_plan.decision_questions != agenda.decision_questions:
            if self._run.metric_plan.decision_questions:
                raise ValueError("analysis run decision_agenda must exactly match metric_plan decision_questions")
        self._run.decision_agenda = agenda.model_copy(deep=True)

    def set_metric_plan(self, plan: MetricPlan) -> None:
        if self._metric_plan_locked or self._run.metric_attempts or self._run.status not in {"draft", "checking_inputs"}:
            raise ValueError("metric_plan_locked")
        if self._run.decision_agenda.decision_questions != plan.decision_questions:
            raise ValueError("analysis run decision_agenda must exactly match metric_plan decision_questions")
        self._run.metric_plan = plan.model_copy(deep=True)
        self._run.catalog_version = plan.catalog_version

    def lock_metric_plan(self) -> None:
        self._metric_plan_locked = True

    def record_stage(
        self,
        stage_id: str,
        title: str,
        *,
        status: AnalysisStageStatus = "completed",
        summary: str = "",
        diagnostics: list[str] | None = None,
    ) -> None:
        record = AnalysisStageRecord(
            stage_id=stage_id,
            title=title,
            status=status,
            summary=summary,
            diagnostics=list(diagnostics or []),
            completed_at=_utc_now() if status not in {"pending", "running"} else "",
        )
        for index, current in enumerate(self._run.stage_records):
            if current.stage_id == stage_id:
                self._run.stage_records[index] = record
                break
        else:
            self._run.stage_records.append(record)
        self._run.current_stage = stage_id
        if status == "running":
            self._metric_plan_locked = True
            self._run.status = "running"

    def set_input_artifacts(self, artifacts: list[AnalysisArtifactRef]) -> None:
        self._run.input_artifact_refs = [
            item.model_copy(deep=True) for item in artifacts
        ]

    def set_metric_attempts(self, attempts: list[MetricAttempt]) -> None:
        self._metric_plan_locked = True
        payload = self._run.model_dump(mode="python")
        payload["metric_attempts"] = [item.model_dump(mode="python") for item in attempts]
        candidate = AnalysisRun.model_validate(payload)
        self._run.metric_attempts = [item.model_copy(deep=True) for item in candidate.metric_attempts]

    def finish(
        self,
        status: AnalysisRunStatus,
        *,
        current_stage: str,
        diagnostics: list[str] | None = None,
        output_artifacts: list[AnalysisArtifactRef] | None = None,
    ) -> AnalysisRun:
        if status in {
            "ready",
            "queued",
            "running",
            "waiting_for_user",
            "chapter_failed",
            "publication_blocked",
            "system_failed",
            "completed",
            "completed_with_warnings",
            "failed",
            "cancelled",
            "stale",
        }:
            self._metric_plan_locked = True
        self._run.status = status
        self._run.current_stage = current_stage
        self._run.diagnostics = list(diagnostics or [])
        self._run.output_artifact_refs = [
            item.model_copy(deep=True) for item in output_artifacts or []
        ]
        if status in {
            "waiting_for_user",
            "chapter_failed",
            "publication_blocked",
            "system_failed",
            "completed",
            "completed_with_warnings",
            "failed",
            "cancelled",
            "stale",
        }:
            self._run.completed_at = _utc_now()
        return self.snapshot()

    def snapshot(self) -> AnalysisRun:
        snapshot = self._run.model_copy(deep=True)
        snapshot.manifest_sha256 = snapshot.canonical_manifest_sha256()
        return snapshot


def build_metric_plan_diagnostics(run: AnalysisRun) -> MetricPlanDiagnostics:
    role_counts: dict[str, int] = {}
    entries = {item.plan_entry_id: item for item in run.metric_plan.entries}
    attempts_by_entry: dict[str, list[MetricAttempt]] = {}
    for attempt in run.metric_attempts:
        attempts_by_entry.setdefault(attempt.plan_entry_id, []).append(attempt)
    for entry in entries.values():
        role_counts[entry.role] = role_counts.get(entry.role, 0) + 1
    blocked_primary = sorted(
        entry_id
        for entry_id, entry in entries.items()
        if entry.role == "primary"
        and entry_id in attempts_by_entry
        and not any(item.execution_status == "succeeded" for item in attempts_by_entry[entry_id])
        and any(item.execution_status in {"blocked", "failed"} for item in attempts_by_entry[entry_id])
    )
    return MetricPlanDiagnostics(
        role_counts=dict(sorted(role_counts.items())),
        blocked_primary_entry_ids=blocked_primary,
        missing_attempt_entry_ids=sorted(
            entry_id
            for entry_id, entry in entries.items()
            if entry.role != "excluded" and entry_id not in attempts_by_entry
        ),
        unplanned_attempt_entry_ids=sorted(set(attempts_by_entry) - set(entries)),
        excluded_entry_ids=sorted(
            entry_id for entry_id, entry in entries.items() if entry.role == "excluded"
        ),
    )


def artifact_ref(
    *,
    artifact_id: str,
    artifact_type: AnalysisArtifactType,
    title: str,
    source_run_id: str = "",
    payload: Any = None,
    filename: str = "",
    source_artifact_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    version: str = "",
) -> AnalysisArtifactRef:
    """Create a lineage-safe artifact index entry from a domain payload."""

    digest = content_digest(payload) if payload is not None else ""
    resolved_version = str(
        version or source_run_id or digest[:24] or "unversioned"
    ).strip()
    return AnalysisArtifactRef(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        title=title,
        version=resolved_version,
        filename=filename,
        source_run_id=source_run_id,
        source_artifact_refs=list(source_artifact_refs or []),
        evidence_refs=list(evidence_refs or []),
        content_digest=digest,
        created_at=_utc_now(),
    )
