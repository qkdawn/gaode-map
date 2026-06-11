"""
Independent AI PostgreSQL connection and schema initialization.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy import text
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
    _ensure_pgvector_extension(engine)
    AiBase.metadata.create_all(bind=engine)
    logger.info("AI 文档数据库初始化完成")


def _ensure_pgvector_extension(engine: Engine) -> None:
    try:
        drivername = make_url(str(engine.url)).drivername
    except Exception:
        drivername = ""
    if not drivername.startswith("postgresql"):
        return
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
