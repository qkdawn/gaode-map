from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DataQualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    dimension: Literal["provenance", "freshness", "sample", "spatial"]
    severity: Literal["error", "warning"]
    evidence_id: str = ""
    message: str
    repair_hint: str = ""


class Stage1DataQualitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "passed_with_gaps", "failed"]
    assessed_count: int = 0
    analytic_count: int = 0
    critical_evidence_ids: list[str] = Field(default_factory=list)
    coverage: dict[str, int] = Field(default_factory=dict)
    coordinate_systems: list[str] = Field(default_factory=list)
    stale_evidence_ids: list[str] = Field(default_factory=list)
    issues: list[DataQualityIssue] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[DataQualityIssue]:
        return [item for item in self.issues if item.severity == "error"]


_ANALYTIC_EVIDENCE_TYPES = {"G", "P", "V"}
_ANALYTIC_MAX_AGE_YEARS = 3
_UNKNOWN_VALUES = {"", "unknown", "未知", "未提供", "not_available"}
_NOT_APPLICABLE_VALUES = {"not_applicable", "n/a", "na", "不适用"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _known(value: Any) -> bool:
    normalized = _text(value).lower()
    return (
        normalized not in _UNKNOWN_VALUES and normalized not in _NOT_APPLICABLE_VALUES
    )


def _applicable(value: Any) -> bool:
    return _text(value).lower() not in _NOT_APPLICABLE_VALUES


def _year(value: Any) -> int | None:
    text = _text(value)
    if not text or text.lower() in _UNKNOWN_VALUES:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).year
    except ValueError:
        pass
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _issue(
    code: str,
    dimension: Literal["provenance", "freshness", "sample", "spatial"],
    message: str,
    *,
    evidence_id: str = "",
    repair_hint: str = "",
    blocking: bool = False,
) -> DataQualityIssue:
    return DataQualityIssue(
        code=code,
        dimension=dimension,
        severity="error" if blocking else "warning",
        evidence_id=evidence_id,
        message=message,
        repair_hint=repair_hint,
    )


