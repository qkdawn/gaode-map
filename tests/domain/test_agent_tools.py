import asyncio

import modules.agent.tool_adapters.scope_dataset_tools as scope_dataset_tools
from modules.agent.context_ask_compaction import compact_evidence_nodes
from modules.agent.selected_sources import evidence_count_from_item, evidence_nodes_from_item, selected_sources_summary_from_items, source_records_from_items
from modules.agent.tool_definitions.source_evidence import read_selected_source_evidence_node
from modules.agent.providers.tool_call_execution import execute_tool_call_step
from modules.agent.schemas import AnalysisSnapshot, ExecutionTraceItem, PlanStep
from modules.agent.executor import validate_tool_arguments
from modules.agent.tools import get_tool_registry
from modules.providers.amap.utils.get_type_info import infer_type_info_from_text, resolve_type_info


def test_get_tool_registry_exposes_stage1_tools():
    registry = get_tool_registry()

    assert set(registry.keys()) == {
        "read_current_scope",
        "read_current_results",
        "plan_business_analyst_analysis",
        "list_selected_sources",
        "search_selected_source_evidence",
        "read_selected_source_evidence_node",
        "search_analysis_context",
        "read_analysis_evidence_node",
        "search_report_context",
        "read_report_evidence_node",
        "list_scope_datasets",
        "query_scope_dataset",
        "aggregate_scope_dataset",
        "read_scope_record",
    }
    assert registry["read_current_scope"].spec.readonly is True
    assert registry["read_current_scope"].spec.input_schema["additionalProperties"] is False
    assert registry["read_current_scope"].spec.output_schema["properties"]["has_scope"]["type"] == "boolean"
    assert registry["read_current_scope"].spec.ui_tier == "foundation"
    assert registry["read_current_results"].spec.llm_exposure == "primary"
    assert registry["plan_business_analyst_analysis"].spec.readonly is True
    assert registry["plan_business_analyst_analysis"].spec.llm_exposure == "primary"
    assert registry["plan_business_analyst_analysis"].spec.produces == ["business_analyst_skeleton"]
    assert registry["list_selected_sources"].spec.readonly is True
    assert registry["search_selected_source_evidence"].spec.input_schema["required"] == ["query"]
    assert registry["read_selected_source_evidence_node"].spec.input_schema["required"] == ["node_id"]
    assert "search_database_context" not in registry
    assert "read_database_record" not in registry
    assert "fetch_pois_in_scope" not in registry
    assert "compute_road_syntax_from_scope" not in registry
    assert "run_area_character_pack" not in registry
    assert "run_site_selection_pack" not in registry
    assert registry["list_scope_datasets"].spec.llm_exposure == "primary"
    assert registry["query_scope_dataset"].spec.readonly is True
    assert registry["query_scope_dataset"].spec.input_schema["properties"]["source_id"]["enum"] == [
        "current:dataset:poi",
        "current:dataset:h3",
        "current:dataset:population",
        "current:dataset:nightlight",
        "current:dataset:road",
    ]


def test_get_tool_registry_keeps_expected_tool_order():
    registry = get_tool_registry()

    assert list(registry.keys()) == [
        "read_current_scope",
        "read_current_results",
        "plan_business_analyst_analysis",
        "list_selected_sources",
        "search_selected_source_evidence",
        "read_selected_source_evidence_node",
        "search_analysis_context",
        "read_analysis_evidence_node",
        "search_report_context",
        "read_report_evidence_node",
        "list_scope_datasets",
        "query_scope_dataset",
        "aggregate_scope_dataset",
        "read_scope_record",
    ]


def test_validate_tool_arguments_rejects_unknown_keys():
    registry = get_tool_registry()
    errors = validate_tool_arguments(
        {"query": "商业", "unexpected": True},
        registry["search_selected_source_evidence"].spec.input_schema,
    )

    assert "arguments.unexpected 不允许出现" in errors


def test_execution_trace_item_accepts_blocked_status():
    trace = ExecutionTraceItem(tool_name="compute_road_syntax_from_scope", status="blocked")

    assert trace.status == "blocked"


def test_scope_dataset_tool_reads_history_id_from_snapshot(monkeypatch):
    seen = {}

    class FakeScopeDatasetService:
        def list_scope_datasets(self, history_id):
            seen["history_id"] = history_id
            return {"datasets": [{"source_id": "current:dataset:poi"}], "warnings": []}

    monkeypatch.setattr(scope_dataset_tools, "ScopeDatasetService", FakeScopeDatasetService)
    result = asyncio.run(
        scope_dataset_tools.list_scope_datasets(
            arguments={},
            snapshot=AnalysisSnapshot(context={"history_id": "history-1"}),
            artifacts={},
            question="当前范围有哪些数据",
        )
    )

    assert result.status == "success"
    assert seen["history_id"] == "history-1"
    assert result.result["datasets"][0]["source_id"] == "current:dataset:poi"


def test_read_selected_source_evidence_node_uses_unified_index_without_cache():
    artifacts = {
        "selected_sources_context": {
            "sources": [
                {
                    "source_id": "web:area-1",
                    "title": "网页来源",
                    "source_kind": "web",
                    "evidence_nodes": [
                        {
                            "id": "web:area-1:node:1",
                            "source_id": "web:area-1",
                            "source_type": "web",
                            "title": "政策网页",
                            "content": "公共服务和城市更新政策资料。",
                        }
                    ],
                }
            ]
        }
    }

    result = asyncio.run(
        read_selected_source_evidence_node(
            arguments={"node_id": "web:area-1:node:1"},
            snapshot=AnalysisSnapshot(),
            artifacts=artifacts,
            question="公共服务",
        )
    )

    assert result.status == "success"
    assert result.result["evidence_node"]["id"] == "web:area-1:node:1"
    assert result.result["source_type"] == "web"


def test_selected_source_evidence_nodes_do_not_fallback_to_summary_evidence():
    source = {
        "source_id": "document:doc-1",
        "title": "文档来源",
        "evidence": [{"title": "摘要证据", "text": "这是展示用摘要，不是 EvidenceNode。"}],
        "evidenceNodes": [{"id": "legacy-camel", "content": "旧 camel 字段不应再被读取。"}],
    }

    assert evidence_nodes_from_item(source) == []
    assert evidence_count_from_item(source) == 0


def test_compact_evidence_nodes_uses_current_source_fields_only():
    nodes = compact_evidence_nodes([
        {
            "nodeId": "legacy-node",
            "sourceId": "legacy-source",
            "sourceType": "legacy-type",
            "title": "旧字段证据",
            "content": "旧 camel 字段不应再参与上下文压缩。",
        },
        {
            "id": "canonical-node",
            "source_id": "canonical-source",
            "source_type": "system",
            "title": "当前字段证据",
            "content": "当前 snake 字段可以进入上下文。",
        },
    ])

    assert "id" not in nodes[0]
    assert "source_id" not in nodes[0]
    assert "source_type" not in nodes[0]
    assert nodes[1]["id"] == "canonical-node"
    assert nodes[1]["source_id"] == "canonical-source"
    assert nodes[1]["source_type"] == "system"


def test_selected_source_summary_uses_current_payload_fields_only():
    source = {
        "source_id": "current:analysis:road",
        "title": "路网分析",
        "source_kind": "system",
        "locatorSummary": "旧定位摘要",
        "metricGaps": ["旧指标缺口"],
        "visualSpecs": [{"visual_id": "legacy-visual"}, {"visual_id": "legacy-visual-2"}],
        "transportStatus": "legacy_ready",
        "locator_summary": "当前定位摘要",
        "metric_gaps": ["当前指标缺口"],
        "visual_specs": [{"visual_id": "current-visual"}],
        "transport_status": "ready_to_send",
    }

    summary = selected_sources_summary_from_items([source])["sources"][0]
    record = source_records_from_items([source])[0]

    assert summary["metric_gaps"] == ["当前指标缺口"]
    assert summary["visual_specs_count"] == 1
    assert summary["transport_status"] == "ready_to_send"
    assert record.locator_summary == "当前定位摘要"


def test_read_selected_source_evidence_node_rejects_unselected_source_id():
    artifacts = {
        "selected_sources_context": {
            "sources": [
                {
                    "source_id": "web:area-1",
                    "title": "网页来源",
                    "source_kind": "web",
                    "evidence_nodes": [],
                }
            ]
        }
    }

    result = asyncio.run(
        read_selected_source_evidence_node(
            arguments={"node_id": "web:not-selected:node:1", "source_id": "web:not-selected"},
            snapshot=AnalysisSnapshot(),
            artifacts=artifacts,
            question="公共服务",
        )
    )

    assert result.status == "failed"
    assert result.error == "source_id_not_selected"
    assert "source_id_not_selected:web:not-selected" in result.warnings


def test_governance_blocked_tool_call_keeps_result_failed_and_trace_blocked():
    registry = get_tool_registry()
    step = PlanStep(tool_name="compute_road_syntax_from_scope", reason="需要路网句法")

    execution = asyncio.run(
        execute_tool_call_step(
            registered_tool=registry.get("compute_road_syntax_from_scope"),
            step=step,
            snapshot=AnalysisSnapshot(scope={"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}),
            artifacts={},
            question="为什么这里路网差",
            governance_mode="guarded",
            confirmed_tools=[],
        )
    )

    assert execution.trace.status == "failed"
    assert execution.result.status == "failed"
    assert execution.result.error == "unknown_tool:compute_road_syntax_from_scope"


def test_resolve_type_info_supports_aliases_for_site_advice():
    coffee_by_label = resolve_type_info("咖啡厅")
    coffee_by_alias = resolve_type_info("咖啡店")
    inferred = infer_type_info_from_text("我想在这里开一家咖啡店，给我建议")

    assert coffee_by_label is not None
    assert coffee_by_alias is not None
    assert inferred is not None
    assert coffee_by_alias["types"] == coffee_by_label["types"]
    assert inferred["keywords"] == "咖啡厅"
    assert resolve_type_info("不存在的业态") is None
