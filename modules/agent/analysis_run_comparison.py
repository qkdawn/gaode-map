from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .analysis_runs import (
    AnalysisArtifactRef,
    AnalysisArtifactSnapshot,
    AnalysisRunV3,
    AnalysisRunV3Detail,
    content_digest,
)

ChangeType = Literal["added", "removed", "changed"]


class AnalysisRunComparisonRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    current_stage: str = ""
    created_at: str = ""
    completed_at: str = ""
    stale_input_artifact_ids: list[str] = Field(default_factory=list)


class AnalysisRunFieldChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    change_type: ChangeType = "changed"
    before: Any = None
    after: Any = None


class AnalysisRunStageChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    title: str
    change_type: ChangeType
    before_status: str = ""
    after_status: str = ""
    before_summary: str = ""
    after_summary: str = ""
    diagnostics_added: list[str] = Field(default_factory=list)
    diagnostics_removed: list[str] = Field(default_factory=list)


class AnalysisRunArtifactChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["input", "output"]
    artifact_id: str
    title: str
    artifact_type: str
    change_type: ChangeType
    before_version: str = ""
    after_version: str = ""
    before_digest: str = ""
    after_digest: str = ""


class AnalysisRunEntityChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "strategy_option",
        "space_decision",
        "evidence",
        "hard_constraint",
        "quality_issue",
    ]
    entity_id: str
    title: str
    change_type: ChangeType
    changed_fields: list[str] = Field(default_factory=list)


class AnalysisRunComparison(BaseModel):
    """Structured, deterministic comparison of two immutable capability Runs."""

    model_config = ConfigDict(extra="forbid")

    history_id: str
    capability_id: str
    base_run: AnalysisRunComparisonRef
    target_run: AnalysisRunComparisonRef
    configuration_changes: list[AnalysisRunFieldChange] = Field(default_factory=list)
    stage_changes: list[AnalysisRunStageChange] = Field(default_factory=list)
    artifact_changes: list[AnalysisRunArtifactChange] = Field(default_factory=list)
    outcome_changes: list[AnalysisRunFieldChange] = Field(default_factory=list)
    entity_changes: list[AnalysisRunEntityChange] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    has_changes: bool = False


_CONFIGURATION_FIELDS = (
    ("configuration_snapshot.question", "分析任务"),
    ("configuration_snapshot.governance_mode", "治理模式"),
    ("configuration_snapshot.execution_mode", "执行模式"),
    ("configuration_snapshot.selected_source_ids", "选定资料"),
    ("configuration_snapshot.analysis_snapshot_digest", "分析快照"),
    ("configuration_snapshot.capability_input_selections", "上游能力输入"),
    ("execution_profile.model_profile_id", "模型配置"),
    ("execution_profile.skill_id", "Skill"),
    ("run_kind", "Run 类型"),
    ("upstream_run_id", "上游 Run"),
    ("source_versions", "来源版本"),
    # Kept for direct comparison of already materialized v2 details. Public
    # comparison entry points reject those details before reaching this layer.
    ("metric_plan.decision_questions", "决策问题与假设"),
    ("metric_plan.entries", "指标计划"),
)

_OUTCOME_FIELDS = (
    ("stage1-strategy-options", "recommended_option_id", "推荐定位方案"),
    ("stage1-decision-matrix", "positioning_option_id", "矩阵定位方案"),
    ("stage1-decision-matrix", "matrix_version", "决策矩阵版本"),
    ("stage1-quality-audit", "status", "质量门状态"),
    ("stage1-quality-audit", "score", "质量审计分数"),
    ("stage1-quality-audit", "checks_passed", "质量检查通过数"),
    ("stage1-quality-audit", "checks_total", "质量检查总数"),
)

_ENTITY_SPECS = (
    ("stage1-strategy-options", "options", "strategy_option", ("id",), ("name", "title", "id")),
    ("stage1-decision-matrix", "space_decisions", "space_decision", ("space_id",), ("space_name", "title", "space_id")),
    ("stage1-evidence-nodes", "", "evidence", ("id",), ("claim", "title", "id")),
    ("stage1-hard-constraint-screening", "assessments", "hard_constraint", ("constraint_id", "id"), ("label", "constraint_id", "id")),
    ("stage1-quality-audit", "issues", "quality_issue", ("code",), ("message", "code")),
)


