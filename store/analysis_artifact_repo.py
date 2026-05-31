from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import AnalysisArtifact


DATA_VERSION = "v1"


def _clone_json_payload(payload: Any) -> Any:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    except TypeError:
        return payload


def canonicalize_params(params: Any) -> Dict[str, Any]:
    return _clone_json_payload(params if isinstance(params, dict) else {}) or {}


def compute_params_hash(params: Any) -> str:
    canonical = canonicalize_params(params)
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_scope_fingerprint(scope_fingerprint: Any) -> str:
    raw = str(scope_fingerprint or "").strip()
    if not raw:
        return ""
    if len(raw) <= 128 and not raw.startswith(("{", "[")):
        return raw
    return f"scope:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _artifact_payload(record: AnalysisArtifact) -> Dict[str, Any]:
    return {
        "id": record.id,
        "history_id": str(record.history_id or ""),
        "artifact_type": str(record.artifact_type or ""),
        "params_hash": str(record.params_hash or ""),
        "params": _clone_json_payload(record.params if isinstance(record.params, dict) else {}),
        "scope_fingerprint": str(record.scope_fingerprint or ""),
        "data_version": str(record.data_version or DATA_VERSION),
        "payload": _clone_json_payload(record.payload if isinstance(record.payload, dict) else {}),
        "summary": _clone_json_payload(record.summary if isinstance(record.summary, dict) else {}),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


class AnalysisArtifactRepo:
    def upsert(
        self,
        *,
        history_id: str,
        artifact_type: str,
        params: Dict[str, Any],
        payload: Dict[str, Any],
        summary: Optional[Dict[str, Any]] = None,
        scope_fingerprint: str = "",
        data_version: str = DATA_VERSION,
    ) -> Dict[str, Any]:
        normalized_history_id = str(history_id or "").strip()
        normalized_type = str(artifact_type or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        if not normalized_type:
            raise ValueError("artifact_type_required")
        canonical_params = canonicalize_params(params)
        params_hash = compute_params_hash(canonical_params)
        normalized_scope = normalize_scope_fingerprint(scope_fingerprint)
        normalized_version = str(data_version or DATA_VERSION).strip() or DATA_VERSION
        now = datetime.utcnow()
        session: Session = SessionLocal()
        try:
            record = (
                session.query(AnalysisArtifact)
                .filter_by(
                    history_id=normalized_history_id,
                    artifact_type=normalized_type,
                    params_hash=params_hash,
                    scope_fingerprint=normalized_scope,
                    data_version=normalized_version,
                )
                .first()
            )
            if record is None:
                record = AnalysisArtifact(
                    history_id=normalized_history_id,
                    artifact_type=normalized_type,
                    params_hash=params_hash,
                    params=canonical_params,
                    scope_fingerprint=normalized_scope,
                    data_version=normalized_version,
                    payload=_clone_json_payload(payload if isinstance(payload, dict) else {}),
                    summary=_clone_json_payload(summary if isinstance(summary, dict) else {}),
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.params = canonical_params
                record.payload = _clone_json_payload(payload if isinstance(payload, dict) else {})
                record.summary = _clone_json_payload(summary if isinstance(summary, dict) else {})
                record.updated_at = now
            session.commit()
            session.refresh(record)
            return _artifact_payload(record)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list(
        self,
        history_id: str,
        *,
        artifact_type: str = "",
        params_hash: str = "",
    ) -> List[Dict[str, Any]]:
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            return []
        session: Session = SessionLocal()
        try:
            query = session.query(AnalysisArtifact.id).filter_by(history_id=normalized_history_id)
            if artifact_type:
                query = query.filter_by(artifact_type=str(artifact_type).strip())
            if params_hash:
                query = query.filter_by(params_hash=str(params_hash).strip())
            id_rows = query.order_by(AnalysisArtifact.updated_at.desc(), AnalysisArtifact.id.desc()).all()
            record_ids = [int(row[0] if isinstance(row, tuple) else getattr(row, "id", row)) for row in id_rows]
            records = [session.get(AnalysisArtifact, record_id) for record_id in record_ids]
            return [_artifact_payload(record) for record in records if record is not None]
        finally:
            session.close()


analysis_artifact_repo = AnalysisArtifactRepo()
