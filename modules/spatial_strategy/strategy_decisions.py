from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import settings


_engine = None
_session_factory = sessionmaker(autoflush=False, autocommit=False, future=True)


def SessionLocal():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.spatial_strategy_state_database_url,
            future=True,
            pool_pre_ping=True,
        )
        _session_factory.configure(bind=_engine)
    return _session_factory()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def read_strategy_decisions(run_id: str) -> dict[str, Any]:
    """Return completed domain decisions for one spatial-strategy run."""
    normalized_run_id = str(UUID(str(run_id)))
    session = SessionLocal()
    try:
        run_exists = session.execute(
            text("SELECT 1 FROM analysis_runs WHERE id = :run_id"),
            {"run_id": normalized_run_id},
        ).scalar_one_or_none()
        if run_exists is None:
            raise LookupError("spatial_strategy_run_not_found")

        rows = session.execute(
            text(
                "SELECT step, output FROM analysis_step_outputs "
                "WHERE run_id = :run_id AND status = 'completed' "
                "ORDER BY step_order, step"
            ),
            {"run_id": normalized_run_id},
        ).mappings().all()
    finally:
        session.close()

    decisions = []
    for row in rows:
        output = _mapping(row.get("output"))
        memo = _mapping(output.get("decision_memo"))
        decision = str(memo.get("decision") or "").strip()
        if not decision:
            continue
        decisions.append(
            {
                "unit_id": str(output.get("unit_id") or row.get("step") or "").strip(),
                "title": str(output.get("title") or "").strip(),
                "decision": decision,
                "key_facts": _list(memo.get("key_facts")),
                "named_entities": _list(memo.get("named_entities")),
                "actions": _list(memo.get("actions")),
                "alternatives_considered": _list(memo.get("alternatives_considered")),
            }
        )
    if not decisions:
        raise LookupError("spatial_strategy_decisions_not_found")
    return {"run_id": normalized_run_id, "decisions": decisions}
