from __future__ import annotations

from typing import Any, Dict

from modules.business_analyst import plan_business_analyst_analysis
from modules.business_analyst.schemas import BusinessAnalystInput

from ..schemas import AnalysisSnapshot, ToolResult


def _ba_input_from_snapshot(snapshot: AnalysisSnapshot, question_type: str) -> BusinessAnalystInput:
    evidence_layers = []
    if snapshot.pois or snapshot.poi_summary:
        evidence_layers.append("poi")
    if (snapshot.h3 or {}).get("summary"):
        evidence_layers.append("h3")
    if (snapshot.population or {}).get("summary"):
        evidence_layers.append("population")
    if (snapshot.nightlight or {}).get("summary"):
        evidence_layers.append("nightlight")
    if (snapshot.road or {}).get("summary"):
        evidence_layers.append("road")
    if snapshot.frontend_analysis:
        evidence_layers.append("frontend_analysis")
    return BusinessAnalystInput(
        scope=dict(snapshot.scope or {}),
        evidence_layers=list(dict.fromkeys(evidence_layers)),
        question_type=question_type,
    )


async def plan_business_analyst_analysis_tool(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del artifacts
    mode = str((arguments or {}).get("mode") or "auto").strip() or "auto"
    target_question = str((arguments or {}).get("question") or question or "").strip()
    question_type = str((arguments or {}).get("question_type") or "").strip()
    skeleton = plan_business_analyst_analysis(
        question=target_question,
        question_type=question_type,
        analysis_input=_ba_input_from_snapshot(snapshot, question_type),
        mode=mode,
    )
    selected_skill = skeleton.get("selected_skill") if isinstance(skeleton.get("selected_skill"), dict) else {}
    result = {
        "status": skeleton.get("status"),
        "reason": skeleton.get("reason"),
        "selected_skill": selected_skill,
        "candidate_skills": list(skeleton.get("candidate_skills") or []),
        "recommended_path": list(skeleton.get("recommended_path") or []),
        "optional_branches": skeleton.get("optional_branches") if isinstance(skeleton.get("optional_branches"), dict) else {},
        "model_tool_map": skeleton.get("model_tool_map") if isinstance(skeleton.get("model_tool_map"), dict) else {},
        "skip_conditions": skeleton.get("skip_conditions") if isinstance(skeleton.get("skip_conditions"), dict) else {},
        "guardrails": list(skeleton.get("guardrails") or []),
        "missing_evidence_defaults": list(skeleton.get("missing_evidence_defaults") or []),
        "answer_guidance": list(skeleton.get("answer_guidance") or []),
    }
    return ToolResult(
        tool_name="plan_business_analyst_analysis",
        status="success",
        result=result,
        evidence=[
            {"field": "ba.status", "value": result.get("status")},
            {"field": "ba.selected_skill", "value": selected_skill.get("skill_id") if selected_skill else ""},
            {"field": "ba.recommended_path", "value": list(result.get("recommended_path") or [])},
        ],
        artifacts={"business_analyst_skeleton": skeleton},
    )
