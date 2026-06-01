from __future__ import annotations

from typing import Any, Dict, List

from modules.agent.schemas import AgentSiteSelectionRequest, AgentSiteSelectionResponse
from modules.agent.tool_adapters.scenario_tools import run_site_selection_pack


_STRATEGY_LABELS = {
    "balanced": "综合评估",
    "supply_gap": "补供给缺口",
    "traffic_vitality": "蹭流量活力",
    "avoid_competition": "避开竞争",
}

_SCENARIO_LABELS = {
    "commuter": "通勤快取",
    "community": "社区日常",
    "night_social": "夜间轻社交",
    "student": "学生消费",
    "family": "家庭亲子",
}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _score(candidate: Dict[str, Any]) -> float:
    try:
        return float(candidate.get("total_score") or candidate.get("totalScore") or 0)
    except (TypeError, ValueError):
        return 0.0


def _positioning(strategy: str, scenario: str, place_type: str) -> str:
    scenario_label = _SCENARIO_LABELS.get(scenario, _SCENARIO_LABELS["commuter"])
    strategy_label = strategy if strategy in {"balanced", "supply_gap", "traffic_vitality", "avoid_competition"} else "balanced"
    suffix = f"{place_type}" if place_type else "门店"
    return f"{scenario_label}{suffix} · {strategy_label}"


def _validation_steps(strategy: str, scenario: str, place_type: str) -> List[str]:
    steps = [
        "field_check_visibility_frontage_access",
        "field_check_rent_area_transfer_fee_price_band",
    ]
    if strategy in {"traffic_vitality", "balanced"} or scenario == "commuter":
        steps.append("field_check_weekday_0800_1000_1700_1900_flow")
    if strategy in {"supply_gap", "avoid_competition"}:
        steps.append(f"field_check_same_category_count_flow_status:{place_type or '-'}")
    if scenario == "night_social":
        steps.append("field_check_1900_2200_stay_and_outdoor_conditions")
    if scenario == "community":
        steps.append("field_check_community_entrances_daily_routes")
    if scenario == "student":
        steps.append("field_check_school_entrances_after_school_peak_price_band")
    if scenario == "family":
        steps.append("field_check_family_stay_space_parking_weekend_flow")
    return steps[:5]


def _why_suitable(candidate: Dict[str, Any], strategy: str) -> List[str]:
    strengths = [_as_text(item) for item in _as_list(candidate.get("strengths")) if _as_text(item)]
    reason = _as_text(candidate.get("reason_summary") or candidate.get("reason") or candidate.get("summary"))
    points = strengths[:3]
    if reason:
        points.insert(0, reason)
    if not points:
        points = {
            "supply_gap": ["strategy=supply_gap"],
            "traffic_vitality": ["strategy=traffic_vitality"],
            "avoid_competition": ["strategy=avoid_competition"],
            "balanced": ["strategy=balanced"],
        }.get(strategy, ["strategy=unknown"])
    return points[:4]


def _avoid_areas(candidates: List[Dict[str, Any]], not_recommended_reason: str) -> List[Dict[str, Any]]:
    avoid: List[Dict[str, Any]] = []
    for item in candidates:
        risks = [_as_text(risk) for risk in _as_list(item.get("risks")) if _as_text(risk)]
        if _score(item) >= 60 and len(risks) < 2:
            continue
        h3_id = _as_text(item.get("h3_id") or item.get("h3Id"))
        title = _as_text(item.get("display_title") or item.get("approx_address") or item.get("label")) or "low_priority_candidate_cell"
        if not h3_id and _score(item) >= 60:
            continue
        avoid.append(
            {
                "h3_id": h3_id,
                "title": title,
                "reason": ";".join(risks) or not_recommended_reason or "score_below_priority_threshold",
                "score": _score(item),
            }
        )
    return avoid[:3]


def _enrich_pack(pack: Dict[str, Any], *, place_type: str, strategy: str, scenario: str) -> Dict[str, Any]:
    enriched = dict(pack or {})
    candidates = [dict(item) for item in _as_list(enriched.get("candidate_sites"))]
    for item in candidates:
        item.setdefault("positioning", _positioning(strategy, scenario, place_type))
        item.setdefault("why_suitable", _why_suitable(item, strategy))
        item.setdefault("next_validation_steps", _validation_steps(strategy, scenario, place_type))
    enriched["candidate_sites"] = candidates
    enriched["strategy"] = strategy
    enriched["strategy_label"] = _STRATEGY_LABELS.get(strategy, _STRATEGY_LABELS["balanced"])
    enriched["scenario"] = scenario
    enriched["scenario_label"] = _SCENARIO_LABELS.get(scenario, _SCENARIO_LABELS["commuter"])
    enriched["place_type"] = _as_text(enriched.get("place_type")) or place_type

    confidence = _as_text(enriched.get("confidence")) or "weak"
    top_score = _score(candidates[0]) if candidates else 0.0
    if not candidates:
        verdict = "not_recommended"
        verdict_text = "candidate_count=0"
    elif top_score >= 75 and confidence != "weak":
        verdict = "suitable"
        verdict_text = f"top_score_ge_75; place_type={place_type or '-'}"
    else:
        verdict = "cautious"
        verdict_text = f"top_score_lt_75_or_confidence_weak; place_type={place_type or '-'}"
    enriched.setdefault("overall_verdict", verdict)
    enriched.setdefault("verdict_text", verdict_text)
    enriched.setdefault("avoid_areas", _avoid_areas(candidates[1:], _as_text(enriched.get("not_recommended_reason"))))
    return enriched


async def generate_site_selection_pack(payload: AgentSiteSelectionRequest) -> AgentSiteSelectionResponse:
    place_type = str(payload.place_type or "").strip()
    if not place_type:
        return AgentSiteSelectionResponse(status="failed", error="missing_place_type")
    strategy = payload.strategy if payload.strategy in _STRATEGY_LABELS else "balanced"
    scenario = payload.scenario if payload.scenario in _SCENARIO_LABELS else "commuter"

    arguments: Dict[str, Any] = {
        "place_type": place_type,
        "policy_key": payload.policy_key or "business_catchment_1km",
        "strategy": strategy,
        "scenario": scenario,
        "source": payload.source or "local",
        "year": payload.year,
    }
    result = await run_site_selection_pack(
        arguments=arguments,
        snapshot=payload.analysis_snapshot,
        artifacts={},
        question=f"区域内开店选址：{place_type}",
    )
    artifacts = result.artifacts or {}
    pack = artifacts.get("site_selection_pack") or result.result or {}
    enriched_pack = _enrich_pack(pack if isinstance(pack, dict) else {}, place_type=place_type, strategy=strategy, scenario=scenario)
    return AgentSiteSelectionResponse(
        status="success" if result.status == "success" else "failed",
        site_selection_pack=enriched_pack,
        current_target_supply_gap=artifacts.get("current_target_supply_gap") or {},
        current_site_candidate_scores=artifacts.get("current_site_candidate_scores") or {},
        warnings=list(result.warnings or []),
        error=result.error or "",
    )
