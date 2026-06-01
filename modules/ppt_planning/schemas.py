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


class PptSpecRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    source_ids: List[str] = Field(default_factory=list)
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


class PptSpecResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    goal: str
    audience: str
    deck_type: str
    page_count: int
    outline: List[str] = Field(default_factory=list)
    source_summary: str = ""
    missing_inputs: List[str] = Field(default_factory=list)


class DeckSlideBrief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    title: str
    purpose: str = ""
    key_message: str = ""
    visual_plan: str = ""
    required_sources: List[str] = Field(default_factory=list)
    speaker_notes: str = ""


class DeckBriefRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    area_id: str = ""
    spec: Optional[PptSpecResponse] = None
    source_ids: List[str] = Field(default_factory=list)
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


class DeckBriefResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["draft", "ready"] = "draft"
    slides: List[DeckSlideBrief] = Field(default_factory=list)
    source_summary: str = ""
    missing_inputs: List[str] = Field(default_factory=list)
