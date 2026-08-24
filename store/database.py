"""
数据库连接与初始化。
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, delete, inspect, select, text, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import make_url

from core.config import ENV_FILE, reload_settings_from_env, settings
from core.spatial import build_scope_fingerprint
from .artifact_identity import build_artifact_slot_key
from .models import (
    AgentSession,
    AnalysisArtifact,
    AnalysisHistory,
    Base,
    PoiResult,
    ProjectDataSnapshot,
    ProjectSpatialUnit,
    SpatialProject,
)

logger = logging.getLogger(__name__)
_engine_lock = Lock()
_env_snapshot: tuple[int | None, int | None] | None = None
_engine_uri = ""
_engine_bind_address = ""
_session_factory = sessionmaker(autoflush=False, autocommit=False, future=True)


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
        io_timeout_s = max(30, int(settings.db_io_timeout_s or 120))
        connect_args = {
            "connect_timeout": 5,
            "read_timeout": io_timeout_s,
            "write_timeout": io_timeout_s,
        }
        bind_address = str(settings.db_bind_address or "").strip()
        if bind_address:
            connect_args["bind_address"] = bind_address

    return create_engine(
        effective_db_uri,
        future=True,
        pool_pre_ping=True,  # Auto-reconnect
        pool_recycle=300,
        pool_size=5,
        max_overflow=5,
        connect_args=connect_args,
    )


def _env_file_snapshot(path: Path = ENV_FILE) -> tuple[int | None, int | None]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None, None
    return stat.st_mtime_ns, stat.st_size


def _refresh_runtime_config_if_needed() -> None:
    global engine, _engine_uri, _engine_bind_address, _env_snapshot
    next_snapshot = _env_file_snapshot()
    if next_snapshot == _env_snapshot:
        return

    with _engine_lock:
        next_snapshot = _env_file_snapshot()
        if next_snapshot == _env_snapshot:
            return
        reload_settings_from_env()
        next_uri = settings.sqlalchemy_database_uri
        next_bind_address = str(settings.db_bind_address or "").strip()
        if next_uri != _engine_uri or next_bind_address != _engine_bind_address:
            old_engine = engine
            engine = _build_engine(next_uri)
            _session_factory.configure(bind=engine)
            old_engine.dispose()
            _engine_uri = next_uri
            _engine_bind_address = next_bind_address
            logger.info("数据库配置已热更新，连接池已重建")
        _env_snapshot = next_snapshot


engine = _build_engine()
_session_factory.configure(bind=engine)
_engine_uri = settings.sqlalchemy_database_uri
_engine_bind_address = str(settings.db_bind_address or "").strip()
_env_snapshot = _env_file_snapshot()


def SessionLocal():
    _refresh_runtime_config_if_needed()
    return _session_factory()


def _ensure_agent_sessions_schema() -> None:
    _refresh_runtime_config_if_needed()
    inspector = inspect(engine)
    if not inspector.has_table("agent_sessions"):
        AgentSession.__table__.create(bind=engine, checkfirst=True)
        return

    columns = {item.get("name") for item in inspector.get_columns("agent_sessions")}
    required_columns = {"history_id", "panel_kind", "codex_thread_id"}
    obsolete_columns = {"snapshot"}
    if required_columns.issubset(columns) and not obsolete_columns.intersection(columns):
        for index in AgentSession.__table__.indexes:
            index.create(bind=engine, checkfirst=True)
        return

    logger.warning("agent_sessions 不是 Codex thread 会话结构，将重建并丢弃旧 AI 历史")
    AgentSession.__table__.drop(bind=engine, checkfirst=True)
    AgentSession.__table__.create(bind=engine, checkfirst=True)


def _ensure_poi_results_schema() -> None:
    _refresh_runtime_config_if_needed()
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

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX ix_poi_results_history_created_id ON poi_results (history_id, created_at, id)"))
    except Exception:
        logger.debug("poi_results history sort index already exists or could not be created", exc_info=True)


def _ensure_analysis_artifacts_schema() -> None:
    _refresh_runtime_config_if_needed()
    inspector = inspect(engine)
    if not inspector.has_table("analysis_artifacts"):
        AnalysisArtifact.__table__.create(bind=engine, checkfirst=True)
        return

    columns = {item.get("name") for item in inspector.get_columns("analysis_artifacts")}
    if "slot_key" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE analysis_artifacts ADD COLUMN slot_key VARCHAR(128) NOT NULL DEFAULT ''"))

    with engine.begin() as conn:
        histories = {
            str(row.id): build_scope_fingerprint(row.result_polygon if isinstance(row.result_polygon, list) else [])
            for row in conn.execute(select(AnalysisHistory.id, AnalysisHistory.result_polygon))
        }
        rows = conn.execute(
            select(
                AnalysisArtifact.id,
                AnalysisArtifact.history_id,
                AnalysisArtifact.artifact_type,
                AnalysisArtifact.params,
                AnalysisArtifact.updated_at,
            ).order_by(AnalysisArtifact.updated_at.desc(), AnalysisArtifact.id.desc())
        ).all()
        keepers: dict[tuple[str, str, str], int] = {}
        duplicate_ids: list[int] = []
        for row in rows:
            try:
                slot_key = build_artifact_slot_key(row.artifact_type, row.params)
            except ValueError:
                slot_key = "year:unknown"
            identity = (str(row.history_id), str(row.artifact_type), slot_key)
            if identity in keepers:
                duplicate_ids.append(int(row.id))
                continue
            keepers[identity] = int(row.id)
            conn.execute(
                update(AnalysisArtifact)
                .where(AnalysisArtifact.id == row.id)
                .values(
                    slot_key=slot_key,
                    scope_fingerprint=histories.get(str(row.history_id), ""),
                )
            )
        if duplicate_ids:
            chunk_size = 500
            for start in range(0, len(duplicate_ids), chunk_size):
                conn.execute(delete(AnalysisArtifact).where(AnalysisArtifact.id.in_(duplicate_ids[start : start + chunk_size])))

    inspector = inspect(engine)
    old_unique_names = {item.get("name") for item in inspector.get_unique_constraints("analysis_artifacts")}
    if "uq_analysis_artifact_identity" in old_unique_names:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE analysis_artifacts DROP INDEX uq_analysis_artifact_identity"))
        except Exception:
            logger.debug("旧 analysis artifact 唯一索引无法删除", exc_info=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX uq_analysis_artifact_slot ON analysis_artifacts (history_id, artifact_type, slot_key)"))
    except Exception:
        logger.debug("analysis artifact 槽位唯一索引已存在或无法创建", exc_info=True)
    for index in AnalysisArtifact.__table__.indexes:
        index.create(bind=engine, checkfirst=True)


def _ensure_spatial_projects_schema() -> None:
    """Create the MCP project tables without requiring DDL privileges on old FKs."""
    _refresh_runtime_config_if_needed()
    for table in (
        SpatialProject.__table__,
        ProjectDataSnapshot.__table__,
        ProjectSpatialUnit.__table__,
    ):
        table.create(bind=engine, checkfirst=True)


def _drop_legacy_analysis_artifact_versions() -> None:
    """Remove obsolete SQL payload storage without introducing FK migrations."""
    _refresh_runtime_config_if_needed()
    if inspect(engine).has_table("analysis_artifact_versions"):
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE analysis_artifact_versions"))


def _drop_legacy_agent_model_profiles() -> None:
    """Remove model selection state superseded by the Codex App Server runtime."""
    _refresh_runtime_config_if_needed()
    if inspect(engine).has_table("agent_model_profiles"):
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE agent_model_profiles"))


def init_db() -> None:
    """
    创建表结构（幂等）。
    """
    _refresh_runtime_config_if_needed()
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        # Older installations can lack permissions for unrelated legacy FKs.
        # Targeted schema ensure functions below still make current capabilities usable.
        logger.exception("全量数据库初始化未完成，继续初始化独立领域表")
    _ensure_agent_sessions_schema()
    _ensure_poi_results_schema()
    _ensure_analysis_artifacts_schema()
    _drop_legacy_analysis_artifact_versions()
    _drop_legacy_agent_model_profiles()
    _ensure_spatial_projects_schema()
    logger.info("数据库初始化完成")
