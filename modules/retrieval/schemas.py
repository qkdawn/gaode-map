from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


RetrievalKind = Literal["analysis", "report"]


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
