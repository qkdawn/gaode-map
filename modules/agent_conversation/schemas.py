from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ConversationStatus = Literal["idle", "running", "answered", "failed"]


class ConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1, max_length=128)
    history_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=20_000)
    panel_kind: str = Field(default="analysis", min_length=1, max_length=64)
    map_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conversation_id", "history_id", "message", "panel_kind")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: Literal["user", "assistant"]
    content: str


class ConversationSessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = ""
    preview: str = ""
    status: ConversationStatus = "idle"
    history_id: str
    panel_kind: str
    is_pinned: bool = False
    created_at: str = ""
    updated_at: str = ""
    pinned_at: str | None = None


class ConversationSessionDetail(ConversationSessionSummary):
    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationSessionMetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=60)
    is_pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized
