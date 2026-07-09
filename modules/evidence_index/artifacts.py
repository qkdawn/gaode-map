from __future__ import annotations

from typing import Any, Dict, List

from modules.evidence_index.manifests import manifest_from_source
from modules.evidence_index.schemas import SourceIndexManifest
from modules.evidence_retrieval.schemas import SourceRecord
from store.analysis_artifact_repo import analysis_artifact_repo


SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE = "source_index_manifest"


def persist_source_index_manifest(
    history_id: str,
    source: Any,
    *,
    repo=analysis_artifact_repo,
) -> Dict[str, Any] | None:
    normalized_history_id = str(history_id or "").strip()
    if not normalized_history_id:
        return None
    source_payload = _source_payload(source)
    if not source_payload:
        return None
    record = SourceRecord.model_validate(source_payload)
    manifest = manifest_from_source(record)
    if manifest is None:
        return None
    return persist_source_index_manifest_payload(normalized_history_id, manifest, source_payload=source_payload, repo=repo)


def persist_source_index_manifest_payload(
    history_id: str,
    manifest: SourceIndexManifest,
    *,
    source_payload: Dict[str, Any] | None = None,
    repo=analysis_artifact_repo,
) -> Dict[str, Any] | None:
    normalized_history_id = str(history_id or "").strip()
    if not normalized_history_id or not manifest.source_id:
        return None
    payload = {
        "version": "source_index_manifest_artifact_v1",
        "history_id": normalized_history_id,
        "source_id": manifest.source_id,
        "source_kind": manifest.source_kind,
        "native_index_kind": manifest.native_index_kind,
        "manifest": manifest.model_dump(mode="json"),
        "source": _compact_source_payload(source_payload or {}),
    }
    return repo.upsert(
        history_id=normalized_history_id,
        artifact_type=SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE,
        params={"source_id": manifest.source_id},
        payload=payload,
        summary={
            "source_id": manifest.source_id,
            "source_kind": manifest.source_kind,
            "native_index_kind": manifest.native_index_kind,
            "index_status": manifest.index_status,
            "node_count": manifest.node_count,
            "diagnostics": list(manifest.diagnostics or []),
        },
        data_version="v1",
    )


def list_source_index_manifests(
    history_id: str,
    *,
    repo=analysis_artifact_repo,
) -> List[SourceIndexManifest]:
    normalized_history_id = str(history_id or "").strip()
    if not normalized_history_id:
        return []
    manifests: List[SourceIndexManifest] = []
    for artifact in repo.list(normalized_history_id, artifact_type=SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE):
        payload = artifact.get("payload") if isinstance(artifact, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        raw_manifest = payload.get("manifest")
        if not isinstance(raw_manifest, dict):
            continue
        try:
            manifest = SourceIndexManifest.model_validate(raw_manifest)
        except Exception:
            continue
        if manifest.source_id:
            manifests.append(manifest)
    return manifests


def _source_payload(source: Any) -> Dict[str, Any]:
    if source is None:
        return {}
    if hasattr(source, "model_dump"):
        payload = source.model_dump(mode="json")
    elif isinstance(source, dict):
        payload = dict(source)
    else:
        return {}
    if "source_id" not in payload and "id" in payload:
        payload["source_id"] = payload.get("id")
    return payload


def _compact_source_payload(source: Dict[str, Any]) -> Dict[str, Any]:
    record = SourceRecord.model_validate(source)
    return {
        "id": record.source_id,
        "title": record.title,
        "source_kind": record.source_kind,
        "status": record.status,
        "evidence_count": record.evidence_count,
        "locator_summary": record.locator_summary,
    }
