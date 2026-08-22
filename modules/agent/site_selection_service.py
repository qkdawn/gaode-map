from __future__ import annotations

from typing import Any, Dict

from modules.agent.schemas import AgentSiteSelectionRequest, AgentSiteSelectionResponse
from modules.agent.tool_adapters.scenario_tools import run_site_selection_pack


_STRATEGIES = {"balanced", "supply_gap", "traffic_vitality", "avoid_competition"}
_SCENARIOS = {"commuter", "community", "night_social", "student", "family"}


async def generate_site_selection_pack(payload: AgentSiteSelectionRequest) -> AgentSiteSelectionResponse:
    place_type = str(payload.place_type or "").strip()
    if not place_type:
        return AgentSiteSelectionResponse(status="failed", error="missing_place_type")
    strategy = payload.strategy if payload.strategy in _STRATEGIES else "balanced"
    scenario = payload.scenario if payload.scenario in _SCENARIOS else "commuter"

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
    fact_pack = dict(pack) if isinstance(pack, dict) else {}
    fact_pack["request_context"] = {
        "place_type": place_type,
        "strategy": strategy,
        "scenario": scenario,
    }
    return AgentSiteSelectionResponse(
        status="success" if result.status == "success" else "failed",
        site_selection_pack=fact_pack,
        current_target_supply_gap=artifacts.get("current_target_supply_gap") or {},
        current_site_candidate_facts=artifacts.get("current_site_candidate_facts") or {},
        warnings=list(result.warnings or []),
        error=result.error or "",
    )
