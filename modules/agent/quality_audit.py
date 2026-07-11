from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AuditIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    message: str
    path: str = ""
    repair_hint: str = ""


class QualityAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed"]
    score: int = Field(ge=0, le=100)
    checks_passed: int = 0
    checks_total: int = 0
    issues: list[AuditIssue] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[AuditIssue]:
        return [item for item in self.issues if item.severity == "error"]


_EVIDENCE_TYPES = {"F", "G", "P", "H", "V"}
_CLAIM_STATUSES = {
    "verified",
    "cross_checked",
    "inferred",
    "hypothesis",
    "blocked",
    "fieldwork_required",
}
_RECOMMENDATION_STATUSES = {"strong", "conditional", "alternative", "excluded"}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}
_PROXY_OVERREACH = (
    (
        re.compile(r"夜光.{0,8}(消费金额|支付能力|客流)"),
        "夜光只能作为活动强度代理，不能直接代表消费或客流",
    ),
    (
        re.compile(r"POI.{0,8}(坪效|消费需求|经营收入)"),
        "POI 供给不能直接代表经营绩效或真实需求",
    ),
    (
        re.compile(r"gap_score.{0,8}(成功率|开店成功|消费力)"),
        "gap_score 不能解释为经营成功概率",
    ),
    (re.compile(r"周边人口.{0,8}(项目客流|到访量)"), "周边人口不能直接等同于项目客流"),
)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _issue(
    code: str,
    message: str,
    *,
    path: str = "",
    repair_hint: str = "",
    warning: bool = False,
) -> AuditIssue:
    return AuditIssue(
        code=code,
        severity="warning" if warning else "error",
        message=message,
        path=path,
        repair_hint=repair_hint,
    )


