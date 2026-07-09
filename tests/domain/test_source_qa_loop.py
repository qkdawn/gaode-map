import asyncio

from modules.agent.schemas import AgentContextAskRequest
from modules.agent.selected_sources import source_summary_payloads_from_items
from modules.agent.source_qa_loop import run_source_qa_loop
from modules.agent.source_qa_prompts import SOURCE_QA_SYSTEM_PROMPT
from modules.agent.source_qa_tools import selected_dataset_source_ids, selected_source_ids


def _payload(*, history_id="history-1", source_id="current:analysis:road"):
    return AgentContextAskRequest(
        conversation_id="agent-1",
        history_id=history_id,
        question="为什么这里路网较差",
        analysis_snapshot={"context": {"scope_label": "测试区域"}},
        target={
            "type": "analysis_sources",
            "id": "analysis-selected-sources",
            "title": "已选分析来源",
            "source": "analysis",
            "payload": {"sources": [{"source_id": source_id, "title": "路网与可达性分析"}]},
        },
        require_ai=True,
    )


def _tool_call_response(tool_name, arguments, call_id="call-1"):
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                }],
            }
        }]
    }


def _final_response(answer="已基于来源工具回答。"):
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": (
                    '{"answer":"%s","evidence":[],"citations":[],"warnings":["没有外部基准，不能证明整体较差。"]}'
                    % answer
                ),
            }
        }]
    }


class FakeScopeDatasetService:
    def list_scope_datasets(self, history_id):
        assert history_id == "history-1"
        return {
            "datasets": [{
                "source_id": "current:dataset:road",
                "record_count": 2,
                "time_scope": {"years": [2024], "label": "2024 年"},
                "query_capabilities": {"sort_fields": ["connectivity"]},
            }],
            "warnings": [],
        }

    def query_scope_dataset(self, **kwargs):
        assert kwargs["history_id"] == "history-1"
        assert kwargs["source_id"] == "current:dataset:road"
        return {
            "source_id": "current:dataset:road",
            "total_count": 1,
            "limit": 5,
            "offset": 0,
            "has_more": False,
            "records": [{
                "record_id": "road:r1",
                "source_id": "current:dataset:road",
                "title": "r1",
                "content": "连接度较低的路段",
                "properties": {"connectivity": 1},
                "time_scope": {"year": 2024},
                "locator": "current:dataset:road/road:r1",
                "citation": "当前范围路网，2024 年",
                "warnings": [],
            }],
            "evidence_nodes": [{
                "id": "current:dataset:road:record:road:r1",
                "source_id": "current:dataset:road",
                "source_type": "system",
                "title": "r1",
                "content": "连接度较低的路段",
                "metadata": {"time_scope": {"year": 2024}},
                "locator": "current:dataset:road/road:r1",
                "citation": "当前范围路网，2024 年",
            }],
            "warnings": [],
        }

    def aggregate_scope_dataset(self, **kwargs):
        return {"source_id": kwargs["source_id"], "group_by": "", "total_groups": 1, "rows": [{"group": "all", "count": 2}], "warnings": []}

    def read_scope_record(self, **kwargs):
        return {"source_id": kwargs["source_id"], "record_id": kwargs["record_id"], "record": {}, "evidence_node": None, "warnings": []}


def test_source_qa_maps_selected_analysis_sources():
    assert selected_dataset_source_ids(_payload()) == ["current:dataset:road"]
    assert selected_dataset_source_ids(_payload(source_id="current:dataset:population")) == ["current:dataset:population"]
    assert selected_dataset_source_ids(_payload(source_id="current:analysis:poi_h3")) == ["current:dataset:h3", "current:dataset:poi"]


def test_source_qa_source_summary_keeps_metric_arrays():
    summaries = source_summary_payloads_from_items([
        {
            "source_id": "current:analysis:poi_h3",
            "title": "POI H3",
            "included": ["metrics", "metric_gaps"],
            "metrics": [
                {"metric_id": "analysis:h3:grid_count", "label": "网格数量", "value": 12},
                {"metric_id": "analysis:h3:avg_density", "label": "平均密度", "value": 42.5},
            ],
            "metric_gaps": [{"metric_id": "analysis:h3:lisa", "reason": "结果未返回"}],
        }
    ])

    assert summaries[0]["metrics"][0]["metric_id"] == "analysis:h3:grid_count"
    assert summaries[0]["metrics"][1]["value"] == 42.5
    assert summaries[0]["metric_gaps"][0]["metric_id"] == "analysis:h3:lisa"


