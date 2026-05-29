"""
数据库连接与初始化。
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import make_url

from core.config import settings
from .models import AgentSession, AnalysisArtifact, Base, PoiResult

logger = logging.getLogger(__name__)


def _build_engine(db_uri: str | None = None):
    """
    构建 SQLAlchemy 引擎。
    """
    effective_db_uri = db_uri or settings.sqlalchemy_database_uri
    if effective_db_uri.lower().startswith("sqlite"):
        raise ValueError("SQLite is no longer supported. Configure DB_URL with mysql+pymysql://...")

    connect_args = {}
    try:
        drivername = make_url(effective_db_uri).drivername
    except Exception:
        drivername = ""
    if "pymysql" in drivername:
        connect_args = {
            "connect_timeout": 5,
            "read_timeout": 30,
            "write_timeout": 30,
        }

    return create_engine(
        effective_db_uri,
        future=True,
        pool_pre_ping=True,  # Auto-reconnect
        pool_recycle=300,
        pool_size=5,
        max_overflow=5,
        connect_args=connect_args,
    )


engine = _build_engine()
SessionLocal = sessionmaker(autoflush=False, autocommit=False, future=True)
SessionLocal.configure(bind=engine)


def _ensure_agent_sessions_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("agent_sessions"):
        AgentSession.__table__.create(bind=engine, checkfirst=True)
        return

    columns = {item.get("name") for item in inspector.get_columns("agent_sessions")}
    if {"history_id", "panel_kind"}.issubset(columns):
        for index in AgentSession.__table__.indexes:
            index.create(bind=engine, checkfirst=True)
        return

    logger.warning("agent_sessions 缺少面板历史字段，将按新结构重建并丢弃旧 AI 历史")
    AgentSession.__table__.drop(bind=engine, checkfirst=True)
    AgentSession.__table__.create(bind=engine, checkfirst=True)


def _ensure_poi_results_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("poi_results"):
        PoiResult.__table__.create(bind=engine, checkfirst=True)
        return

    columns = {item.get("name") for item in inspector.get_columns("poi_results")}
    statements = []
    if "source" not in columns:
        statements.append("ALTER TABLE poi_results ADD COLUMN source VARCHAR(32)")
    if "year" not in columns:
        statements.append("ALTER TABLE poi_results ADD COLUMN year INTEGER")

    if statements:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX uq_poi_results_history_source_year ON poi_results (history_id, source, year)"))
    except Exception:
        logger.debug("poi_results multi-year unique index already exists or could not be created", exc_info=True)


def _ensure_analysis_artifacts_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("analysis_artifacts"):
        AnalysisArtifact.__table__.create(bind=engine, checkfirst=True)
        return
    for index in AnalysisArtifact.__table__.indexes:
        index.create(bind=engine, checkfirst=True)


def init_db() -> None:
    """
    创建表结构（幂等）。
    """
    Base.metadata.create_all(bind=engine)
    _ensure_agent_sessions_schema()
    _ensure_poi_results_schema()
    _ensure_analysis_artifacts_schema()
    logger.info("数据库初始化完成")
