from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import AgentSession


def _clone_json_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: _clone_json_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_clone_json_payload(item) for item in payload]
    return payload


def _normalize_title_source(value: Any) -> str:
    source = str(value or "").strip().lower()
    if source in {"user", "ai", "fallback"}:
        return source
    return "fallback"


def _extract_snapshot_meta(snapshot: Any) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    meta = snapshot.get("_meta")
    return meta if isinstance(meta, dict) else {}


def _normalize_panel_kind(value: Any) -> str:
    return str(value or "").strip().lower()


def _require_panel_identity(history_id: Any, panel_kind: Any) -> tuple[str, str]:
    normalized_history_id = str(history_id or "").strip()
    normalized_panel_kind = _normalize_panel_kind(panel_kind)
    if not normalized_history_id:
        raise ValueError("agent_sessions.history_id is required")
    if not normalized_panel_kind:
        raise ValueError("agent_sessions.panel_kind is required")
    return normalized_history_id, normalized_panel_kind


class AgentSessionRepo:
    @staticmethod
    def _resolve_summary_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **payload,
            "title_source": _normalize_title_source(payload.get("title_source")),
            "history_id": str(payload.get("history_id") or "").strip(),
            "panel_kind": _normalize_panel_kind(payload.get("panel_kind")),
        }

    @staticmethod
    def _build_summary_payload(record: AgentSession) -> Dict[str, Any]:
        snapshot = record.snapshot if isinstance(record.snapshot, dict) else {}
        meta = _extract_snapshot_meta(snapshot)
        return AgentSessionRepo._resolve_summary_payload({
            "id": str(record.id or ""),
            "title": str(record.title or ""),
            "preview": str(record.preview or ""),
            "status": str(record.status or "idle"),
            "history_id": str(record.history_id or ""),
            "panel_kind": str(record.panel_kind or ""),
            "is_pinned": bool(record.is_pinned),
            "title_source": _normalize_title_source(meta.get("title_source")),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "pinned_at": record.pinned_at,
        })

    def _build_detail_payload(self, record: AgentSession) -> Dict[str, Any]:
        payload = self._build_summary_payload(record)
        payload["snapshot"] = _clone_json_payload(record.snapshot if isinstance(record.snapshot, dict) else {})
        return payload

    def list_records(self) -> List[Dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            rows = session.execute(
                select(
                    AgentSession.id.label("id"),
                    AgentSession.title.label("title"),
                    AgentSession.preview.label("preview"),
                    AgentSession.status.label("status"),
                    AgentSession.history_id.label("history_id"),
                    AgentSession.panel_kind.label("panel_kind"),
                    AgentSession.is_pinned.label("is_pinned"),
                    AgentSession.created_at.label("created_at"),
                    AgentSession.updated_at.label("updated_at"),
                    AgentSession.pinned_at.label("pinned_at"),
                )
                .select_from(AgentSession)
                .order_by(
                    desc(AgentSession.is_pinned),
                    desc(AgentSession.pinned_at),
                    desc(AgentSession.updated_at),
                    desc(AgentSession.created_at),
                )
            ).mappings().all()
            payloads: List[Dict[str, Any]] = []
            for row in rows:
                payload = dict(row)
                payloads.append(self._resolve_summary_payload(payload))
            return payloads
        finally:
            session.close()

    def get_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            record = session.get(AgentSession, session_id)
            if record is None:
                return None
            return self._build_detail_payload(record)
        finally:
            session.close()

    def upsert_record(
        self,
        session_id: str,
        *,
        title: str,
        preview: str,
        status: str,
        history_id: str,
        panel_kind: str,
        snapshot: Dict[str, Any],
        is_pinned: Optional[bool] = None,
        title_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        session: Session = SessionLocal()
        try:
            record = session.get(AgentSession, session_id)
            if record is None:
                record = AgentSession(
                    id=session_id,
                    created_at=now,
                    is_pinned=bool(is_pinned) if is_pinned is not None else False,
                )
                session.add(record)
            if is_pinned is not None:
                next_is_pinned = bool(is_pinned)
                if next_is_pinned and not record.is_pinned:
                    record.pinned_at = now
                elif not next_is_pinned:
                    record.pinned_at = None
                record.is_pinned = next_is_pinned
            elif record.is_pinned and record.pinned_at is None:
                record.pinned_at = now
            record.title = title
            record.preview = preview
            record.status = status
            record.history_id, record.panel_kind = _require_panel_identity(history_id, panel_kind)
            next_snapshot = _clone_json_payload(snapshot if isinstance(snapshot, dict) else {})
            next_meta = {
                **_extract_snapshot_meta(record.snapshot),
                **_extract_snapshot_meta(next_snapshot),
                "history_id": record.history_id,
                "panel_kind": record.panel_kind,
            }
            if title_source is not None:
                next_meta["title_source"] = _normalize_title_source(title_source)
            elif not next_meta.get("title_source"):
                next_meta["title_source"] = "fallback"
            next_snapshot["_meta"] = next_meta
            record.snapshot = next_snapshot
            record.updated_at = now
            session.commit()
            session.refresh(record)
            return self._build_detail_payload(record)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_metadata(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        is_pinned: Optional[bool] = None,
        title_source: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.utcnow()
        session: Session = SessionLocal()
        try:
            record = session.get(AgentSession, session_id)
            if record is None:
                return None
            if title is not None:
                record.title = title
            snapshot = _clone_json_payload(record.snapshot if isinstance(record.snapshot, dict) else {})
            meta = _extract_snapshot_meta(snapshot)
            if title_source is not None:
                meta["title_source"] = _normalize_title_source(title_source)
            elif title is not None:
                meta["title_source"] = "user"
            if meta:
                snapshot["_meta"] = meta
                record.snapshot = snapshot
            if is_pinned is not None:
                next_is_pinned = bool(is_pinned)
                if next_is_pinned and not record.is_pinned:
                    record.pinned_at = now
                elif not next_is_pinned:
                    record.pinned_at = None
                record.is_pinned = next_is_pinned
            elif record.is_pinned and record.pinned_at is None:
                record.pinned_at = now

            record.updated_at = now
            session.commit()
            session.refresh(record)
            return self._build_detail_payload(record)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_record(self, session_id: str) -> bool:
        session: Session = SessionLocal()
        try:
            rows = session.query(AgentSession).filter_by(id=session_id).delete()
            session.commit()
            return rows > 0
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()


agent_session_repo = AgentSessionRepo()
