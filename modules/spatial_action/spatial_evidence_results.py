from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from store.analysis_artifact_repo import AnalysisArtifactRepo, analysis_artifact_repo


SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE = "spatial_evidence_result"
SPATIAL_EVIDENCE_RESULT_SCHEMA = "spatial_evidence_result/v1"


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    return text


class SpatialEvidenceResultStore:
    """Persist and retrieve immutable, model-safe spatial evidence results."""

    def __init__(self, repo: AnalysisArtifactRepo = analysis_artifact_repo) -> None:
        self._repo = repo

    def persist(self, *, history_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        normalized_history_id = _required_text(history_id, "history_id")
        payload = deepcopy(dict(result))
        result_id = _required_text(payload.get("result_id"), "result_id")
        if not result_id.startswith("spatial:"):
            raise ValueError("spatial_evidence_result_id_invalid")

        existing = self._find(normalized_history_id, result_id)
        if existing is not None:
            if existing != payload:
                raise ValueError("spatial_evidence_result_immutable")
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

    def _find(self, history_id: str, result_id: str) -> dict[str, Any] | None:
        for artifact in self._repo.list(
            history_id,
            artifact_type=SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE,
        ):
            artifact_payload = artifact.get("payload") if isinstance(artifact, Mapping) else None
            if not isinstance(artifact_payload, Mapping):
                continue
            if artifact_payload.get("schema_version") != SPATIAL_EVIDENCE_RESULT_SCHEMA:
                continue
            if str(artifact_payload.get("result_id") or "") != result_id:
                continue
            result = artifact_payload.get("result")
            if isinstance(result, Mapping):
                return deepcopy(dict(result))
        return None


spatial_evidence_result_store = SpatialEvidenceResultStore()


__all__ = [
    "SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE",
    "SPATIAL_EVIDENCE_RESULT_SCHEMA",
    "SpatialEvidenceResultStore",
    "spatial_evidence_result_store",
]
