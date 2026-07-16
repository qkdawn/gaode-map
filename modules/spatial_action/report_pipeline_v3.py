"""Schema-v3 orchestration helpers for the six-object report workflow.

The public contract speaks in evidence capabilities.  This module owns the
private mapping to metric ids and converts deterministic execution results into
one EvidenceSnapshot.  Agent-facing projections never expose that lineage.
"""

from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.agent.analysis_runs import content_digest
from modules.spatial_action.report_orchestration import (
    EVIDENCE_CAPABILITY_REGISTRY,
    EVIDENCE_CAPABILITY_REGISTRY_HASH,
    AnalysisBlueprint,
    BlueprintCompleteness,
    BlueprintEvidenceRequirement,
    BlueprintLock,
    ChapterAssignments,
    ChapterPackage,
    EditorialReview,
    EditorialReviewDraft,
    EvidenceExecutionLineage,
    EvidenceSnapshot,
    ExecutionAttemptLineage,
    OrchestrationError,
    QuestionEvidenceRequirements,
    ReportAssembly,
    SnapshotEvidence,
    SnapshotGap,
    SnapshotVisual,
    SpatialReportOrchestrator,
    V3ChapterAssignment,
    build_editorial_review,
    build_report_visual_catalog,
    validate_v3_contracts,
    validate_chapter_package,
)
from modules.spatial_action.report_visuals import render_report_visual


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    return content_digest(value)


class CapabilityExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str
    unit: str
    source: str
    adapter_id: str


# This is deliberately private.  Public blueprints depend only on the stable
# semantic keys defined by EVIDENCE_CAPABILITY_REGISTRY.
_CAPABILITY_EXECUTION: dict[str, CapabilityExecution] = {
    "project_constraints": CapabilityExecution(metric_id="project.document_constraints", unit="scope", source="project-documents", adapter_id="project_documents"),
    "facility_supply_structure": CapabilityExecution(metric_id="poi.category_count", unit="scope", source="poi", adapter_id="scope_poi"),
    "spatial_concentration": CapabilityExecution(metric_id="spatial.gi_star", unit="grid_cell", source="poi-grid", adapter_id="scope_grid"),
    "network_access_structure": CapabilityExecution(metric_id="road.integration", unit="road_segment", source="road-edges", adapter_id="road_syntax"),
    "entrance_comparison": CapabilityExecution(metric_id="road.entrance_distance", unit="entrance", source="formal-entrances", adapter_id="entrance_routes"),
    "population_context": CapabilityExecution(metric_id="population.total", unit="scope", source="history-polygon", adapter_id="population"),
    "night_activity_context": CapabilityExecution(metric_id="nightlight.activity_level", unit="scope", source="history-polygon", adapter_id="nightlight"),
    "temporal_change": CapabilityExecution(metric_id="poi.multi_year_count", unit="scope", source="poi", adapter_id="scope_poi_timeseries"),
}


def capability_execution_registry() -> dict[str, dict[str, str]]:
    """Return an audit copy; callers cannot mutate the engine registry."""

    return {key: value.model_dump(mode="json") for key, value in _CAPABILITY_EXECUTION.items()}


def build_metric_execution_plan(blueprint: AnalysisBlueprint) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Translate semantic evidence requirements into the engine's private plan."""

    entries: list[dict[str, Any]] = []
    requirement_by_entry: dict[str, str] = {}
    for group in blueprint.evidence_requirements:
        question = next(item for item in blueprint.decision_questions if item.question_id == group.question_id)
        hypothesis_ids = [item.hypothesis_id for item in question.hypotheses]
        for requirement in group.items:
            capability = requirement.evidence_capability
            execution = _CAPABILITY_EXECUTION.get(capability)
            if requirement.kind == "gap" or execution is None:
                continue
            plan_entry_id = f"internal:{requirement.requirement_id}"
            requirement_by_entry[plan_entry_id] = requirement.requirement_id
            entries.append(
                {
                    "plan_entry_id": plan_entry_id,
                    "metric_id": execution.metric_id,
                    "role": "primary",
                    "decision_question_id": group.question_id,
                    "hypothesis_ids": hypothesis_ids,
                    "planned_spatial_target": {
                        "unit": execution.unit,
                        "source": execution.source,
                        "runtime_parameters": [],
                    },
                    "selection_reason": requirement.objective,
                    "expected_decision_use": requirement.failure_effect,
                    "required_source_ids": list(requirement.required_sources),
                    "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                    "exclusion_reason": "",
                }
            )
    return entries, requirement_by_entry