def test_source_qa_prompt_contains_professional_output_rules():
    for token in ["专业分析", "结构清晰", "支撑证据", "空间或商业含义", "边界", "下一步", "Markdown", "分析目的", "小标题"]:
        assert token in SOURCE_QA_SYSTEM_PROMPT
    for token in ["## 总体判断", "## 关键证据", "## 空间/商业解释", "## 边界与下一步"]:
        assert token not in SOURCE_QA_SYSTEM_PROMPT
    for token in ["Observation", "Mechanism", "Alternative", "Evidence Quality", "Implication", "替代解释", "证据质量"]:
        assert token in SOURCE_QA_SYSTEM_PROMPT
    assert "直接回答：" not in SOURCE_QA_SYSTEM_PROMPT
    assert "可继续追问：" not in SOURCE_QA_SYSTEM_PROMPT


def test_source_qa_loop_can_answer_non_dataset_sources_with_source_tools(monkeypatch):
    import modules.agent.source_qa_loop as loop

    captured = {}
    responses = [
        _tool_call_response("search_selected_source_evidence", '{"query":"公共服务","source_ids":["document:doc-1"],"top_k":5}'),
        _final_response("已基于文档 EvidenceNode 回答。"),
    ]

    async def fake_chat_completion(body):
        if not captured:
            captured.update(body)
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    payload = _payload(source_id="document:doc-1", history_id="")
    payload.target.payload["sources"][0].update({
        "source_kind": "document",
        "evidence_nodes": [{
            "id": "document:doc-1:evidence:1",
            "source_id": "document:doc-1",
            "title": "公共服务配置",
            "content": "片区需要补足公共服务与慢行连通。",
            "citation": "PageIndex p.3",
        }],
    })
    result = asyncio.run(run_source_qa_loop(payload))

    assert result.status == "success"
    assert "search_selected_source_evidence" in [tool["function"]["name"] for tool in captured["tools"]]
    assert result.used_tools == ["search_selected_source_evidence"]
    assert result.evidence[0]["source_id"] == "document:doc-1"
    assert result.citations == ["PageIndex p.3"]


def test_source_qa_loop_executes_allowed_scope_dataset_tool(monkeypatch):
    import modules.agent.source_qa_loop as loop
    import modules.agent.tool_adapters.scope_dataset_tools as scope_tools

    responses = [
        _tool_call_response(
            "query_scope_dataset",
            '{"source_id":"current:dataset:road","filters":{"feature_kind":"road"},"sort":{"field":"connectivity","direction":"asc"},"limit":5}',
        ),
        _final_response(),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)
    monkeypatch.setattr(scope_tools, "ScopeDatasetService", FakeScopeDatasetService)

    result = asyncio.run(run_source_qa_loop(_payload()))

    assert result.status == "success"
    assert result.used_tools == ["query_scope_dataset"]
    assert result.tool_results[0].result["records"][0]["record_id"] == "road:r1"
    assert result.evidence[0]["source_id"] == "current:dataset:road"
    assert result.citations == ["当前范围路网，2024 年"]
    assert any("外部基准" in item for item in result.warnings)


