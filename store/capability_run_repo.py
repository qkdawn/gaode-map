from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import CapabilityArtifactVersion, CapabilityRunRecord


def _clone_json(value: Any) -> Any:
    return json.loads(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    )


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _artifact_payload(record: CapabilityArtifactVersion) -> dict[str, Any]:
    return {
        "direction": str(record.direction or ""),
        "artifact": {
            "artifact_id": str(record.artifact_id or ""),
            "artifact_type": str(record.artifact_type or ""),
            "title": str(record.title or ""),
            "version": str(record.version or ""),
            "filename": str(record.filename or ""),
            "source_run_id": str(record.source_run_id or ""),
            "source_artifact_refs": _clone_json(record.source_artifact_refs or []),
            "evidence_refs": _clone_json(record.evidence_refs or []),
            "content_digest": str(record.content_digest or ""),
            "created_at": record.created_at.isoformat() + "Z"
            if record.created_at
            else "",
        },
        "payload": _clone_json(record.payload),
    }


class CapabilityRunRepo:
    """Persist immutable run manifests and artifact versions without domain policy."""

    def save(
        self,
        *,
        history_id: str,
        manifest: dict[str, Any],
        artifact_payloads: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_history_id = str(history_id or "").strip()
        run_id = str(manifest.get("run_id") or "").strip()
        capability_id = str(manifest.get("capability_id") or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        if not run_id:
            raise ValueError("capability_run_id_required")
        if not capability_id:
            raise ValueError("capability_id_required")

        canonical_manifest = _clone_json(manifest)
        payloads = artifact_payloads or {}
        session: Session = SessionLocal()
        try:
            existing = session.get(CapabilityRunRecord, run_id)
            if existing is not None:
                self._assert_existing_immutable(
                    session,
                    existing,
                    history_id=normalized_history_id,
                    manifest=canonical_manifest,
                    artifact_payloads=payloads,
                )
                return self._detail_payload(session, existing)

            record = CapabilityRunRecord(
                run_id=run_id,
                history_id=normalized_history_id,
                capability_id=capability_id,
                status=str(manifest.get("status") or "draft"),
                current_stage=str(manifest.get("current_stage") or ""),
                manifest=canonical_manifest,
                created_at=_parse_datetime(manifest.get("created_at"))
                or _utc_naive_now(),
                completed_at=_parse_datetime(manifest.get("completed_at")),
                persisted_at=_utc_naive_now(),
            )
            session.add(record)
            for direction, key in (
                ("input", "input_artifact_refs"),
                ("output", "output_artifact_refs"),
            ):
                for artifact in manifest.get(key) or []:
                    if not isinstance(artifact, dict):
                        continue
                    artifact_id = str(artifact.get("artifact_id") or "").strip()
                    if not artifact_id:
                        continue
                    session.add(
                        CapabilityArtifactVersion(
                            run_id=run_id,
                            history_id=normalized_history_id,
                            artifact_id=artifact_id,
                            direction=direction,
                            artifact_type=str(
                                artifact.get("artifact_type") or "structured_data"
                            ),
                            version=str(artifact.get("version") or "unversioned"),
                            title=str(artifact.get("title") or ""),
                            filename=str(artifact.get("filename") or ""),
                            source_run_id=str(artifact.get("source_run_id") or ""),
                            source_artifact_refs=_clone_json(
                                artifact.get("source_artifact_refs") or []
                            ),
                            evidence_refs=_clone_json(
                                artifact.get("evidence_refs") or []
                            ),
                            content_digest=str(artifact.get("content_digest") or ""),
                            payload=_clone_json(payloads.get(artifact_id))
                            if direction == "output" and artifact_id in payloads
                            else None,
                            created_at=_parse_datetime(artifact.get("created_at"))
                            or _utc_naive_now(),
                        )
                    )
            session.commit()
            session.refresh(record)
            return self._detail_payload(session, record)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list(self, history_id: str, *, capability_id: str = "") -> list[dict[str, Any]]:
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        session: Session = SessionLocal()
        try:
            query = session.query(CapabilityRunRecord).filter_by(
                history_id=normalized_history_id
            )
            normalized_capability_id = str(capability_id or "").strip()
            if normalized_capability_id:
                query = query.filter_by(capability_id=normalized_capability_id)
            records = query.order_by(
                CapabilityRunRecord.persisted_at.desc(),
                CapabilityRunRecord.run_id.desc(),
            ).all()
            return [_clone_json(record.manifest) for record in records]
        finally:
            session.close()

    def get(self, run_id: str) -> dict[str, Any] | None:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return None
        session: Session = SessionLocal()
        try:
            record = session.get(CapabilityRunRecord, normalized_run_id)
            return self._detail_payload(session, record) if record is not None else None
        finally:
            session.close()

    def changed_input_artifact_ids(
        self,
        *,
        history_id: str,
        run_id: str,
        input_artifacts: list[dict[str, Any]],
    ) -> list[str]:
        expected = {
            str(item.get("artifact_id") or "").strip(): str(
                item.get("content_digest") or ""
            ).strip()
            for item in input_artifacts
            if isinstance(item, dict) and str(item.get("artifact_id") or "").strip()
        }
        if not expected:
            return []
        session: Session = SessionLocal()
        try:
            current = session.get(CapabilityRunRecord, run_id)
            if current is None:
                return []
            rows = (
                session.query(CapabilityArtifactVersion)
                .join(
                    CapabilityRunRecord,
                    CapabilityRunRecord.run_id == CapabilityArtifactVersion.run_id,
                )
                .filter(
                    CapabilityArtifactVersion.history_id
                    == str(history_id or "").strip(),
                    CapabilityArtifactVersion.direction == "input",
                    CapabilityArtifactVersion.artifact_id.in_(list(expected)),
                    CapabilityRunRecord.persisted_at > current.persisted_at,
                )
                .order_by(
                    CapabilityRunRecord.persisted_at.desc(),
                    CapabilityArtifactVersion.id.desc(),
                )
                .all()
            )
            latest: dict[str, str] = {}
            for row in rows:
                latest.setdefault(str(row.artifact_id), str(row.content_digest or ""))
            return sorted(
                artifact_id
                for artifact_id, digest in expected.items()
                if artifact_id in latest and latest[artifact_id] != digest
            )
        finally:
            session.close()

    @staticmethod
    def _assert_existing_immutable(
        session: Session,
        record: CapabilityRunRecord,
        *,
        history_id: str,
        manifest: dict[str, Any],
        artifact_payloads: dict[str, Any],
    ) -> None:
        if (
            str(record.history_id or "") != history_id
            or _clone_json(record.manifest) != manifest
        ):
            raise ValueError("capability_run_immutable")
        if not artifact_payloads:
            return
        stored_outputs = {
            str(item.artifact_id): _clone_json(item.payload)
            for item in session.query(CapabilityArtifactVersion)
            .filter_by(run_id=record.run_id, direction="output")
            .all()
        }
        for artifact_id, payload in artifact_payloads.items():
            if artifact_id not in stored_outputs or stored_outputs[
                artifact_id
            ] != _clone_json(payload):
                raise ValueError("capability_run_immutable")

    @staticmethod
    def _detail_payload(
        session: Session, record: CapabilityRunRecord
    ) -> dict[str, Any]:
        artifacts = (
            session.query(CapabilityArtifactVersion)
            .filter_by(run_id=record.run_id)
            .order_by(CapabilityArtifactVersion.direction, CapabilityArtifactVersion.id)
            .all()
        )
        return {
            "history_id": str(record.history_id or ""),
            "run": _clone_json(record.manifest),
            "artifacts": [_artifact_payload(item) for item in artifacts],
        }


capability_run_repo = CapabilityRunRepo()