def assess_stage1_data_quality(
    ledger: list[dict[str, Any]],
    *,
    critical_evidence_ids: set[str] | None = None,
    as_of: date | None = None,
) -> Stage1DataQualitySummary:
    """Audit evidence provenance, freshness, sample diagnostics and spatial metadata.

    Missing metadata becomes blocking only when the evidence supports the recommended
    strategy or a deliverable space decision. This keeps unrelated evidence gaps visible
    without allowing them to invalidate a decision they do not support.
    """

    current_date = as_of or date.today()
    critical_ids = {item for item in (critical_evidence_ids or set()) if item}
    nodes = [dict(item) for item in ledger if isinstance(item, dict)]
    issues: list[DataQualityIssue] = []
    stale_ids: list[str] = []
    coordinate_systems: set[str] = set()
    coverage = {
        "source_date": 0,
        "source_locator": 0,
        "analysis_date": 0,
        "sample_diagnostics": 0,
        "coordinate_system": 0,
    }

    analytic_nodes: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        evidence_id = _text(node.get("id")) or f"evidence-{index + 1}"
        blocking = evidence_id in critical_ids
        evidence_type = _text(node.get("evidence_type"))
        analytic = evidence_type in _ANALYTIC_EVIDENCE_TYPES
        if analytic:
            analytic_nodes.append(node)

        source_date = node.get("source_date")
        if _known(source_date):
            coverage["source_date"] += 1
        else:
            issues.append(
                _issue(
                    "source_date_missing",
                    "freshness",
                    f"证据 {evidence_id} 未提供来源日期，无法判断时效性。",
                    evidence_id=evidence_id,
                    repair_hint="补充来源发布年份或 ISO 日期；无法确认时明确标记 unknown 并降低结论强度。",
                    blocking=blocking,
                )
            )

        source_locator = node.get("source_locator")
        if _known(source_locator):
            coverage["source_locator"] += 1
        else:
            issues.append(
                _issue(
                    "source_locator_missing",
                    "provenance",
                    f"证据 {evidence_id} 缺少可下钻的页码、节点或分析产物定位。",
                    evidence_id=evidence_id,
                    repair_hint="写入文档页码/章节/节点 ID，或分析 artifact 路径与结果键。",
                    blocking=blocking,
                )
            )

        if not analytic:
            continue

        analysis_date = node.get("analysis_date")
        if _known(analysis_date):
            coverage["analysis_date"] += 1
        else:
            issues.append(
                _issue(
                    "analysis_date_missing",
                    "freshness",
                    f"分析证据 {evidence_id} 未记录计算日期。",
                    evidence_id=evidence_id,
                    repair_hint="从分析产物元数据写入 analysis_date，禁止用当前日期猜测。",
                    blocking=blocking,
                )
            )

        source_year = _year(source_date)
        if (
            source_year is not None
            and current_date.year - source_year > _ANALYTIC_MAX_AGE_YEARS
        ):
            stale_ids.append(evidence_id)
            issues.append(
                _issue(
                    "analytic_source_stale",
                    "freshness",
                    f"分析证据 {evidence_id} 的来源年份为 {source_year}，距当前分析超过 {_ANALYTIC_MAX_AGE_YEARS} 年。",
                    evidence_id=evidence_id,
                    repair_hint="更新数据，或把结论降级为历史背景并补充当前口径交叉验证。",
                    blocking=blocking,
                )
            )

        coordinate_system = _text(node.get("coordinate_system"))
        if _known(coordinate_system) and _applicable(coordinate_system):
            coverage["coordinate_system"] += 1
            coordinate_systems.add(coordinate_system)
        else:
            issues.append(
                _issue(
                    "coordinate_system_missing",
                    "spatial",
                    f"空间分析证据 {evidence_id} 未记录坐标系。",
                    evidence_id=evidence_id,
                    repair_hint="从分析 artifact 写入 EPSG/GCJ-02 等实际坐标口径及必要的转换说明。",
                    blocking=blocking,
                )
            )

        quality_counts = {
            key: _count(node.get(key))
            for key in (
                "sample_size",
                "missing_count",
                "duplicate_count",
                "anomaly_count",
            )
        }
        if all(value is not None for value in quality_counts.values()):
            coverage["sample_diagnostics"] += 1
            sample_size = quality_counts["sample_size"] or 0
            defect_counts = {
                key: quality_counts[key] or 0
                for key in ("missing_count", "duplicate_count", "anomaly_count")
            }
            impossible_counts = [
                key for key, value in defect_counts.items() if value > sample_size
            ]
            if impossible_counts and sample_size > 0:
                issues.append(
                    _issue(
                        "sample_diagnostics_inconsistent",
                        "sample",
                        f"分析证据 {evidence_id} 的单项质量计数超过样本量：{'、'.join(impossible_counts)}。",
                        evidence_id=evidence_id,
                        repair_hint="回到原始分析产物复核样本量与缺失、重复、异常统计口径。",
                        blocking=True,
                    )
                )
            elif sample_size == 0:
                issues.append(
                    _issue(
                        "sample_empty",
                        "sample",
                        f"分析证据 {evidence_id} 的样本量为 0。",
                        evidence_id=evidence_id,
                        repair_hint="重新生成有效分析结果，或将该证据状态改为 blocked。",
                        blocking=blocking,
                    )
                )
            elif any(defect_counts.values()):
                issues.append(
                    _issue(
                        "sample_quality_gaps",
                        "sample",
                        (
                            f"分析证据 {evidence_id} 存在质量缺口："
                            f"缺失 {defect_counts['missing_count']}、重复 {defect_counts['duplicate_count']}、"
                            f"异常 {defect_counts['anomaly_count']}。"
                        ),
                        evidence_id=evidence_id,
                        repair_hint="在 limitation 中解释清洗规则、计数是否重叠及其对结论的影响。",
                    )
                )
        else:
            issues.append(
                _issue(
                    "sample_diagnostics_missing",
                    "sample",
                    f"分析证据 {evidence_id} 缺少样本量、缺失、重复或异常诊断。",
                    evidence_id=evidence_id,
                    repair_hint="从分析产物写入 sample_size、missing_count、duplicate_count、anomaly_count。",
                    blocking=blocking,
                )
            )

    if len(coordinate_systems) > 1:
        missing_transform_ids = [
            _text(node.get("id"))
            for node in analytic_nodes
            if _text(node.get("coordinate_system")) in coordinate_systems
            and not _known(node.get("coordinate_transform"))
        ]
        if missing_transform_ids:
            issues.append(
                _issue(
                    "coordinate_system_mismatch",
                    "spatial",
                    f"分析证据使用多个坐标系（{'、'.join(sorted(coordinate_systems))}），但缺少统一转换记录。",
                    repair_hint="在各分析 artifact 中登记转换链、目标坐标系和转换后的范围校验。",
                    blocking=bool(critical_ids.intersection(missing_transform_ids)),
                )
            )

    blocking_issues = [item for item in issues if item.severity == "error"]
    if blocking_issues:
        status = "failed"
    elif issues:
        status = "passed_with_gaps"
    else:
        status = "passed"
    return Stage1DataQualitySummary(
        status=status,
        assessed_count=len(nodes),
        analytic_count=len(analytic_nodes),
        critical_evidence_ids=sorted(critical_ids),
        coverage=coverage,
        coordinate_systems=sorted(coordinate_systems),
        stale_evidence_ids=stale_ids,
        issues=issues,
    )
