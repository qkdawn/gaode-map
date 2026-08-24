from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from store.analysis_artifact_repo import (
    AnalysisArtifactRepo,
    analysis_artifact_repo,
    compute_params_hash,
)


SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE = "spatial_evidence_result"
SPATIAL_EVIDENCE_RESULT_SCHEMA = "spatial_evidence_result/v1"


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    return text


def _stable_value(value: Any) -> Any:
    """Normalize machine-level float noise before identity comparison and storage."""

    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 12) if math.isfinite(value) else value
    if isinstance(value, Mapping):
        return {str(key): _stable_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_value(item) for item in value]
    return value


class SpatialEvidenceResultStore:
    """Persist and retrieve immutable, model-safe spatial evidence results."""

    def __init__(self, repo: AnalysisArtifactRepo = analysis_artifact_repo) -> None:
        self._repo = repo

    def persist(self, *, history_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        normalized_history_id = _required_text(history_id, "history_id")
        payload = _stable_value(deepcopy(dict(result)))
        result_id = _required_text(payload.get("result_id"), "result_id")
        if not result_id.startswith("spatial:"):
            raise ValueError("spatial_evidence_result_id_invalid")

        existing = self._find(normalized_history_id, result_id)
        if existing is not None:
            if existing != payload:
                old_status = str(existing.get("status") or "")
                new_status = str(payload.get("status") or "")
                # An unavailable placeholder is not evidence. Replace it when
                # the same deterministic request later produces a real result.
                if old_status != "unavailable" or new_status not in {"available", "partial"}:
                    raise ValueError("spatial_evidence_result_immutable")
            else:
                return existing

        self._repo.upsert(
            history_id=normalized_history_id,
            artifact_type=SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE,
            params={"result_id": result_id},
            payload={
                "schema_version": SPATIAL_EVIDENCE_RESULT_SCHEMA,
                "history_id": normalized_history_id,
                "result_id": result_id,
                "result": payload,
            },
            summary={
                "result_id": result_id,
                "status": str(payload.get("status") or ""),
                "analysis": str(payload.get("analysis") or ""),
                "fact_domains": list(payload.get("fact_domains") or []),
                "evidence_dimensions": list(payload.get("evidence_dimensions") or []),
            },
            data_version="v1",
        )
        return deepcopy(payload)

    def read(self, *, history_id: str, result_id: str) -> dict[str, Any]:
        normalized_history_id = _required_text(history_id, "history_id")
        normalized_result_id = _required_text(result_id, "result_id")
        result = self._find(normalized_history_id, normalized_result_id)
        if result is None:
            raise LookupError("spatial_evidence_result_not_found")
        return result

    def list_references(self, *, history_id: str, limit: int = 16) -> list[dict[str, Any]]:
        """Return a bounded lightweight index of persisted computations."""

        normalized_history_id = _required_text(history_id, "history_id")
        artifacts = self._repo.list_summaries(
            normalized_history_id,
            artifact_type=SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE,
            limit=limit,
        )
        references: list[dict[str, Any]] = []
        for artifact in artifacts:
            summary = artifact.get("summary") if isinstance(artifact, Mapping) else None
            params = artifact.get("params") if isinstance(artifact, Mapping) else None
            if not isinstance(summary, Mapping):
                summary = {}
            if not isinstance(params, Mapping):
                params = {}
            result_id = str(summary.get("result_id") or params.get("result_id") or "").strip()
            if not result_id.startswith("spatial:"):
                continue
            references.append({
                "result_id": result_id,
                "status": str(summary.get("status") or ""),
                "analysis": str(summary.get("analysis") or ""),
                "fact_domains": list(summary.get("fact_domains") or []),
                "evidence_dimensions": list(summary.get("evidence_dimensions") or []),
            })
        return references

    def _find(self, history_id: str, result_id: str) -> dict[str, Any] | None:
        artifact = self._repo.get_by_params_hash(
            history_id,
            artifact_type=SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE,
            params_hash=compute_params_hash({"result_id": result_id}),
        )
        artifact_payload = artifact.get("payload") if isinstance(artifact, Mapping) else None
        if isinstance(artifact_payload, Mapping):
            if artifact_payload.get("schema_version") != SPATIAL_EVIDENCE_RESULT_SCHEMA:
                return None
            if str(artifact_payload.get("result_id") or "") != result_id:
                return None
            result = artifact_payload.get("result")
            if isinstance(result, Mapping):
                return _stable_value(deepcopy(dict(result)))
        return None


spatial_evidence_result_store = SpatialEvidenceResultStore()


__all__ = [
    "SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE",
    "SPATIAL_EVIDENCE_RESULT_SCHEMA",
    "SpatialEvidenceResultStore",
    "spatial_evidence_result_store",
]
