from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.spatial import build_scope_fingerprint
from .artifact_identity import artifact_year, build_artifact_slot_key
from .database import SessionLocal
from .models import AnalysisArtifact, AnalysisHistory


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
        "slot_key": str(record.slot_key or ""),
        "params_hash": str(record.params_hash or ""),
        "params": _clone_json_payload(record.params if isinstance(record.params, dict) else {}),
        "scope_fingerprint": str(record.scope_fingerprint or ""),
        "data_version": str(record.data_version or DATA_VERSION),
        "payload": _clone_json_payload(record.payload if isinstance(record.payload, dict) else {}),
        "summary": _clone_json_payload(record.summary if isinstance(record.summary, dict) else {}),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _history_scope_fingerprint(session: Session, history_id: str) -> str:
    history = session.query(AnalysisHistory.result_polygon).filter(AnalysisHistory.id == history_id).first()
    if history is None:
        raise ValueError("history_not_found")
    polygon_wgs84 = history[0] if isinstance(history, tuple) else getattr(history, "result_polygon", None)
    return build_scope_fingerprint(polygon_wgs84 if isinstance(polygon_wgs84, list) else [])


class AnalysisArtifactRepo:
    def upsert(
        self,
        *,
        history_id: str,
        artifact_type: str,
        params: Dict[str, Any],
        payload: Dict[str, Any],
        summary: Optional[Dict[str, Any]] = None,
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
        slot_key = build_artifact_slot_key(normalized_type, canonical_params, payload)
        normalized_version = str(data_version or DATA_VERSION).strip() or DATA_VERSION
        now = datetime.utcnow()
        session: Session = SessionLocal()
        try:
            normalized_scope = _history_scope_fingerprint(session, normalized_history_id)
            record = (
                session.query(AnalysisArtifact)
                .filter_by(
                    history_id=normalized_history_id,
                    artifact_type=normalized_type,
                    slot_key=slot_key,
                )
                .first()
            )
            if record is None:
                record = AnalysisArtifact(
                    history_id=normalized_history_id,
                    artifact_type=normalized_type,
                    slot_key=slot_key,
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
                record.params_hash = params_hash
                record.scope_fingerprint = normalized_scope
                record.data_version = normalized_version
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
            query = session.query(AnalysisArtifact).filter_by(history_id=normalized_history_id)
            if artifact_type:
                query = query.filter_by(artifact_type=str(artifact_type).strip())
            if params_hash:
                query = query.filter_by(params_hash=str(params_hash).strip())
            records = query.order_by(AnalysisArtifact.updated_at.desc(), AnalysisArtifact.id.desc()).all()
            payloads = [_artifact_payload(record) for record in records if record is not None]
            return sorted(
                payloads,
                key=lambda item: (
                    artifact_year(item.get("params"), item.get("payload")) or -1,
                    str(item.get("updated_at") or ""),
                    int(item.get("id") or 0),
                ),
                reverse=True,
            )
        finally:
            session.close()

    def list_summaries(
        self,
        history_id: str,
        *,
        artifact_type: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Read a bounded artifact index without loading the stored payload column."""

        normalized_history_id = str(history_id or "").strip()
        normalized_type = str(artifact_type or "").strip()
        normalized_limit = max(1, min(int(limit), 100))
        if not normalized_history_id or not normalized_type:
            return []
        session: Session = SessionLocal()
        try:
            rows = (
                session.query(
                    AnalysisArtifact.id,
                    AnalysisArtifact.params,
                    AnalysisArtifact.summary,
                    AnalysisArtifact.updated_at,
                )
                .filter_by(
                    history_id=normalized_history_id,
                    artifact_type=normalized_type,
                )
                .order_by(AnalysisArtifact.updated_at.desc(), AnalysisArtifact.id.desc())
                .limit(normalized_limit)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "params": _clone_json_payload(row.params if isinstance(row.params, dict) else {}),
                    "summary": _clone_json_payload(row.summary if isinstance(row.summary, dict) else {}),
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                }
                for row in rows
            ]
        finally:
            session.close()

    def get_by_id(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        normalized_id = str(artifact_id or "").strip()
        if not normalized_id:
            return None
        try:
            record_id = int(normalized_id)
        except (TypeError, ValueError):
            return None
        session: Session = SessionLocal()
        try:
            record = session.get(AnalysisArtifact, record_id)
            if record is None:
                return None
            return _artifact_payload(record)
        finally:
            session.close()

    def get_by_params_hash(
        self,
        history_id: str,
        *,
        artifact_type: str,
        params_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """Read one immutable artifact by its stable identity parameters."""

        normalized_history_id = str(history_id or "").strip()
        normalized_type = str(artifact_type or "").strip()
        normalized_hash = str(params_hash or "").strip()
        if not normalized_history_id or not normalized_type or not normalized_hash:
            return None
        session: Session = SessionLocal()
        try:
            record = (
                session.query(AnalysisArtifact)
                .filter_by(
                    history_id=normalized_history_id,
                    artifact_type=normalized_type,
                    params_hash=normalized_hash,
                )
                .first()
            )
            return _artifact_payload(record) if record is not None else None
        finally:
            session.close()

    def delete_by_source_id(
        self,
        history_id: str,
        *,
        source_id: str,
        artifact_types: Optional[List[str]] = None,
    ) -> int:
        normalized_history_id = str(history_id or "").strip()
        normalized_source_id = str(source_id or "").strip()
        if not normalized_history_id or not normalized_source_id:
            return 0
        allowed_types = {str(item or "").strip() for item in (artifact_types or []) if str(item or "").strip()}
        session: Session = SessionLocal()
        try:
            query = session.query(AnalysisArtifact).filter_by(history_id=normalized_history_id)
            if allowed_types:
                query = query.filter(AnalysisArtifact.artifact_type.in_(sorted(allowed_types)))
            records = query.all()
            deleted = 0
            for record in records:
                payload = _clone_json_payload(record.payload if isinstance(record.payload, dict) else {}) or {}
                source = payload.get("source") if isinstance(payload, dict) else {}
                if not isinstance(source, dict) or str(source.get("id") or "").strip() != normalized_source_id:
                    continue
                session.delete(record)
                deleted += 1
            session.commit()
            return deleted
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


analysis_artifact_repo = AnalysisArtifactRepo()
