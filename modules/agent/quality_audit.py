from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .stage1_data_quality import Stage1DataQualitySummary
from .stage1_hard_constraints import HARD_CONSTRAINT_DEFINITIONS
from .stage1_provenance import Stage1ProvenanceSummary


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
    checks_total = 18
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
    conflict_register = _list(package.get("conflict_register"))
    data_quality_payload = package.get("data_quality")
    provenance_payload = package.get("provenance_binding")
    hard_constraint_screening = (
        package.get("hard_constraint_screening")
        if isinstance(package.get("hard_constraint_screening"), dict)
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

    ledger_nodes = [node for node in ledger if isinstance(node, dict)]
    evidence_id_list = [
        _text(node.get("id")) for node in ledger_nodes if _text(node.get("id"))
    ]
    evidence_ids = set(evidence_id_list)
    duplicate_ids = sorted(
        {item for item in evidence_id_list if evidence_id_list.count(item) > 1}
    )
    if not duplicate_ids:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "evidence_id_duplicate",
                f"证据台账存在重复 ID：{'、'.join(duplicate_ids)}。",
                path="evidence_ledger",
                repair_hint="为每条证据生成唯一稳定 ID，禁止后写节点覆盖前一条证据。",
            )
        )

    incomplete_provenance = [
        _text(node.get("id")) or str(index)
        for index, node in enumerate(ledger_nodes)
        if not _text(node.get("source_artifact_id")) or not _text(node.get("method"))
    ]
    if ledger_nodes and not incomplete_provenance:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "evidence_provenance_incomplete",
                "证据节点缺少可追溯的来源 artifact 或取得/计算方法。",
                path="evidence_ledger",
                repair_hint="逐条补齐 source_artifact_id 和 method；文档证据保留节点 ID，计算证据写明算法。",
            )
        )
    try:
        data_quality = Stage1DataQualitySummary.model_validate(data_quality_payload)
    except ValidationError:
        data_quality = None
    if data_quality is None:
        issues.append(
            _issue(
                "data_quality_missing",
                "缺少稳定的数据质量诊断结果。",
                path="data_quality",
                repair_hint="对证据台账执行来源日期、定位、样本和空间口径审计后再进入交付。",
            )
        )
    else:
        for item in data_quality.issues:
            issues.append(
                _issue(
                    item.code,
                    item.message,
                    path=(
                        f"evidence_ledger.{item.evidence_id}"
                        if item.evidence_id
                        else "data_quality"
                    ),
                    repair_hint=item.repair_hint,
                    warning=item.severity == "warning",
                )
            )
        if not data_quality.blocking_issues:
            checks_passed += 1

    try:
        provenance = Stage1ProvenanceSummary.model_validate(provenance_payload)
    except ValidationError:
        provenance = None
    if provenance is None:
        issues.append(
            _issue(
                "provenance_binding_missing",
                "缺少证据与真实文档节点或分析产物的绑定结果。",
                path="provenance_binding",
                repair_hint="用后端权威 artifact 注册表重新绑定证据，禁止只信任模型声明。",
            )
        )
    else:
        for item in provenance.issues:
            issues.append(
                _issue(
                    item.code,
                    item.message,
                    path=f"evidence_ledger.{item.evidence_id}",
                    repair_hint=item.repair_hint,
                    warning=item.severity == "warning",
                )
            )
        bound_ids = {item.evidence_id for item in provenance.bindings}
        if bound_ids != evidence_ids:
            missing_ids = sorted(evidence_ids - bound_ids)
            extra_ids = sorted(bound_ids - evidence_ids)
            details = []
            if missing_ids:
                details.append(f"未绑定：{'、'.join(missing_ids)}")
            if extra_ids:
                details.append(f"无对应证据：{'、'.join(extra_ids)}")
            issues.append(
                _issue(
                    "provenance_binding_coverage_invalid",
                    "证据溯源绑定未完整覆盖当前台账；" + "；".join(details) + "。",
                    path="provenance_binding.bindings",
                    repair_hint="对最终证据台账逐条重新执行 artifact 绑定。",
                )
            )
        elif not provenance.blocking_issues:
            checks_passed += 1

    referenced_ids: set[str] = set()
    for workpack in workpacks:
        if isinstance(workpack, dict):
            referenced_ids.update(
                _text(item)
                for item in _list(workpack.get("evidence_refs"))
                if _text(item)
            )
    for option in _list(strategy.get("options")):
        if isinstance(option, dict):
            referenced_ids.update(
                _text(item)
                for item in _list(option.get("evidence_refs"))
                if _text(item)
            )
    for decision in _list(matrix.get("space_decisions")):
        if isinstance(decision, dict):
            referenced_ids.update(
                _text(item)
                for item in _list(decision.get("evidence_refs"))
                if _text(item)
            )
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

    required_constraint_ids = {
        item.constraint_id for item in HARD_CONSTRAINT_DEFINITIONS
    }
    constraint_assessments = _list(hard_constraint_screening.get("assessments"))
    constraint_by_id = {
        _text(item.get("constraint_id")): item
        for item in constraint_assessments
        if isinstance(item, dict) and _text(item.get("constraint_id"))
    }
    valid_constraint_states = {"verified", "constrained", "unknown", "not_applicable"}
    valid_constraint_effects = {"allow", "condition", "exclude"}
    invalid_constraints = []
    for constraint_id in sorted(required_constraint_ids):
        item = constraint_by_id.get(constraint_id, {})
        state = item.get("state")
        effect = item.get("decision_effect")
        refs = {_text(ref) for ref in _list(item.get("evidence_refs")) if _text(ref)}
        requires_action = state in {"unknown", "constrained"} or effect in {"condition", "exclude"}
        if (
            state not in valid_constraint_states
            or effect not in valid_constraint_effects
            or not _text(item.get("finding"))
            or bool(refs - evidence_ids)
            or (state in {"verified", "not_applicable"} and not refs)
            or (requires_action and not _text(item.get("verification_action")))
        ):
            invalid_constraints.append(constraint_id)
    declared_required_ids = {
        _text(item)
        for item in _list(hard_constraint_screening.get("required_constraint_ids"))
        if _text(item)
    }
    expected_screening_status = (
        "blocked"
        if any(item.get("decision_effect") == "exclude" for item in constraint_by_id.values())
        else "conditional"
        if any(
            item.get("state") in {"unknown", "constrained"}
            or item.get("decision_effect") == "condition"
            for item in constraint_by_id.values()
        )
        else "clear"
    )
    if (
        set(constraint_by_id) == required_constraint_ids
        and len(constraint_assessments) == len(required_constraint_ids)
        and declared_required_ids == required_constraint_ids
        and not invalid_constraints
        and hard_constraint_screening.get("status") == expected_screening_status
    ):
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "hard_constraint_screening_invalid",
                "产权、消防、结构、排污、停车装卸、无障碍或居民噪声约束未形成完整可核验筛选。",
                path="hard_constraint_screening",
                repair_hint="逐项登记状态、决策影响、证据和核验动作；没有证据时保留 unknown，不得猜测为已满足。",
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

    matrix_positioning_id = _text(matrix.get("positioning_option_id"))
    if matrix_positioning_id and matrix_positioning_id == recommended_id:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "matrix_positioning_mismatch",
                "空间功能矩阵未明确绑定到首选定位方案。",
                path="spatial_matrix.positioning_option_id",
                repair_hint="使用 strategy.recommended_option_id 作为矩阵唯一 positioning_option_id 后重新生成。",
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

    evidence_by_id = {_text(node.get("id")): node for node in ledger_nodes}
    recommended_option = next(
        (
            item
            for item in options
            if isinstance(item, dict) and _text(item.get("id")) == recommended_id
        ),
        {},
    )
    recommended_refs = {
        _text(item)
        for item in _list(recommended_option.get("evidence_refs"))
        if _text(item)
    }
    direct_statuses = {"verified", "cross_checked"}
    has_direct_recommendation_evidence = any(
        evidence_by_id.get(evidence_id, {}).get("status") in direct_statuses
        for evidence_id in recommended_refs
    )

    unresolved_conflicts = [
        item
        for item in conflict_register
        if isinstance(item, dict) and item.get("unresolved") is True
    ]
    conflicted_artifact_ids = {
        _text(evidence_id)
        for conflict in unresolved_conflicts
        for evidence_id in _list(conflict.get("evidence_ids"))
        if _text(evidence_id)
    }
    conflicted_ledger_ids = {
        _text(node.get("id"))
        for node in ledger_nodes
        if _text(node.get("source_artifact_id")) in conflicted_artifact_ids
        or _text(node.get("id")) in conflicted_artifact_ids
    }
    strong_conflicted_spaces = [
        _text(decision.get("space_id")) or str(index)
        for index, decision in enumerate(_list(matrix.get("space_decisions")))
        if isinstance(decision, dict)
        and decision.get("recommendation_status") == "strong"
        and conflicted_ledger_ids.intersection(
            {
                _text(item)
                for item in _list(decision.get("evidence_refs"))
                if _text(item)
            }
        )
    ]
    recommendation_uses_conflict = bool(
        recommended_refs.intersection(conflicted_ledger_ids)
    )
    if (
        has_direct_recommendation_evidence
        and not recommendation_uses_conflict
        and not strong_conflicted_spaces
    ):
        checks_passed += 1
    else:
        details = []
        if recommended_refs and not has_direct_recommendation_evidence:
            details.append("首选定位缺少 verified/cross_checked 直接证据")
        if recommendation_uses_conflict:
            details.append("首选定位引用了未解决冲突证据")
        if strong_conflicted_spaces:
            details.append(
                f"强推荐空间依赖冲突证据：{'、'.join(strong_conflicted_spaces)}"
            )
        issues.append(
            _issue(
                "decision_evidence_strength_invalid",
                "；".join(details) or "首选定位没有形成可验证的直接证据支撑。",
                path="strategy/spatial_matrix",
                repair_hint="补充直接证据、解决来源冲突，或将建议降级为条件式推荐并明确失效条件。",
            )
        )
    option_constraint_gaps = []
    for index, option in enumerate(options):
        node = option if isinstance(option, dict) else {}
        refs = {_text(item) for item in _list(node.get("hard_constraint_refs")) if _text(item)}
        if refs != required_constraint_ids or node.get("recommendation_status") not in _RECOMMENDATION_STATUSES:
            option_constraint_gaps.append(_text(node.get("id")) or str(index))
    decision_constraint_gaps = []
    for index, decision in enumerate(_list(matrix.get("space_decisions"))):
        node = decision if isinstance(decision, dict) else {}
        refs = {_text(item) for item in _list(node.get("hard_constraint_refs")) if _text(item)}
        if refs != required_constraint_ids:
            decision_constraint_gaps.append(_text(node.get("space_id")) or str(index))
    conditional_screening = hard_constraint_screening.get("status") == "conditional"
    recommended_status = recommended_option.get("recommendation_status")
    recommendation_conditions_missing = conditional_screening and (
        recommended_status != "conditional"
        or not _list(recommended_option.get("preconditions"))
        or not _list(recommended_option.get("validation_actions"))
    )
    strong_conditional_spaces = [
        _text(item.get("space_id")) or str(index)
        for index, item in enumerate(_list(matrix.get("space_decisions")))
        if isinstance(item, dict)
        and conditional_screening
        and item.get("recommendation_status") == "strong"
    ]
    screening_blocked = hard_constraint_screening.get("status") == "blocked"
    if (
        options
        and not option_constraint_gaps
        and not decision_constraint_gaps
        and not recommendation_conditions_missing
        and not strong_conditional_spaces
        and not screening_blocked
    ):
        checks_passed += 1
    else:
        details = []
        if option_constraint_gaps:
            details.append(f"方案未逐项响应硬约束：{'、'.join(option_constraint_gaps)}")
        if decision_constraint_gaps:
            details.append(f"空间决策未逐项响应硬约束：{'、'.join(decision_constraint_gaps)}")
        if recommendation_conditions_missing:
            details.append("硬约束尚未全部确认，但首选方案未降级并登记前置条件与验证动作")
        if strong_conditional_spaces:
            details.append(f"硬约束未确认时仍标记强推荐：{'、'.join(strong_conditional_spaces)}")
        if screening_blocked:
            details.append("存在 decision_effect=exclude 的硬约束，当前首选方案不可交付")
        issues.append(
            _issue(
                "hard_constraint_application_invalid",
                "；".join(details) or "硬约束未进入定位和空间方案筛选。",
                path="strategy/spatial_matrix",
                repair_hint="让每个定位方案和空间决策引用完整硬约束；未知项降级为条件推荐，排除项解决前不得交付。",
            )
        )

    for conflict in unresolved_conflicts:
        label = (
            _text(conflict.get("label"))
            or _text(conflict.get("metric_key"))
            or "未命名事项"
        )
        issues.append(
            _issue(
                "unresolved_evidence_conflict",
                f"存在尚未解决的来源冲突：{label}。",
                path="conflict_register",
                repair_hint=_text(conflict.get("explanation"))
                or "保留不同来源口径，指定权威来源或登记人工核实任务。",
                warning=True,
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

    incomplete_handoffs = []
    required_handoff_sections = (
        "current_state",
        "change_logic",
        "access_and_movement",
        "operation_strategy",
        "renovation_and_delivery",
    )
    for index, decision in enumerate(decisions):
        node = decision if isinstance(decision, dict) else {}
        if any(
            not isinstance(node.get(field), dict) or not node.get(field)
            for field in required_handoff_sections
        ) or not _list(node.get("validation_actions")):
            incomplete_handoffs.append(index)
    if decisions and not incomplete_handoffs:
        checks_passed += 1
    else:
        issues.append(
            _issue(
                "space_design_handoff_incomplete",
                "空间决策尚未形成可直接交给设计端的现状、改变逻辑、动线、运营、改造交付和验证动作。",
                path="spatial_matrix.space_decisions",
                repair_hint="逐空间补齐 current_state、change_logic、access_and_movement、operation_strategy、renovation_and_delivery 和 validation_actions。",
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
