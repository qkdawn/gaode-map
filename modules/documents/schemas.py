from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentStatus = Literal["uploaded", "parsing", "parsed", "failed"]


class DocumentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    file_name: str
    file_type: Literal["pdf", "docx"]
    file_path: str
    document_role: str = "evidence_document"
    upload_time: datetime
    status: DocumentStatus


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


class EvidenceChunkRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: str
    document_role: str
    text: str
    summary: str = ""
    page_start: int
    page_end: int
    section_path: List[str] = Field(default_factory=list)
    chunk_type: Literal["paragraph", "table", "title", "figure", "caption"]
    semantic_type: str = "background_statement"
    tags: List[str] = Field(default_factory=list)
    citation: str
    created_at: datetime


class EvidenceChunksResponse(BaseModel):
    document_id: str
    chunks: List[EvidenceChunkRecord]
