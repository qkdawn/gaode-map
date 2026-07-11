from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

CapabilityRunStatus = Literal[
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
CapabilityStageStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "waiting_for_user",
    "skipped",
]
CapabilityArtifactType = Literal[
    "structured_data",
    "map_layer",
    "table",
    "chart",
    "report",
    "presentation",
    "evidence_ledger",
    "design_handoff",
    "export_file",
    "diagnostic_report",
]


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


class CapabilityArtifactRef(BaseModel):
    """Stable artifact identity used by workbenches instead of runtime file paths."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: CapabilityArtifactType
    title: str
    version: str = "unversioned"
    filename: str = ""
    source_run_id: str = ""
    source_artifact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    content_digest: str = ""
    created_at: str = ""


class CapabilityStageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    title: str
    status: CapabilityStageStatus
    summary: str = ""
    diagnostics: list[str] = Field(default_factory=list)
    completed_at: str = ""


class CapabilityRun(BaseModel):
    """Immutable snapshot of one capability execution and its artifact lineage."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    capability_id: str
    project_context: dict[str, Any] = Field(default_factory=dict)
    configuration_snapshot: dict[str, Any] = Field(default_factory=dict)
    execution_profile: dict[str, Any] = Field(default_factory=dict)
    input_artifact_refs: list[CapabilityArtifactRef] = Field(default_factory=list)
    status: CapabilityRunStatus
    current_stage: str = ""
    stage_records: list[CapabilityStageRecord] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    stale_input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_refs: list[CapabilityArtifactRef] = Field(default_factory=list)
    created_at: str
    completed_at: str = ""


class CapabilityArtifactSnapshot(BaseModel):
    """Persisted artifact version with its immutable payload when available."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["input", "output"]
    artifact: CapabilityArtifactRef
    payload: Any = None


class CapabilityRunDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: str
    run: CapabilityRun
    artifacts: list[CapabilityArtifactSnapshot] = Field(default_factory=list)


class CapabilityRunRecorder:
    """Own mutable orchestration state while only exposing copied run snapshots."""

    def __init__(
        self,
        *,
        capability_id: str,
        project_context: dict[str, Any],
        configuration_snapshot: dict[str, Any],
        execution_profile: dict[str, Any],
        run_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self._run = CapabilityRun(
            run_id=run_id or f"caprun-{uuid4().hex}",
            capability_id=capability_id,
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
        status: CapabilityStageStatus = "completed",
        summary: str = "",
        diagnostics: list[str] | None = None,
    ) -> None:
        record = CapabilityStageRecord(
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

    def set_input_artifacts(self, artifacts: list[CapabilityArtifactRef]) -> None:
        self._run.input_artifact_refs = [
            item.model_copy(deep=True) for item in artifacts
        ]

    def finish(
        self,
        status: CapabilityRunStatus,
        *,
        current_stage: str,
        diagnostics: list[str] | None = None,
        output_artifacts: list[CapabilityArtifactRef] | None = None,
    ) -> CapabilityRun:
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

    def snapshot(self) -> CapabilityRun:
        return self._run.model_copy(deep=True)


def artifact_ref(
    *,
    artifact_id: str,
    artifact_type: CapabilityArtifactType,
    title: str,
    source_run_id: str = "",
    payload: Any = None,
    filename: str = "",
    source_artifact_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    version: str = "",
) -> CapabilityArtifactRef:
    """Create a lineage-safe artifact index entry from a domain payload."""

    digest = content_digest(payload) if payload is not None else ""
    resolved_version = str(
        version or source_run_id or digest[:24] or "unversioned"
    ).strip()
    return CapabilityArtifactRef(
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
