from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Literal

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


class DocumentRagSourceRequest(BaseModel):
    tenant_id: str = "default"
    visibility: Literal["public", "restricted"] = "restricted"
    access_groups: List[str] = Field(default_factory=list)
    source_type: str = "project_document"
    source_url: str = ""
    decision_steps: List[str] = Field(default_factory=list)
    project_types: List[str] = Field(default_factory=list)
    geography: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "tenant_id",
        "source_type",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("value_must_not_be_empty")
        return normalized

    @field_validator("source_url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("access_groups", "decision_steps", "project_types", "geography", mode="before")
    @classmethod
    def normalize_string_list(cls, value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        result: List[str] = []
        seen = set()
        for item in value:
            normalized = str(item or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


class DocumentRagChunk(BaseModel):
    ordinal: int
    page_start: int
    page_end: int
    section: str = ""
    content: str
    search_terms: str
    decision_steps: List[str] = Field(default_factory=list)
    project_types: List[str] = Field(default_factory=list)
    geography: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRagSource(BaseModel):
    source_key: str
    title: str
    source_type: str
    source_url: str = ""
    object_key: str
    version: int = 1
    checksum: str
    tenant_id: str
    visibility: Literal["public", "restricted"]
    access_groups: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: List[DocumentRagChunk]


class DocumentRagSourceResponse(BaseModel):
    document: DocumentRagSource