def _node_result(node: dict[str, Any]) -> dict[str, Any]:
    for key in ("data", "result", "metadata"):
        value = node.get(key)
        if isinstance(value, dict) and value:
            return deepcopy(value)
    return {
        "title": str(node.get("title") or ""),
        "summary": str(node.get("summary") or node.get("content") or node.get("claim") or ""),
    }


def _node_sources(node: dict[str, Any], requirement: BlueprintEvidenceRequirement) -> list[str]:
    for key in ("source_refs", "source_ids", "sources"):
        value = node.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    return list(requirement.required_sources) or ["locked-project-snapshot"]


def build_evidence_snapshot(
    *,
    blueprint: AnalysisBlueprint,
    metric_attempts: list[dict[str, Any]],
    evidence_nodes: list[dict[str, Any]],
    spatial_action_map: dict[str, Any],
) -> tuple[EvidenceSnapshot, dict[str, str]]:
    """Build the sole public evidence artifact and deterministic SVG assets."""

    entries, requirement_by_entry = build_metric_execution_plan(blueprint)
    entry_by_id = {item["plan_entry_id"]: item for item in entries}
    requirement_by_id = {
        item.requirement_id: (group.question_id, item)
        for group in blueprint.evidence_requirements
        for item in group.items
    }
    nodes_by_id = {str(item.get("id") or ""): item for item in evidence_nodes if str(item.get("id") or "")}
    public_evidence: list[SnapshotEvidence] = []
    gaps: list[SnapshotGap] = []
    lineage: list[ExecutionAttemptLineage] = []
    attempted_requirements: set[str] = set()

    for raw_attempt in metric_attempts:
        entry_id = str(raw_attempt.get("plan_entry_id") or "")
        requirement_id = requirement_by_entry.get(entry_id)
        if not requirement_id:
            continue
        attempted_requirements.add(requirement_id)
        question_id, requirement = requirement_by_id[requirement_id]
        status = str(raw_attempt.get("execution_status") or "failed")
        evidence_ids = [str(item) for item in raw_attempt.get("evidence_node_ids") or [] if str(item) in nodes_by_id]
        if status == "succeeded" and evidence_ids:
            for evidence_id in evidence_ids:
                node = nodes_by_id[evidence_id]
                state = str(node.get("evidence_state") or node.get("state") or "proxy")
                public_evidence.append(
                    SnapshotEvidence(
                        evidence_id=evidence_id,
                        requirement_id=requirement_id,
                        question_ids=[question_id],
                        state="measured" if state == "measured" else "proxy",
                        sources=_node_sources(node, requirement),
                        scope=deepcopy(node.get("scope") or {}),
                        result=_node_result(node),
                        limitations=[str(item) for item in node.get("limitations") or []],
                    )
                )
            lineage.append(
                ExecutionAttemptLineage(
                    attempt_id=f"attempt:{requirement_id}",
                    requirement_id=requirement_id,
                    evidence_capability=requirement.evidence_capability,
                    adapter_id=_CAPABILITY_EXECUTION[requirement.evidence_capability].adapter_id,
                    metric_id=str(entry_by_id[entry_id]["metric_id"]),
                    parameters=deepcopy(raw_attempt.get("parameters") or {}),
                    execution_status="succeeded",
                    evidence_ids=evidence_ids,
                )
            )
            continue
        gap_id = f"gap:{requirement_id}"
        reason = str(raw_attempt.get("reason") or "证据执行未成功。")
        gaps.append(
            SnapshotGap(
                gap_id=gap_id,
                requirement_id=requirement_id,
                question_id=question_id,
                missing_inputs=list(requirement.required_sources) or ["required execution input"],
                decision_limit=requirement.failure_effect,
                collection_action=f"补齐输入并重新执行 {requirement.objective}",
                stop_condition=f"在 {requirement.objective} 完成前不得形成肯定性结论。",
            )
        )
        lineage.append(
            ExecutionAttemptLineage(
                attempt_id=f"attempt:{requirement_id}",
                requirement_id=requirement_id,
                evidence_capability=requirement.evidence_capability,
                adapter_id=_CAPABILITY_EXECUTION[requirement.evidence_capability].adapter_id,
                metric_id=str(entry_by_id[entry_id]["metric_id"]),
                parameters=deepcopy(raw_attempt.get("parameters") or {}),
                execution_status=status if status in {"blocked", "failed", "not_applicable"} else "failed",
                gap_ids=[gap_id],
                reason=reason,
            )
        )

    for requirement_id, (question_id, requirement) in requirement_by_id.items():
        if requirement_id in attempted_requirements:
            continue
        gap_id = f"gap:{requirement_id}"
        gaps.append(
            SnapshotGap(
                gap_id=gap_id,
                requirement_id=requirement_id,
                question_id=question_id,
                missing_inputs=list(requirement.required_sources) or ["declared external evidence"],
                decision_limit=requirement.failure_effect,
                collection_action=f"采集并登记：{requirement.objective}",
                stop_condition=f"补数前禁止推导：{requirement.failure_effect}",
            )
        )
        lineage.append(
            ExecutionAttemptLineage(
                attempt_id=f"attempt:{requirement_id}",
                requirement_id=requirement_id,
                evidence_capability=requirement.evidence_capability,
                execution_status="registered_gap" if requirement.kind == "gap" else "blocked",
                gap_ids=[gap_id],
                reason="Requirement has no deterministic adapter or is an explicit evidence gap.",
            )
        )

    evidence_by_question = {question.question_id: 0 for question in blueprint.decision_questions}
    gaps_by_question = {question.question_id: 0 for question in blueprint.decision_questions}
    for item in public_evidence:
        for question_id in item.question_ids:
            evidence_by_question[question_id] += 1
    for item in gaps:
        gaps_by_question[item.question_id] += 1
    readiness = {
        question_id: (
            "conditional" if evidence_by_question[question_id] and gaps_by_question[question_id]
            else "ready" if evidence_by_question[question_id]
            else "gap_bound" if gaps_by_question[question_id]
            else "not_reportable"
        )
        for question_id in evidence_by_question
    }

    legacy_visuals = build_report_visual_catalog(
        evidence_nodes,
        spatial_action_map,
        metric_attempts,
        run_id=blueprint.run_id,
    )
    svg_assets: dict[str, str] = {}
    visuals: list[SnapshotVisual] = []
    public_ids = {item.evidence_id for item in public_evidence}
    for candidate in legacy_visuals.candidates:
        if not set(candidate.evidence_ids) <= public_ids:
            continue
        svg = render_report_visual(candidate)
        svg_assets[candidate.filename] = svg
        bound_fields = sorted({
            key
            for evidence_id in candidate.evidence_ids
            for item in public_evidence
            if item.evidence_id == evidence_id
            for key in item.result
        })
        if not bound_fields:
            continue
        visuals.append(
            SnapshotVisual(
                visual_id=candidate.visual_id,
                visual_type=candidate.visual_type,
                title=candidate.title,
                evidence_ids=candidate.evidence_ids,
                data_fields=bound_fields[:8],
                transform=candidate.transform,
                filename=candidate.filename,
                spec_hash=candidate.spec_hash,
                asset_hash=f"sha256:{hashlib.sha256(svg.encode('utf-8')).hexdigest()}",
            )
        )

    payload = {
        "schema_version": "3.0",
        "run_id": blueprint.run_id,
        "snapshot_id": f"evidence:{blueprint.blueprint_id}",
        "blueprint_hash": blueprint.lock.content_hash,
        "evidence": [item.model_dump(mode="json") for item in public_evidence],
        "gaps": [item.model_dump(mode="json") for item in gaps],
        "question_readiness": readiness,
        "visuals": [item.model_dump(mode="json") for item in visuals],
        "execution_lineage": EvidenceExecutionLineage(
            capability_registry_hash=EVIDENCE_CAPABILITY_REGISTRY_HASH,
            attempts=lineage,
        ).model_dump(mode="json"),
    }
    payload["snapshot_hash"] = _digest(payload)
    return EvidenceSnapshot.model_validate(payload), svg_assets