def _value_at(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return deepcopy(current)


def _change_type(before: Any, after: Any) -> ChangeType:
    if before is None:
        return "added"
    if after is None:
        return "removed"
    return "changed"


def _field_changes(base: dict[str, Any], target: dict[str, Any]) -> list[AnalysisRunFieldChange]:
    changes: list[AnalysisRunFieldChange] = []
    for path, label in _CONFIGURATION_FIELDS:
        before = _value_at(base, path)
        after = _value_at(target, path)
        if before == after:
            continue
        changes.append(
            AnalysisRunFieldChange(
                field=path,
                label=label,
                change_type=_change_type(before, after),
                before=before,
                after=after,
            )
        )
    return changes


def _stage_changes(base: AnalysisRunV3, target: AnalysisRunV3) -> list[AnalysisRunStageChange]:
    before_by_id = {item.stage_id: item for item in base.stage_records}
    after_by_id = {item.stage_id: item for item in target.stage_records}
    changes: list[AnalysisRunStageChange] = []
    for stage_id in sorted(set(before_by_id) | set(after_by_id)):
        before = before_by_id.get(stage_id)
        after = after_by_id.get(stage_id)
        if (
            before is not None
            and after is not None
            and before.title == after.title
            and before.status == after.status
            and before.summary == after.summary
            and before.diagnostics == after.diagnostics
        ):
            continue
        before_diagnostics = set(before.diagnostics if before else [])
        after_diagnostics = set(after.diagnostics if after else [])
        changes.append(
            AnalysisRunStageChange(
                stage_id=stage_id,
                title=(after.title if after else before.title),
                change_type=_change_type(before, after),
                before_status=before.status if before else "",
                after_status=after.status if after else "",
                before_summary=before.summary if before else "",
                after_summary=after.summary if after else "",
                diagnostics_added=sorted(after_diagnostics - before_diagnostics),
                diagnostics_removed=sorted(before_diagnostics - after_diagnostics),
            )
        )
    return changes


def _artifact_snapshots(detail: AnalysisRunV3Detail) -> dict[tuple[str, str], AnalysisArtifactSnapshot]:
    return {
        (item.direction, item.artifact.artifact_id): item
        for item in detail.artifacts
    }


def _artifact_refs(detail: AnalysisRunV3Detail) -> dict[tuple[str, str], AnalysisArtifactRef]:
    refs: dict[tuple[str, str], AnalysisArtifactRef] = {}
    for direction, artifacts in (
        ("input", detail.run.input_artifact_refs),
        ("output", detail.run.output_artifact_refs),
    ):
        for artifact in artifacts:
            refs[(direction, artifact.artifact_id)] = artifact
    for snapshot in detail.artifacts:
        refs[(snapshot.direction, snapshot.artifact.artifact_id)] = snapshot.artifact
    return refs


def _artifact_changes(base: AnalysisRunV3Detail, target: AnalysisRunV3Detail) -> list[AnalysisRunArtifactChange]:
    before_refs = _artifact_refs(base)
    after_refs = _artifact_refs(target)
    before_snapshots = _artifact_snapshots(base)
    after_snapshots = _artifact_snapshots(target)
    changes: list[AnalysisRunArtifactChange] = []
    for key in sorted(set(before_refs) | set(after_refs)):
        before = before_refs.get(key)
        after = after_refs.get(key)
        before_payload = before_snapshots.get(key)
        after_payload = after_snapshots.get(key)
        before_digest = before.content_digest if before else ""
        after_digest = after.content_digest if after else ""
        if before_payload is not None and before_payload.payload is not None:
            before_digest = before_digest or content_digest(before_payload.payload)
        if after_payload is not None and after_payload.payload is not None:
            after_digest = after_digest or content_digest(after_payload.payload)
        if before is not None and after is not None:
            same_content = bool(before_digest and after_digest and before_digest == after_digest)
            same_metadata_version = not before_digest and not after_digest and before.version == after.version
            if same_content or same_metadata_version:
                continue
        ref = after or before
        changes.append(
            AnalysisRunArtifactChange(
                direction=key[0],
                artifact_id=key[1],
                title=ref.title,
                artifact_type=ref.artifact_type,
                change_type=_change_type(before, after),
                before_version=before.version if before else "",
                after_version=after.version if after else "",
                before_digest=before_digest,
                after_digest=after_digest,
            )
        )
    return changes


def _output_payloads(detail: AnalysisRunV3Detail) -> dict[str, Any]:
    return {
        item.artifact.artifact_id: deepcopy(item.payload)
        for item in detail.artifacts
        if item.direction == "output" and item.payload is not None
    }


def _outcome_changes(base: AnalysisRunV3Detail, target: AnalysisRunV3Detail) -> list[AnalysisRunFieldChange]:
    before_payloads = _output_payloads(base)
    after_payloads = _output_payloads(target)
    changes: list[AnalysisRunFieldChange] = []
    for artifact_id, field, label in _OUTCOME_FIELDS:
        before = _value_at(before_payloads.get(artifact_id), field)
        after = _value_at(after_payloads.get(artifact_id), field)
        if before == after:
            continue
        changes.append(
            AnalysisRunFieldChange(
                field=f"{artifact_id}.{field}",
                label=label,
                change_type=_change_type(before, after),
                before=before,
                after=after,
            )
        )
    return changes


def _text_field(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return ""


def _entity_collection(payload: Any, collection_key: str) -> list[dict[str, Any]]:
    value = payload
    if collection_key:
        value = payload.get(collection_key) if isinstance(payload, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _changed_entity_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in set(before) | set(after)
        if key not in {"feature"} and content_digest(before.get(key)) != content_digest(after.get(key))
    )


def _entity_changes(base: AnalysisRunV3Detail, target: AnalysisRunV3Detail) -> list[AnalysisRunEntityChange]:
    before_payloads = _output_payloads(base)
    after_payloads = _output_payloads(target)
    changes: list[AnalysisRunEntityChange] = []
    for artifact_id, collection_key, category, id_fields, title_fields in _ENTITY_SPECS:
        before_items = {
            _text_field(item, id_fields): item
            for item in _entity_collection(before_payloads.get(artifact_id), collection_key)
            if _text_field(item, id_fields)
        }
        after_items = {
            _text_field(item, id_fields): item
            for item in _entity_collection(after_payloads.get(artifact_id), collection_key)
            if _text_field(item, id_fields)
        }
        for entity_id in sorted(set(before_items) | set(after_items)):
            before = before_items.get(entity_id)
            after = after_items.get(entity_id)
            if before is not None and after is not None:
                changed_fields = _changed_entity_fields(before, after)
                if not changed_fields:
                    continue
            else:
                changed_fields = []
            item = after or before
            changes.append(
                AnalysisRunEntityChange(
                    category=category,
                    entity_id=entity_id,
                    title=_text_field(item, title_fields) or entity_id,
                    change_type=_change_type(before, after),
                    changed_fields=changed_fields,
                )
            )
    return changes


def _run_ref(run: AnalysisRunV3) -> AnalysisRunComparisonRef:
    return AnalysisRunComparisonRef(
        run_id=run.run_id,
        status=run.status,
        current_stage=run.current_stage,
        created_at=run.created_at,
        completed_at=run.completed_at,
        stale_input_artifact_ids=list(run.stale_input_artifact_ids),
    )


def compare_run_details(base: AnalysisRunV3Detail, target: AnalysisRunV3Detail) -> AnalysisRunComparison:
    if base.run.run_id == target.run.run_id:
        raise ValueError("analysis_run_comparison_requires_distinct_runs")
    if base.history_id != target.history_id:
        raise ValueError("analysis_run_history_mismatch")
    if base.run.capability_id != target.run.capability_id:
        raise ValueError("analysis_run_capability_mismatch")

    configuration_changes = _field_changes(
        base.run.model_dump(mode="json"), target.run.model_dump(mode="json")
    )
    stage_changes = _stage_changes(base.run, target.run)
    artifact_changes = _artifact_changes(base, target)
    outcome_changes = _outcome_changes(base, target)
    entity_changes = _entity_changes(base, target)
    summary = []
    if outcome_changes:
        summary.append(f"{len(outcome_changes)} 项核心结果发生变化。")
    if entity_changes:
        summary.append(f"{len(entity_changes)} 个策略、空间或证据对象发生变化。")
    if artifact_changes:
        summary.append(f"{len(artifact_changes)} 个输入或输出产物版本不同。")
    if configuration_changes:
        summary.append(f"{len(configuration_changes)} 项执行配置不同。")
    if stage_changes:
        summary.append(f"{len(stage_changes)} 个执行阶段记录不同。")
    if not summary:
        summary.append("两个运行版本的已保存契约未发现差异。")

    return AnalysisRunComparison(
        history_id=base.history_id,
        capability_id=base.run.capability_id,
        base_run=_run_ref(base.run),
        target_run=_run_ref(target.run),
        configuration_changes=configuration_changes,
        stage_changes=stage_changes,
        artifact_changes=artifact_changes,
        outcome_changes=outcome_changes,
        entity_changes=entity_changes,
        summary=summary,
        has_changes=any(
            (
                configuration_changes,
                stage_changes,
                artifact_changes,
                outcome_changes,
                entity_changes,
            )
        ),
    )
