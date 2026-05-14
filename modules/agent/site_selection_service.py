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
    strategy_label = {
        "balanced": "稳健综合型",
        "supply_gap": "补缺口型",
        "traffic_vitality": "高活力型",
        "avoid_competition": "低竞争型",
    }.get(strategy, "稳健综合型")
    suffix = f"{place_type}" if place_type else "门店"
    return f"{scenario_label}{suffix} · {strategy_label}"


def _validation_steps(strategy: str, scenario: str, place_type: str) -> List[str]:
    steps = [
        "现场复核临街可见度、门面开口和动线方向",
        "核对租金、面积、转让费与同类店价格带",
    ]
    if strategy in {"traffic_vitality", "balanced"} or scenario == "commuter":
        steps.append("观察工作日 8:00-10:00 与 17:00-19:00 人流")
    if strategy in {"supply_gap", "avoid_competition"}:
        steps.append(f"步行核查周边同类{place_type or '业态'}数量、客流和营业状态")
    if scenario == "night_social":
        steps.append("观察 19:00-22:00 夜间停留和外摆条件")
    if scenario == "community":
        steps.append("确认社区出入口、买菜/接送/归家动线是否经过")
    if scenario == "student":
        steps.append("确认学校出入口、放学高峰和学生价格敏感度")
    if scenario == "family":
        steps.append("确认亲子家庭停留空间、停车和周末客流")
    return steps[:5]


def _why_suitable(candidate: Dict[str, Any], strategy: str) -> List[str]:
    strengths = [_as_text(item) for item in _as_list(candidate.get("strengths")) if _as_text(item)]
    reason = _as_text(candidate.get("reason_summary") or candidate.get("reason") or candidate.get("summary"))
    points = strengths[:3]
    if reason:
        points.insert(0, reason)
    if not points:
        points = {
            "supply_gap": ["优先看供给缺口与需求支撑是否匹配"],
            "traffic_vitality": ["优先看活力、人流和可达性是否支撑开店"],
            "avoid_competition": ["优先看同类竞争是否可控"],
            "balanced": ["综合供给缺口、人口、活力和路网支撑形成候选"],
        }.get(strategy, ["综合证据形成候选"])
    return points[:4]


def _avoid_areas(candidates: List[Dict[str, Any]], not_recommended_reason: str) -> List[Dict[str, Any]]:
    avoid: List[Dict[str, Any]] = []
    for item in candidates:
        risks = [_as_text(risk) for risk in _as_list(item.get("risks")) if _as_text(risk)]
        if _score(item) >= 60 and len(risks) < 2:
            continue
        h3_id = _as_text(item.get("h3_id") or item.get("h3Id"))
        title = _as_text(item.get("display_title") or item.get("approx_address") or item.get("label")) or "低优先级候选网格"
        if not h3_id and _score(item) >= 60:
            continue
        avoid.append(
            {
                "h3_id": h3_id,
                "title": title,
                "reason": "；".join(risks) or not_recommended_reason or "综合评分偏低，暂不作为优先看点。",
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
        verdict_text = "当前证据不足，暂不能形成稳定候选片区。"
    elif top_score >= 75 and confidence != "weak":
        verdict = "suitable"
        verdict_text = f"当前范围可优先验证{place_type or '目标业态'}，首选片区综合支撑较好。"
    else:
        verdict = "cautious"
        verdict_text = f"当前范围可以做{place_type or '目标业态'}预筛，但需要重点复核客流、租金和竞争。"
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
