from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
NODE_NAMES = {
    "Build Structured Decision Request": "构建证据路由请求",
    "Prepare MCP Agent Tool Call": "准备证据路由工具调用",
    "Build MCP Agent Follow-up": "更新证据简报",
}


def _code(name: str) -> str:
    workflow = _workflow()
    localized = NODE_NAMES.get(name, name)
    return next(node for node in workflow["nodes"] if node["name"] == localized)["parameters"]["jsCode"]


@lru_cache(maxsize=1)
def _workflow() -> dict:
    script = "import('./n8n/workflow-generators/urban-renewal-agent.workflow.mjs').then((m) => process.stdout.write(JSON.stringify(m.default)));"
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _run_follow_up(prior: dict, tool_result: dict | list[dict], prepared_items: list[dict] | None = None) -> dict:
    tool_results = tool_result if isinstance(tool_result, list) else [tool_result]
    prepared = prepared_items or [
        {
            **prior,
            "batch_index": index,
            "mcp_tool_name": str(result.get("tool_name") or prior.get("mcp_tool_name") or ""),
            "mcp_call_id": str(result.get("mcp_call_id") or f"call-{index}"),
        }
        for index, result in enumerate(tool_results)
    ]
    script = f"""
const code = {json.dumps(_code('Build MCP Agent Follow-up'), ensure_ascii=False)};
const prior = {json.dumps(prior, ensure_ascii=False)};
const toolResults = {json.dumps(tool_results, ensure_ascii=False)};
const preparedItems = {json.dumps(prepared, ensure_ascii=False)};
const run = new Function('$input', '$', code);
const output = run(
  {{ all: () => toolResults.map((result) => ({{ json: result }})), first: () => ({{ json: toolResults[0] }}) }},
  () => ({{ all: () => preparedItems.map((item) => ({{ json: item }})), first: () => ({{ json: preparedItems[0] }}) }}),
);
process.stdout.write(JSON.stringify(output[0].json));
"""
    result = subprocess.run(
        ["node", "-"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=script,
    )
    return json.loads(result.stdout)


def _run_prepare(payload: dict, state: dict) -> list[dict]:
    script = f"""
const code = {json.dumps(_code('Prepare MCP Agent Tool Call'), ensure_ascii=False)};
const payload = {json.dumps(payload, ensure_ascii=False)};
const state = {json.dumps(state, ensure_ascii=False)};
const run = new Function('$input', '$', code);
const output = run(
  {{ first: () => ({{ json: payload }}), all: () => [{{ json: payload }}] }},
  () => ({{ first: () => ({{ json: {{ state }} }}) }}),
);
process.stdout.write(JSON.stringify(output.map((item) => item.json)));
"""
    result = subprocess.run(
        ["node", "-"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", input=script
    )
    return json.loads(result.stdout)


def _run_input_code(name: str, payload: dict) -> dict:
    script = f"""
const code = {json.dumps(_code(name), ensure_ascii=False)};
const payload = {json.dumps(payload, ensure_ascii=False)};
const run = new Function('$input', code);
const output = run({{ first: () => ({{ json: payload }}), all: () => [{{ json: payload }}] }});
process.stdout.write(JSON.stringify(output[0].json));
"""
    result = subprocess.run(
        ["node", "-"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", input=script
    )
    return json.loads(result.stdout)


def _prior(**overrides: object) -> dict:
    return {
        "conversation_items": [{"role": "user", "content": [{"type": "input_text", "text": "question"}]}],
        "output": [{"type": "function_call", "call_id": "call-1", "name": "project_context"}],
        "mcp_call_id": "call-1",
        "mcp_tool_name": "project_context",
        "agent_turn": 1,
        "usage": {"total_tokens": 1000},
        "instructions": "write chapter",
        "tools": [{"type": "function", "name": "project_context"}],
        "text": {"format": {"type": "json_schema"}},
        "tool_result_fingerprints": [],
        "tool_request_fingerprints": [],
        "stale_tool_turns": 0,
        "tool_error_count": 0,
        "tool_call_count": 0,
        "tool_call_limit": 12,
        "max_parallel_tools": 3,
        **overrides,
    }


def test_decision_agent_uses_dynamic_stop_conditions_instead_of_six_turn_limit():
    request = _code("Build Structured Decision Request")
    follow_up = _code("Build MCP Agent Follow-up")

    assert "parallel_tool_calls: false" in request
    assert "context_budget_tokens: 24000" in request
    assert "context_reserve_tokens: 6000" in request
    assert "no_new_evidence_limit: 2" in request
    assert "tool_error_limit: 2" in request
    assert "tool_call_limit: 12" in request
    assert "max_parallel_tools: 3" in request
    assert "execution_budget: { max_parallel: 3, remaining_tool_calls: 12 }" in request

    assert "const forceFinal = turn >= 6" not in follow_up
    assert "context_budget" in follow_up
    assert "no_new_evidence" in follow_up
    assert "tool_errors" in follow_up
    assert "emergency_cap" not in follow_up
    assert "tool_choice: 'none'" in follow_up
    assert "tool_call_limit" in follow_up
    assert "nextMandatoryWebTool" not in follow_up
    assert "tools: resolvedStopReason ? [] : prior.tools" in follow_up


def test_dynamic_stop_code_nodes_compile_and_task_completion_exits_tool_loop():
    codes = [
        _code("Build Structured Decision Request"),
        _code("Prepare MCP Agent Tool Call"),
        _code("Build MCP Agent Follow-up"),
    ]
    script = "\n".join(
        f"new Function('$input', '$', 'return (async () => {{\\n' + {json.dumps(code)} + '\\n}})();');"
        for code in codes
    )
    subprocess.run(["node", "-"], cwd=ROOT, check=True, capture_output=True, text=True, input=script)

    connections = _workflow()["connections"]["路由 Agent 请求工具？"]["main"]
    assert connections[0][0]["node"] == "准备证据路由工具调用"
    assert connections[1][0]["node"] == "构建章节研究分析请求"
    assert _workflow()["connections"]["解析证据路由响应"]["main"][0][0]["node"] == "校验证据路由决策"
    assert _workflow()["connections"]["解析章节研究模型响应"]["main"][0][0]["node"] == "构建独立章节成稿请求"


def test_tool_contract_tracks_returned_calls():
    prepare = _code("Prepare MCP Agent Tool Call")

    assert "return calls.map" in prepare
    assert "parallel_agent_tool_calls_not_supported" not in prepare
    assert "tool_call_count: Number(response.tool_call_count ?? 0) + calls.length" in prepare
    assert "batch_index: Number(call.batch_index ?? 0)" in prepare


def test_prepare_tool_batch_creates_three_ordered_n8n_items_and_injects_history_id():
    calls = [
        {
            "call_id": f"route-0-{index}-search_public_web",
            "name": "search_public_web",
            "arguments": {"query": f"query-{index}"},
            "batch_index": index,
            "batch_size": 3,
        }
        for index in range(3)
    ]
    output = _run_prepare(
        {"tool_calls": calls, "tool_call_count": 0, "agent_turn": 0},
        {"history_id": "history-1", "decision_state": {}, "step_order": 1},
    )

    assert [item["batch_index"] for item in output] == [0, 1, 2]
    assert all(item["batch_size"] == 3 for item in output)
    assert all(item["tool_call_count"] == 3 for item in output)
    bodies = [json.loads(item["mcp_request_body"]) for item in output]
    assert [body["history_id"] for body in bodies] == ["history-1"] * 3
    assert [body["arguments"]["query"] for body in bodies] == ["query-0", "query-1", "query-2"]


def test_follow_up_restores_batch_order_and_keeps_successes_when_one_call_fails():
    prior = _prior(tool_call_count=3)
    prepared = [
        {**prior, "batch_index": 2, "mcp_tool_name": "search_literature_evidence", "mcp_call_id": "call-2", "mcp_arguments": {"question": "q"}},
        {**prior, "batch_index": 0, "mcp_tool_name": "analyze_spatial_evidence", "mcp_call_id": "call-0", "mcp_arguments": {"analysis": "scope"}},
        {**prior, "batch_index": 1, "mcp_tool_name": "read_project_document", "mcp_call_id": "call-1", "mcp_arguments": {"document_id": "doc-1"}},
    ]
    results = [
        {"tool_name": "search_literature_evidence", "structured_content": {"status": "available", "answer": "literature"}},
        {"tool_name": "analyze_spatial_evidence", "structured_content": {"status": "available", "analysis": "scope", "summary": "spatial"}},
        {"tool_name": "read_project_document", "error": {"message": "timeout"}},
    ]
    output = _run_follow_up(prior, results, prepared)
    payload = json.loads(output["input"][1]["content"][0]["text"])

    assert [item["batch_index"] for item in payload["latest_tool_results"]] == [0, 1, 2]
    assert [item["tool_name"] for item in payload["latest_tool_results"]] == [
        "analyze_spatial_evidence",
        "read_project_document",
        "search_literature_evidence",
    ]
    assert payload["latest_tool_results"][1]["is_error"] is True
    assert payload["execution_budget"] == {"max_parallel": 3, "remaining_tool_calls": 9}
    assert output["tool_error_count"] == 0
    assert output["stop_reason"] is None
    assert {item["tool_name"] for item in output["research_result_store"]} == {
        "analyze_spatial_evidence",
        "read_project_document",
        "search_literature_evidence",
    }


def test_follow_up_clears_stale_model_output():
    follow_up = _code("Build MCP Agent Follow-up")

    assert "output_text: ''" in follow_up
    assert "tool_calls: []" in follow_up
    assert "response_id: ''" in follow_up


def test_evidence_fingerprint_is_recursive_and_context_estimate_covers_request_state():
    follow_up = _code("Build MCP Agent Follow-up")

    assert "Array.isArray(value)" in follow_up
    assert "Object.keys(value).sort()" in follow_up
    assert "JSON.stringify({ input: nextItems" in follow_up
    assert "instructions: prior.instructions" in follow_up
    assert "tools: prior.tools" in follow_up
    assert "text: prior.text" in follow_up


def test_new_evidence_keeps_tools_available():
    output = _run_follow_up(_prior(), {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}})

    assert output["stop_reason"] is None
    assert output["tools"] == [{"type": "function", "name": "project_context"}]
    assert output["stale_tool_turns"] == 0
    assert len(output["input"]) == 2
    assert all(item.get("type") != "function_call_output" for item in output["input"])
    assert output["working_research_brief"]["cards"]
    assert output["research_result_store"]


def test_rolling_brief_is_bounded_and_full_results_stay_outside_model_input():
    cards = [
        {"result_ref": f"run-result:test:{index}", "tool_name": "test", "summary": "x" * 2000}
        for index in range(16)
    ]
    output = _run_follow_up(
        _prior(
            initial_context_items=[{"role": "user", "content": [{"type": "input_text", "text": "question"}]}],
            working_research_brief={"version": 1, "cards": cards},
        ),
        {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}},
    )

    assert len(json.dumps(output["working_research_brief"]["cards"], ensure_ascii=False)) <= 15_000
    assert len(output["input"]) == 2
    model_input = json.dumps(output["input"], ensure_ascii=False)
    assert "research_result_store" not in model_input
    assert "function_call_output" not in model_input


def test_spatial_results_do_not_create_hidden_expansion_state():
    output = _run_follow_up(
        _prior(mcp_tool_name="analyze_spatial_evidence", mcp_arguments={"analysis": "direction"}),
        {"tool_name": "analyze_spatial_evidence", "structured_content": {"status": "available", "analysis": "direction"}},
    )
    assert "pending_expansions" not in output["working_research_brief"]
    assert "ready_for_writing" not in output["working_research_brief"]


def test_oversized_spatial_result_keeps_named_poi_and_road_facts():
    highlights = [
        {
            "record_ref": "current:dataset:poi/poi-1",
            "title": "长沙简牍博物馆",
            "identity": {
                "dataset_id": "poi",
                "display_name": "长沙简牍博物馆",
                "name": "长沙简牍博物馆",
                "category": "科教文化服务",
                "subcategory": "博物馆",
                "address": "白沙路92号",
            },
            "distance_m": 438.2,
            "direction": "西北",
            "values": {"poi.count": 1},
            "reason": "具名 POI",
        },
        {
            "record_ref": "current:dataset:road_edges/road-1",
            "title": "芙蓉中路",
            "identity": {
                "dataset_id": "road_edges",
                "display_name": "芙蓉中路",
                "road_name": "芙蓉中路",
                "road_class": "主干路",
            },
            "distance_m": 215.4,
            "direction": "东",
            "values": {"road.segment_length": 1240.5},
            "reason": "具名道路",
        },
    ]
    highlights.extend(
        {
            "record_ref": f"current:dataset:poi/filler-{index}",
            "title": f"测试设施{index}",
            "identity": {
                "dataset_id": "poi",
                "name": f"测试设施{index}",
                "category": "测试分类",
                "subcategory": "测试子类",
                "address": "很长的地址" * 200,
            },
            "distance_m": index * 10,
            "direction": "南",
            "values": {"poi.count": 1},
        }
        for index in range(30)
    )
    spatial_result = {
        "tool_name": "analyze_spatial_evidence",
        "structured_content": {
            "status": "available",
            "analysis": "scope",
            "summary": {"description": "超大空间汇总" * 2000},
            "metrics": [
                {"metric_id": "poi.count", "label": "POI 数量", "unit": "places"},
                {"metric_id": "road.segment_length", "label": "道路长度", "unit": "m"},
            ],
            "groups": [{"key": f"group-{index}", "values": {"text": "x" * 1000}} for index in range(20)],
            "highlights": highlights,
            "coverage": {"complete": True},
            "limitations": [],
        },
    }

    output = _run_follow_up(
        _prior(mcp_tool_name="analyze_spatial_evidence", mcp_arguments={"analysis": "scope"}),
        spatial_result,
    )

    named = output["working_research_brief"]["named_spatial_records"]
    by_ref = {item["record_ref"]: item for item in named}
    assert by_ref["current:dataset:poi/poi-1"]["name"] == "长沙简牍博物馆"
    assert by_ref["current:dataset:poi/poi-1"]["identity"]["category"] == "科教文化服务"
    assert by_ref["current:dataset:poi/poi-1"]["identity"]["subcategory"] == "博物馆"
    assert by_ref["current:dataset:road_edges/road-1"]["name"] == "芙蓉中路"
    assert by_ref["current:dataset:road_edges/road-1"]["identity"]["road_class"] == "主干路"

    model_payload = json.loads(output["input"][1]["content"][0]["text"])
    latest_named = model_payload["latest_tool_results"][0]["result"]["named_records"]
    latest_by_ref = {item["record_ref"]: item for item in latest_named}
    assert "current:dataset:poi/poi-1" in latest_by_ref
    assert "current:dataset:road_edges/road-1" in latest_by_ref
    assert len(json.dumps(model_payload["latest_tool_results"][0], ensure_ascii=False)) <= 5_600


def test_named_spatial_facts_survive_later_non_spatial_brief_compaction():
    first = _run_follow_up(
        _prior(mcp_tool_name="analyze_spatial_evidence", mcp_arguments={"analysis": "scope"}),
        {
            "tool_name": "analyze_spatial_evidence",
            "structured_content": {
                "status": "available",
                "analysis": "scope",
                "summary": {"poi.count": 1},
                "highlights": [{
                    "record_ref": "current:dataset:poi/poi-anchor",
                    "title": "潮宗街历史文化街区",
                    "identity": {"dataset_id": "poi", "name": "潮宗街历史文化街区", "category": "风景名胜"},
                    "distance_m": 320,
                    "direction": "北",
                    "values": {"poi.count": 1},
                }],
            },
        },
    )
    later_prior = {
        **first,
        "mcp_tool_name": "read_project_document",
        "mcp_arguments": {"document_id": "document-1", "start_block": 0},
        "mcp_call_id": "call-2",
        "output": [],
    }
    second = _run_follow_up(
        later_prior,
        {
            "tool_name": "read_project_document",
            "structured_content": {
                "status": "available",
                "document_id": "document-1",
                "blocks": [
                    {"heading": f"章节{index}", "page": index + 1, "text": "项目正文" * 3000}
                    for index in range(10)
                ],
                "complete": False,
                "next_start_block": 10,
            },
        },
    )

    named = second["working_research_brief"]["named_spatial_records"]
    assert any(
        item["record_ref"] == "current:dataset:poi/poi-anchor"
        and item["name"] == "潮宗街历史文化街区"
        and item["identity"]["category"] == "风景名胜"
        for item in named
    )


@pytest.mark.parametrize("tool_count", [1, 2, 3])
def test_evidence_route_agent_can_choose_one_to_three_independent_tools(tool_count: int):
    candidates = [
        {"name": "analyze_spatial_evidence", "arguments": {"analysis": "scope"}},
        {"name": "read_project_document", "arguments": {"document_id": "document-1", "max_blocks": 4}},
        {"name": "search_literature_evidence", "arguments": {"question": "步行可达性如何影响历史城区活力？", "mode": "focused"}},
    ]
    route = {"decision": "continue", "reason": "独立取得三类证据", "next_tools": candidates[:tool_count]}
    output = _run_input_code(
        "校验证据路由决策",
        {"output_text": json.dumps(route, ensure_ascii=False), "agent_turn": 2, "tool_call_count": 0},
    )

    assert output["route_decision"] == route
    assert [call["batch_index"] for call in output["tool_calls"]] == list(range(tool_count))
    assert all(call["batch_size"] == tool_count for call in output["tool_calls"])
    assert output["tool_calls"][0]["call_id"] == "route-2-0-analyze_spatial_evidence"


def test_evidence_route_agent_can_finish_with_empty_batch():
    route = {"decision": "finish", "reason": "证据已足够开始研究", "next_tools": []}
    output = _run_input_code(
        "校验证据路由决策",
        {
            "output_text": json.dumps(route, ensure_ascii=False),
            "working_research_brief": {
                "cards": [{"tool_name": "analyze_spatial_evidence", "analysis": "rank", "status": "available"}]
            },
        },
    )

    assert output["route_decision"] == route
    assert output["tool_calls"] == []


def test_evidence_route_accepts_json_wrapped_in_a_code_fence():
    route = {"decision": "finish", "reason": "证据已足够开始研究", "next_tools": []}
    output = _run_input_code(
        "校验证据路由决策",
        {
            "output_text": f"```json\n{json.dumps(route, ensure_ascii=False)}\n```",
            "working_research_brief": {
                "cards": [{"tool_name": "analyze_spatial_evidence", "analysis": "rank", "status": "available"}]
            },
        },
    )

    assert output["route_decision"] == route


@pytest.mark.parametrize(
    "cards",
    [
        [],
        [{"tool_name": "analyze_spatial_evidence", "analysis": "scope", "status": "available"}],
    ],
)
def test_evidence_route_finish_is_not_overridden_by_workflow_code(cards: list[dict]):
    route = {"decision": "finish", "reason": "证据已足够开始研究", "next_tools": []}
    output = _run_input_code(
        "校验证据路由决策",
        {
            "output_text": json.dumps(route),
            "working_research_brief": {"cards": cards},
        },
    )

    assert output["route_retry_required"] is False
    assert output["route_decision"] == route
    assert output["tool_calls"] == []


def test_evidence_route_rejects_unknown_tool_and_history_id():
    unknown = {"decision": "continue", "reason": "x", "next_tools": [{"name": "query_data", "arguments": {}}]}
    with pytest.raises(subprocess.CalledProcessError):
        _run_input_code("校验证据路由决策", {"output_text": json.dumps(unknown)})
    injected = {"decision": "continue", "reason": "x", "next_tools": [{"name": "analyze_spatial_evidence", "arguments": {"analysis": "scope", "history_id": "forbidden"}}]}
    with pytest.raises(subprocess.CalledProcessError):
        _run_input_code("校验证据路由决策", {"output_text": json.dumps(injected)})


def test_evidence_route_returns_missing_arguments_to_router_for_correction():
    route = {
        "decision": "continue",
        "reason": "读取搜索结果正文",
        "next_tools": [{"name": "fetch_public_web_page", "arguments": {}}],
    }
    output = _run_input_code("校验证据路由决策", {"output_text": json.dumps(route)})

    assert output["route_retry_required"] is True
    assert output["route_diagnostics"][0]["kind"] == "invalid_tool_arguments_retry"
    assert "evidence_route_argument_missing:urls" in output["route_diagnostics"][0]["message"]


def test_evidence_route_retries_empty_continue_batch_without_choosing_a_tool():
    route = {"decision": "continue", "reason": "暂无新的独立取证请求", "next_tools": []}
    original_input = [{"role": "user", "content": [{"type": "input_text", "text": "current task"}]}]
    output = _run_input_code(
        "校验证据路由决策",
        {"output_text": json.dumps(route), "input": original_input},
    )

    assert output["route_retry_required"] is True
    assert output["route_format_retry_count"] == 1
    assert output["route_decision"] is None
    assert output["tool_calls"] == []
    assert output["input"][:1] == original_input
    assert "next_tools 为空" in output["input"][-1]["content"][0]["text"]
    assert output["route_diagnostics"] == [{"kind": "empty_continue_batch_retry", "attempt": 1}]


def test_evidence_route_rejects_empty_continue_after_four_corrections():
    route = {"decision": "continue", "reason": "x", "next_tools": []}

    with pytest.raises(subprocess.CalledProcessError):
        _run_input_code(
            "校验证据路由决策",
            {"output_text": json.dumps(route), "route_format_retry_count": 4},
        )


def test_evidence_route_trims_batch_over_parallel_limit():
    route = {
        "decision": "continue",
        "reason": "取得相互独立的公开网页证据",
        "next_tools": [
            {"name": "search_public_web", "arguments": {"query": f"query-{index}"}}
            for index in range(4)
        ],
    }
    output = _run_input_code("校验证据路由决策", {"output_text": json.dumps(route)})

    assert len(output["tool_calls"]) == 3
    assert output["route_diagnostics"] == [
        {"kind": "batch_trimmed_to_max_parallel", "requested": 4, "executed": 3}
    ]


@pytest.mark.parametrize(
    "route",
    [
        {"decision": "finish", "reason": "x", "next_tools": [{"name": "search_public_web", "arguments": {"query": "x"}}]},
        {"decision": "continue", "reason": "x", "next_tool": {"name": "search_public_web", "arguments": {"query": "x"}}},
    ],
)
def test_evidence_route_rejects_invalid_batch_shapes_and_legacy_contract(route: dict):
    with pytest.raises(subprocess.CalledProcessError):
        _run_input_code("校验证据路由决策", {"output_text": json.dumps(route)})


def test_evidence_route_rejects_duplicate_requests_within_a_batch():
    call = {"name": "search_public_web", "arguments": {"query": "长沙历史城区"}}
    route = {"decision": "continue", "reason": "x", "next_tools": [call, call]}

    with pytest.raises(subprocess.CalledProcessError):
        _run_input_code("校验证据路由决策", {"output_text": json.dumps(route, ensure_ascii=False)})


def test_evidence_route_trims_batch_to_remaining_call_budget():
    route = {
        "decision": "continue",
        "reason": "并行取得独立证据",
        "next_tools": [
            {"name": "search_public_web", "arguments": {"query": "query-1"}},
            {"name": "search_public_web", "arguments": {"query": "query-2"}},
            {"name": "search_public_web", "arguments": {"query": "query-3"}},
        ],
    }
    output = _run_input_code(
        "校验证据路由决策",
        {"output_text": json.dumps(route), "tool_call_count": 11, "tool_call_limit": 12},
    )

    assert len(output["tool_calls"]) == 1
    assert output["tool_calls"][0]["batch_size"] == 1
    assert output["route_diagnostics"] == [
        {"kind": "batch_trimmed_to_remaining_budget", "requested": 3, "executed": 1}
    ]


def test_budget_trim_diagnostic_is_consumed_once_by_follow_up():
    diagnostic = {"kind": "batch_trimmed_to_remaining_budget", "requested": 3, "executed": 1}
    output = _run_follow_up(
        _prior(route_diagnostics=[diagnostic]),
        {"tool_name": "search_public_web", "structured_content": {"status": "available", "results": []}},
    )

    assert diagnostic in output["tool_diagnostics"]
    assert output["route_diagnostics"] == []


def test_research_and_writing_are_separate_requests():
    request = _code("Build Structured Decision Request")
    research = _code("构建章节研究分析请求")
    draft = _code("构建独立章节成稿请求")

    assert "name: 'evidence_route'" in request
    assert "decision: { type: 'string', enum: ['continue', 'finish'] }" in request
    assert "next_tools: { type: 'array', maxItems: 3" in request
    assert "next_tool:" not in request
    assert "tool_choice: 'none'" in request
    assert "max_output_tokens: 5000" in request
    assert "research_summary" not in request
    assert "key_findings" not in request
    assert "ready_to_write" not in request
    assert "properties: { decision_brief:" not in request
    assert "不负责形成研究结论" in request
    assert "不规定后续研究和写作结构" in request
    assert "evidence_brief" in research
    assert "tools: []" in research
    assert "reasoning: { effort: 'medium' }" in research
    assert "text: undefined" in research
    assert "你不受证据路由 Agent 的简短 JSON、低推理配置或工具调用规则约束" in research
    assert "working_research_brief" in draft
    assert "research_memo" in draft
    assert "research_handoff" not in draft
    assert "chapter_research_memo_empty" in draft
    assert "chapter_spatial_expansion_incomplete" not in draft
    assert "tools: []" in draft
    assert "reasoning: { effort: 'high' }" in draft
    assert "name: 'reader_chapter'" in draft


def test_context_budget_stops_tool_loop():
    output = _run_follow_up(
        _prior(context_budget_tokens=100, context_reserve_tokens=0),
        {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}},
    )

    assert output["stop_reason"] == "context_budget"
    assert output["tool_choice"] == "none"
    assert output["tools"] == []


def test_tool_call_limit_stops_router_loop():
    output = _run_follow_up(
        _prior(tool_call_count=12, tool_call_limit=12),
        {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}},
    )

    assert output["stop_reason"] == "tool_call_limit"
    assert output["tool_choice"] == "none"
    assert output["tools"] == []


def test_repeated_evidence_stops_after_configured_stale_limit():
    tool_result = {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}}
    first = _run_follow_up(_prior(), tool_result)
    second = _run_follow_up(
        _prior(
            tool_result_fingerprints=first["tool_result_fingerprints"],
            tool_request_fingerprints=first["tool_request_fingerprints"],
            stale_tool_turns=1,
        ),
        tool_result,
    )

    assert second["stop_reason"] == "no_new_evidence"
    assert second["tools"] == []


def test_repeated_tool_errors_stop_the_loop():
    output = _run_follow_up(
        _prior(tool_error_count=1),
        {"tool_name": "project_context", "is_error": True, "content": "unavailable"},
    )

    assert output["stop_reason"] == "tool_errors"
    assert output["tools"] == []
