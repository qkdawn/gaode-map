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
    polygon_id = Column(Integer, ForeignKey("polygon_data.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("map_id", "polygon_id", name="uq_map_polygon"),
    )


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
    history_id = Column(String(64), ForeignKey("analysis_history.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(32), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)
    
    # 完整的 POI 数据列表
    poi_data = Column(JSON, nullable=False)
    
    # 统计摘要 (e.g. {"咖啡": 50, "便利店": 30})
    summary = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("history_id", "source", "year", name="uq_poi_results_history_source_year"),
    )


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
