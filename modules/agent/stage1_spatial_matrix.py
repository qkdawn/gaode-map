from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .stage1_spatial_objects import bind_spatial_matrix_to_objects

HierarchyLevel = Literal["system", "cluster", "unit"]
CurrentStateCategory = Literal[
    "active", "underused", "vacant", "constrained", "unknown"
]
RecommendationStatus = Literal["strong", "conditional", "alternative", "excluded"]
RiskLevel = Literal["low", "medium", "high", "critical"]
ImplementationPhase = Literal["phase_1", "phase_2", "phase_3", "long_term"]
ConfidenceLevel = Literal["high", "medium", "low"]


class SpatialMatrixContractError(ValueError):
    """Stable domain error for invalid model-produced spatial matrices."""

    def __init__(self, diagnostics: list[str]):
        self.diagnostics = tuple(diagnostics)
        super().__init__("；".join(self.diagnostics))


def _validation_diagnostics(error: ValidationError) -> list[str]:
    diagnostics: list[str] = []
    for issue in error.errors(include_url=False):
        location = ".".join(str(part) for part in issue.get("loc", ())) or "matrix"
        message = str(issue.get("msg") or "不符合契约")
        diagnostics.append(f"{location}：{message}")
    return diagnostics or ["空间功能策划矩阵不符合结构化契约"]


class SpatialHierarchyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    level: HierarchyLevel
    parent_id: str = ""
    role: str = Field(min_length=1)
    member_space_ids: list[str] = Field(default_factory=list)


class SpatialDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1)
    hierarchy_id: str = Field(min_length=1)
    space_name: str = Field(min_length=1)
    future_role: str = Field(min_length=1)
    core_audiences: list[Any] = Field(min_length=1)
    movement_role: str = Field(min_length=1)
    value_role: str = Field(min_length=1)
    current_state_category: CurrentStateCategory
    current_state: dict[str, Any]
    change_logic: dict[str, Any]
    candidate_functions: list[Any] = Field(min_length=2)
    preferred_function: dict[str, Any]
    compatible_functions: list[Any] = Field(default_factory=list)
    excluded_functions: list[Any] = Field(default_factory=list)
    audience_scenarios: list[Any] = Field(min_length=1)
    access_and_movement: dict[str, Any]
    operation_strategy: dict[str, Any]
    renovation_and_delivery: dict[str, Any]
    implementation_phase: ImplementationPhase
    risk_level: RiskLevel
    risk_summary: str = Field(min_length=1)
    preconditions: list[Any] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    hard_constraint_refs: list[str] = Field(default_factory=list)
    assumptions: list[Any] = Field(default_factory=list)
    validation_actions: list[Any] = Field(default_factory=list)
    recommendation_status: RecommendationStatus
    confidence: ConfidenceLevel
    map_binding: dict[str, Any]


class SpatialProgrammingMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matrix_version: str = Field(min_length=1)
    positioning_option_id: str = Field(min_length=1)
    spatial_hierarchy: list[SpatialHierarchyNode] = Field(min_length=3)
    space_decisions: list[SpatialDecision] = Field(min_length=1)
    portfolio_checks: list[Any] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "SpatialProgrammingMatrix":
        nodes = {node.id: node for node in self.spatial_hierarchy}
        if len(nodes) != len(self.spatial_hierarchy):
            raise ValueError("spatial_hierarchy 中存在重复稳定 ID")
        levels = {node.level for node in self.spatial_hierarchy}
        if levels != {"system", "cluster", "unit"}:
            raise ValueError("spatial_hierarchy 必须同时包含 system、cluster、unit")
        for node in self.spatial_hierarchy:
            if node.level == "system":
                if node.parent_id:
                    raise ValueError(f"系统层 {node.id} 不能设置 parent_id")
                continue
            parent = nodes.get(node.parent_id)
            expected = "system" if node.level == "cluster" else "cluster"
            if parent is None or parent.level != expected:
                raise ValueError(
                    f"{node.level} 节点 {node.id} 必须引用一个 {expected} 层 parent_id"
                )
        decision_ids = [decision.space_id for decision in self.space_decisions]
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("space_decisions 中存在重复稳定 space_id")
        for decision in self.space_decisions:
            hierarchy = nodes.get(decision.hierarchy_id)
            if hierarchy is None:
                raise ValueError(
                    f"空间决策 {decision.space_id} 引用了不存在的 hierarchy_id"
                )
            if decision.space_id not in hierarchy.member_space_ids:
                raise ValueError(
                    f"空间决策 {decision.space_id} 未登记在层级节点 {hierarchy.id} 的 member_space_ids"
                )
        return self


