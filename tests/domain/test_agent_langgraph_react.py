import asyncio
import json

from modules.agent.context_builder import build_context_bundle
from modules.agent.providers.langgraph_react import _initial_payload, _react_tool_result_payload
from modules.agent.providers.prompts import loop_system_prompt, synthesizer_system_prompt
from modules.agent.providers.tool_loop import apply_tool_allocation, select_react_tool_registry, tool_allocation_candidates
from modules.agent.schemas import AnalysisSnapshot, ToolResult
from modules.agent.tool_definitions.source_evidence import search_selected_source_evidence
from modules.agent.tools import get_tool_registry


def _snapshot_with_scope() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        scope={
            "polygon": [
                [116.38, 39.90],
                [116.39, 39.90],
                [116.39, 39.91],
                [116.38, 39.91],
                [116.38, 39.90],
            ]
        },
        poi_summary={"total": 2},
        pois=[{"name": "A"}, {"name": "B"}],
        road={"summary": {"node_count": 3, "edge_count": 2}},
    )


def test_loop_prompt_is_main_agent_deep_only():
    prompt = loop_system_prompt()

    assert f"{'qu'}ick 模式" not in prompt
    assert "Main Agent 深度分析链路" in prompt
    assert "固定栏目" in prompt
    assert "城市空间与文旅商业策划分析顾问" in prompt
    assert "空间现象、人的体验、策划影响、下一步动作" in prompt
    assert "plan_business_analyst_analysis" in prompt
    assert "BA 分析骨架" in prompt
    finalizer_prompt = synthesizer_system_prompt()
    assert "business_analyst_skeleton" in finalizer_prompt
    assert "输出模板" in finalizer_prompt
    assert "只有用户明确要求 BA 报告" in finalizer_prompt
    assert "必须包含一个 Model Scorecard" not in finalizer_prompt


def test_langgraph_initial_payload_uses_digest_instead_of_full_snapshot():
    snapshot = AnalysisSnapshot(
        scope={"polygon": [[116.38, 39.90], [116.39, 39.90], [116.39, 39.91], [116.38, 39.90]]},
        poi_summary={"total": 1200},
        h3={
            "summary": {"grid_count": 3},
            "charts": {"huge_series": list(range(500))},
            "poi_h3_evidence": {"cells": [{"cell_id": f"cell-{index}", "poi_count": index} for index in range(120)]},
        },
        population={"summary": {"total_population": 10000}, "grid_evidence": {"cells": list(range(300))}},
        frontend_analysis={"poi": {"large": list(range(300))}, "h3": {"large": list(range(300))}},
        shared_grid={"cells": [{"cell_id": f"shared-{index}"} for index in range(200)]},
    )
    registry = get_tool_registry()
    payload = _initial_payload(
        question="这个区域怎么样",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        registry={"read_current_results": registry["read_current_results"]},
    )
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "analysis_snapshot" not in payload
    assert "analysis_snapshot_digest" in payload
    assert "huge_series" not in encoded
    assert "shared-199" not in encoded
    assert "cell-119" not in encoded
    assert "frontend_analysis" in encoded


def test_langgraph_initial_payload_catalogs_business_analyst_skeleton():
    registry = get_tool_registry()
    payload = _initial_payload(
        question="这里适合开咖啡店吗",
        snapshot=_snapshot_with_scope(),
        context=build_context_bundle(_snapshot_with_scope()),
        registry={"read_current_results": registry["read_current_results"]},
        artifacts={
            "business_analyst_skeleton": {
                "status": "ready",
                "selected_skill": {
                    "skill_id": "ba.single_category_site_selection",
                    "title": "Single category site selection",
                    "purpose": "Judge site suitability.",
                    "uses_model_graph": "ba.business_analyst_model_graph.v1",
                },
                "model_graph": {"graph_id": "ba.business_analyst_model_graph.v1"},
                "recommended_path": ["TradeAreaModel", "MarketPotentialModel", "RetailGapModel", "SiteSuitabilityModel"],
                "path_relations": [{"from": "RetailGapModel", "to": "SiteSuitabilityModel", "relation": "provides_candidate_zones"}],
                "model_tool_map": {"SiteSuitabilityModel": {"required_tools": ["query_scope_dataset"]}},
                "skip_conditions": {"HuffGravityModel": ["no candidate site"]},
                "guardrails": ["recommendation_requires_validation"],
                "answer_guidance": ["Use this Business Analyst output as an analysis skeleton, not as an answer template."],
            }
        },
    )

    catalog = payload["artifact_catalog"]["business_analyst_skeleton"]
    assert catalog["selected_skill"]["skill_id"] == "ba.single_category_site_selection"
    assert catalog["recommended_path"][-1] == "SiteSuitabilityModel"
    assert catalog["model_tool_map"]["SiteSuitabilityModel"]["required_tools"] == ["query_scope_dataset"]
    assert catalog["skip_conditions"]["HuffGravityModel"] == ["no candidate site"]


