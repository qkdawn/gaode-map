from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.evidence_retrieval.schemas import EvidenceNode, EvidenceSearchRequest, EvidenceSearchResponse, SourceKind, SourceRecord


IndexStatus = Literal["ready", "pending", "building", "failed"]
RetrievalMode = Literal["auto", "keyword", "structure", "vector", "hybrid"]


class SourceIndexManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    source_kind: SourceKind = "unknown"
    native_index_kind: str = "payload_index"
    index_status: IndexStatus = "ready"
    node_count: int = 0
    retrieval_modes: List[str] = Field(default_factory=lambda: ["keyword"])
    read_modes: List[str] = Field(default_factory=lambda: ["node_id"])
    storage_ref: Dict[str, Any] = Field(default_factory=dict)
    model_versions: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: List[str] = Field(default_factory=list)


class EvidenceSearchQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    top_k: int = Field(default=8, ge=1, le=50)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[SourceRecord] = Field(default_factory=list)
    source_kinds: List[SourceKind] = Field(default_factory=list)
    retrieval_mode: RetrievalMode = "auto"
    filters: Dict[str, Any] = Field(default_factory=dict)
    include_diagnostics: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        source_ids = payload.get("source_ids") or payload.get("sourceIds") or []
        if isinstance(source_ids, str):
            source_ids = [source_ids] if source_ids.strip() else []
        payload["source_ids"] = source_ids
        return payload

    @classmethod
    def from_request(cls, request: EvidenceSearchRequest) -> "EvidenceSearchQuery":
        return cls(
            question=request.question,
            top_k=request.top_k,
            source_ids=list(request.source_ids or []),
            sources=list(request.sources or []),
        )


class EvidenceIndexRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    source_id: str
    source_kind: SourceKind = "unknown"
    title: str = ""
    summary: str = ""
    content_ref: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    scores: Dict[str, float] = Field(default_factory=dict)
    node: EvidenceNode

    @property
    def score(self) -> float:
        return float(self.scores.get("total") or self.node.score or 0.0)


class EvidenceTrace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str
    matched: bool = False
    source_id: str = ""
    source_kind: SourceKind = "unknown"
    native_index_kind: str = ""
    adapter: str = ""
    diagnostics: List[str] = Field(default_factory=list)
    manifests: List[SourceIndexManifest] = Field(default_factory=list)


__all__ = [
    "EvidenceIndexRecord",
    "EvidenceNode",
    "EvidenceSearchQuery",
    "EvidenceSearchRequest",
    "EvidenceSearchResponse",
    "EvidenceTrace",
    "SourceIndexManifest",
    "SourceRecord",
]
