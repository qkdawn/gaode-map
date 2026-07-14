from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .analysis_run_storage import AnalysisRunStorage, analysis_run_storage
from .database import SessionLocal
from .models import AnalysisRunRecord


def _clone_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


class AnalysisRunRepo:
    """Index immutable run manifests in MySQL and keep payloads in local storage."""

    def __init__(self, storage: AnalysisRunStorage | None = None) -> None:
        self.storage = storage or analysis_run_storage

    def save(self, *, history_id: str, manifest: dict[str, Any], artifact_payloads: dict[str, Any] | None = None, execution_request: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_history_id = str(history_id or "").strip()
        canonical_manifest = _clone_json(manifest)
        run_id = str(canonical_manifest.get("run_id") or "").strip()
        capability_id = str(canonical_manifest.get("capability_id") or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        if not run_id:
            raise ValueError("analysis_run_id_required")
        if not capability_id:
            raise ValueError("capability_id_required")
        payloads = _clone_json(artifact_payloads or {})
        request = _clone_json(execution_request or {"history_id": normalized_history_id})
        had_storage = self.storage._path(capability_id, run_id).exists()

        # Publish the immutable local snapshot before making the database index visible.
        self.storage.create(history_id=normalized_history_id, manifest=canonical_manifest, artifact_payloads=payloads, execution_request=request)
        session: Session = SessionLocal()
        try:
            existing = session.get(AnalysisRunRecord, run_id)
            if existing is not None:
                if str(existing.history_id or "") != normalized_history_id or _clone_json(existing.manifest) != canonical_manifest:
                    raise ValueError("analysis_run_immutable")
                return self._detail(capability_id, run_id)
            record = AnalysisRunRecord(
                run_id=run_id,
                history_id=normalized_history_id,
                capability_id=capability_id,
                status=str(canonical_manifest.get("status") or "draft"),
                current_stage=str(canonical_manifest.get("current_stage") or ""),
                manifest=canonical_manifest,
                created_at=_parse_datetime(canonical_manifest.get("created_at")) or _utc_naive_now(),
                completed_at=_parse_datetime(canonical_manifest.get("completed_at")),
                persisted_at=_utc_naive_now(),
            )
            session.add(record)
            session.commit()
            return self._detail(capability_id, run_id)
        except Exception:
            session.rollback()
            if not had_storage:
                self.storage.delete(capability_id, run_id)
            raise
        finally:
            session.close()

    def list(self, history_id: str, *, capability_id: str = "") -> list[dict[str, Any]]:
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        session: Session = SessionLocal()
        try:
            query = session.query(AnalysisRunRecord).filter_by(history_id=normalized_history_id)
            if str(capability_id or "").strip():
                query = query.filter_by(capability_id=str(capability_id).strip())
            return [_clone_json(record.manifest) for record in query.order_by(AnalysisRunRecord.persisted_at.desc(), AnalysisRunRecord.run_id.desc()).all()]
        finally:
            session.close()

    def get(self, run_id: str) -> dict[str, Any] | None:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return None
        session: Session = SessionLocal()
        try:
            record = session.get(AnalysisRunRecord, normalized_run_id)
            if record is None:
                return None
            return self._detail(str(record.capability_id), normalized_run_id)
        finally:
            session.close()

    def changed_input_artifact_ids(self, *, history_id: str, run_id: str, input_artifacts: list[dict[str, Any]]) -> list[str]:
        expected = {str(item.get("artifact_id") or "").strip(): str(item.get("content_digest") or "").strip() for item in input_artifacts if isinstance(item, dict) and str(item.get("artifact_id") or "").strip()}
        if not expected:
            return []
        session: Session = SessionLocal()
        try:
            current = session.get(AnalysisRunRecord, run_id)
            if current is None:
                return []
            records = session.query(AnalysisRunRecord).filter(AnalysisRunRecord.history_id == str(history_id or "").strip(), AnalysisRunRecord.persisted_at > current.persisted_at).order_by(AnalysisRunRecord.persisted_at.desc(), AnalysisRunRecord.run_id.desc()).all()
            latest: dict[str, str] = {}
            for record in records:
                for item in record.manifest.get("input_artifact_refs") or []:
                    if isinstance(item, dict) and str(item.get("artifact_id") or "") in expected:
                        latest.setdefault(str(item["artifact_id"]), str(item.get("content_digest") or ""))
            return sorted(artifact_id for artifact_id, digest in expected.items() if artifact_id in latest and latest[artifact_id] != digest)
        finally:
            session.close()

    def _detail(self, capability_id: str, run_id: str) -> dict[str, Any]:
        detail = self.storage.read(capability_id, run_id)
        return {key: value for key, value in detail.items() if key != "execution_request"}


analysis_run_repo = AnalysisRunRepo()