def test_source_qa_loop_lists_selected_sources(monkeypatch):
    import modules.agent.source_qa_loop as loop

    responses = [
        _tool_call_response("list_selected_sources", "{}"),
        _final_response("已列出来源。"),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    result = asyncio.run(run_source_qa_loop(_payload(source_id="current:scope", history_id="")))

    assert result.status == "success"
    assert result.used_tools == ["list_selected_sources"]
    assert result.tool_results[0].result["sources"][0]["source_id"] == "current:scope"


def test_source_qa_loop_rejects_unselected_source_id(monkeypatch):
    import modules.agent.source_qa_loop as loop

    responses = [
        _tool_call_response("query_scope_dataset", '{"source_id":"current:dataset:poi","limit":5}'),
        _final_response("已拒绝未选来源。"),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    result = asyncio.run(run_source_qa_loop(_payload()))

    assert result.status == "success"
    assert result.tool_results[0].status == "failed"
    assert result.tool_results[0].error == "source_id_not_selected:current:dataset:poi"
    assert any("source_id_not_selected" in item for item in result.warnings)


def test_source_qa_loop_rejects_unselected_evidence_source(monkeypatch):
    import modules.agent.source_qa_loop as loop

    responses = [
        _tool_call_response("search_selected_source_evidence", '{"query":"商业","source_ids":["web:not-selected"],"top_k":5}'),
        _final_response("已拒绝未选来源。"),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    result = asyncio.run(run_source_qa_loop(_payload(source_id="document:doc-1", history_id="")))

    assert result.status == "success"
    assert result.tool_results[0].status == "failed"
    assert result.tool_results[0].error == "source_id_not_selected"
    assert any("source_id_not_selected:web:not-selected" in item for item in result.warnings)


def test_source_qa_loop_reads_selected_source_node_through_unified_index(monkeypatch):
    import modules.agent.source_qa_loop as loop

    responses = [
        _tool_call_response("read_selected_source_evidence_node", '{"node_id":"web:area-1:web:node-1","source_id":"web:area-1"}'),
        _final_response("已读取网页节点。"),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    payload = _payload(source_id="web:area-1", history_id="")
    payload.target.payload["sources"][0].update({
        "source_kind": "web",
        "evidence_nodes": [{
            "id": "web:area-1:web:node-1",
            "source_id": "web:area-1",
            "source_type": "web",
            "title": "政策网页",
            "content": "公共服务和城市更新政策资料。",
            "metadata": {"url": "https://example.com/policy"},
            "locator": "https://example.com/policy",
            "citation": "example.com",
        }],
        "index_manifest": {
            "source_id": "web:area-1",
            "source_kind": "web",
            "native_index_kind": "webpage_index",
            "node_count": 1,
            "retrieval_modes": ["keyword"],
            "read_modes": ["node_id", "url"],
            "storage_ref": {"urls": ["https://example.com/policy"]},
        },
    })

    result = asyncio.run(run_source_qa_loop(payload))

    assert result.status == "success"
    assert result.used_tools == ["read_selected_source_evidence_node"]
    assert result.tool_results[0].status == "success"
    assert result.tool_results[0].result["evidence_node"]["id"] == "web:area-1:web:node-1"
    assert result.evidence[0]["source_id"] == "web:area-1"


def test_source_qa_loop_rejects_unselected_source_id_when_reading_node(monkeypatch):
    import modules.agent.source_qa_loop as loop

    responses = [
        _tool_call_response("read_selected_source_evidence_node", '{"node_id":"web:not-selected:node:1","source_id":"web:not-selected"}'),
        _final_response("已拒绝未选来源。"),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    result = asyncio.run(run_source_qa_loop(_payload(source_id="web:area-1", history_id="")))

    assert result.status == "success"
    assert result.tool_results[0].status == "failed"
    assert result.tool_results[0].error == "source_id_not_selected"
    assert any("source_id_not_selected:web:not-selected" in item for item in result.warnings)


def test_source_qa_loop_allows_poi_aggregation_for_poi_h3_source(monkeypatch):
    import modules.agent.source_qa_loop as loop
    import modules.agent.tool_adapters.scope_dataset_tools as scope_tools

    class FakePoiScopeDatasetService(FakeScopeDatasetService):
        def aggregate_scope_dataset(self, **kwargs):
            assert kwargs["history_id"] == "history-1"
            assert kwargs["source_id"] == "current:dataset:poi"
            assert kwargs["group_by"] == "category"
            return {
                "source_id": "current:dataset:poi",
                "group_by": "category",
                "total_groups": 2,
                "rows": [{"group": "餐饮", "count": 12}, {"group": "零售", "count": 8}],
                "warnings": [],
            }

    responses = [
        _tool_call_response(
            "aggregate_scope_dataset",
            '{"source_id":"current:dataset:poi","group_by":"category","metrics":[{"op":"count","field":"*","as":"count"}],"top_k":10}',
        ),
        _final_response("已基于 POI 业态聚合回答。"),
    ]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)
    monkeypatch.setattr(scope_tools, "ScopeDatasetService", FakePoiScopeDatasetService)

    result = asyncio.run(run_source_qa_loop(_payload(source_id="current:analysis:poi_h3")))

    assert result.status == "success"
    assert result.used_tools == ["aggregate_scope_dataset"]
    assert result.tool_results[0].status == "success"
    assert result.tool_results[0].result["rows"][0]["group"] == "餐饮"


def test_source_qa_loop_requires_history_id_without_tool_call(monkeypatch):
    import modules.agent.source_qa_loop as loop

    async def fake_chat_completion(_body):
        raise AssertionError("history_id failure should not call LLM tools")

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)

    result = asyncio.run(run_source_qa_loop(_payload(history_id="")))

    assert result.status == "failed"
    assert result.error == "history_id_required"
    assert any("history_id" in item for item in result.warnings)


def test_source_qa_selected_source_ids_include_non_dataset_sources():
    assert selected_source_ids(_payload(source_id="document:doc-1")) == ["document:doc-1"]


def test_source_qa_loop_respects_tool_call_limit(monkeypatch):
    import modules.agent.source_qa_loop as loop
    import modules.agent.tool_adapters.scope_dataset_tools as scope_tools

    first_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call-{index}",
                        "type": "function",
                        "function": {
                            "name": "query_scope_dataset",
                            "arguments": '{"source_id":"current:dataset:road","limit":1}',
                        },
                    }
                    for index in range(9)
                ],
            }
        }]
    }
    responses = [first_response, _final_response("已达到工具调用上限。")]

    async def fake_chat_completion(_body):
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)
    monkeypatch.setattr(scope_tools, "ScopeDatasetService", FakeScopeDatasetService)

    result = asyncio.run(run_source_qa_loop(_payload()))

    assert len(result.tool_results) == 8
    assert any("工具调用超过上限" in item for item in result.warnings)


