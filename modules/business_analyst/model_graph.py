from __future__ import annotations

from typing import Any, Dict, List

from .schemas import ModelEdge, ModelGraph, ModelNode

GRAPH_ID = "ba.business_analyst_model_graph.v1"


def default_model_graph() -> ModelGraph:
    return ModelGraph(
        graph_id=GRAPH_ID,
        title="Business Analyst model graph",
        entry_nodes=["TradeAreaModel"],
        target_nodes=["SiteSuitabilityModel"],
        nodes={
            "TradeAreaModel": ModelNode(
                model_id="TradeAreaModel",
                role="boundary",
                purpose="Normalize the spatial scope, trade area basis, and analysis boundary for downstream BA models.",
                outputs=["trade_area_context"],
            ),
            "MarketPotentialModel": ModelNode(
                model_id="MarketPotentialModel",
                role="demand",
                purpose="Estimate demand baseline and market potential proxies from scope evidence.",
                outputs=["market_potential_result"],
            ),
            "RetailGapModel": ModelNode(
                model_id="RetailGapModel",
                role="supply_gap",
                purpose="Identify supply gaps, retail voids, and spatial mismatch for target categories.",
                outputs=["retail_gap_result", "candidate_zones"],
            ),
            "OpportunityCategoryScreeningModel": ModelNode(
                model_id="OpportunityCategoryScreeningModel",
                role="opportunity_screening",
                purpose="Screen plausible tenant categories or business directions from trade area demand, supply mix, anchors, and saturation signals.",
                required=False,
                outputs=["opportunity_category_shortlist"],
            ),
            "HuffGravityModel": ModelNode(
                model_id="HuffGravityModel",
                role="competition",
                purpose="Estimate relative attraction and competitive diversion proxy when candidate sites and competitor evidence exist.",
                required=False,
                outputs=["huff_proxy_result"],
            ),
            "CustomerProfileFitModel": ModelNode(
                model_id="CustomerProfileFitModel",
                role="customer_fit",
                purpose="Check whether observed population and activity proxies fit the target customer profile.",
                required=False,
                outputs=["customer_profile_fit_result"],
            ),
            "SiteSuitabilityModel": ModelNode(
                model_id="SiteSuitabilityModel",
                role="decision",
                purpose="Combine boundary, demand, supply gap, competition, customer fit, and accessibility evidence into site suitability judgment.",
                outputs=["site_suitability_result"],
            ),
        },
        edges=[
            ModelEdge(source="TradeAreaModel", target="MarketPotentialModel", relation="defines_scope_for", required=True),
            ModelEdge(source="TradeAreaModel", target="RetailGapModel", relation="defines_scope_for", required=True),
            ModelEdge(source="TradeAreaModel", target="HuffGravityModel", relation="defines_scope_for"),
            ModelEdge(source="TradeAreaModel", target="CustomerProfileFitModel", relation="defines_scope_for"),
            ModelEdge(source="MarketPotentialModel", target="RetailGapModel", relation="provides_demand_baseline"),
            ModelEdge(source="MarketPotentialModel", target="OpportunityCategoryScreeningModel", relation="contributes_demand_score"),
            ModelEdge(source="MarketPotentialModel", target="SiteSuitabilityModel", relation="contributes_demand_score", required=True),
            ModelEdge(source="RetailGapModel", target="OpportunityCategoryScreeningModel", relation="provides_gap_signals"),
            ModelEdge(source="RetailGapModel", target="SiteSuitabilityModel", relation="provides_candidate_zones", required=True),
            ModelEdge(source="OpportunityCategoryScreeningModel", target="SiteSuitabilityModel", relation="provides_candidate_categories"),
            ModelEdge(
                source="HuffGravityModel",
                target="SiteSuitabilityModel",
                relation="adjusts_for_competition",
                use_when=["question asks about competition", "same or substitute competitors exist", "candidate sites and distance proxy exist"],
            ),
            ModelEdge(
                source="CustomerProfileFitModel",
                target="SiteSuitabilityModel",
                relation="adjusts_for_target_user_fit",
                use_when=["question asks about customer profile", "brand target profile is provided", "scenario has clear target users"],
            ),
        ],
    )


def compact_graph(graph: ModelGraph) -> Dict[str, Any]:
    return {
        "graph_id": graph.graph_id,
        "title": graph.title,
        "entry_nodes": list(graph.entry_nodes),
        "target_nodes": list(graph.target_nodes),
        "nodes": {
            model_id: {
                "role": node.role,
                "purpose": node.purpose,
                "required": node.required,
                "outputs": list(node.outputs),
            }
            for model_id, node in graph.nodes.items()
        },
        "edges": [
            {
                "from": edge.source,
                "to": edge.target,
                "relation": edge.relation,
                "required": edge.required,
                "use_when": list(edge.use_when),
            }
            for edge in graph.edges
        ],
    }


def model_relations_for_path(graph: ModelGraph, path: List[str]) -> List[Dict[str, Any]]:
    relations: List[Dict[str, Any]] = []
    for index, source in enumerate(path[:-1]):
        target = path[index + 1]
        edge = next((item for item in graph.edges if item.source == source and item.target == target), None)
        if edge:
            relations.append({"from": source, "to": target, "relation": edge.relation, "required": edge.required})
    return relations
