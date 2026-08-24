from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import AgentSession


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"agent_sessions.{field} is required")
    return text


def _record_payload(record: AgentSession) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "codex_thread_id": str(record.codex_thread_id),
        "title": str(record.title or ""),
        "preview": str(record.preview or ""),
        "status": str(record.status or "idle"),
        "history_id": str(record.history_id or ""),
        "panel_kind": str(record.panel_kind or ""),
        "is_pinned": bool(record.is_pinned),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "pinned_at": record.pinned_at,
    }


class AgentSessionRepo:
    def list_records(self) -> list[dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            records = session.scalars(
                select(AgentSession).order_by(
                    desc(AgentSession.is_pinned),
                    desc(AgentSession.pinned_at),
                    desc(AgentSession.updated_at),
                    desc(AgentSession.created_at),
                )
            ).all()
            return [_record_payload(record) for record in records]
        finally:
            session.close()

    def get_record(self, session_id: str) -> dict[str, Any] | None:
        session: Session = SessionLocal()
        try:
            record = session.get(AgentSession, session_id)
            return _record_payload(record) if record is not None else None
        finally:
            session.close()

    def upsert_record(
        self,
        session_id: str,
        *,
        codex_thread_id: str,
        title: str,
        preview: str,
        status: str,
        history_id: str,
        panel_kind: str,
    ) -> dict[str, Any]:
        now = datetime.utcnow()
        session: Session = SessionLocal()
        try:
            normalized_id = _required_text(session_id, "id")
            record = session.get(AgentSession, normalized_id)
            if record is None:
                record = AgentSession(id=normalized_id, created_at=now, is_pinned=False)
                session.add(record)
            record.codex_thread_id = _required_text(codex_thread_id, "codex_thread_id")
            record.title = str(title or "").strip()[:255]
            record.preview = str(preview or "").strip()[:1000]
            record.status = str(status or "idle").strip().lower()
            record.history_id = _required_text(history_id, "history_id")
            record.panel_kind = _required_text(panel_kind, "panel_kind").lower()
            record.updated_at = now
            session.commit()
            session.refresh(record)
            return _record_payload(record)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_metadata(
        self,
        session_id: str,
        *,
        title: str | None = None,
        is_pinned: bool | None = None,
        preview: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        now = datetime.utcnow()
        session: Session = SessionLocal()
        try:
            record = session.get(AgentSession, session_id)
            if record is None:
                return None
            if title is not None:
                record.title = str(title).strip()[:255]
            if preview is not None:
                record.preview = str(preview).strip()[:1000]
            if status is not None:
                record.status = str(status).strip().lower()
            if is_pinned is not None:
                next_pinned = bool(is_pinned)
                record.pinned_at = now if next_pinned else None
                record.is_pinned = next_pinned
            record.updated_at = now
            session.commit()
            session.refresh(record)
            return _record_payload(record)
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
            raise
        finally:
            session.close()


agent_session_repo = AgentSessionRepo()
