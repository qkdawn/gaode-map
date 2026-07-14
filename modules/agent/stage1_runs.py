from __future__ import annotations

from typing import Any

from .capability_inputs import ResolvedCapabilityInputs
from .analysis_runs import (
    AnalysisArtifactRef,
    AnalysisArtifactType,
    AnalysisRunRecorder,
    AnalysisSourceVersion,
    artifact_ref,
    content_digest,
)
from .llm_digest import snapshot_digest
from .schemas import AgentTurnRequest, EffectiveExecutionProfile
from .stage1_provenance import ArtifactProvenance


def _wgs84_origin(payload: AgentTurnRequest) -> tuple[float, float] | None:
    candidates = (
        payload.analysis_snapshot.param_bundles.get("center"),
        payload.analysis_snapshot.context.get("center"),
        payload.analysis_snapshot.scope.get("center"),
    )
    for value in candidates:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            continue
        try:
            lng, lat = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lng <= 180 and -90 <= lat <= 90:
            return (lng, lat)
    return None


def _source_versions(
    payload: AgentTurnRequest,
    selected_sources: list[dict[str, Any]],
) -> list[AnalysisSourceVersion]:
    scope_sha = content_digest(payload.analysis_snapshot.scope)
    versions: list[AnalysisSourceVersion] = []
    snapshot = payload.analysis_snapshot
    system_sources = (
        ("current:dataset:poi", snapshot.poi_summary or snapshot.pois),
        ("current:dataset:h3", snapshot.h3),
        ("current:dataset:population", snapshot.population),
        ("current:dataset:nightlight", snapshot.nightlight),
        ("current:dataset:road_edges", (snapshot.road or {}).get("road_edges") if isinstance(snapshot.road, dict) else None),
        ("current:dataset:road_grid", (snapshot.road or {}).get("road_grid") if isinstance(snapshot.road, dict) else None),
    )
    sources = list(selected_sources)
    known_ids = {
        str(item.get("source_id") or item.get("id") or "").strip()
        for item in sources
    }
    for source_id, data in system_sources:
        if not data or source_id in known_ids:
            continue
        sources.append(
            {
                "source_id": source_id,
                "content_sha256": content_digest(data),
                "scope_fingerprint": scope_sha,
                "record_count": len(data) if isinstance(data, list) else 0,
                "year": data.get("year") if isinstance(data, dict) else None,
            }
        )
    for source in sources:
        source_id = str(source.get("source_id") or source.get("id") or "").strip()
        if not source_id:
            continue
        meta = source.get("meta") if isinstance(source.get("meta"), dict) else {}
        ai_payload = meta.get("aiPayload") or meta.get("ai_payload")
        ai_payload = ai_payload if isinstance(ai_payload, dict) else {}
        raw_year = source.get("year") or source.get("source_year") or ai_payload.get("year")
        try:
            year = int(str(raw_year)[:4]) if raw_year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        sha256 = str(
            source.get("sha256")
            or source.get("content_sha256")
            or ai_payload.get("dataset_content_sha256")
            or content_digest(source)
        )
        raw_count = (
            source.get("record_count")
            or source.get("count")
            or (ai_payload.get("counts") or {}).get("records")
            or 0
        )
        try:
            record_count = max(0, int(raw_count))
        except (TypeError, ValueError):
            record_count = 0
        versions.append(
            AnalysisSourceVersion(
                source_id=source_id,
                year=year,
                sha256=sha256,
                scope_fingerprint=str(
                    source.get("scope_fingerprint")
                    or ai_payload.get("scope_fingerprint")
                    or scope_sha
                ),
                record_count=record_count,
            )
        )
    return versions


