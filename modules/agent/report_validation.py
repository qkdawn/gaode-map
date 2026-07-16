from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from modules.evidence_retrieval.schemas import EvidenceNode

from .analysis_runs import AnalysisRun


CATALOG_PATH = Path(__file__).resolve().parents[2] / "skills" / "spatial-business-analyst" / "references" / "metric-catalog.yaml"
_CITATION_RE = re.compile(r"\[([A-Z]\d+)\]")
_RELATIVE_TERMS = ("较高", "较低", "高于", "低于", "领先", "落后", "优势", "短板", "最密集", "最多", "最少")


class ReportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    run_id: str
    markdown: str
    citations: dict[str, list[str]] = Field(default_factory=dict)


class ReportViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    citation_label: str = ""
    node_id: str = ""
    metric_id: str = ""
    allowed_expression: str = ""


class ReportValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publishable: bool
    report: ReportArtifact | None = None
    violations: list[ReportViolation] = Field(default_factory=list)
    attempts: int = 1


def _catalog_metrics(path: Path = CATALOG_PATH) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(item.get("id") or ""): item for item in payload.get("metrics") or [] if item.get("id")}


def _sentence_for_label(markdown: str, label: str) -> str:
    for line in markdown.splitlines():
        if f"[{label}]" in line:
            return line.strip()
    return ""


def validate_report(
    report: ReportArtifact,
    *,
    run: AnalysisRun,
    evidence_nodes: list[EvidenceNode],
    catalog_path: Path = CATALOG_PATH,
) -> ReportValidationResult:
    nodes = {node.id: node for node in evidence_nodes}
    metrics = _catalog_metrics(catalog_path)
    planned_entries = {item.plan_entry_id: item for item in run.metric_plan.entries}
    succeeded = {
        (attempt.metric_id, node_id)
        for attempt in run.metric_attempts
        if attempt.execution_status == "succeeded"
        and attempt.plan_entry_id in planned_entries
        and planned_entries[attempt.plan_entry_id].role != "excluded"
        for node_id in attempt.evidence_node_ids
    }
    violations: list[ReportViolation] = []
    if report.run_id != run.run_id:
        violations.append(ReportViolation(code="report_run_mismatch", message="报告不属于当前 AnalysisRun。"))

    referenced_labels = set(_CITATION_RE.findall(report.markdown))
    if evidence_nodes and not referenced_labels:
        violations.append(
            ReportViolation(
                code="report_citations_missing",
                message="报告正文没有引用当前 AnalysisRun 的 EvidenceNode。",
                allowed_expression="为每个主要事实添加 [E1] 形式的引用，并在 citations 中映射真实节点 ID。",
            )
        )
    for label in sorted(referenced_labels - set(report.citations)):
        violations.append(ReportViolation(code="citation_mapping_missing", message=f"正文引用 {label} 缺少节点映射。", citation_label=label))

    for label, node_ids in report.citations.items():
        sentence = _sentence_for_label(report.markdown, label)
        for node_id in node_ids:
            node = nodes.get(node_id)
            if node is None:
                violations.append(ReportViolation(code="evidence_node_missing", message="引用节点不存在。", citation_label=label, node_id=node_id))
                continue
            if node.run_id and node.run_id != run.run_id:
                violations.append(ReportViolation(code="cross_run_citation", message="引用节点属于其他 AnalysisRun。", citation_label=label, node_id=node_id))
            for metric_id in node.metric_ids:
                metric = metrics.get(metric_id)
                if metric is None:
                    violations.append(ReportViolation(code="metric_not_cataloged", message="节点引用了目录外指标。", citation_label=label, node_id=node_id, metric_id=metric_id))
                    continue
                if metric.get("implementation_status") != "implemented":
                    violations.append(ReportViolation(code="metric_not_implemented", message="报告引用了未实现指标。", citation_label=label, node_id=node_id, metric_id=metric_id))
                planned_roles = {
                    planned_entries[attempt.plan_entry_id].role
                    for attempt in run.metric_attempts
                    if attempt.metric_id == metric_id
                    and node_id in attempt.evidence_node_ids
                    and attempt.plan_entry_id in planned_entries
                }
                if not planned_roles:
                    violations.append(ReportViolation(code="metric_not_planned", message="报告引用了未进入 MetricPlan 的指标。", citation_label=label, node_id=node_id, metric_id=metric_id))
                elif "excluded" in planned_roles:
                    violations.append(ReportViolation(code="excluded_metric_cited", message="报告引用了已排除指标。", citation_label=label, node_id=node_id, metric_id=metric_id))
                if (metric_id, node_id) not in succeeded:
                    violations.append(ReportViolation(code="metric_attempt_not_succeeded", message="指标本次运行未成功产出该节点。", citation_label=label, node_id=node_id, metric_id=metric_id))
                for boundary in metric.get("does_not_support") or []:
                    boundary_text = str(boundary).strip()
                    if boundary_text and boundary_text in sentence:
                        violations.append(ReportViolation(
                            code="catalog_semantic_overreach",
                            message=f"结论越过 {metric_id} 的解释边界。",
                            citation_label=label,
                            node_id=node_id,
                            metric_id=metric_id,
                            allowed_expression=f"仅陈述 {metric.get('supports', ['该指标的直接观测结果'])[0]}。",
                        ))
                if metric.get("proxy") and any(term in sentence for term in ("证明", "确定", "必然", "真实")):
                    violations.append(ReportViolation(code="proxy_promoted_to_fact", message="代理指标被升级为直接事实。", citation_label=label, node_id=node_id, metric_id=metric_id))
            if any(term in sentence for term in _RELATIVE_TERMS) and not node.data.get("comparison_baseline"):
                violations.append(ReportViolation(
                    code="comparison_baseline_missing",
                    message="相对判断缺少可追溯比较基准。",
                    citation_label=label,
                    node_id=node_id,
                    allowed_expression="改为描述当前范围的绝对观测值，并说明缺少比较基准。",
                ))
    return ReportValidationResult(publishable=not violations, report=report if not violations else None, violations=violations)


def generate_validated_report(
    generator: Callable[[list[ReportViolation]], ReportArtifact],
    *,
    run: AnalysisRun,
    evidence_nodes: list[EvidenceNode],
    max_rewrites: int = 2,
) -> ReportValidationResult:
    violations: list[ReportViolation] = []
    for attempt in range(max_rewrites + 1):
        report = generator(violations)
        result = validate_report(report, run=run, evidence_nodes=evidence_nodes)
        result.attempts = attempt + 1
        if result.publishable:
            return result
        violations = result.violations
    return ReportValidationResult(publishable=False, report=None, violations=violations, attempts=max_rewrites + 1)


async def generate_validated_report_async(
    generator: Callable[[list[ReportViolation]], Awaitable[ReportArtifact]],
    *,
    run: AnalysisRun,
    evidence_nodes: list[EvidenceNode],
    max_rewrites: int = 2,
) -> ReportValidationResult:
    """Generate and validate without persisting a parallel claim object."""

    violations: list[ReportViolation] = []
    for attempt in range(max_rewrites + 1):
        report = await generator(violations)
        result = validate_report(report, run=run, evidence_nodes=evidence_nodes)
        result.attempts = attempt + 1
        if result.publishable:
            return result
        violations = result.violations
    return ReportValidationResult(
        publishable=False,
        report=None,
        violations=violations,
        attempts=max_rewrites + 1,
    )
