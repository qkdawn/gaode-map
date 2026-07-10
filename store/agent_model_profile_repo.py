from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import AgentModelProfile


class AgentModelProfileRepo:
    @staticmethod
    def _open_session() -> Session:
        session: Session = SessionLocal()
        AgentModelProfile.__table__.create(bind=session.get_bind(), checkfirst=True)
        return session

    def list_records(self) -> List[Dict[str, Any]]:
        session = self._open_session()
        try:
            rows = session.execute(
                select(AgentModelProfile).order_by(
                    AgentModelProfile.is_default.desc(),
                    AgentModelProfile.updated_at.desc(),
                )
            ).scalars().all()
            return [self._payload(row) for row in rows]
        finally:
            session.close()

    def get_record(self, profile_id: str) -> Optional[Dict[str, Any]]:
        session = self._open_session()
        try:
            row = session.get(AgentModelProfile, profile_id)
            return self._payload(row) if row is not None else None
        finally:
            session.close()

    def upsert_record(self, profile_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        session = self._open_session()
        try:
            now = datetime.utcnow()
            row = session.get(AgentModelProfile, profile_id)
            if row is None:
                row = AgentModelProfile(id=profile_id, created_at=now)
                session.add(row)
            if values.get("is_default"):
                session.execute(update(AgentModelProfile).values(is_default=False))
            for key in (
                "display_name", "provider", "base_url", "model_name",
                "api_key_ciphertext", "enabled", "is_default",
            ):
                if key in values:
                    setattr(row, key, values[key])
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return self._payload(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_record(self, profile_id: str) -> bool:
        session = self._open_session()
        try:
            row = session.get(AgentModelProfile, profile_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _payload(row: AgentModelProfile) -> Dict[str, Any]:
        return {
            "id": str(row.id or ""),
            "display_name": str(row.display_name or ""),
            "provider": str(row.provider or ""),
            "base_url": str(row.base_url or ""),
            "model_name": str(row.model_name or ""),
            "api_key_ciphertext": str(row.api_key_ciphertext or ""),
            "enabled": bool(row.enabled),
            "is_default": bool(row.is_default),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


agent_model_profile_repo = AgentModelProfileRepo()
