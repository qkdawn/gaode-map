from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from store.analysis_artifact_repo import DATA_VERSION, analysis_artifact_repo


class AnalysisArtifactUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str = Field(..., min_length=1)
    params: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    data_version: str = DATA_VERSION


def upsert_history_artifact(history_id: str, payload: AnalysisArtifactUpsertRequest, repo=analysis_artifact_repo) -> Dict[str, Any]:
    try:
        return repo.upsert(
            history_id=history_id,
            artifact_type=payload.artifact_type,
            params=payload.params,
            payload=payload.payload,
            summary=payload.summary,
            data_version=payload.data_version or DATA_VERSION,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def list_history_artifacts(
    history_id: str,
    *,
    artifact_type: str = "",
    params_hash: str = "",
    repo=analysis_artifact_repo,
) -> List[Dict[str, Any]]:
    return repo.list(history_id, artifact_type=artifact_type, params_hash=params_hash)


def get_history_artifacts_by_type(
    history_id: str,
    artifact_type: str,
    *,
    params_hash: Optional[str] = None,
    repo=analysis_artifact_repo,
) -> List[Dict[str, Any]]:
    return repo.list(history_id, artifact_type=artifact_type, params_hash=params_hash or "")
