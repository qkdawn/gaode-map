from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _canonical_source_kind(raw_kind: Any = "", source_id: Any = "", fallback: str = "") -> str:
    allowed = {"system", "document", "image", "web", "database", "package"}
    text = str(raw_kind or "").strip()
    source = str(source_id or "").strip()
    if text in allowed:
        return text
    if source.startswith("current:"):
        return "system"
    if ":" in source:
        prefix = source.split(":", 1)[0]
        return prefix if prefix in allowed else "unknown"
    fallback_text = str(fallback or "").strip()
    return fallback_text if fallback_text in allowed else "unknown"


class PptSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    type: str = "source"
    title: str
    status: Literal["ready", "pending", "generating", "failed"] = "pending"
    selected: bool = False
    source_kind: str = ""
    summary: str = ""
    evidence_count: int = 0
    locator_summary: str = ""
    availability: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_source_fields(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        source_id = str(payload.get("id") or payload.get("source_id") or payload.get("sourceId") or "").strip()
        source_kind = str(payload.get("source_kind") or payload.get("sourceKind") or meta.get("sourceKind") or "").strip()
        source_kind = _canonical_source_kind(source_kind, source_id, str(payload.get("type") or "source"))
        ai_payload = meta.get("aiPayload") or meta.get("ai_payload")
        ai_payload = ai_payload if isinstance(ai_payload, dict) else {}
        counts = ai_payload.get("counts") if isinstance(ai_payload.get("counts"), dict) else {}
        evidence_nodes = (
            ai_payload.get("evidence_nodes")
            if isinstance(ai_payload.get("evidence_nodes"), list)
            else ai_payload.get("evidenceNodes")
            if isinstance(ai_payload.get("evidenceNodes"), list)
            else []
        )
        transport = meta.get("transport") if isinstance(meta.get("transport"), dict) else {}
        evidence_count = (
            payload.get("evidence_count")
            or payload.get("evidenceCount")
            or transport.get("evidence_count")
            or transport.get("evidenceCount")
            or len(evidence_nodes)
            or counts.get("evidence")
            or 0
        )
        summary = str(payload.get("summary") or meta.get("label") or "").strip()
        payload.update({
            "source_kind": source_kind,
            "summary": summary,
            "evidence_count": int(evidence_count or 0),
            "locator_summary": str(payload.get("locator_summary") or payload.get("locatorSummary") or "").strip(),
            "availability": str(payload.get("availability") or ("available" if payload.get("status") == "ready" else "")).strip(),
        })
        return payload


class PptSourceGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    title: str
    emoji: str = ""
    source_ids: List[str] = Field(default_factory=list)
    collapsed: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_group_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class PptSourceGroupClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)
    previous_groups: List[PptSourceGroup] = Field(default_factory=list)


class PptSourceGroupClassifyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    groups: List[PptSourceGroup] = Field(default_factory=list)


class PptDataSourceSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str = "data"
    title: str
    status: Literal["ready", "pending", "generating", "failed"] = "pending"
    summary: str = ""
    count: int = 0
    source_kind: str = ""
    evidence_count: int = 0
    locator_summary: str = ""
    availability: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_summary_fields(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        source_id = str(payload.get("id") or payload.get("source_id") or payload.get("sourceId") or "").strip()
        source_kind = str(payload.get("source_kind") or payload.get("sourceKind") or meta.get("sourceKind") or "").strip()
        source_kind = _canonical_source_kind(source_kind, source_id, str(payload.get("type") or "data"))
        evidence_count = payload.get("evidence_count") or payload.get("evidenceCount") or payload.get("count") or 0
        payload.update({
            "source_kind": source_kind,
            "evidence_count": int(evidence_count or 0),
            "locator_summary": str(payload.get("locator_summary") or payload.get("locatorSummary") or "").strip(),
            "availability": str(payload.get("availability") or ("available" if payload.get("status") == "ready" else "")).strip(),
        })
        return payload


class PptPoiQueryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class PptPoiPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    location: List[float] = Field(default_factory=list)
    address: str = ""
    category: str = ""
    subcategory: str = ""
    typecode: str = ""
    year: Optional[int] = None
    source: str = ""
    distance_m: Optional[float] = None


class PptPoiQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    coordinate_system: str = "WGS84"
    items: List[PptPoiPoint] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    available_years: List[int] = Field(default_factory=list)
    selected_year: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)


class PptPoiNearbyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    center: List[float] = Field(default_factory=list)
    center_coord_type: str = "wgs84"
    radius_m: float = Field(1000, gt=0, le=50000)
    filters: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(50, ge=1, le=200)


class PptEvidenceQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    purpose: str = ""
    query_terms: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    subcategories: List[str] = Field(default_factory=list)
    typecodes: List[str] = Field(default_factory=list)
    nearby_required: bool = False
    radius_m: Optional[float] = None
    target_count: int = Field(3, ge=1, le=50)


class PptEvidenceIntentGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    purpose: str = ""
    query_terms: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    subcategories: List[str] = Field(default_factory=list)
    typecodes: List[str] = Field(default_factory=list)
    nearby_required: bool = False
    radius_m: Optional[float] = None
    target_count: int = Field(6, ge=1, le=50)
    queries: List[PptEvidenceQuery] = Field(default_factory=list)


class PptEvidenceIntentPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query_terms: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    subcategories: List[str] = Field(default_factory=list)
    typecodes: List[str] = Field(default_factory=list)
    nearby_required: bool = False
    radius_m: Optional[float] = None
    package_title: str = "POI 资料包"
    selection_reason: str = ""
    evidence_groups: List[PptEvidenceIntentGroup] = Field(default_factory=list)


class PptDataPackageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    source_ids: List[str] = Field(default_factory=list)
    package_mode: str = "evidence"
    intent: str = ""
    package_version: str = ""
    query: str = ""
    limit: int = Field(50, ge=1, le=200)
    filters: Dict[str, Any] = Field(default_factory=dict)
    center: List[float] = Field(default_factory=list)
    center_coord_type: str = "wgs84"
    radius_m: Optional[float] = Field(default=None, gt=0, le=50000)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_package_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class PptDataPackageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: PptSource
    summary: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PptWebSourceLocationDefaultRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""


class PptWebSourceLocationDefaultResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    region_name: str = "当前分析区域"
    administrative_area: str = ""
    center: List[float] = Field(default_factory=list)
    center_coord_type: str = "wgs84"
    confidence: str = "fallback"
    warnings: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


class PptWebSourceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    region_name: str = ""
    administrative_area: str = ""
    topic: str = ""
    intent: str = ""
    categories: List[str] = Field(default_factory=list)
    source_modes: List[str] = Field(default_factory=lambda: ["trusted", "market"])
    urls: List[str] = Field(default_factory=list)
    limit: int = Field(8, ge=1, le=20)


class PptWebSourceCommitRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    preview: Dict[str, Any] = Field(default_factory=dict)


class PptSpecRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    source_ids: List[str] = Field(default_factory=list)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    web_sources_enabled: bool = True
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class PptOutlineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    page_no: int = Field(..., ge=1)
    theme: str
    purpose: str = ""


class PptSpecResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    goal: str
    audience: str
    deck_type: str
    page_count: int
    outline: List[PptOutlineItem] = Field(default_factory=list)
    source_summary: str = ""
    missing_inputs: List[str] = Field(default_factory=list)
    context_manifest: Dict[str, Any] = Field(default_factory=dict)


class PptOutlineSectionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    spec: Optional[PptSpecResponse] = None
    outline: List[PptOutlineItem] = Field(default_factory=list)
    target: PptOutlineItem
    revision_note: str = Field(..., min_length=1)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    web_sources_enabled: bool = True

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class DeckSlideBrief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    title: str
    purpose: str = ""
    key_message: str = ""
    insight: str = ""
    evidence_explanation: List[str] = Field(default_factory=list)
    visual_plan: str = ""
    required_sources: List[str] = Field(default_factory=list)
    metric_claims: List[Dict[str, Any]] = Field(default_factory=list)
    metric_gaps: List[Dict[str, Any]] = Field(default_factory=list)
    visual_specs: List[Dict[str, Any]] = Field(default_factory=list)
    visual_artifacts: List[Dict[str, Any]] = Field(default_factory=list)


class DeckBriefRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    spec: Optional[PptSpecResponse] = None
    source_ids: List[str] = Field(default_factory=list)
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    web_sources_enabled: bool = True

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class DeckNarrativeSlideRole(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_no: int = Field(..., ge=1)
    role: str = ""
    job: str = ""
    evidence_bucket: str = ""
    visual_family: str = ""
    transition_note: str = ""


class DeckNarrativeChapter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    page_range: str = ""
    job: str = ""
    output: str = ""


class DeckNarrativeEvidenceBucket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    label: str = ""
    allowed_sources: List[str] = Field(default_factory=list)


class DeckNarrativeVisualStrategy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spatial_first: bool = False
    numeric_charts_require_data: bool = True
    diagram_for_strategy_pages: bool = True
    no_fallback_bar: bool = True


class DeckNarrativePlanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    spec: Optional[PptSpecResponse] = None
    outline: List[PptOutlineItem] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    web_sources_enabled: bool = True

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class DeckNarrativePlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    storyline: str = ""
    chapters: List[DeckNarrativeChapter] = Field(default_factory=list)
    evidence_buckets: List[DeckNarrativeEvidenceBucket] = Field(default_factory=list)
    slide_roles: List[DeckNarrativeSlideRole] = Field(default_factory=list)
    visual_rules: DeckNarrativeVisualStrategy = Field(default_factory=DeckNarrativeVisualStrategy)
    missing_inputs: List[str] = Field(default_factory=list)


class DeckBriefResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["draft", "ready"] = "draft"
    slides: List[DeckSlideBrief] = Field(default_factory=list)
    source_summary: str = ""
    missing_inputs: List[str] = Field(default_factory=list)
    context_manifest: Dict[str, Any] = Field(default_factory=dict)


class DeckBriefJobCreateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: Literal["queued", "running", "validating", "completed", "failed"] = "queued"


class DeckBriefJobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: Literal["queued", "running", "validating", "completed", "failed"] = "queued"
    progress: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[DeckBriefResponse] = None
    error: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class DeckBriefSlideRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    context_id: str = ""
    page_no: int = Field(0, ge=0)
    spec: Optional[PptSpecResponse] = None
    outline: List[PptOutlineItem] = Field(default_factory=list)
    slides: List[DeckSlideBrief] = Field(default_factory=list)
    target: DeckSlideBrief
    outline_item: Optional[PptOutlineItem] = None
    narrative_plan: Optional[DeckNarrativePlanResponse] = None
    previous_slide_summary: Dict[str, Any] = Field(default_factory=dict)
    next_outline_summary: Dict[str, Any] = Field(default_factory=dict)
    deck_progress_summary: Dict[str, Any] = Field(default_factory=dict)
    revision_note: str = Field(..., min_length=1)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    web_sources_enabled: bool = True

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class PptVisualArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slide_index: int = Field(..., ge=1)
    visual_specs: List[Dict[str, Any]] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    existing_assets: List[Dict[str, Any]] = Field(default_factory=list)
    metric_context: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class PptVisualArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slide_index: int
    visual_specs: List[Dict[str, Any]] = Field(default_factory=list)
    visual_artifacts: List[Dict[str, Any]] = Field(default_factory=list)
