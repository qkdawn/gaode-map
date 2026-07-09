from __future__ import annotations

from typing import Any, Dict, List

from modules.evidence_index.schemas import SourceIndexManifest
from modules.evidence_retrieval.schemas import SourceRecord


def build_source_index_manifest_payload(
    *,
    source_id: str,
    source_kind: str,
    native_index_kind: str,
    node_count: int = 0,
    retrieval_modes: List[str] | None = None,
    read_modes: List[str] | None = None,
    storage_ref: Dict[str, Any] | None = None,
    model_versions: Dict[str, Any] | None = None,
    diagnostics: List[str] | None = None,
) -> Dict[str, Any]:
    manifest = SourceIndexManifest(
        source_id=str(source_id or "").strip(),
        source_kind=source_kind,  # type: ignore[arg-type]
        native_index_kind=str(native_index_kind or "payload_index").strip() or "payload_index",
        index_status="ready" if int(node_count or 0) > 0 else "pending",
        node_count=int(node_count or 0),
        retrieval_modes=list(retrieval_modes or ["keyword"]),
        read_modes=list(read_modes or ["node_id"]),
        storage_ref=dict(storage_ref or {}),
        model_versions=dict(model_versions or {}),
        diagnostics=list(diagnostics or ([] if int(node_count or 0) > 0 else ["empty_index"])),
    )
    return manifest.model_dump(mode="json")


def attach_index_manifest(ai_payload: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(ai_payload or {})
    payload["index_manifest"] = manifest
    return payload


def manifest_from_source(source: SourceRecord) -> SourceIndexManifest | None:
    meta = source.meta if isinstance(source.meta, dict) else {}
    ai_payload = meta.get("aiPayload") or meta.get("ai_payload")
    ai_payload = ai_payload if isinstance(ai_payload, dict) else {}
    raw_manifest = ai_payload.get("index_manifest")
    if not isinstance(raw_manifest, dict):
        return None
    payload = {
        **raw_manifest,
        "source_id": str(raw_manifest.get("source_id") or source.source_id).strip(),
        "source_kind": str(raw_manifest.get("source_kind") or source.source_kind).strip(),
    }
    return SourceIndexManifest.model_validate(payload)