class _BlueprintDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str
    analysis_scope: Literal["full_project", "focused_diagnostic"]
    report_title: str
    project_judgment: str
    decision_questions: list[dict[str, Any]] = Field(min_length=1)
    evidence_requirements: list[QuestionEvidenceRequirements] = Field(min_length=1)
    excluded_topics: list[dict[str, Any]] = Field(default_factory=list)
    report_logic: list[str] = Field(min_length=1)
    shared_glossary: dict[str, str] = Field(default_factory=dict)


class SpatialReportOrchestratorV3(SpatialReportOrchestrator):
    """Agent orchestration that exposes only the schema-v3 domain objects."""

    async def plan_project_v3(
        self,
        *,
        project_documents: dict[str, Any],
        source_versions: list[dict[str, Any]],
        data_preview: dict[str, Any],
        run_id: str,
        analysis_scope: Literal["full_project", "focused_diagnostic"] = "full_project",
        user_question: str = "",
    ) -> AnalysisBlueprint:
        source_hash = _digest({"project_documents": project_documents, "source_versions": source_versions, "data_preview": data_preview})

        def validate_draft(raw: dict[str, Any]) -> _BlueprintDraft:
            draft = _BlueprintDraft.model_validate(raw)
            if draft.analysis_scope != analysis_scope:
                raise ValueError("planner returned the wrong analysis_scope")
            return draft

        async def review(draft: _BlueprintDraft) -> BlueprintCompleteness:
            return await self._validated_chat(
                system_prompt=(
                    "你是独立完整性审查角色。检查动态决策问题是否覆盖项目材料，是否每题都有证据要求，"
                    "排除问题是否有理由，且没有恢复固定议题。只返回 BlueprintCompleteness JSON。"
                ),
                user_payload={"user_question": user_question, "project_documents": project_documents, "draft": draft.model_dump(mode="json")},
                phase="spatial-v3-blueprint-review",
                title="独立审查分析蓝图",
                reasoning_id="spatial-v3-blueprint-review",
                validator=BlueprintCompleteness.model_validate,
            )

        prompt_payload = {
            "run_id": run_id,
            "analysis_scope": analysis_scope,
            "user_question": user_question,
            "project_documents": project_documents,
            "source_versions": source_versions,
            "data_preview": data_preview,
            "evidence_capability_registry": EVIDENCE_CAPABILITY_REGISTRY,
        }
        draft = await self._validated_chat(
            system_prompt=(
                "你是项目主分析师。阅读全部项目材料后动态设计报告，不使用固定六议题或固定专业域。"
                "每个决策问题必须有 evidence_requirements；metric/spatial/comparison 只能使用给定 evidence_capability。"
                "不得输出 MetricPlan、Attempt、章节正文、完整性结论或 lock。只返回蓝图草案 JSON。"
            ),
            user_payload=prompt_payload,
            phase="spatial-v3-blueprint",
            title="建立 schema-v3 分析蓝图",
            reasoning_id="spatial-v3-main-blueprint",
            validator=validate_draft,
        )
        completeness = await review(draft)
        if completeness.status != "accepted":
            draft = await self._validated_chat(
                system_prompt="你是原主分析师。根据独立审查修订完整蓝图草案；不得删除问题规避审查。只返回完整替换 JSON。",
                user_payload={**prompt_payload, "previous_draft": draft.model_dump(mode="json"), "completeness_review": completeness.model_dump(mode="json")},
                phase="spatial-v3-blueprint-repair",
                title="修订 schema-v3 分析蓝图",
                reasoning_id="spatial-v3-main-blueprint",
                validator=validate_draft,
            )
            completeness = await review(draft)
            if completeness.status != "accepted":
                raise OrchestrationError("schema-v3 blueprint remained incomplete after one repair", run_status="publication_blocked")
        content = draft.model_dump(mode="json") | {
            "schema_version": "3.0",
            "run_id": run_id,
            "completeness_review": completeness.model_dump(mode="json"),
        }
        lock_payload = {
            "source_snapshot_hash": source_hash,
            "capability_registry_hash": EVIDENCE_CAPABILITY_REGISTRY_HASH,
            "locked_at": _utc_now(),
        }
        content["lock"] = lock_payload
        lock_payload["content_hash"] = _digest(content)
        return AnalysisBlueprint.model_validate(content)

    async def assign_chapters_v3(self, blueprint: AnalysisBlueprint, snapshot: EvidenceSnapshot) -> ChapterAssignments:
        validate_base = {"blueprint_hash": blueprint.lock.content_hash, "evidence_snapshot_hash": snapshot.snapshot_hash}

        def validate(raw: dict[str, Any]) -> ChapterAssignments:
            payload = dict(raw)
            payload.update({"schema_version": "3.0", "run_id": blueprint.run_id, **validate_base})
            chapters = payload.get("chapters") or []
            for chapter in chapters:
                chapter.pop("assignment_hash", None)
                chapter["assignment_hash"] = _digest({
                    "blueprint_hash": blueprint.lock.content_hash,
                    "evidence_snapshot_hash": snapshot.snapshot_hash,
                    "assignment": chapter,
                })
            payload["content_hash"] = ""
            payload["content_hash"] = _digest(payload)
            result = ChapterAssignments.model_validate(payload)
            validate_v3_contracts(blueprint, snapshot, result)
            return result

        return await self._validated_chat(
            system_prompt=(
                "你是项目主分析师。证据执行已结束，现在动态锁定最终章节。每个问题只能有一个主责章节；"
                "证据、缺口和视觉必须通过 evidence_access 白名单授权。不得看到或推断 execution_lineage。"
                "每章给出完整 subsection_tasks 和 required_argument_units。只返回 ChapterAssignments JSON。"
            ),
            user_payload={"analysis_blueprint": blueprint.model_dump(mode="json"), "evidence_snapshot": snapshot.public_projection()},
            phase="spatial-v3-assignments",
            title="锁定 schema-v3 章节任务",
            reasoning_id="spatial-v3-main-assignments",
            validator=validate,
        )

    async def author_chapters_v3(
        self,
        *,
        blueprint: AnalysisBlueprint,
        snapshot: EvidenceSnapshot,
        assignments: ChapterAssignments,
        project_documents: dict[str, Any],
    ) -> tuple[list[ChapterPackage], list[ChapterPackage], EditorialReview]:
        async def author(assignment: V3ChapterAssignment, revision: int = 1, previous: ChapterPackage | None = None, instructions: list[str] | None = None) -> ChapterPackage:
            projection = assignments.specialist_projection(assignment.chapter_id, snapshot)

            def validate(raw: dict[str, Any]) -> ChapterPackage:
                payload = dict(raw)
                payload.update({
                    "schema_version": "3.0",
                    "run_id": blueprint.run_id,
                    "chapter_id": assignment.chapter_id,
                    "assignment_hash": assignment.assignment_hash,
                    "evidence_snapshot_hash": snapshot.snapshot_hash,
                })
                payload["content_hash"] = ""
                payload["content_hash"] = _digest({key: value for key, value in payload.items() if key != "content_hash"})
                chapter = ChapterPackage.model_validate(payload)
                validate_chapter_package(chapter, assignment, snapshot, expected_revision=revision)
                return chapter

            return await self._validated_chat(
                system_prompt=(
                    "你是专业章节 Subagent。直接提交可发布 ChapterPackage，不是 Memo。每个 ArgumentUnit 必须包含主张、"
                    "证据或缺口、比较基准、机制、项目影响、行动、假设和停止条件。只使用投影中的证据；"
                    "measured/proxy 主张必须填写 evidence_result_refs，指向 EvidenceSnapshot.result 中真实存在的字段路径。"
                    "不得创造数值、读取 execution_lineage、代写其他章节或发布文件。"
                ),
                user_payload={"analysis_blueprint": blueprint.model_dump(mode="json"), **projection, "project_documents": project_documents, "previous_chapter": previous.model_dump(mode="json") if previous else None, "repair_instructions": instructions or []},
                phase="spatial-v3-chapter-repair" if revision == 2 else "spatial-v3-chapter",
                title=f"专业章节：{assignment.title}",
                reasoning_id=f"spatial-v3-chapter-{assignment.chapter_id}",
                validator=validate,
            )

        first_results = await asyncio.gather(*(author(item) for item in assignments.chapters), return_exceptions=True)
        errors = [item for item in first_results if isinstance(item, Exception)]
        chapters = [item for item in first_results if isinstance(item, ChapterPackage)]
        if errors:
            raise OrchestrationError("one or more schema-v3 chapters failed validation: " + "; ".join(map(str, errors)), run_status="chapter_failed")
        versions = list(chapters)

        async def review_chapters(current: list[ChapterPackage], final: bool) -> EditorialReviewDraft:
            def validate(raw: dict[str, Any]) -> EditorialReviewDraft:
                draft = EditorialReviewDraft.model_validate(raw)
                known_versions = {item.chapter_version_id for item in current}
                if not {item.chapter_version_id for item in draft.chapter_decisions} <= known_versions:
                    raise ValueError("editorial review references unknown chapter versions")
                if final and draft.publication_decision != "ready":
                    raise ValueError("final editorial pass must be ready")
                return draft
            return await self._validated_chat(
                system_prompt=(
                    "你是主分析师总编。只能验收、裁决冲突或退回原 Subagent，不能修改专业正文。"
                    "保留具体章节版本决定；跨章冲突不得静默合并。不要生成 accepted_claims，系统会生成。"
                    + ("这是唯一退修后的最终审校，必须给出最终决定。" if final else "首次审校可要求一次定向退修。")
                ),
                user_payload={"analysis_blueprint": blueprint.model_dump(mode="json"), "evidence_snapshot": snapshot.public_projection(), "chapters": [item.model_dump(mode="json") for item in current]},
                phase="spatial-v3-editorial-final" if final else "spatial-v3-editorial",
                title="最终审校" if final else "章节审校",
                reasoning_id="spatial-v3-main-editorial",
                validator=validate,
            )

        first_draft = await review_chapters(chapters, False)
        revisions = {item.chapter_id: item for item in first_draft.chapter_decisions if item.status == "revise"}
        if revisions:
            by_id = {item.chapter_id: item for item in chapters}
            assignment_by_id = {item.chapter_id: item for item in assignments.chapters}
            repairs = await asyncio.gather(*(
                author(assignment_by_id[chapter_id], 2, by_id[chapter_id], decision.repair_instructions)
                for chapter_id, decision in revisions.items()
            ), return_exceptions=True)
            repair_errors = [item for item in repairs if isinstance(item, Exception)]
            if repair_errors:
                raise OrchestrationError("schema-v3 chapter repair failed: " + "; ".join(map(str, repair_errors)), run_status="chapter_failed")
            for repaired in repairs:
                assert isinstance(repaired, ChapterPackage)
                versions.append(repaired)
                by_id[repaired.chapter_id] = repaired
            chapters = [by_id[item.chapter_id] for item in sorted(assignments.chapters, key=lambda item: item.order)]
            final_draft = await review_chapters(chapters, True)
            combined = first_draft.model_dump(mode="json")
            combined["chapter_decisions"] = [
                *first_draft.model_dump(mode="json")["chapter_decisions"],
                *final_draft.model_dump(mode="json")["chapter_decisions"],
            ]
            combined["conflicts"] = final_draft.model_dump(mode="json")["conflicts"]
            combined["terminology_rules"] = final_draft.terminology_rules
            combined["publication_decision"] = final_draft.publication_decision
            final_draft = EditorialReviewDraft.model_validate(combined)
        else:
            final_draft = first_draft
        if final_draft.publication_decision != "ready":
            raise OrchestrationError("editorial review blocked schema-v3 publication", run_status="publication_blocked")
        return chapters, versions, build_editorial_review(final_draft, chapters)

    @staticmethod
    def assemble_v3(
        *,
        blueprint: AnalysisBlueprint,
        chapters: list[ChapterPackage],
        review: EditorialReview,
        executive_summary: dict[str, Any],
        integrated_recommendations: list[dict[str, Any]],
        transitions: list[dict[str, Any]] | None = None,
    ) -> ReportAssembly:
        accepted_versions = {
            item.chapter_version_id for item in review.chapter_decisions if item.status == "accepted"
        }
        selected = [item for item in chapters if item.chapter_version_id in accepted_versions]
        payload = {
            "schema_version": "3.0",
            "run_id": blueprint.run_id,
            "assembly_id": f"assembly:{blueprint.blueprint_id}",
            "title": blueprint.report_title,
            "accepted_chapters": [
                {"chapter_id": item.chapter_id, "chapter_version_id": item.chapter_version_id, "content_hash": item.content_hash}
                for item in selected
            ],
            "chapter_order": [item.chapter_id for item in selected],
            "executive_summary": executive_summary,
            "transitions": transitions or [],
            "integrated_recommendations": integrated_recommendations,
            "conflict_references": [item.conflict_id for item in review.conflicts],
        }
        known_claims = {item.claim_id for item in review.accepted_claims}
        statements = [payload["executive_summary"], *payload["integrated_recommendations"], *payload["transitions"]]
        if any(not set(item.get("claim_ids") or []) <= known_claims for item in statements):
            raise ValueError("ReportAssembly synthesis references unknown accepted claims")
        payload["content_hash"] = _digest(payload)
        return ReportAssembly.model_validate(payload)

    async def assemble_with_main_agent_v3(
        self,
        *,
        blueprint: AnalysisBlueprint,
        chapters: list[ChapterPackage],
        review: EditorialReview,
    ) -> ReportAssembly:
        known_claims = [item.model_dump(mode="json") for item in review.accepted_claims]

        class AssemblySynthesis(BaseModel):
            model_config = ConfigDict(extra="forbid")
            executive_summary: dict[str, Any]
            integrated_recommendations: list[dict[str, Any]] = Field(default_factory=list)
            transitions: list[dict[str, Any]] = Field(default_factory=list)

        def validate(raw: dict[str, Any]) -> ReportAssembly:
            synthesis = AssemblySynthesis.model_validate(raw)
            return self.assemble_v3(
                blueprint=blueprint,
                chapters=chapters,
                review=review,
                executive_summary=synthesis.executive_summary,
                integrated_recommendations=synthesis.integrated_recommendations,
                transitions=synthesis.transitions,
            )

        return await self._validated_chat(
            system_prompt=(
                "你是项目主分析师总编。专业章节已经验收，只能使用 accepted_claims 写执行摘要、综合建议和章节过渡。"
                "不得创造新判断、改写章节或引用未知 claim_id。只返回 assembly synthesis JSON。"
            ),
            user_payload={
                "analysis_blueprint": blueprint.model_dump(mode="json"),
                "accepted_chapters": [item.model_dump(mode="json") for item in chapters],
                "accepted_claims": known_claims,
                "conflicts": [item.model_dump(mode="json") for item in review.conflicts],
            },
            phase="spatial-v3-assembly",
            title="组装 schema-v3 项目报告",
            reasoning_id="spatial-v3-main-assembly",
            validator=validate,
        )
