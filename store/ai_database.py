"""
Independent AI PostgreSQL connection and schema initialization.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from core.config import settings
from .ai_models import AiBase

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory = sessionmaker(autoflush=False, autocommit=False, future=True)


def _build_ai_engine(db_uri: str | None = None) -> Engine:
    effective_db_uri = db_uri or settings.ai_sqlalchemy_database_uri
    connect_args = {}
    engine_kwargs = {
        "future": True,
        "pool_pre_ping": True,
    }

    try:
        drivername = make_url(effective_db_uri).drivername
    except Exception:
        drivername = ""

    if drivername.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    else:
        engine_kwargs.update({
            "pool_recycle": 300,
            "pool_size": 5,
            "max_overflow": 5,
        })

    return create_engine(effective_db_uri, connect_args=connect_args, **engine_kwargs)


def get_ai_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_ai_engine()
        _session_factory.configure(bind=_engine)
    return _engine


def SessionLocal():
    get_ai_engine()
    return _session_factory()


def init_ai_db() -> None:
    engine = get_ai_engine()
    AiBase.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        columns = {item.get("name") for item in inspect(engine).get_columns("documents")}
        if "history_id" not in columns:
            connection.execute(text("ALTER TABLE documents ADD COLUMN history_id VARCHAR(64)"))
        indexes = {item.get("name") for item in inspect(engine).get_indexes("documents")}
        if "ix_documents_history_id" not in indexes:
            connection.execute(text("CREATE INDEX ix_documents_history_id ON documents (history_id)"))
        connection.execute(
            text(
                "UPDATE documents SET document_role = 'reference_document' "
                "WHERE document_role = 'evidence_document' OR document_role IS NULL OR document_role = ''"
            )
        )
    logger.info("AI 文档数据库初始化完成")