def start_stage1_run(
    payload: AgentTurnRequest,
    *,
    profile: EffectiveExecutionProfile,
    question: str,
    selected_sources: list[dict[str, Any]],
    capability_id: str = "urban-strategy-stage1",
    resolved_inputs: ResolvedCapabilityInputs | None = None,
) -> AnalysisRunRecorder:
    """Lock one Stage 1 configuration before readiness or model execution begins."""

    origin = _wgs84_origin(payload)
    return AnalysisRunRecorder(
        capability_id=capability_id,
        project_context={
            "scope": payload.analysis_snapshot.scope,
            "context": payload.analysis_snapshot.context,
        },
        configuration_snapshot={
            "conversation_id": payload.conversation_id,
            "history_id": payload.history_id,
            "question": question,
            "governance_mode": payload.governance_mode,
            "execution_mode": payload.execution_mode,
            "selected_source_ids": [
                str(item.get("source_id") or "").strip()
                for item in selected_sources
                if str(item.get("source_id") or "").strip()
            ],
            "analysis_snapshot_digest": snapshot_digest(payload.analysis_snapshot),
            "capability_input_selections": (
                resolved_inputs.configuration_snapshot() if resolved_inputs else []
            ),
        },
        execution_profile=profile.model_dump(mode="json"),
        project_location=origin,
        scope_origin=origin,
        partition_origin=origin,
        source_versions=_source_versions(payload, selected_sources),
    )


def bind_stage1_input_artifacts(
    registry: list[ArtifactProvenance],
) -> list[AnalysisArtifactRef]:
    return [
        artifact_ref(
            artifact_id=str(item.artifact_id),
            artifact_type="structured_data",
            title=str(item.title or item.source_id or item.artifact_id),
            source_run_id="",
            payload={
                "source_id": item.source_id,
                "source_kind": item.source_kind,
                "locator": item.locator,
                "metadata": item.metadata,
            },
        )
        for item in registry
    ]


