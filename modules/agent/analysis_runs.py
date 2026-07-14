from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnalysisRunStatus = Literal[
    "draft",
    "checking_inputs",
    "ready",
    "queued",
    "running",
    "waiting_for_user",
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
    "presentation",
    "evidence_nodes",
    "design_handoff",
    "export_file",
    "diagnostic_report",
]
MetricExecutionStatus = Literal["succeeded", "blocked", "not_applicable", "failed"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def content_digest(value: Any) -> str:
    """Return a stable digest for lineage comparisons without leaking payloads."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


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
    record_count: int = Field(default=0, ge=0)


class MetricAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str
    spatial_target: str = "scope"
    execution_status: MetricExecutionStatus
    reason: str = ""
    evidence_node_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence_refs(self):
        if self.execution_status == "succeeded" and not self.evidence_node_ids:
            raise ValueError("succeeded metric attempt requires evidence_node_ids")
        if self.execution_status != "succeeded" and self.evidence_node_ids:
            raise ValueError("non-succeeded metric attempt cannot reference evidence nodes")
        return self


class AnalysisRun(BaseModel):
    """Immutable snapshot of one capability execution and its artifact lineage."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    capability_id: str
    manifest_sha256: str = ""
    catalog_version: str = "1.0.0"
    code_version: str = "unversioned"
    analysis_code_sha256: str = ""
    project_location: tuple[float, float] | None = None
    scope_origin: tuple[float, float] | None = None
    partition_origin: tuple[float, float] | None = None
    source_versions: list[AnalysisSourceVersion] = Field(default_factory=list)
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


class AnalysisRunRecorder:
    """Own mutable orchestration state while only exposing copied run snapshots."""

    def __init__(
        self,
        *,
        capability_id: str,
        project_context: dict[str, Any],
        configuration_snapshot: dict[str, Any],
        execution_profile: dict[str, Any],
        catalog_version: str = "1.0.0",
        code_version: str = "unversioned",
        analysis_code_sha256: str = "",
        project_location: tuple[float, float] | None = None,
        scope_origin: tuple[float, float] | None = None,
        partition_origin: tuple[float, float] | None = None,
        source_versions: list[AnalysisSourceVersion] | None = None,
        run_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
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
            self._run.status = "running"

    def set_input_artifacts(self, artifacts: list[AnalysisArtifactRef]) -> None:
        self._run.input_artifact_refs = [
            item.model_copy(deep=True) for item in artifacts
        ]

    def set_metric_attempts(self, attempts: list[MetricAttempt]) -> None:
        self._run.metric_attempts = [item.model_copy(deep=True) for item in attempts]

    def finish(
        self,
        status: AnalysisRunStatus,
        *,
        current_stage: str,
        diagnostics: list[str] | None = None,
        output_artifacts: list[AnalysisArtifactRef] | None = None,
    ) -> AnalysisRun:
        self._run.status = status
        self._run.current_stage = current_stage
        self._run.diagnostics = list(diagnostics or [])
        self._run.output_artifact_refs = [
            item.model_copy(deep=True) for item in output_artifacts or []
        ]
        if status in {
            "waiting_for_user",
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