def audit_stage1_package(package: dict[str, Any]) -> QualityAuditResult:
    issues: list[AuditIssue] = []
    checks_total = 9
    checks_passed = 0
    ledger = _list(package.get("evidence_ledger"))
    workpacks = _list(package.get("workpacks"))
    strategy = (
        package.get("strategy") if isinstance(package.get("strategy"), dict) else {}
    )
    matrix = (
        package.get("spatial_matrix")
        if isinstance(package.get("spatial_matrix"), dict)
        else {}
    )

    if ledger:
        invalid_nodes = []
        for index, node in enumerate(ledger):
            node = node if isinstance(node, dict) else {}
            required_text = (
                "id",
                "claim",
                "source_ref",
                "scope",
                "limitation",
            )
            if (
                any(not _text(node.get(field)) for field in required_text)
                or node.get("evidence_type") not in _EVIDENCE_TYPES
                or node.get("status") not in _CLAIM_STATUSES
                or node.get("confidence") not in _CONFIDENCE_LEVELS
            ):
                invalid_nodes.append(index)
        if invalid_nodes:
            issues.append(
                _issue(
                    "evidence_contract_invalid",
                    "证据节点缺少稳定 ID、F/G/P/H/V 类型、验证状态或来源定位。",
                    path="evidence_ledger",
                    repair_hint="逐条补齐 id、evidence_type、status、source_ref、scope 和 limitation。",
                )
            )
        else:
            checks_passed += 1
    else:
        issues.append(
            _issue(
                "evidence_ledger_missing", "未生成证据台账。", path="evidence_ledger"
            )
        )

    evidence_ids = {
        _text(node.get("id")) for node in ledger if isinstance(node, dict) and _text(node.get("id"))
    }
    referenced_ids: set[str] = set()
    for workpack in workpacks:
        if isinstance(workpack, dict):
            referenced_ids.update(_text(item) for item in _list(workpack.get("evidence_refs")) if _text(item))
    for option in _list(strategy.get("options")):
        if isinstance(option, dict):
            referenced_ids.update(_text(item) for item in _list(option.get("evidence_refs")) if _text(item))
    for decision in _list(matrix.get("space_decisions")):
        if isinstance(decision, dict):
            referenced_ids.update(_text(item) for item in _list(decision.get("evidence_refs")) if _text(item))
    unknown_refs = sorted(referenced_ids - evidence_ids)
    if referenced_ids and not unknown_refs:
        checks_passed += 1
    else:
        message = (
            f"专业结论引用了证据台账中不存在的 ID：{'、'.join(unknown_refs)}。"
            if unknown_refs
            else "专业工作包、定位方案和空间决策没有形成可追溯的证据引用。"
        )
        issues.append(
            _issue(
                "evidence_reference_invalid",
                message,
                path="workpacks/strategy/spatial_matrix",
                repair_hint="只引用本轮证据台账中的稳定 evidence id，并为专业结论补齐引用。",
            )
        )

    required_workpacks = {
        "spatial",
        "audience",
        "culture_tourism",
        "renewal_operations",
    }
    actual_workpacks = {
        _text(item.get("type")) for item in workpacks if isinstance(item, dict)
    }
    if required_workpacks.issubset(actual_workpacks):
        checks_passed += 1
    else:
        missing = sorted(required_workpacks - actual_workpacks)
        issues.append(
            _issue(
                "workpacks_incomplete",
                f"专业工作包不完整，缺少：{'、'.join(missing)}。",
                path="workpacks",
                repair_hint="分别完成区域结构、人群场景、文化文旅、存量更新与运营工作包。",
            )
        )

    options = _list(strategy.get("options"))
    option_ids = {_text(item.get("id")) for item in options if isinstance(item, dict)}
    recommended_id = _text(strategy.get("recommended_option_id"))
    if len(options) >= 3 and recommended_id in option_ids:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "strategy_competition_missing",
                "定位方案不足三个，或首选方案未通过稳定 ID 指向候选集合。",
                path="strategy",
                repair_hint="提供至少三个实质不同的定位，包含证据、反证、淘汰理由和失效条件。",
            )
        )

    incomplete_options = [
        index
        for index, option in enumerate(options)
        if not isinstance(option, dict)
        or not _list(option.get("evidence_refs"))
        or not _list(option.get("counter_evidence"))
        or not _list(option.get("invalidation_conditions"))
    ]
    if options and not incomplete_options:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "strategy_falsification_missing",
                "定位方案缺少证据、反证或失效条件。",
                path="strategy.options",
                repair_hint="每个方案必须说明支持证据、反对证据和何时应放弃。",
            )
        )

    hierarchy = _list(matrix.get("spatial_hierarchy"))
    levels = {_text(item.get("level")) for item in hierarchy if isinstance(item, dict)}
    if {"system", "cluster", "unit"}.issubset(levels):
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "spatial_hierarchy_incomplete",
                "空间层级未同时覆盖系统、组团和单元。",
                path="spatial_matrix.spatial_hierarchy",
            )
        )

    decisions = _list(matrix.get("space_decisions"))
    invalid_decisions = []
    for index, decision in enumerate(decisions):
        decision = decision if isinstance(decision, dict) else {}
        candidates = _list(decision.get("candidate_functions"))
        audience = _list(decision.get("audience_scenarios"))
        if (
            not _text(decision.get("space_id"))
            or len(candidates) < 2
            or not isinstance(decision.get("preferred_function"), dict)
            or not _list(decision.get("excluded_functions"))
            or not _list(decision.get("preconditions"))
            or not _list(decision.get("evidence_refs"))
            or not audience
            or decision.get("recommendation_status") not in _RECOMMENDATION_STATUSES
            or decision.get("confidence") not in _CONFIDENCE_LEVELS
        ):
            invalid_decisions.append(index)
    if decisions and not invalid_decisions:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "space_decisions_incomplete",
                "关键空间缺少候选比较、排除理由、客群场景、前置条件、证据或推荐强度。",
                path="spatial_matrix.space_decisions",
                repair_hint="每个空间至少比较两个候选，并给出首选、排除项、场景化客群和成立条件。",
            )
        )

    if _list(matrix.get("portfolio_checks")):
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "portfolio_check_missing",
                "缺少项目级引流、收入、公共服务、后勤、居民和分期平衡检查。",
                path="spatial_matrix.portfolio_checks",
            )
        )

    serialized = str(package)
    overreach = [
        message for pattern, message in _PROXY_OVERREACH if pattern.search(serialized)
    ]
    if not overreach:
        checks_passed += 1
    else:
        for message in overreach:
            issues.append(
                _issue(
                    "proxy_overreach",
                    message,
                    repair_hint="降级为代理信号并补充验证边界。",
                )
            )

    errors = [item for item in issues if item.severity == "error"]
    score = round(100 * checks_passed / checks_total)
    return QualityAuditResult(
        status="failed" if errors else "passed",
        score=score,
        checks_passed=checks_passed,
        checks_total=checks_total,
        issues=issues,
    )
