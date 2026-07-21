from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def public_scope_summary(value: Any) -> dict[str, Any]:
    """Return source metadata without raw geometry or coordinate payloads."""
    private = {"geometry", "coordinates", "polygon", "polygon_wgs84", "features"}

    def scrub(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                str(key): scrub(child)
                for key, child in item.items()
                if str(key).lower() not in private
            }
        if isinstance(item, list):
            return [scrub(child) for child in item]
        return deepcopy(item)

    return scrub(value) if isinstance(value, dict) else {}


class SourceIndexItem(BaseModel):
    """One reusable source, existing result, metric result, or visual asset."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    resource_type: Literal[
        "project_material",
        "spatial_scope",
        "dataset",
        "history_result",
        "analysis_result",
        "asset",
    ]
    title: str
    status: Literal["available", "unavailable", "failed"] = "available"
    summary: str = ""
    source_ids: list[str] = Field(default_factory=list)
    spatial_scope: dict[str, Any] = Field(default_factory=dict)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_item(self):
        self.resource_id = _text(self.resource_id, "resource_id")
        self.title = _text(self.title, "title")
        return self


class SourceIndex(BaseModel):
    """In-memory evidence directory used by spatial metric and visual tools."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    generated_at: str = Field(default_factory=utc_now)
    project_name: str = ""
    items: list[SourceIndexItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_index(self):
        ids = [item.resource_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("source_index_resource_ids_must_be_unique")
        return self

    def resource_ids(self) -> set[str]:
        return {item.resource_id for item in self.items}

    def result(self, result_id: str) -> SourceIndexItem | None:
        return next(
            (
                item
                for item in self.items
                if item.resource_id == result_id
                and item.resource_type == "analysis_result"
            ),
            None,
        )

    def upsert(self, item: SourceIndexItem) -> SourceIndexItem:
        for index, current in enumerate(self.items):
            if current.resource_id == item.resource_id:
                self.items[index] = item
                return item
        self.items.append(item)
        return item


def build_source_index(
    *,
    run_id: str,
    project_documents: dict[str, Any],
    source_versions: list[dict[str, Any]],
    data_preview: dict[str, Any],
) -> SourceIndex:
    """Build the lightweight evidence directory used by Skill-facing tools."""
    items: list[SourceIndexItem] = []
    documents = project_documents.get("documents")
    documents = documents if isinstance(documents, list) else []
    for index, document in enumerate(documents):
        payload = deepcopy(document) if isinstance(document, dict) else {}
        identifier = str(
            payload.get("source_id")
            or payload.get("id")
            or f"document:{index + 1}"
        )
        extracts = payload.get("extracts")
        items.append(
            SourceIndexItem(
                resource_id=identifier,
                resource_type="project_material",
                title=str(payload.get("title") or payload.get("name") or identifier),
                status="available",
                summary=str(payload.get("summary") or payload.get("content") or "")[:1000],
                source_ids=[identifier],
                payload={"extract_count": len(extracts) if isinstance(extracts, list) else 0},
            )
        )
    if not items:
        items.append(
            SourceIndexItem(
                resource_id="project:brief",
                resource_type="project_material",
                title="项目摘要",
                status="available",
                summary=str(project_documents.get("project_name") or "项目材料尚待补充"),
                source_ids=["project:brief"],
            )
        )
    for source in source_versions:
        value = deepcopy(source) if isinstance(source, dict) else {}
        identifier = str(value.get("source_id") or value.get("id") or "").strip()
        if not identifier:
            continue
        record_count = value.get("record_count")
        is_raster = str(value.get("data_kind") or "") == "raster"
        summary = (
            "栅格数据已发现；将在分析范围裁剪后检查有效像元与覆盖。"
            if is_raster
            else f"记录数：{record_count if record_count is not None else '未知'}"
        )
        items.append(
            SourceIndexItem(
                resource_id=f"dataset:{identifier}",
                resource_type="dataset",
                title=identifier,
                status="available",
                summary=summary,
                source_ids=[identifier],
                time_scope={"year": value.get("year")} if value.get("year") else {},
                payload={
                    "version": value.get("sha256") or value.get("version") or "",
                    "data_kind": value.get("data_kind") or "record",
                    "health_hint": value.get("health_hint") or "",
                },
            )
        )
    scope = data_preview.get("scope") or data_preview.get("spatial_scope")
    scope = deepcopy(scope) if isinstance(scope, dict) else {}
    if scope:
        items.append(
            SourceIndexItem(
                resource_id="scope:analysis",
                resource_type="spatial_scope",
                title="项目空间范围",
                summary="当前分析历史绑定的分析范围。",
                source_ids=["scope:analysis"],
                spatial_scope=scope,
            )
        )
    for key, value in sorted(data_preview.items()):
        if key in {"scope", "spatial_scope", "source_versions"} or value in (None, {}, []):
            continue
        items.append(
            SourceIndexItem(
                resource_id=f"history:{key}",
                resource_type="history_result",
                title=f"历史分析结果：{key}",
                summary="当前历史快照中可供本轮项目判断复用的结果摘要。",
                source_ids=[f"history:{key}"],
                payload={"preview": deepcopy(value)},
            )
        )
    return SourceIndex(
        run_id=run_id,
        project_name=str(project_documents.get("project_name") or ""),
        items=items,
    )
