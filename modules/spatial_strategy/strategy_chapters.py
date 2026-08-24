from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, create_engine, text
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


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def read_strategy_chapters(run_id: str, unit_ids: list[str]) -> dict[str, Any]:
    """Return exactly the requested completed strategy chapters in stored order."""
    normalized_run_id = str(UUID(str(run_id)))
    requested = list(dict.fromkeys(str(item).strip() for item in unit_ids if str(item).strip()))
    if not requested:
        raise ValueError("strategy_chapter_unit_ids_required")

    session = SessionLocal()
    try:
        run = session.execute(
            text("SELECT history_id, request FROM analysis_runs WHERE id = :run_id"),
            {"run_id": normalized_run_id},
        ).mappings().one_or_none()
        if run is None:
            raise LookupError("spatial_strategy_run_not_found")
        chapter_query = text(
                "SELECT step, output FROM analysis_step_outputs "
                "WHERE run_id = :run_id AND status = 'completed' AND step IN :unit_ids "
                "ORDER BY step_order, step"
            ).bindparams(bindparam("unit_ids", expanding=True))
        rows = session.execute(
            chapter_query,
            {"run_id": normalized_run_id, "unit_ids": requested},
        ).mappings().all()
    finally:
        session.close()

    by_unit_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        output = _mapping(row.get("output"))
        unit_id = str(output.get("unit_id") or row.get("step") or "").strip()
        if (
            unit_id in requested
            and str(output.get("title") or "").strip()
            and str(output.get("content") or "").strip()
            and isinstance(output.get("citations"), list)
        ):
            by_unit_id[unit_id] = {
                "unit_id": unit_id,
                "title": str(output["title"]).strip(),
                "content": str(output["content"]).strip(),
                "citations": output["citations"],
            }

    missing = [unit_id for unit_id in requested if unit_id not in by_unit_id]
    if missing:
        raise LookupError("spatial_strategy_chapters_not_found:" + ",".join(missing))
    request = _mapping(run.get("request"))
    return {
        "run_id": normalized_run_id,
        "history_id": str(run.get("history_id") or request.get("history_id") or "").strip(),
        "project_question": str(request.get("project_question") or "").strip(),
        "chapters": [by_unit_id[unit_id] for unit_id in requested],
    }
