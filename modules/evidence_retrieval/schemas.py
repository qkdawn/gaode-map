from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class EvidenceIndexRequest(BaseModel):
    document_id: str | None = None


class EvidenceSearchRequest(BaseModel):
    question: str
    top_k: int = Field(default=8, ge=1, le=50)
    document_ids: List[str] = Field(default_factory=list)


class EvidenceSearchResult(BaseModel):
    evidence_id: int
    document_id: str
    text: str
    summary: str
    semantic_type: str
    tags: List[str]
    page_start: int
    page_end: int
    citation: str
    score: float


class EvidenceSearchResponse(BaseModel):
    results: List[EvidenceSearchResult]
