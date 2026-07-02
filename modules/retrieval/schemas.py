from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


RetrievalKind = Literal["analysis", "report"]
AttachmentStatus = Literal["uploaded", "processing", "ready", "failed"]


class KnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    kind: RetrievalKind
    domain: str
    title: str
    content: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    source_artifacts: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    evidence_level: str = "derived_metric"


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    title: str
    domain: str
    snippet: str
    evidence_level: str
    score: float


class AttachmentRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attachment_id: str
    conversation_id: str
    history_id: str = ""
    filename: str
    mime_type: str = ""
    size_bytes: int = 0
    status: AttachmentStatus = "uploaded"
    summary: str = ""
    warnings: List[str] = Field(default_factory=list)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    file_path: str = ""
    working_dir: str = ""
    output_dir: str = ""


class AttachmentSearchHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    attachment_id: str
    filename: str
    mime_type: str = ""
    snippet: str
    evidence_level: str = "uploaded_attachment"
    score: float = 1.0
    locator: str = ""
    warnings: List[str] = Field(default_factory=list)


class AttachmentChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    attachment_id: str
    filename: str
    title: str
    content: str
    locator: str = ""
    evidence_level: str = "uploaded_attachment"
    warnings: List[str] = Field(default_factory=list)
    source_artifacts: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