def test_langgraph_initial_payload_catalogs_spatial_evidence_memo_for_parent_consumption():
    registry = get_tool_registry()
    payload = _initial_payload(
        question="继续完成正式报告",
        snapshot=_snapshot_with_scope(),
        context=build_context_bundle(_snapshot_with_scope()),
        registry={"read_current_results": registry["read_current_results"]},
        artifacts={"spatial_evidence_research": {
            "skill_id": "spatial-evidence-research",
            "status": "completed",
            "artifacts": {"spatial_evidence_packet": {
                "status": "partial",
                "decision_questions": ["入口如何组织"],
                "limitations": ["消防边界待核验"],
                "does_not_prove": ["不证明客流"],
            }},
        }},
    )

    catalog = payload["artifact_catalog"]["spatial_evidence_research"]
    assert catalog["decision_questions"] == ["入口如何组织"]
    assert catalog["does_not_prove"] == ["不证明客流"]


def test_react_tool_registry_defaults_to_core_analysis_tools():
    selected = select_react_tool_registry(
        get_tool_registry(),
        question="总结这个区域的空间结构",
        artifacts={},
        include_secondary=True,
    )

    assert list(selected) == [
        "read_current_scope",
        "read_current_results",
        "search_analysis_context",
        "read_analysis_evidence_node",
    ]


def test_react_tool_registry_opens_contextual_tool_windows():
    registry = get_tool_registry()

    source_selected = select_react_tool_registry(
        registry,
        question="分析已选资料里的政策依据",
        artifacts={"selected_sources_context": {"sources": [{"source_id": "document:1"}]}},
        include_secondary=True,
    )
    assert {"list_selected_sources", "search_selected_source_evidence", "read_selected_source_evidence_node"}.issubset(source_selected)

    report_selected = select_react_tool_registry(
        registry,
        question="报告里这个结论的依据是什么",
        artifacts={},
        include_secondary=True,
    )
    assert {"search_report_context", "read_report_evidence_node"}.issubset(report_selected)

    dataset_selected = select_react_tool_registry(
        registry,
        question="当前范围 POI 类别分别有多少",
        artifacts={},
        include_secondary=True,
    )
    assert {"list_scope_datasets", "aggregate_scope_dataset", "query_scope_dataset", "read_scope_record"}.issubset(dataset_selected)
    assert "query_current_pois" in dataset_selected

    poi_list_selected = select_react_tool_registry(
        registry,
        question="范围内所有学校有哪些",
        artifacts={},
        include_secondary=True,
    )
    assert "query_current_pois" in poi_list_selected

    ba_selected = select_react_tool_registry(
        registry,
        question="这里适合开咖啡店吗",
        artifacts={},
        include_secondary=True,
    )
    assert "plan_business_analyst_analysis" in ba_selected

    web_research_selected = select_react_tool_registry(
        registry,
        question="请为这个历史建筑更新项目检索公开网页和竞品资料",
        artifacts={},
        include_secondary=True,
    )
    assert "search_public_web" in web_research_selected


def test_tool_allocation_candidates_are_role_bound_and_override_keyword_windows():
    registry = get_tool_registry()
    cultural_candidates = tool_allocation_candidates(registry, agent_role="cultural_tourism_research")
    market_candidates = tool_allocation_candidates(registry, agent_role="market_audience_research")

    assert {"search_public_web", "query_scope_dataset", "aggregate_scope_dataset"}.issubset(cultural_candidates)
    assert {"search_public_web", "plan_business_analyst_analysis", "query_scope_dataset"}.issubset(market_candidates)

    granted = apply_tool_allocation(registry, ["read_current_scope", "search_public_web"])
    assert list(granted) == ["read_current_scope", "search_public_web"]


def test_selected_source_search_miss_warning_is_scoped_to_selected_sources():
    result = asyncio.run(
        search_selected_source_evidence(
            arguments={"query": "商业决策路径", "top_k": 3},
            snapshot=_snapshot_with_scope(),
            artifacts={
                "selected_sources_context": {
                    "sources": [{
                        "source_id": "document:1",
                        "title": "项目文档",
                        "source_kind": "document",
                        "evidence_nodes": [{"id": "node-1", "title": "更新目标", "content": "城市更新。"}],
                    }]
                }
            },
            question="请整理商业决策路径",
        )
    )

    assert result.warnings
    assert "已选来源 EvidenceNode 未命中" in result.warnings[0]
    assert "不代表当前地图分析上下文没有证据" in result.warnings[0]


def test_langgraph_tool_result_payload_compacts_large_results_and_artifacts():
    result = ToolResult(
        tool_name="read_current_results",
        status="success",
        result={"rows": [{"id": index, "value": index} for index in range(80)], "total": 80},
        evidence=[{"field": f"metric.{index}", "value": index} for index in range(40)],
        artifacts={
            "current_poi_h3": {"grid": [{"cell_id": f"cell-{index}"} for index in range(200)]},
            "current_frontend_analysis": {"poi": {"large": list(range(200))}},
        },
    )
    payload = json.loads(_react_tool_result_payload(result))
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["result_summary"]
    assert payload["artifact_keys"] == ["current_poi_h3", "current_frontend_analysis"]
    assert "current_frontend_analysis" in encoded
    assert "cell-199" not in encoded
    assert "metric.39" not in encoded
    assert payload["result"]["rows"]["type"] == "array"
    assert payload["evidence"]["type"] == "array"
