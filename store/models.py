"""
ORM 模型定义。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MapData(Base):
    __tablename__ = "map_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data = Column(JSON, nullable=False)
    center = Column(JSON, nullable=False)
    center_fingerprint = Column(String(512), nullable=False, index=True)
    search_type = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class PolygonData(Base):
    __tablename__ = "polygon_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    coordinates = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MapPolygonLink(Base):
    __tablename__ = "map_polygon_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    map_id = Column(Integer, ForeignKey("map_data.id"), nullable=False, index=True)
    polygon_id = Column(
        Integer, ForeignKey("polygon_data.id"), nullable=False, index=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("map_id", "polygon_id", name="uq_map_polygon"),)


class AnalysisHistory(Base):
    """
    空间分析历史记录
    """

    __tablename__ = "analysis_history"

    id = Column(String(64), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # 存储分析参数 (中心点, 时长, 出行方式)
    params = Column(JSON, nullable=False)

    # 存储生成的等时圈多边形 (GeoJSON/Coordinates)
    result_polygon = Column(JSON, nullable=True)

    # 简短描述 (e.g. "人民广场 - 15分钟步行")
    description = Column(String(255), nullable=True)


class PoiResult(Base):
    """
    POI 抓取结果
    """

    __tablename__ = "poi_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    history_id = Column(
        String(64),
        ForeignKey("analysis_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(32), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)

    # 完整的 POI 数据列表
    poi_data = Column(JSON, nullable=False)

    # 统计摘要 (e.g. {"咖啡": 50, "便利店": 30})
    summary = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "history_id", "source", "year", name="uq_poi_results_history_source_year"
        ),
        Index("ix_poi_results_history_created_id", "history_id", "created_at", "id"),
    )


class AnalysisArtifact(Base):
    """
    可复用分析证据单元。
    """

    __tablename__ = "analysis_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    history_id = Column(
        String(64),
        ForeignKey("analysis_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type = Column(String(64), nullable=False, index=True)
    params_hash = Column(String(64), nullable=False, index=True)
    params = Column(JSON, nullable=False, default=dict)
    scope_fingerprint = Column(String(128), nullable=False, default="", index=True)
    data_version = Column(String(32), nullable=False, default="v1", index=True)
    payload = Column(JSON, nullable=False, default=dict)
    summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "history_id",
            "artifact_type",
            "params_hash",
            "scope_fingerprint",
            "data_version",
            name="uq_analysis_artifact_identity",
        ),
        Index("ix_analysis_artifacts_history_type", "history_id", "artifact_type"),
        Index(
            "ix_analysis_artifacts_history_updated_id", "history_id", "updated_at", "id"
        ),
    )


class CapabilityRunRecord(Base):
    """Immutable capability execution manifest bound to one analysis history."""

    __tablename__ = "capability_runs"

    run_id = Column(String(96), primary_key=True)
    history_id = Column(String(64), nullable=False, index=True)
    capability_id = Column(String(96), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True)
    current_stage = Column(String(96), nullable=False, default="")
    manifest = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    persisted_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index(
            "ix_capability_runs_history_capability_persisted",
            "history_id",
            "capability_id",
            "persisted_at",
        ),
    )


class CapabilityArtifactVersion(Base):
    """Run-scoped immutable artifact payload and lineage snapshot."""

    __tablename__ = "capability_artifact_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String(96),
        ForeignKey("capability_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    history_id = Column(String(64), nullable=False, index=True)
    artifact_id = Column(String(160), nullable=False, index=True)
    direction = Column(String(16), nullable=False, index=True)
    artifact_type = Column(String(32), nullable=False, index=True)
    version = Column(String(128), nullable=False)
    title = Column(String(255), nullable=False, default="")
    filename = Column(String(512), nullable=False, default="")
    source_run_id = Column(String(96), nullable=False, default="", index=True)
    source_artifact_refs = Column(JSON, nullable=False, default=list)
    evidence_refs = Column(JSON, nullable=False, default=list)
    content_digest = Column(String(80), nullable=False, default="", index=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "direction",
            "artifact_id",
            name="uq_capability_artifact_run_direction_id",
        ),
        Index(
            "ix_capability_artifacts_history_artifact_created",
            "history_id",
            "artifact_id",
            "created_at",
        ),
    )


class AgentModelProfile(Base):
    __tablename__ = "agent_model_profiles"

    id = Column(String(64), primary_key=True)
    display_name = Column(String(120), nullable=False)
    provider = Column(String(32), nullable=False)
    base_url = Column(String(512), nullable=False)
    model_name = Column(String(160), nullable=False)
    api_key_ciphertext = Column(Text, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    is_default = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class AgentSession(Base):
    """
    AI 面板历史记录
    """

    __tablename__ = "agent_sessions"

    id = Column(String(128), primary_key=True)
    title = Column(String(255), nullable=False, default="")
    preview = Column(Text, nullable=False, default="")
    status = Column(String(64), nullable=False, default="idle")
    history_id = Column(String(64), nullable=False, index=True)
    panel_kind = Column(String(64), nullable=False, index=True)
    is_pinned = Column(Boolean, nullable=False, default=False, index=True)
    pinned_at = Column(DateTime, nullable=True)
    snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_agent_sessions_history_panel", "history_id", "panel_kind"),
    )