def test_source_qa_final_payload_contains_expanded_answer_instructions(monkeypatch):
    import modules.agent.source_qa_loop as loop
    import modules.agent.tool_adapters.scope_dataset_tools as scope_tools

    captured_final_payload = {}
    first_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call-{index}",
                        "type": "function",
                        "function": {
                            "name": "query_scope_dataset",
                            "arguments": '{"source_id":"current:dataset:road","limit":1}',
                        },
                    }
                    for index in range(9)
                ],
            }
        }]
    }
    responses = [first_response, _final_response("已达到工具调用上限。")]

    async def fake_chat_completion(body):
        if body.get("response_format") == {"type": "json_object"}:
            captured_final_payload.update(body)
        return responses.pop(0)

    monkeypatch.setattr(loop, "_chat_completion", fake_chat_completion)
    monkeypatch.setattr(scope_tools, "ScopeDatasetService", FakeScopeDatasetService)

    result = asyncio.run(run_source_qa_loop(_payload()))

    assert result.status == "success"
    final_user_payload = captured_final_payload["messages"][1]["content"]
    for token in ["Markdown", "因果链", "支撑证据", "空间或商业含义", "边界", "下一步", "EvidenceNode"]:
        assert token in final_user_payload
    for token in ["## 总体判断", "## 关键证据", "## 空间/商业解释", "## 边界与下一步"]:
        assert token not in final_user_payload
    for token in ["Observation", "Mechanism", "Alternative", "Evidence Quality", "Implication", "替代解释", "证据质量"]:
        assert token in final_user_payload


def test_source_qa_reasoning_rubric_allows_simple_quantity_answers():
    assert "简单数量、状态、定义类问题可以简洁" in SOURCE_QA_SYSTEM_PROMPT
    assert "answer 长度按问题决定" in SOURCE_QA_SYSTEM_PROMPT
    assert "600-1200" not in SOURCE_QA_SYSTEM_PROMPT
    assert "简单问题直接回答" in SOURCE_QA_SYSTEM_PROMPT
