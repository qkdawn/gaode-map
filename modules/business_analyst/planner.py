from __future__ import annotations

from typing import Any, Dict

from .model_graph import compact_graph, default_model_graph, model_relations_for_path
from .schemas import BusinessAnalystInput, BusinessAnalystSkeleton, SkillSpec
from .skill_registry import get_skill, suggest_skills

MISSING_OPERATIONAL_EVIDENCE = [
    "real foot traffic",
    "rent",
    "sales or revenue",
    "same-category operating status",
    "customer points or order origins",
]

MODE_TO_SKILL = {
    "area_diagnosis": "ba.area_commercial_diagnosis",
    "opportunity_screening": "ba.open_opportunity_screening",
    "site_selection": "ba.single_category_site_selection",
    "competition": "ba.competition_impact",
    "customer_fit": "ba.customer_profile_review",
}


def _input_has_scope(analysis_input: BusinessAnalystInput) -> bool:
    scope = analysis_input.scope if isinstance(analysis_input.scope, dict) else {}
    return bool(scope.get("polygon") or scope.get("center") or scope.get("bounds"))


def business_analyst_input_from_snapshot(
    snapshot: Any,
    *,
    question_type: str = "",
    has_selected_sources: bool = False,
) -> BusinessAnalystInput:
    def field(name: str) -> Any:
        if isinstance(snapshot, dict):
            return snapshot.get(name)
        return getattr(snapshot, name, None)

    evidence_layers: list[str] = []
    if field("pois") or field("poi_summary"):
        evidence_layers.append("poi")
    if (field("h3") or {}).get("summary"):
        evidence_layers.append("h3")
    if (field("population") or {}).get("summary"):
        evidence_layers.append("population")
    if (field("nightlight") or {}).get("summary"):
        evidence_layers.append("nightlight")
    if (field("road") or {}).get("summary"):
        evidence_layers.append("road")
    if field("frontend_analysis"):
        evidence_layers.append("frontend_analysis")
    if has_selected_sources:
        evidence_layers.append("selected_sources")
    return BusinessAnalystInput(
        scope=dict(field("scope") or {}),
        evidence_layers=list(dict.fromkeys(evidence_layers)),
        question_type=question_type,
    )


def evaluate_business_analyst_report_readiness(
    analysis_input: BusinessAnalystInput,
) -> Dict[str, Any]:
    has_scope = _input_has_scope(analysis_input)
    has_evidence = bool(analysis_input.evidence_layers)
    missing_required = []
    actions = []
    if not has_scope:
        missing_required.append("分析范围或商圈边界")
        actions.append({"id": "select-scope", "label": "选择分析范围", "target": "scope-selection"})
    if not has_evidence:
        missing_required.append("POI、人口、夜光、路网或项目资料证据")
        actions.append({"id": "add-evidence", "label": "准备分析证据", "target": "analysis-sources"})
    return {
        "ready": not missing_required,
        "satisfied": [
            label
            for present, label in (
                (has_scope, "分析范围或商圈边界"),
                (has_evidence, "当前范围分析证据"),
            )
            if present
        ],
        "missing_required": missing_required,
        "missing_optional": ["消费、客流、租金、销售与客户来源等运营校准数据"],
        "actions": actions,
    }


def _answer_guidance(skill: SkillSpec) -> list[str]:
    return [
        "Use this Business Analyst output as an analysis skeleton, not as an answer template.",
        "Translate the selected model path into natural judgment that directly answers the user.",
        "Run or reuse mapped tools only when evidence is needed for the selected path.",
        "Skip optional branches when inputs are missing and explain important skips briefly.",
        "Never turn proxy evidence into revenue, foot traffic, market share, customer origin, or operating performance claims.",
        f"Selected BA skill: {skill.skill_id}.",
    ]


def _select_candidates(question: str, question_type: str, mode: str) -> list[SkillSpec]:
    normalized_mode = str(mode or "auto").strip() or "auto"
    if normalized_mode != "auto":
        skill = get_skill(MODE_TO_SKILL.get(normalized_mode, ""))
        return [skill] if skill else []
    return suggest_skills(question, question_type)


def build_business_analyst_skeleton(
    *,
    question: str,
    question_type: str = "",
    analysis_input: BusinessAnalystInput | Dict[str, Any] | None = None,
    mode: str = "auto",
) -> Dict[str, Any]:
    input_model = analysis_input if isinstance(analysis_input, BusinessAnalystInput) else BusinessAnalystInput(**dict(analysis_input or {}))
    resolved_question_type = question_type or input_model.question_type
    candidates = _select_candidates(question, resolved_question_type, mode)
    if not candidates:
        return BusinessAnalystSkeleton(status="skipped", reason="no_business_analyst_skill_matched").model_dump(mode="json", exclude_none=True)

    selected = candidates[0]
    graph = default_model_graph()
    has_scope = _input_has_scope(input_model)
    reason = "ready" if has_scope else "matched_but_scope_missing"
    skeleton = BusinessAnalystSkeleton(
        status="ready" if has_scope else "partial",
        reason=reason,
        selected_skill=selected,
        candidate_skills=[skill.skill_id for skill in candidates],
        model_graph=compact_graph(graph),
        recommended_path=list(selected.required_path),
        path_relations=model_relations_for_path(graph, list(selected.required_path)),
        optional_branches=dict(selected.optional_branches),
        model_tool_map=dict(selected.model_tool_map),
        skip_conditions=dict(selected.skip_conditions),
        guardrails=list(selected.guardrails),
        missing_evidence_defaults=list(MISSING_OPERATIONAL_EVIDENCE),
        answer_guidance=_answer_guidance(selected),
    )
    return skeleton.model_dump(mode="json", exclude_none=True)


def plan_business_analyst_analysis(
    *,
    question: str,
    question_type: str = "",
    analysis_input: BusinessAnalystInput | Dict[str, Any] | None = None,
    mode: str = "auto",
) -> Dict[str, Any]:
    return build_business_analyst_skeleton(question=question, question_type=question_type, analysis_input=analysis_input, mode=mode)
