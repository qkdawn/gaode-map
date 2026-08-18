from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ReaderRunStatus = Literal["准备中", "分析中", "已完成", "需要处理", "已停止"]
ReaderChapterStatus = Literal["等待分析", "正在分析", "已完成", "需要处理", "已停止"]


class SpatialStrategyRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_question: str = Field(min_length=1, max_length=12000)
    history_id: str = ""
    project_types: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    deliver_to_feishu: bool = False

    @field_validator("project_question", "history_id", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("project_types", "geography", mode="before")
    @classmethod
    def normalize_string_list(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip()))


class SpatialStrategyRunAccepted(BaseModel):
    accepted: Literal[True]
    run_id: str
    status: Literal["准备中"]
    message: str
    status_url: str


class SpatialStrategyProgress(BaseModel):
    completed_chapters: int = Field(ge=0, le=32)
    total_chapters: int = Field(ge=1, le=32)


class SpatialStrategyCurrentChapter(BaseModel):
    number: int = Field(ge=1, le=32)
    title: str


class SpatialStrategyReaderChapter(BaseModel):
    number: int = Field(ge=1, le=32)
    title: str
    status: ReaderChapterStatus
    content: str = ""
    updated_at: datetime | None = None


class SpatialStrategyReaderReport(BaseModel):
    title: str = "空间分析报告"
    summary: str = ""
    markdown: str = ""
    evidence_labels: list[str] = Field(default_factory=list)
    visual_assets: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime | None = None


class SpatialStrategyRunDetail(BaseModel):
    run_id: str
    status: ReaderRunStatus
    message: str
    created_at: datetime
    updated_at: datetime
    progress: SpatialStrategyProgress
    current_chapter: SpatialStrategyCurrentChapter | None = None
    chapters: list[SpatialStrategyReaderChapter] = Field(default_factory=list)
    report: SpatialStrategyReaderReport | None = None


class SpatialStrategyReportFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    history_id: str = ""
    project_question: str = Field(min_length=1, max_length=12000)
    project_context: dict[str, Any] = Field(default_factory=dict)
    decision_state: dict[str, Any] = Field(default_factory=dict)
    visual_assets: list[dict[str, Any]] = Field(default_factory=list)
    editorial_narrative: str = Field(min_length=1, max_length=50000)

    @field_validator("history_id", "project_question", "editorial_narrative", mode="before")
    @classmethod
    def normalize_report_text(cls, value: object) -> str:
        return str(value or "").strip()


class SpatialStrategyReportDeliveryRequest(BaseModel):
    run_id: UUID
    title: str = Field(min_length=1, max_length=500)
    summary: str = ""
    markdown: str = Field(min_length=1)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    decision_state: dict[str, Any] = Field(default_factory=dict)
    visual_assets: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("title", "summary", "markdown", mode="before")
    @classmethod
    def normalize_delivery_text(cls, value: object) -> str:
        return str(value or "").strip()


class SpatialStrategyProjectContextRequest(BaseModel):
    history_id: str = ""
    tenant_id: str = "default"

    @field_validator("history_id", "tenant_id", mode="before")
    @classmethod
    def normalize_context_text(cls, value: object) -> str:
        return str(value or "").strip()


class SpatialStrategyProjectDataRequest(BaseModel):
    history_id: str = ""
    step_key: str = Field(min_length=1, max_length=96)
    project_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("history_id", "step_key", mode="before")
    @classmethod
    def normalize_project_data_text(cls, value: object) -> str:
        return str(value or "").strip()


class SpatialStrategyAgentToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: str = Field(min_length=1, max_length=200)
    tool_name: Literal[
        "analyze_spatial_evidence",
        "read_project_document",
        "search_literature_evidence",
        "search_public_web",
        "fetch_public_web_page",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("history_id", mode="before")
    @classmethod
    def normalize_agent_tool_history(cls, value: object) -> str:
        return str(value or "").strip()


class SpatialStrategyVisualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    history_id: str = ""
    project_context: dict[str, Any] = Field(default_factory=dict)
    visual_plan: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeBaseIngestRequest(BaseModel):
    document_id: str = Field(min_length=1)
    visibility: Literal["public", "restricted"] = "restricted"
    source_type: Literal[
        "knowledge_base",
        "policy",
        "planning_guidance",
        "case_study",
        "statistics",
        "research",
    ] = "knowledge_base"
    source_url: str = ""
    decision_steps: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_id", "source_type", "source_url", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("decision_steps", "project_types", "geography", mode="before")
    @classmethod
    def normalize_string_list(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip()))


class KnowledgeBaseIngestAccepted(BaseModel):
    accepted: Literal[True]
    status: Literal["published"]
    document_id: str
    tenant_id: str
    result: dict[str, Any] = Field(default_factory=dict)
