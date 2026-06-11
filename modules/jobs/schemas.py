from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


JobType = Literal[
    "parse_document",
    "build_evidence",
    "build_embedding",
    "profile_dataset",
    "build_package",
    "generate_ppt",
]
JobStatus = Literal["pending", "running", "succeeded", "failed"]


class JobRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None = None
    job_type: JobType
    target_type: str
    target_id: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    message: str = ""
    error: str = ""
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
