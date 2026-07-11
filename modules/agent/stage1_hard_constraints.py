from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HardConstraintState = Literal["verified", "constrained", "unknown", "not_applicable"]
HardConstraintEffect = Literal["allow", "condition", "exclude"]
HardConstraintExecutor = Literal["agent", "manual_authority", "fieldwork"]


class HardConstraintDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    label: str
    default_verification_action: str
    default_executor: HardConstraintExecutor


class HardConstraintAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    label: str
    state: HardConstraintState
    decision_effect: HardConstraintEffect
    scope: str = "项目范围"
    finding: str
    evidence_refs: list[str] = Field(default_factory=list)
    affected_space_ids: list[str] = Field(default_factory=list)
    verification_action: str = ""
    executor: HardConstraintExecutor = "manual_authority"


class HardConstraintScreening(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0"
    status: Literal["clear", "conditional", "blocked"]
    assessments: list[HardConstraintAssessment]
    status_counts: dict[str, int] = Field(default_factory=dict)
    required_constraint_ids: list[str] = Field(default_factory=list)
    pending_actions: list[dict[str, str]] = Field(default_factory=list)


HARD_CONSTRAINT_DEFINITIONS: tuple[HardConstraintDefinition, ...] = (
    HardConstraintDefinition(
        constraint_id="ownership",
        label="产权与使用权",
        default_verification_action="核验权属、租赁、开放及统一运营授权边界。",
        default_executor="manual_authority",
    ),
    HardConstraintDefinition(
        constraint_id="fire_safety",
        label="消防与疏散",
        default_verification_action="完成消防现状、疏散能力、消防车道与目标业态适配核验。",
        default_executor="fieldwork",
    ),
    HardConstraintDefinition(
        constraint_id="structural_condition",
        label="结构安全与承载",
        default_verification_action="完成逐栋结构安全、荷载及改造可行性鉴定。",
        default_executor="fieldwork",
    ),
    HardConstraintDefinition(
        constraint_id="drainage_sewage",
        label="排水排污与机电",
        default_verification_action="核验给排水、排污、隔油排烟和机电增容条件。",
        default_executor="fieldwork",
    ),
    HardConstraintDefinition(
        constraint_id="parking_loading",
        label="停车、装卸与后勤",
        default_verification_action="核验停车供给、货运装卸、垃圾清运与后勤时段边界。",
        default_executor="fieldwork",
    ),
    HardConstraintDefinition(
        constraint_id="accessibility",
        label="无障碍连续性",
        default_verification_action="核验入口、路径、垂直交通和公共服务空间的无障碍连续性。",
        default_executor="fieldwork",
    ),
    HardConstraintDefinition(
        constraint_id="resident_noise",
        label="居民、噪声与邻里边界",
        default_verification_action="核验居民敏感点、营业时段、噪声控制与协商治理边界。",
        default_executor="manual_authority",
    ),
)

_DEFINITION_BY_ID = {item.constraint_id: item for item in HARD_CONSTRAINT_DEFINITIONS}
_VALID_STATES = {"verified", "constrained", "unknown", "not_applicable"}
_VALID_EFFECTS = {"allow", "condition", "exclude"}
_VALID_EXECUTORS = {"agent", "manual_authority", "fieldwork"}


def _mapping(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _raw_assessments(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    else:
        items = _mapping(payload).get("assessments")
    return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def build_hard_constraint_screening(
    payload: Any,
    *,
    evidence_ids: set[str] | None = None,
) -> HardConstraintScreening:
    """Normalize model output into one complete, conservative screening contract.

    Missing or malformed categories never disappear: they become explicit unknown
    constraints with a responsible verification action. This keeps uncertainty in
    the domain result instead of asking every caller to reconstruct fallback rules.
    """

    valid_evidence_ids = set(evidence_ids or set())
    supplied = {
        _text(item.get("constraint_id")): item
        for item in _raw_assessments(payload)
        if _text(item.get("constraint_id")) in _DEFINITION_BY_ID
    }
    assessments: list[HardConstraintAssessment] = []
    for definition in HARD_CONSTRAINT_DEFINITIONS:
        raw = supplied.get(definition.constraint_id, {})
        state = _text(raw.get("state"))
        if state not in _VALID_STATES:
            state = "unknown"
        default_effect = {
            "verified": "allow",
            "not_applicable": "allow",
            "constrained": "condition",
            "unknown": "condition",
        }[state]
        effect = _text(raw.get("decision_effect"))
        if effect not in _VALID_EFFECTS:
            effect = default_effect
        if state == "unknown" and effect == "allow":
            effect = "condition"
        evidence_refs = [
            item
            for item in _text_list(raw.get("evidence_refs"))
            if not valid_evidence_ids or item in valid_evidence_ids
        ]
        finding = _text(raw.get("finding"))
        if not finding:
            finding = (
                f"当前证据尚未形成{definition.label}的可核验结论。"
                if state == "unknown"
                else f"{definition.label}已登记为{state}，但缺少明确说明。"
            )
        needs_action = state in {"unknown", "constrained"} or effect in {"condition", "exclude"}
        verification_action = _text(raw.get("verification_action"))
        if needs_action and not verification_action:
            verification_action = definition.default_verification_action
        executor = _text(raw.get("executor"))
        if executor not in _VALID_EXECUTORS:
            executor = definition.default_executor
        assessments.append(
            HardConstraintAssessment(
                constraint_id=definition.constraint_id,
                label=definition.label,
                state=state,
                decision_effect=effect,
                scope=_text(raw.get("scope")) or "项目范围",
                finding=finding,
                evidence_refs=evidence_refs,
                affected_space_ids=_text_list(raw.get("affected_space_ids")),
                verification_action=verification_action,
                executor=executor,
            )
        )

    status = "clear"
    if any(item.decision_effect == "exclude" for item in assessments):
        status = "blocked"
    elif any(
        item.state in {"unknown", "constrained"} or item.decision_effect == "condition"
        for item in assessments
    ):
        status = "conditional"
    counts = {state: 0 for state in ("verified", "constrained", "unknown", "not_applicable")}
    pending_actions: list[dict[str, str]] = []
    for item in assessments:
        counts[item.state] += 1
        if item.verification_action:
            pending_actions.append(
                {
                    "constraint_id": item.constraint_id,
                    "label": item.label,
                    "action": item.verification_action,
                    "executor": item.executor,
                }
            )
    return HardConstraintScreening(
        status=status,
        assessments=assessments,
        status_counts=counts,
        required_constraint_ids=[item.constraint_id for item in HARD_CONSTRAINT_DEFINITIONS],
        pending_actions=pending_actions,
    )
