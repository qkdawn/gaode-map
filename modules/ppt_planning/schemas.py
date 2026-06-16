from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PptSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    type: str = "file"
    title: str
    status: Literal["ready", "pending", "failed"] = "pending"
    selected: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)


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
    status: Literal["ready", "pending", "failed"] = "pending"
    summary: str = ""
    count: int = 0
    meta: Dict[str, Any] = Field(default_factory=dict)


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


class PptSpecRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    source_ids: List[str] = Field(default_factory=list)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    research_enabled: bool = True
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
    research_enabled: bool = True

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
    research_enabled: bool = True

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
    objective: str = ""
    evidence_focus: List[str] = Field(default_factory=list)
    visual_direction: str = ""
    chart_intent: str = ""
    transition_note: str = ""


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
    research_enabled: bool = True

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
    style_guide: str = ""
    evidence_strategy: str = ""
    chart_strategy: str = ""
    slide_roles: List[DeckNarrativeSlideRole] = Field(default_factory=list)
    missing_inputs: List[str] = Field(default_factory=list)
    context_manifest: Dict[str, Any] = Field(default_factory=dict)


class DeckBriefResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["draft", "ready"] = "draft"
    slides: List[DeckSlideBrief] = Field(default_factory=list)
    source_summary: str = ""
    missing_inputs: List[str] = Field(default_factory=list)
    context_manifest: Dict[str, Any] = Field(default_factory=dict)


class DeckBriefSlideRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    spec: Optional[PptSpecResponse] = None
    outline: List[PptOutlineItem] = Field(default_factory=list)
    slides: List[DeckSlideBrief] = Field(default_factory=list)
    target: DeckSlideBrief
    outline_item: Optional[PptOutlineItem] = None
    narrative_plan: Optional[DeckNarrativePlanResponse] = None
    revision_note: str = Field(..., min_length=1)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[PptSource] = Field(default_factory=list)
    current: Dict[str, Any] = Field(default_factory=dict)
    topic: str = ""
    audience: str = "政府评审"
    deck_type: str = "城市更新概念策划"
    page_count: int = Field(15, ge=1, le=80)
    research_enabled: bool = True

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
    visual_artifacts: List[Dict[str, Any]] = Field(default_factory=list)
