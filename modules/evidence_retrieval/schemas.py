from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceKind = Literal["system", "document", "image", "web", "database", "package", "unknown"]
SourceStatus = Literal["ready", "pending", "generating", "failed"]
EvidenceKind = Literal[
    "analysis_summary",
    "spatial_metric",
    "dataset_record",
    "document_excerpt",
    "image_observation",
    "web_excerpt",
    "database_record",
    "package_summary",
    "package_item",
    "spatial_carrier",
]


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source_id: str = Field(default="", alias="id")
    title: str = ""
    source_kind: SourceKind = "unknown"
    status: SourceStatus = "pending"
    summary: str = ""
    evidence_count: int = 0
    locator_summary: str = ""
    availability: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_source_record(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        source_id = str(payload.get("source_id") or payload.get("id") or "").strip()
        source_kind = str(payload.get("source_kind") or "").strip()
        if not source_kind:
            if source_id.startswith("document:"):
                source_kind = "document"
            elif source_id.startswith("image:"):
                source_kind = "image"
            elif source_id.startswith("web:"):
                source_kind = "web"
            elif source_id.startswith("database:"):
                source_kind = "database"
            elif source_id.startswith("package:"):
                source_kind = "package"
            elif source_id.startswith("current:"):
                source_kind = "system"
            else:
                source_kind = "unknown"
        evidence_count = payload.get("evidence_count")
        if evidence_count is None:
            transport = meta.get("transport") if isinstance(meta.get("transport"), dict) else {}
            ai_payload = meta.get("aiPayload") or meta.get("ai_payload")
            ai_payload = ai_payload if isinstance(ai_payload, dict) else {}
            counts = ai_payload.get("counts") if isinstance(ai_payload.get("counts"), dict) else {}
            evidence_nodes = ai_payload.get("evidence_nodes") if isinstance(ai_payload.get("evidence_nodes"), list) else []
            evidence_count = (
                transport.get("evidence_count")
                or len(evidence_nodes)
                or counts.get("evidence")
                or payload.get("count")
                or 0
            )
        summary = str(payload.get("summary") or meta.get("label") or "").strip()
        payload.update(
            {
                "id": source_id,
                "source_id": source_id,
                "source_kind": source_kind,
                "summary": summary,
                "evidence_count": int(evidence_count or 0),
                "locator_summary": str(payload.get("locator_summary") or "").strip(),
                "availability": str(payload.get("availability") or ("available" if payload.get("status") == "ready" else "")).strip(),
            }
        )
        return payload


class EvidenceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: EvidenceKind
    run_id: str = ""
    source_ids: List[str] = Field(min_length=1)
    metric_ids: List[str] = Field(default_factory=list)
    title: str = ""
    summary: str = ""
    content: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    time_scope: Dict[str, Any] = Field(default_factory=dict)
    spatial_scope: Dict[str, Any] = Field(default_factory=dict)
    method: str = ""
    quality_flags: List[Dict[str, Any]] = Field(default_factory=list)
    locator: str | Dict[str, Any] = ""
    citation: str = ""

    @model_validator(mode="after")
    def _require_readable_payload(self):
        if not self.content.strip() and not self.data:
            raise ValueError("EvidenceNode requires content or data")
        return self


class EvidenceSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: EvidenceNode
    score: float = 0.0


class EvidenceSearchRequest(BaseModel):
    question: str
    top_k: int = Field(default=8, ge=1, le=50)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[SourceRecord] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        source_ids = payload.get("source_ids") or []
        if isinstance(source_ids, str):
            source_ids = [source_ids] if source_ids.strip() else []
        payload["source_ids"] = source_ids
        return payload


class EvidenceSearchResponse(BaseModel):
    hits: List[EvidenceSearchHit] = Field(default_factory=list)
