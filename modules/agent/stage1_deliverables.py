from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Stage1DeliverableArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    filename: str
    title: str
    format: Literal["markdown", "json"]
    status: Literal["ready"] = "ready"
    summary: str = ""


class DesignSpaceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str
    preferred_function: dict[str, Any] = Field(default_factory=dict)
    candidate_functions: list[Any] = Field(default_factory=list)
    excluded_functions: list[Any] = Field(default_factory=list)
    audience_scenarios: list[Any] = Field(default_factory=list)
    access_and_movement: dict[str, Any] = Field(default_factory=dict)
    operation_strategy: dict[str, Any] = Field(default_factory=dict)
    renovation_and_delivery: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[Any] = Field(default_factory=list)
    assumptions: list[Any] = Field(default_factory=list)
    validation_actions: list[Any] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    recommendation_status: str = ""
    confidence: str = ""


class DesignHandoffContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0"
    positioning_option_id: str
    positioning_option: dict[str, Any] = Field(default_factory=dict)
    matrix_version: str = ""
    spatial_hierarchy: list[dict[str, Any]] = Field(default_factory=list)
    space_requirements: list[DesignSpaceRequirement] = Field(default_factory=list)
    portfolio_requirements: list[Any] = Field(default_factory=list)
    unresolved_constraints: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ledger_ids: list[str] = Field(default_factory=list)