def build_stage1_output_artifacts(
    *,
    run_id: str,
    package: dict[str, Any],
    input_artifact_ids: list[str],
    report_markdown: str = "",
    evidence_appendix: str = "",
    design_handoff: dict[str, Any] | None = None,
    include_manifest: bool = False,
) -> list[AnalysisArtifactRef]:
    evidence_ids = [
        str(item.get("id") or "").strip()
        for item in package.get("evidence_nodes") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    artifacts: list[AnalysisArtifactRef] = []

    def add(
        artifact_id: str,
        artifact_type: AnalysisArtifactType,
        title: str,
        filename: str,
        payload: Any,
        dependencies: list[str],
        *,
        evidence_refs: list[str] | None = None,
    ) -> None:
        artifacts.append(
            artifact_ref(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                title=title,
                filename=filename,
                source_run_id=run_id,
                payload=payload,
                source_artifact_refs=dependencies,
                evidence_refs=evidence_refs or [],
            )
        )

    if "project_brief" in package:
        add(
            "stage1-project-brief",
            "structured_data",
            "项目任务摘要",
            "project_brief.json",
            package["project_brief"],
            input_artifact_ids,
        )
    if "source_readiness" in package:
        add(
            "stage1-source-readiness",
            "diagnostic_report",
            "资料就绪度",
            "source_readiness.json",
            package["source_readiness"],
            input_artifact_ids,
        )
    if "evidence_nodes" in package:
        add(
            "stage1-evidence-nodes",
            "evidence_nodes",
            "证据节点",
            "evidence_nodes.jsonl",
            package["evidence_nodes"],
            input_artifact_ids,
            evidence_refs=evidence_ids,
        )
    if "conflict_register" in package:
        add(
            "stage1-conflict-register",
            "diagnostic_report",
            "冲突登记表",
            "conflict_register.json",
            package["conflict_register"],
            ["stage1-evidence-nodes"],
            evidence_refs=evidence_ids,
        )
    if "hard_constraint_screening" in package:
        add(
            "stage1-hard-constraint-screening",
            "diagnostic_report",
            "硬约束筛选",
            "hard_constraint_screening.json",
            package["hard_constraint_screening"],
            ["stage1-evidence-nodes", "stage1-conflict-register"],
            evidence_refs=evidence_ids,
        )
    workpack_ids: list[str] = []
    for index, workpack in enumerate(package.get("workpacks") or []):
        if not isinstance(workpack, dict):
            continue
        workpack_type = str(workpack.get("type") or f"workpack-{index + 1}").strip()
        artifact_id = f"stage1-workpack-{workpack_type}"
        workpack_ids.append(artifact_id)
        add(
            artifact_id,
            "structured_data",
            f"专业工作包：{workpack_type}",
            f"expert_workpacks/{workpack_type}.json",
            workpack,
            ["stage1-evidence-nodes", "stage1-conflict-register"],
            evidence_refs=[
                str(item).strip()
                for item in workpack.get("evidence_refs") or []
                if str(item).strip()
            ],
        )
    if "strategy" in package:
        add(
            "stage1-strategy-options",
            "structured_data",
            "定位方案与比较矩阵",
            "strategy_options.json",
            package["strategy"],
            [
                "stage1-evidence-nodes",
                "stage1-conflict-register",
                "stage1-hard-constraint-screening",
                *workpack_ids,
            ],
            evidence_refs=evidence_ids,
        )
    matrix_dependencies = ["stage1-strategy-options", *workpack_ids]
    if "spatial_object_registry" in package:
        add(
            "stage1-spatial-object-registry",
            "diagnostic_report",
            "权威空间对象目录诊断",
            "spatial_object_registry.json",
            package["spatial_object_registry"],
            input_artifact_ids,
        )
        matrix_dependencies.append("stage1-spatial-object-registry")
    matrix_repair = package.get("spatial_matrix_repair")
    if isinstance(matrix_repair, dict):
        add(
            "stage1-spatial-matrix-repair",
            "diagnostic_report",
            "空间矩阵契约自主修复记录",
            "spatial_matrix_repair.json",
            matrix_repair,
            matrix_dependencies,
            evidence_refs=evidence_ids,
        )
        matrix_dependencies = [
            *matrix_dependencies,
            "stage1-spatial-matrix-repair",
        ]
    if "spatial_matrix" in package:
        add(
            "stage1-decision-matrix",
            "structured_data",
            "空间功能策划决策矩阵",
            "decision_matrix.json",
            package["spatial_matrix"],
            matrix_dependencies,
            evidence_refs=evidence_ids,
        )
    auditable_ids = {
        "stage1-evidence-nodes",
        "stage1-conflict-register",
        "stage1-hard-constraint-screening",
        "stage1-strategy-options",
        "stage1-decision-matrix",
        "stage1-spatial-matrix-repair",
        "stage1-spatial-object-registry",
        *workpack_ids,
    }
    audited_artifact_ids = [
        item.artifact_id for item in artifacts if item.artifact_id in auditable_ids
    ]
    repair_plan = package.get("repair_plan")
    repair_recorded = (
        isinstance(repair_plan, dict) and repair_plan.get("status") != "not_needed"
    )
    if repair_recorded:
        add(
            "stage1-quality-repair",
            "diagnostic_report",
            "自主质量修复计划与记录",
            "quality_repair.json",
            {
                "plan": repair_plan,
                "attempts": package.get("repair_attempts") or [],
            },
            audited_artifact_ids,
            evidence_refs=evidence_ids,
        )
    if "quality_audit" in package:
        add(
            "stage1-quality-audit",
            "diagnostic_report",
            "交付质量审计",
            "quality_audit.json",
            package["quality_audit"],
            [
                *audited_artifact_ids,
                *(["stage1-quality-repair"] if repair_recorded else []),
            ],
            evidence_refs=evidence_ids,
        )
    if report_markdown:
        add(
            "stage1-report",
            "report",
            "Stage 1 主报告",
            "stage1_report.md",
            report_markdown,
            [
                "stage1-evidence-nodes",
                "stage1-strategy-options",
                "stage1-decision-matrix",
            ],
            evidence_refs=evidence_ids,
        )
    if evidence_appendix:
        add(
            "stage1-evidence-appendix",
            "evidence_nodes",
            "证据附录",
            "evidence_appendix.md",
            evidence_appendix,
            ["stage1-evidence-nodes", "stage1-conflict-register"],
            evidence_refs=evidence_ids,
        )
    if design_handoff is not None:
        add(
            "stage1-design-handoff",
            "design_handoff",
            "设计任务书",
            "design_handoff.json",
            design_handoff,
            ["stage1-strategy-options", "stage1-decision-matrix"],
            evidence_refs=evidence_ids,
        )
    if include_manifest:
        add(
            "stage1-run-manifest",
            "diagnostic_report",
            "运行清单",
            "run_manifest.json",
            None,
            [item.artifact_id for item in artifacts],
        )
    return artifacts
