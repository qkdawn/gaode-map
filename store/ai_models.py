"""
AI document storage ORM models.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

AiBase = declarative_base()

class Document(AiBase):
    """
    Uploaded document library metadata.
    """
    __tablename__ = "documents"

    id = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False, default="")
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(32), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    history_id = Column(String(64), nullable=True, index=True)
    document_role = Column(String(64), nullable=False, default="reference_document", index=True)
    upload_time = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    status = Column(String(32), nullable=False, default="uploaded", index=True)


class DocumentBlock(AiBase):
    """
    Parsed document content block.
    """
    __tablename__ = "document_blocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_index = Column(Integer, nullable=False, default=0, index=True)
    block_index = Column(Integer, nullable=False, default=0, index=True)
    block_type = Column(String(32), nullable=False, index=True)
    text = Column(Text, nullable=False)
    section_title = Column(String(255), nullable=False, default="")

    __table_args__ = (
        Index("ix_document_blocks_document_order", "document_id", "page_index", "block_index"),
    )


class DocumentIndexNode(AiBase):
    """
    PageIndex-style semantic outline node built from parsed document blocks.
    """
    __tablename__ = "document_index_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(128), nullable=False)
    parent_node_id = Column(String(128), nullable=False, default="", index=True)
    title = Column(String(255), nullable=False)
    level = Column(Integer, nullable=False, default=1, index=True)
    ordinal = Column(Integer, nullable=False, default=0, index=True)
    start_block_index = Column(Integer, nullable=False, default=0)
    end_block_index = Column(Integer, nullable=False, default=0)
    page_start = Column(Integer, nullable=False, default=1, index=True)
    page_end = Column(Integer, nullable=False, default=1)
    summary = Column(Text, nullable=False, default="")
    text = Column(Text, nullable=False, default="")
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("document_id", "node_id", name="uq_document_index_nodes_document_node"),
        Index("ix_document_index_nodes_document_order", "document_id", "ordinal", "id"),
    )


class Job(AiBase):
    """
    AI document pipeline job record.
    """
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), nullable=True, index=True)
    job_type = Column(String(64), nullable=False, index=True)
    target_type = Column(String(64), nullable=False, index=True)
    target_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True, index=True)
    finished_at = Column(DateTime, nullable=True, index=True)
