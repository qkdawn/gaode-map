from __future__ import annotations

from typing import Any

from .capability_inputs import ResolvedCapabilityInputs
from .capability_runs import (
    CapabilityArtifactRef,
    CapabilityArtifactType,
    CapabilityRunRecorder,
    artifact_ref,
)
from .llm_digest import snapshot_digest
from .schemas import AgentTurnRequest, EffectiveExecutionProfile
from .stage1_provenance import ArtifactProvenance


def start_stage1_run(
    payload: AgentTurnRequest,
    *,
    profile: EffectiveExecutionProfile,
    question: str,
    selected_sources: list[dict[str, Any]],
    capability_id: str = "urban-strategy-stage1",
    resolved_inputs: ResolvedCapabilityInputs | None = None,
) -> CapabilityRunRecorder:
    """Lock one Stage 1 configuration before readiness or model execution begins."""

    return CapabilityRunRecorder(
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
    )


def bind_stage1_input_artifacts(
    registry: list[ArtifactProvenance],
) -> list[CapabilityArtifactRef]:
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
) -> list[CapabilityArtifactRef]:
    evidence_ids = [
        str(item.get("id") or "").strip()
        for item in package.get("evidence_ledger") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    artifacts: list[CapabilityArtifactRef] = []

    def add(
        artifact_id: str,
        artifact_type: CapabilityArtifactType,
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
    if "evidence_ledger" in package:
        add(
            "stage1-evidence-ledger",
            "evidence_ledger",
            "证据台账",
            "evidence_ledger.jsonl",
            package["evidence_ledger"],
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
            ["stage1-evidence-ledger"],
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
            ["stage1-evidence-ledger", "stage1-conflict-register"],
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
            ["stage1-evidence-ledger", "stage1-conflict-register", *workpack_ids],
            evidence_refs=evidence_ids,
        )
    if "spatial_matrix" in package:
        add(
            "stage1-decision-matrix",
            "structured_data",
            "空间功能策划决策矩阵",
            "decision_matrix.json",
            package["spatial_matrix"],
            ["stage1-strategy-options", *workpack_ids],
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
                "stage1-evidence-ledger",
                "stage1-strategy-options",
                "stage1-decision-matrix",
            ],
            evidence_refs=evidence_ids,
        )
    if evidence_appendix:
        add(
            "stage1-evidence-appendix",
            "evidence_ledger",
            "证据附录",
            "evidence_appendix.md",
            evidence_appendix,
            ["stage1-evidence-ledger", "stage1-conflict-register"],
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