_MODE_DEFINITIONS = (
    ("current_state", "现状", "按空间当前利用与约束状态显示"),
    ("suggested_function", "建议功能", "按首选功能类别显示"),
    ("recommendation_strength", "推荐强度", "按建议成立强度显示"),
    ("risk", "风险", "按当前决策风险等级显示"),
    ("implementation_phase", "实施阶段", "按建议进入实施的阶段显示"),
)
_LEVEL_LABELS = {"system": "系统层", "cluster": "组团层", "unit": "单元层"}
_CURRENT_STATE_STYLES = {
    "active": ("正常使用", "#16a34a"),
    "underused": ("利用不足", "#d97706"),
    "vacant": ("闲置", "#64748b"),
    "constrained": ("受约束", "#dc2626"),
    "unknown": ("状态待核", "#94a3b8"),
}
_RECOMMENDATION_STYLES = {
    "strong": ("强推荐", "#15803d"),
    "conditional": ("有条件推荐", "#d97706"),
    "alternative": ("备选", "#2563eb"),
    "excluded": ("排除", "#be123c"),
}
_RISK_STYLES = {
    "low": ("低风险", "#16a34a"),
    "medium": ("中风险", "#d97706"),
    "high": ("高风险", "#ea580c"),
    "critical": ("关键阻断", "#be123c"),
}
_PHASE_STYLES = {
    "phase_1": ("一期", "#0f766e"),
    "phase_2": ("二期", "#2563eb"),
    "phase_3": ("三期", "#7c3aed"),
    "long_term": ("远期", "#64748b"),
}
_FUNCTION_COLORS = (
    "#0f766e",
    "#2563eb",
    "#7c3aed",
    "#c2410c",
    "#be123c",
    "#4d7c0f",
    "#0369a1",
    "#a16207",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _function_identity(value: dict[str, Any]) -> tuple[str, str]:
    key = (
        _text(value.get("id")) or _text(value.get("name")) or _text(value.get("label"))
    )
    label = _text(value.get("name")) or _text(value.get("label")) or key
    return key, label


def _value(key: str, label: str, color: str, detail: str = "") -> dict[str, str]:
    return {"key": key, "label": label, "color": color, "detail": detail}


def _legend(values: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for value in values:
        key = _text(value.get("key"))
        if key and key not in unique:
            unique[key] = {
                "key": key,
                "label": _text(value.get("label")) or key,
                "color": _text(value.get("color")),
            }
    return list(unique.values())


def _build_map_presentation(matrix: dict[str, Any]) -> dict[str, Any]:
    hierarchy = {
        _text(item.get("id")): item
        for item in matrix.get("spatial_hierarchy", [])
        if isinstance(item, dict)
    }
    decisions = [
        item for item in matrix.get("space_decisions", []) if isinstance(item, dict)
    ]
    function_ids = sorted(
        {
            _function_identity(item.get("preferred_function") or {})[0]
            for item in decisions
            if _function_identity(item.get("preferred_function") or {})[0]
        }
    )
    function_styles = {
        function_id: _FUNCTION_COLORS[index % len(_FUNCTION_COLORS)]
        for index, function_id in enumerate(function_ids)
    }
    items: list[dict[str, Any]] = []
    for decision in decisions:
        hierarchy_node = hierarchy.get(_text(decision.get("hierarchy_id")), {})
        function_key, function_label = _function_identity(
            decision.get("preferred_function") or {}
        )
        current_key = _text(decision.get("current_state_category"))
        recommendation_key = _text(decision.get("recommendation_status"))
        risk_key = _text(decision.get("risk_level"))
        phase_key = _text(decision.get("implementation_phase"))
        current_label, current_color = _CURRENT_STATE_STYLES[current_key]
        recommendation_label, recommendation_color = _RECOMMENDATION_STYLES[
            recommendation_key
        ]
        risk_label, risk_color = _RISK_STYLES[risk_key]
        phase_label, phase_color = _PHASE_STYLES[phase_key]
        items.append(
            {
                "space_id": _text(decision.get("space_id")),
                "space_name": _text(decision.get("space_name")),
                "hierarchy_id": _text(decision.get("hierarchy_id")),
                "hierarchy_level": _text(hierarchy_node.get("level")),
                "hierarchy_title": _text(hierarchy_node.get("title")),
                "map_binding": deepcopy(decision.get("map_binding") or {}),
                "values": {
                    "current_state": _value(
                        current_key,
                        current_label,
                        current_color,
                        _text((decision.get("current_state") or {}).get("summary")),
                    ),
                    "suggested_function": _value(
                        function_key,
                        function_label,
                        function_styles[function_key],
                    ),
                    "recommendation_strength": _value(
                        recommendation_key,
                        recommendation_label,
                        recommendation_color,
                    ),
                    "risk": _value(
                        risk_key,
                        risk_label,
                        risk_color,
                        _text(decision.get("risk_summary")),
                    ),
                    "implementation_phase": _value(
                        phase_key,
                        phase_label,
                        phase_color,
                    ),
                },
            }
        )
    level_counts = Counter(
        _text(item.get("hierarchy_level"))
        for item in items
        if item.get("hierarchy_level")
    )
    modes = []
    for mode_id, label, description in _MODE_DEFINITIONS:
        modes.append(
            {
                "id": mode_id,
                "label": label,
                "description": description,
                "legend": _legend([item["values"][mode_id] for item in items]),
            }
        )
    return {
        "modes": modes,
        "hierarchy_levels": [
            {"id": level, "label": label, "decision_count": level_counts[level]}
            for level, label in _LEVEL_LABELS.items()
        ],
        "items": items,
        "bound_item_count": sum(
            1
            for item in items
            if (item.get("map_binding") or {}).get("status") == "bound"
        ),
    }


def compile_spatial_programming_matrix(
    raw_matrix: dict[str, Any],
    spatial_object_registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate one spatial-planning contract and derive all map presentation data."""

    try:
        validated = SpatialProgrammingMatrix.model_validate(raw_matrix)
    except ValidationError as error:
        raise SpatialMatrixContractError(_validation_diagnostics(error)) from error
    matrix = validated.model_dump(mode="json")
    bound = bind_spatial_matrix_to_objects(matrix, spatial_object_registry)
    bound["map_presentation"] = _build_map_presentation(bound)
    return bound
