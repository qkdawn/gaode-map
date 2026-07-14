from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


DocumentStatus = Literal["uploaded", "parsing", "parsed", "failed"]


class DocumentRole(str, Enum):
    PROJECT_BRIEF = "project_brief"
    DESIGN_VISION = "design_vision"
    REFERENCE_DOCUMENT = "reference_document"


class DocumentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    file_name: str
    file_type: Literal["pdf", "docx"]
    file_path: str
    document_role: DocumentRole
    history_id: str = ""
    upload_time: datetime
    status: DocumentStatus

    @field_validator("history_id", mode="before")
    @classmethod
    def normalize_history_id(cls, value: object) -> str:
        return str(value or "").strip()


class DocumentUploadResponse(DocumentRecord):
    pass


class DocumentBlockRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    document_id: str
    page_index: int
    block_index: int
    block_type: Literal["title", "paragraph", "table"]
    text: str
    section_title: str = ""


class DocumentBlockResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    pageIndex: int
    blockIndex: int
    blockType: Literal["title", "paragraph", "table"]
    text: str
    sectionTitle: str = ""


class DocumentBlocksResponse(BaseModel):
    document: DocumentRecord
    status: DocumentStatus
    blocks: List[DocumentBlockResponse]


class DocumentIndexNodeRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: str
    node_id: str
    parent_node_id: str = ""
    title: str
    level: int
    ordinal: int
    start_block_index: int
    end_block_index: int
    page_start: int
    page_end: int
    summary: str = ""
    text: str = ""
    meta: dict = Field(default_factory=dict)
    created_at: datetime


class DocumentIndexResponse(BaseModel):
    document_id: str
    nodes: List[DocumentIndexNodeRecord]


class PageIndexContentResponse(BaseModel):
    document_id: str
    pages: str
    items: List[dict] = Field(default_factory=list)
