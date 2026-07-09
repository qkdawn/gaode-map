from __future__ import annotations

from typing import Dict, List

from .model_graph import GRAPH_ID
from .schemas import SkillSpec

GUARDRAILS = [
    "population_not_spending_power",
    "nightlight_not_sales",
    "poi_not_business_performance",
    "huff_proxy_not_market_share",
    "customer_profile_requires_customer_data",
    "no_revenue_without_source",
    "recommendation_requires_validation",
]

AUTONOMY = {
    "may_skip_models": True,
    "may_reorder_models": True,
    "may_combine_with_other_skills": True,
    "may_request_clarification": True,
    "may_stop_with_partial_conclusion": True,
    "should_explain_skipped_models": True,
}

MODEL_TOOL_MAP = {
    "TradeAreaModel": {"required_tools": ["read_current_results"], "optional_tools": ["read_current_scope"]},
    "MarketPotentialModel": {"required_tools": ["read_current_results"], "optional_tools": ["aggregate_scope_dataset", "search_analysis_context"]},
    "RetailGapModel": {"required_tools": ["query_scope_dataset"], "optional_tools": ["aggregate_scope_dataset"]},
    "OpportunityCategoryScreeningModel": {
        "required_tools": ["read_current_results"],
        "optional_tools": ["aggregate_scope_dataset", "query_scope_dataset", "search_analysis_context"],
    },
    "HuffGravityModel": {"required_tools": ["query_scope_dataset"], "optional_tools": ["read_scope_record"]},
    "CustomerProfileFitModel": {"required_tools": ["read_current_results"], "optional_tools": ["aggregate_scope_dataset", "search_analysis_context"]},
    "SiteSuitabilityModel": {"required_tools": ["query_scope_dataset"], "optional_tools": ["read_scope_record"]},
}


def _skills() -> Dict[str, SkillSpec]:
    return {
        "ba.single_category_site_selection": SkillSpec(
            skill_id="ba.single_category_site_selection",
            title="Single category site selection",
            purpose="Judge whether a target category can enter the current area and, when evidence allows, rank candidate zones.",
            uses_model_graph=GRAPH_ID,
            entry_nodes=["TradeAreaModel"],
            target_nodes=["SiteSuitabilityModel"],
            required_path=["TradeAreaModel", "MarketPotentialModel", "RetailGapModel", "SiteSuitabilityModel"],
            optional_branches={
                "competition": {"model": "HuffGravityModel", "use_when": ["competition question", "same-category POIs exist", "candidate zones exist"]},
                "opportunity_screening": {"model": "OpportunityCategoryScreeningModel", "use_when": ["open-ended opportunity question", "target category is not fixed"]},
                "customer_fit": {"model": "CustomerProfileFitModel", "use_when": ["customer profile question", "target customer is supplied"]},
            },
            model_tool_map=MODEL_TOOL_MAP,
            skip_conditions={
                "HuffGravityModel": ["no candidate site", "no competitor evidence", "no distance or accessibility proxy"],
                "CustomerProfileFitModel": ["question does not ask about customer profile", "no target user profile"],
                "SiteSuitabilityModel": ["question only asks for regional diagnosis and not candidate ranking"],
            },
            guardrails=GUARDRAILS,
            agent_autonomy=AUTONOMY,
            trigger_tokens=["选址", "开店", "适合开", "推荐哪个位置", "候选", "补一家", "适合补充"],
        ),
        "ba.area_commercial_diagnosis": SkillSpec(
            skill_id="ba.area_commercial_diagnosis",
            title="Area commercial diagnosis",
            purpose="Diagnose commercial structure, demand proxies, supply gaps, and evidence limits for the current area.",
            uses_model_graph=GRAPH_ID,
            entry_nodes=["TradeAreaModel"],
            target_nodes=["OpportunityCategoryScreeningModel"],
            required_path=["TradeAreaModel", "MarketPotentialModel", "RetailGapModel", "OpportunityCategoryScreeningModel"],
            optional_branches={
                "customer_fit": {"model": "CustomerProfileFitModel", "use_when": ["question asks who the area serves", "population/activity proxies are available"]},
                "site_suitability": {"model": "SiteSuitabilityModel", "use_when": ["question asks where to locate or prioritize candidate zones"]},
            },
            model_tool_map=MODEL_TOOL_MAP,
            skip_conditions={
                "RetailGapModel": ["no target category and only high-level summary is requested"],
                "OpportunityCategoryScreeningModel": ["question only asks about one specified category", "no category mix or demand proxy exists"],
                "SiteSuitabilityModel": ["no candidate ranking requested"],
            },
            guardrails=GUARDRAILS,
            agent_autonomy=AUTONOMY,
            trigger_tokens=["商业特征", "缺什么", "业态缺口", "零售空白", "补位", "区域商业", "商业基础", "适合做什么", "能发展什么", "引入什么业态", "商业机会", "租户组合"],
        ),
        "ba.open_opportunity_screening": SkillSpec(
            skill_id="ba.open_opportunity_screening",
            title="Open opportunity category screening",
            purpose="Screen candidate business directions when the user asks what the current trade area is suitable for without naming a target category.",
            uses_model_graph=GRAPH_ID,
            entry_nodes=["TradeAreaModel"],
            target_nodes=["OpportunityCategoryScreeningModel"],
            required_path=["TradeAreaModel", "MarketPotentialModel", "RetailGapModel", "OpportunityCategoryScreeningModel"],
            optional_branches={
                "customer_fit": {"model": "CustomerProfileFitModel", "use_when": ["target customer or persona is mentioned"]},
                "site_suitability": {"model": "SiteSuitabilityModel", "use_when": ["candidate zones or ranking are requested"]},
            },
            model_tool_map=MODEL_TOOL_MAP,
            skip_conditions={
                "OpportunityCategoryScreeningModel": ["no category mix", "no demand or activity proxy"],
                "SiteSuitabilityModel": ["no candidate ranking requested"],
                "HuffGravityModel": ["no candidate site", "no competitor evidence", "no distance or accessibility proxy"],
            },
            guardrails=GUARDRAILS,
            agent_autonomy=AUTONOMY,
            trigger_tokens=["适合做什么", "做什么合适", "能发展什么", "该引入什么", "引入什么业态", "商业机会", "业态方向", "租户组合"],
        ),
        "ba.competition_impact": SkillSpec(
            skill_id="ba.competition_impact",
            title="Competition impact diagnosis",
            purpose="Assess competitive pressure and relative attraction proxy without claiming real market share.",
            uses_model_graph=GRAPH_ID,
            entry_nodes=["TradeAreaModel"],
            target_nodes=["HuffGravityModel"],
            required_path=["TradeAreaModel", "RetailGapModel", "HuffGravityModel"],
            optional_branches={"site_suitability": {"model": "SiteSuitabilityModel", "use_when": ["candidate ranking is requested"]}},
            model_tool_map=MODEL_TOOL_MAP,
            skip_conditions={"HuffGravityModel": ["no competitor evidence", "no candidate site", "no distance or accessibility proxy"]},
            guardrails=GUARDRAILS,
            agent_autonomy=AUTONOMY,
            trigger_tokens=["竞争", "竞品", "同类店", "分流", "Huff", "值得进"],
        ),
        "ba.customer_profile_review": SkillSpec(
            skill_id="ba.customer_profile_review",
            title="Customer profile fit review",
            purpose="Review whether the trade area fits a target customer or persona using real customer evidence when available and proxy evidence otherwise.",
            uses_model_graph=GRAPH_ID,
            entry_nodes=["TradeAreaModel"],
            target_nodes=["CustomerProfileFitModel"],
            required_path=["TradeAreaModel", "CustomerProfileFitModel", "MarketPotentialModel"],
            optional_branches={},
            model_tool_map=MODEL_TOOL_MAP,
            skip_conditions={"CustomerProfileFitModel": ["no target profile and no customer/persona question"]},
            guardrails=GUARDRAILS,
            agent_autonomy=AUTONOMY,
            trigger_tokens=["客群", "人群", "画像", "学生", "家庭", "游客", "白领", "目标用户"],
        ),
    }