class Stage1Deliverables(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"] = "ready"
    source_contract: str = "audited_stage1_package"
    report_markdown: str
    evidence_appendix_markdown: str
    design_handoff: DesignHandoffContract
    artifacts: list[Stage1DeliverableArtifact] = Field(default_factory=list)


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _markdown_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = str(value)
    else:
        text = _text(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ") or "—"


def _selected_option(strategy: dict[str, Any]) -> dict[str, Any]:
    option_id = _text(strategy.get("recommended_option_id"))
    return next(
        (
            _mapping(option)
            for option in _list(strategy.get("options"))
            if _text(_mapping(option).get("id")) == option_id
        ),
        {},
    )


def _unresolved_constraints(package: dict[str, Any]) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for conflict in _list(package.get("conflict_register")):
        node = _mapping(conflict)
        if node.get("unresolved") is False:
            continue
        constraints.append(
            {
                "type": "evidence_conflict",
                "id": _text(node.get("metric_key")) or _text(node.get("label")),
                "description": _text(node.get("explanation"))
                or _text(node.get("label")),
                "evidence_refs": [
                    _text(item)
                    for item in _list(node.get("evidence_ids"))
                    if _text(item)
                ],
            }
        )
    for evidence in _list(package.get("evidence_ledger")):
        node = _mapping(evidence)
        if node.get("status") not in {"blocked", "fieldwork_required"}:
            continue
        constraints.append(
            {
                "type": _text(node.get("status")),
                "id": _text(node.get("id")),
                "description": _text(node.get("limitation"))
                or _text(node.get("claim")),
                "evidence_refs": [_text(node.get("id"))],
                "next_action": _text(node.get("next_action")),
                "executor": _text(node.get("executor")),
            }
        )
    return constraints


def build_design_handoff(package: dict[str, Any]) -> DesignHandoffContract:
    """Compile the design handoff from the same audited strategy and matrix."""

    strategy = _mapping(package.get("strategy"))
    matrix = _mapping(package.get("spatial_matrix"))
    requirements = []
    for decision in _list(matrix.get("space_decisions")):
        node = _mapping(decision)
        requirements.append(
            DesignSpaceRequirement(
                space_id=_text(node.get("space_id")),
                preferred_function=_mapping(node.get("preferred_function")),
                candidate_functions=_list(node.get("candidate_functions")),
                excluded_functions=_list(node.get("excluded_functions")),
                audience_scenarios=_list(node.get("audience_scenarios")),
                access_and_movement=_mapping(node.get("access_and_movement")),
                operation_strategy=_mapping(node.get("operation_strategy")),
                renovation_and_delivery=_mapping(node.get("renovation_and_delivery")),
                preconditions=_list(node.get("preconditions")),
                assumptions=_list(node.get("assumptions")),
                validation_actions=_list(node.get("validation_actions")),
                evidence_refs=[
                    _text(item)
                    for item in _list(node.get("evidence_refs"))
                    if _text(item)
                ],
                recommendation_status=_text(node.get("recommendation_status")),
                confidence=_text(node.get("confidence")),
            )
        )
    evidence_ids = [
        _text(_mapping(item).get("id"))
        for item in _list(package.get("evidence_ledger"))
        if _text(_mapping(item).get("id"))
    ]
    return DesignHandoffContract(
        positioning_option_id=_text(strategy.get("recommended_option_id")),
        positioning_option=_selected_option(strategy),
        matrix_version=_text(matrix.get("matrix_version")),
        spatial_hierarchy=[
            _mapping(item) for item in _list(matrix.get("spatial_hierarchy"))
        ],
        space_requirements=requirements,
        portfolio_requirements=_list(matrix.get("portfolio_checks")),
        unresolved_constraints=_unresolved_constraints(package),
        evidence_ledger_ids=evidence_ids,
    )


def build_evidence_appendix(package: dict[str, Any]) -> str:
    """Render an immutable evidence appendix from the audited ledger."""

    lines = [
        "# Stage 1 证据附录",
        "",
        "本附录由已通过交付前质量审计的结构化证据台账确定性生成。",
        "",
        "## Claim—Evidence Ledger",
        "",
        "| ID | 类型 | 状态 | 主张 | 来源 | 精确定位 | 范围 | 置信度 | 限制 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for evidence in _list(package.get("evidence_ledger")):
        node = _mapping(evidence)
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(node.get(field))
                for field in (
                    "id",
                    "evidence_type",
                    "status",
                    "claim",
                    "source_ref",
                    "source_locator",
                    "scope",
                    "confidence",
                    "limitation",
                )
            )
            + " |"
        )
    lines.extend(["", "## 来源冲突与待裁决事项", ""])
    conflicts = _list(package.get("conflict_register"))
    if conflicts:
        for conflict in conflicts:
            node = _mapping(conflict)
            state = "未解决" if node.get("unresolved", True) else "已裁决"
            lines.append(
                f"- **{_text(node.get('label')) or _text(node.get('metric_key'))}**"
                f"（{state}）：{_text(node.get('explanation')) or '未提供说明'}"
            )
    else:
        lines.append("- 本轮未登记来源冲突。")
    lines.extend(["", "## 数据质量与真实资产绑定", ""])
    data_quality = _mapping(package.get("data_quality"))
    provenance = _mapping(package.get("provenance_binding"))
    lines.append(
        f"- 数据质量状态：{_text(data_quality.get('status')) or 'unknown'}；"
        f"审计证据 {data_quality.get('assessed_count', 0)} 条。"
    )
    lines.append(
        f"- 真实资产绑定状态：{_text(provenance.get('status')) or 'unknown'}；"
        f"核对证据 {provenance.get('assessed_count', 0)} 条。"
    )
    return "\n".join(lines).strip() + "\n"


def compile_stage1_deliverables(
    package: dict[str, Any], *, report_markdown: str
) -> Stage1Deliverables:
    """Compile all Stage 1 deliverables from one audited source contract."""

    report = _text(report_markdown)
    if not report:
        raise ValueError("Stage 1 主报告为空，不能形成交付物")
    handoff = build_design_handoff(package)
    appendix = build_evidence_appendix(package)
    evidence_count = len(handoff.evidence_ledger_ids)
    space_count = len(handoff.space_requirements)
    return Stage1Deliverables(
        report_markdown=report,
        evidence_appendix_markdown=appendix,
        design_handoff=handoff,
        artifacts=[
            Stage1DeliverableArtifact(
                artifact_id="stage1-report",
                filename="stage1_report.md",
                title="Stage 1 主报告",
                format="markdown",
                summary=f"引用同一审计包中的 {evidence_count} 条证据。",
            ),
            Stage1DeliverableArtifact(
                artifact_id="stage1-evidence-appendix",
                filename="evidence_appendix.md",
                title="证据附录",
                format="markdown",
                summary=f"保留 {evidence_count} 条证据及冲突、质量与来源定位。",
            ),
            Stage1DeliverableArtifact(
                artifact_id="stage1-design-handoff",
                filename="design_handoff.json",
                title="设计任务书",
                format="json",
                summary=f"向下一阶段传递 {space_count} 个空间单元要求。",
            ),
        ],
    )