def get_skill(skill_id: str) -> SkillSpec | None:
    return _skills().get(skill_id)


def list_skills() -> List[SkillSpec]:
    return list(_skills().values())


def suggest_skills(question: str, question_type: str = "") -> List[SkillSpec]:
    text = str(question or "")
    normalized_type = str(question_type or "").strip()
    ranked: List[tuple[int, SkillSpec]] = []
    for skill in list_skills():
        score = sum(1 for token in skill.trigger_tokens if token and token in text)
        if normalized_type == "site_selection" and skill.skill_id == "ba.single_category_site_selection":
            score += 6
        if normalized_type == "facility_gap" and skill.skill_id == "ba.area_commercial_diagnosis":
            score += 5
        if any(token in text for token in ("竞争", "竞品", "同类店", "分流", "Huff")) and skill.skill_id == "ba.competition_impact":
            score += 5
        if any(token in text for token in ("适合做什么", "做什么合适", "能发展什么", "该引入什么", "引入什么业态", "商业机会")) and skill.skill_id == "ba.open_opportunity_screening":
            score += 6
        if any(token in text for token in ("客群", "人群", "画像", "学生", "家庭", "游客", "白领", "目标用户")) and skill.skill_id == "ba.customer_profile_review":
            score += 5
        if score > 0:
            ranked.append((score, skill))
    ranked.sort(key=lambda item: (-item[0], item[1].skill_id))
    return [skill for _, skill in ranked[:3]]


def validate_model_tool_map(available_tool_names: set[str] | List[str]) -> List[str]:
    available = {str(name) for name in available_tool_names}
    missing: List[str] = []
    for model_id, mapping in MODEL_TOOL_MAP.items():
        for group in ("required_tools", "optional_tools"):
            for tool_name in list(mapping.get(group) or []):
                if tool_name not in available and tool_name not in missing:
                    missing.append(tool_name)
    return missing
