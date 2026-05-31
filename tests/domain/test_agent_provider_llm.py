import asyncio
import json

import httpx
import pytest

from core.config import settings
from modules.agent.context_builder import build_context_bundle
from modules.agent.llm_digest import compact_context_summary_dump, context_digest, snapshot_digest, trim_messages
from modules.agent.providers.chat_parser import extract_json_object
from modules.agent.providers.llm_provider import _invoke_json_role, audit_with_llm, generate_answer_output_with_llm, plan_with_llm, run_gate_with_llm, run_llm_tool_loop
from modules.agent.providers.tool_loop import compact_tool_catalog
from modules.agent.schemas import AgentMessage, AnalysisSnapshot, AuditResult, GateDecision, PlanStep, PlanningResult, ToolResult, ToolSpec, WorkingMemory
from modules.agent.tools import RegisteredTool, get_tool_registry


class _FakeStreamResponse:
    def __init__(self, url: str, chunks):
        self.request = httpx.Request("POST", url)
        self._lines = []
        for chunk in chunks:
            if chunk == "[DONE]":
                self._lines.extend(["data: [DONE]", ""])
            else:
                self._lines.extend([f"data: {json.dumps(chunk, ensure_ascii=False)}", ""])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _completion_stream(*, response_id: str, content: str = "", reasoning_parts=None, tool_calls=None, finish_reason: str = "stop"):
    chunks = []
    for part in reasoning_parts or []:
        chunks.append(
            {
                "id": response_id,
                "choices": [{"index": 0, "delta": {"reasoning_content": part}, "finish_reason": None}],
            }
        )
    if content:
        chunks.append(
            {
                "id": response_id,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
            }
        )
    if tool_calls:
        chunks.append(
            {
                "id": response_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "id": item["id"],
                                    "type": "function",
                                    "function": {
                                        "name": item["name"],
                                        "arguments": item.get("arguments", "{}"),
                                    },
                                }
                                for index, item in enumerate(tool_calls)
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        )
    chunks.append({"id": response_id, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]})
    chunks.append("[DONE]")
    return chunks


def _mock_streams(monkeypatch, requests, stream_chunks):
    def fake_stream(self, method, url, *, headers=None, json=None):
        del self, headers
        requests.append({"method": method, "url": url, "json": json})
        return _FakeStreamResponse(url, stream_chunks[len(requests) - 1])

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)


def _snapshot_with_scope() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        scope={
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        }
    )


def test_run_llm_tool_loop_sends_tools_and_appends_tool_results(monkeypatch):
    requests = []
    events = []
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    registry = get_tool_registry()
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)
    monkeypatch.setattr(settings, "ai_max_tool_steps", 8)
    monkeypatch.setattr(settings, "ai_max_tool_errors", 2)

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-1",
                reasoning_parts=["先读取", "当前范围。"],
                tool_calls=[{"id": "call-1", "name": "read_current_scope", "arguments": "{}"}],
                finish_reason="tool_calls",
            ),
            _completion_stream(response_id="resp-2", content="已拿到足够结果。"),
        ],
    )

    result = asyncio.run(
        run_llm_tool_loop(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            registry=registry,
            governance_mode="auto",
            confirmed_tools=[],
            emit=lambda event_type, payload: events.append({"type": event_type, "payload": payload}),
        )
    )

    assert result.status == "completed"
    assert result.used_tools == ["read_current_scope"]
    assert result.stop_reason == "assistant_completed"
    assert requests[0]["url"].endswith("/chat/completions")
    assert requests[0]["json"]["tools"]
    assert requests[0]["json"]["stream"] is True
    assert requests[0]["json"]["thinking"] == {"type": "enabled"}
    assert requests[0]["json"]["messages"][0]["role"] == "system"
    assert requests[1]["json"]["messages"][-1]["role"] == "tool"
    assert requests[1]["json"]["messages"][-2]["reasoning_content"] == "先读取当前范围。"
    reasoning_events = [item for item in events if item["type"] == "reasoning_delta"]
    assert [item["payload"]["delta"] for item in reasoning_events[:2]] == ["先读取", "当前范围。"]
    start_trace = next(item["payload"] for item in events if item["type"] == "trace" and item["payload"]["status"] == "start")
    success_trace = next(item["payload"] for item in events if item["type"] == "trace" and item["payload"]["status"] == "success")
    assert start_trace["arguments_summary"] == "无参数"
    assert success_trace["result_summary"]
    assert success_trace["evidence_count"] >= 0
    assert isinstance(success_trace["produced_artifacts"], list)


def test_run_llm_tool_loop_returns_failed_for_invalid_output(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    registry = get_tool_registry()
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)

    _mock_streams(monkeypatch, [], [_completion_stream(response_id="resp-1", content="")])

    result = asyncio.run(
        run_llm_tool_loop(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            registry=registry,
            governance_mode="auto",
            confirmed_tools=[],
        )
    )

    assert result.status == "failed"
    assert result.stop_reason == "no_parseable_output"


def test_run_llm_tool_loop_reuses_duplicate_readonly_tool_calls(monkeypatch):
    requests = []
    events = []
    executions = {"count": 0}
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)
    monkeypatch.setattr(settings, "ai_max_tool_steps", 8)
    monkeypatch.setattr(settings, "ai_max_tool_errors", 2)

    async def fake_runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        executions["count"] += 1
        return ToolResult(
            tool_name="read_current_results",
            status="success",
            result={"poi_count": 2},
            evidence=[{"field": "poi.count", "value": 2}],
            artifacts={"current_pois": [{"id": "poi-1"}, {"id": "poi-2"}]},
        )

    registry = {
        "read_current_results": RegisteredTool(
            spec=ToolSpec(
                name="read_current_results",
                description="读取当前 analysis snapshot 中已存在的结果摘要",
                category="information",
                layer="L1",
                produces=["current_pois"],
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                readonly=True,
            ),
            runner=fake_runner,
        )
    }

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-1",
                tool_calls=[
                    {"id": "call-1", "name": "read_current_results", "arguments": "{}"},
                    {"id": "call-2", "name": "read_current_results", "arguments": "{}"},
                ],
                finish_reason="tool_calls",
            ),
            _completion_stream(response_id="resp-2", content="已拿到足够结果。"),
        ],
    )

    result = asyncio.run(
        run_llm_tool_loop(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            registry=registry,
            governance_mode="auto",
            confirmed_tools=[],
            emit=lambda event_type, payload: events.append({"type": event_type, "payload": payload}),
        )
    )

    tool_messages = [item for item in requests[1]["json"]["messages"] if item["role"] == "tool"]
    trace_statuses = [item.status for item in result.execution_trace]

    assert result.status == "completed"
    assert executions["count"] == 1
    assert result.used_tools == ["read_current_results"]
    assert len(result.tool_results) == 1
    assert trace_statuses == ["success", "skipped"]
    assert len(tool_messages) == 2
    for message in tool_messages:
        content = json.loads(message["content"])
        assert "result" not in content
        assert "evidence" not in content
        assert "artifacts" not in content
        assert content["result_summary"] == "poi_count=2"
        assert content["artifact_keys"] == ["current_pois"]
        assert content["artifact_shapes"]["current_pois"] == {"type": "array", "count": 2}
    assert any(
        item["type"] == "trace" and item["payload"]["status"] == "skipped" and item["payload"]["message"] == "复用已有工具结果"
        for item in events
    )


def test_run_llm_tool_loop_sends_compact_tool_output_payload(monkeypatch):
    requests = []
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    huge_points = [{"id": f"poi-{index}", "lng": 112.98 + index * 0.001, "lat": 28.19} for index in range(300)]

    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)
    monkeypatch.setattr(settings, "ai_max_tool_steps", 8)
    monkeypatch.setattr(settings, "ai_max_tool_errors", 2)

    async def fake_runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="read_large_payload",
            status="success",
            result={"poi_count": 300, "raw_points": huge_points},
            evidence=[{"field": f"poi.{index}", "value": f"evidence-{index}"} for index in range(20)],
            warnings=[f"warning-{index}" for index in range(12)],
            artifacts={
                "current_pois": huge_points,
                "current_frontend_analysis": {"poi": {"raw_points": huge_points}},
            },
        )

    registry = {
        "read_large_payload": RegisteredTool(
            spec=ToolSpec(
                name="read_large_payload",
                description="读取大结果",
                category="information",
                layer="L1",
                produces=["current_pois"],
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                readonly=True,
                llm_exposure="primary",
            ),
            runner=fake_runner,
        )
    }

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-1",
                tool_calls=[{"id": "call-1", "name": "read_large_payload", "arguments": "{}"}],
                finish_reason="tool_calls",
            ),
            _completion_stream(response_id="resp-2", content="已拿到足够结果。"),
        ],
    )

    result = asyncio.run(
        run_llm_tool_loop(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            registry=registry,
            governance_mode="auto",
            confirmed_tools=[],
        )
    )

    assert result.status == "completed"
    tool_messages = [item for item in requests[1]["json"]["messages"] if item["role"] == "tool"]
    assert len(tool_messages) == 1

    content = json.loads(tool_messages[0]["content"])
    encoded = json.dumps(content, ensure_ascii=False)

    assert "result" not in content
    assert "evidence" not in content
    assert "artifacts" not in content
    assert "poi-299" not in encoded
    assert "evidence-19" not in encoded
    assert content["result_summary"] == "poi_count=300"
    assert content["result_shape"] == {"type": "object", "key_count": 2, "keys": ["poi_count", "raw_points"]}
    assert len(content["evidence_sample"]) == 8
    assert content["evidence_count"] == 20
    assert content["warnings"] == [f"warning-{index}" for index in range(8)]
    assert content["artifact_keys"] == ["current_pois", "current_frontend_analysis"]
    assert content["artifact_shapes"]["current_pois"] == {"type": "array", "count": 300}
    assert content["artifact_shapes"]["current_frontend_analysis"]["keys"] == ["poi"]


def test_generate_answer_output_with_llm_parses_cards(monkeypatch):
    requests = []
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-answer-1",
                reasoning_parts=["组织卡片。"],
                content='{"cards":[{"type":"summary","title":"概览","content":"区域商业较成熟。","items":[]},{"type":"evidence","title":"证据","content":"基于现有指标。","items":["POI 数量：12"]},{"type":"recommendation","title":"建议","content":"可继续查看路网。","items":["优先补做路网分析"]}],"next_suggestions":["继续看路网"]}',
            )
        ],
    )

    output = asyncio.run(
        generate_answer_output_with_llm(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            synthesis_payload={"metrics": {"poi_count": 12}},
        )
    )

    assert output.cards[0].type == "summary"
    assert output.cards[0].content == "区域商业较成熟。"
    assert output.next_suggestions == ["继续看路网"]
    system_prompt = requests[0]["json"]["messages"][0]["content"]
    assert "核心判断" in system_prompt
    assert "证据依据" in system_prompt
    assert "下一步建议" in system_prompt
    assert "decision_strength" in system_prompt
    assert "evidence_matrix" in system_prompt
    assert "不建议直接推断" in system_prompt


def test_generate_answer_output_with_llm_allows_card_items_without_content(monkeypatch):
    requests = []
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-answer-missing-card-content",
                reasoning_parts=["组织卡片。"],
                content='{"cards":[{"type":"summary","title":"概览","content":"区域商业较成熟。","items":[]},{"type":"evidence","title":"证据","items":["POI 数量：12"]},{"type":"recommendation","title":"建议","items":["优先补做路网分析"]}],"next_suggestions":["继续看路网"]}',
            )
        ],
    )

    output = asyncio.run(
        generate_answer_output_with_llm(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            synthesis_payload={"metrics": {"poi_count": 12}},
        )
    )

    assert output.cards[1].type == "evidence"
    assert output.cards[1].content == ""
    assert output.cards[1].items == ["POI 数量：12"]
    assert output.cards[2].type == "recommendation"
    assert output.cards[2].content == ""
    assert output.next_suggestions == ["继续看路网"]


def test_invoke_json_role_requests_json_object_response(monkeypatch):
    requests = []
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", False)
    monkeypatch.setattr(settings, "ai_timeout_s", 5)
    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-json-1",
                content='{"ok":true}',
            )
        ],
    )

    result = asyncio.run(_invoke_json_role(
        system_prompt="只输出 json",
        user_payload={"task": "unit_test"},
        emit=None,
        phase="unit",
        title="JSON unit",
        reasoning_id="json-unit",
    ))

    assert result == {"ok": True}
    assert requests[0]["json"]["response_format"] == {"type": "json_object"}


def test_extract_json_object_repairs_trailing_commas():
    parsed = extract_json_object(
        """
        ```json
        {
          "cards": [
            {"type": "summary", "title": "概览", "content": "可回答",},
          ],
          "next_suggestions": ["继续看路网",],
        }
        ```
        """
    )

    assert parsed["cards"][0]["content"] == "可回答"
    assert parsed["next_suggestions"] == ["继续看路网"]


def test_plan_with_llm_sends_planner_specific_prompt_and_payload(monkeypatch):
    snapshot = AnalysisSnapshot(
        scope={
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        },
        poi_summary={"total": 10},
        h3={"summary": {"grid_count": 4, "avg_density_poi_per_km2": 5.2}},
        frontend_analysis={"poi": {"category_stats": {"labels": ["餐饮"], "values": [10]}}, "h3": {}},
    )
    context = build_context_bundle(snapshot)
    registry = get_tool_registry()
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_poi_structure_analysis": {"dominant_categories": ["餐饮"], "summary_text": "POI 结构已存在"},
            "current_business_profile": {"business_profile": "生活消费主导"},
        }
    )
    captured = {}

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del emit, phase, title
        captured[reasoning_id] = {"system_prompt": system_prompt, "user_payload": user_payload}
        if reasoning_id == "planner-reasoning":
            return {
                "goal": user_payload["latest_user_message"],
                "question_type": "area_character",
                "summary": "优先走区域画像场景包，再按缺口补证。",
                "requires_tools": True,
                "stop_condition": "证据足够时停止。",
                "evidence_focus": ["区域调性"],
                "tool_selection_brief": "需要判断商业核心和空间热点。",
            }
        return {
            "summary": "选择区域画像场景包。",
            "requires_tools": True,
            "steps": [
                    {
                        "tool_name": "run_area_character_pack",
                        "arguments": {"policy_key": "district_summary"},
                        "reason": "统一输出区域标签和证据链。",
                        "evidence_goal": "区域调性与证据链",
                        "expected_artifacts": ["area_character_pack"],
                        "optional": False,
                    }
            ],
        }

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)

    plan = asyncio.run(
        plan_with_llm(
            messages=[AgentMessage(role="user", content="这个区域的商业核心集中在哪")],
            snapshot=snapshot,
            context=context,
            registry=registry,
            memory=memory,
            audit_feedback={"missing_evidence": ["空间热点分析"]},
        )
    )

    assert plan.steps[0].tool_name == "read_current_scope"
    planner_payload = captured["planner-reasoning"]["user_payload"]
    selector_payload = captured["tool-selector-reasoning"]["user_payload"]
    assert "具体工具选择会交给 Tool Selector Agent" in captured["planner-reasoning"]["system_prompt"]
    assert "Tool Selector Agent" in captured["tool-selector-reasoning"]["system_prompt"]
    assert "frontend_analysis 中键存在不等于有可用分析" in captured["planner-reasoning"]["system_prompt"]
    assert planner_payload["question_archetype"] == "metric"
    assert "available_tools" not in planner_payload
    assert "fallback_plan" not in planner_payload
    assert "tool_routing_hints" not in planner_payload
    assert "artifact_digest" in planner_payload
    assert "current_poi_structure_analysis" in planner_payload["artifact_digest"]["analysis_artifacts"]
    assert planner_payload["artifact_digest"]["analysis_readiness"]["h3"] is False
    assert "h3" in planner_payload["artifact_digest"]["empty_analysis_dimensions"]
    assert "current_business_profile" in planner_payload["artifact_digest"]["derived_artifacts"]
    assert "area_character" in selector_payload["tool_routing_hints"]["question_routes"]
    assert "run_area_character_pack" in selector_payload["tool_routing_hints"]["layers"]["scenario"]
    tool_names = [item["name"] for item in selector_payload["available_tools"]]
    assert "run_area_character_pack" in tool_names
    assert "run_business_site_advice" not in tool_names
    assert all("input_schema" not in item for item in selector_payload["available_tools"])
    assert all("evidence_contract" not in item for item in selector_payload["available_tools"])


def test_plan_with_llm_uses_site_advice_archetype_for_target_supply_questions(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    registry = get_tool_registry()
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})
    captured = {}

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, emit, phase, title
        captured[reasoning_id] = user_payload
        if reasoning_id == "planner-reasoning":
            return {
                "goal": user_payload["latest_user_message"],
                "question_type": "site_selection",
                "summary": "围绕目标业态补证。",
                "requires_tools": True,
                "stop_condition": "目标业态证据足够时停止。",
                "evidence_focus": ["候选点排序"],
                "tool_selection_brief": "需要选择选址工具并抽取目标业态。",
            }
        return {
            "summary": "选择选址场景包。",
            "requires_tools": True,
            "steps": [
                    {
                        "tool_name": "run_site_selection_pack",
                        "arguments": {"place_type": "咖啡厅", "policy_key": "business_catchment_1km"},
                        "reason": "先统一完成候选区筛选和排序。",
                        "evidence_goal": "候选点排序",
                        "expected_artifacts": ["site_selection_pack"],
                        "optional": False,
                    }
            ],
        }

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)

    plan = asyncio.run(
        plan_with_llm(
            messages=[AgentMessage(role="user", content="这里适合补咖啡吗")],
            snapshot=snapshot,
            context=context,
            registry=registry,
            memory=memory,
        )
    )

    assert any(step.tool_name == "run_site_selection_pack" for step in plan.steps)
    assert captured["planner-reasoning"]["question_archetype"] == "site_selection"
    assert captured["tool-selector-reasoning"]["planning_intent"]["question_type"] == "site_selection"


def test_compact_tool_catalog_omits_full_schema_and_long_contracts():
    catalog = compact_tool_catalog(get_tool_registry())
    area_tool = next(item for item in catalog if item["name"] == "run_area_character_pack")

    assert "input_schema" not in area_tool
    assert "applicable_scenarios" not in area_tool
    assert "evidence_contract" not in area_tool
    assert "toolkit_id" not in area_tool
    assert area_tool["argument_hints"]["policy_key"] == "district_summary"
    assert len(area_tool["intent"]) <= 96


def test_planner_digests_do_not_include_large_frontend_analysis_or_filters():
    huge_points = [{"lng": 112.98 + index * 0.001, "lat": 28.19, "name": f"poi-{index}"} for index in range(300)]
    snapshot = AnalysisSnapshot(
        scope={"polygon": [[112.98, 28.19], [112.99, 28.19], [112.99, 28.20], [112.98, 28.20]]},
        poi_summary={"total": 300, "raw_points": huge_points},
        h3={"summary": {"cells": huge_points}},
        frontend_analysis={
            "poi": {"raw_points": huge_points, "category_stats": {"labels": [f"cat-{i}" for i in range(200)]}},
            "road": {"segments": huge_points},
        },
        current_filters={"poi_details": huge_points, "selected_categories": [f"cat-{i}" for i in range(200)]},
    )
    context = build_context_bundle(snapshot)

    planner_payload = {
        "analysis_snapshot_digest": snapshot_digest(snapshot),
        "context_digest": context_digest(context),
        "context_summary": compact_context_summary_dump(context.context_summary),
    }
    encoded = json.dumps(planner_payload, ensure_ascii=False)

    assert len(encoded) < 30000
    assert "poi-299" not in encoded
    assert planner_payload["context_digest"]["analysis"]["frontend_analysis"] == {
        "available_sections": ["poi", "road"],
        "section_count": 2,
    }
    assert planner_payload["analysis_snapshot_digest"]["current_filters"]["poi_details"]["count"] == 300
    assert planner_payload["context_summary"]["filters_digest"]["poi_details"]["count"] == 300


def test_trim_messages_caps_each_message_content(monkeypatch):
    monkeypatch.setattr(settings, "ai_max_context_turns", 2)
    messages = [
        AgentMessage(role="user", content="old"),
        AgentMessage(role="assistant", content="x" * 9000),
        AgentMessage(role="user", content="latest"),
    ]

    trimmed = trim_messages(messages)

    assert [item["role"] for item in trimmed] == ["assistant", "user"]
    assert len(trimmed[0]["content"]) == 4003
    assert trimmed[0]["content"].endswith("...")
    assert trimmed[1]["content"] == "latest"


def test_plan_with_llm_falls_back_when_tool_selector_fails(monkeypatch):
    calls = []

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, user_payload, emit, phase, title
        calls.append(reasoning_id)
        if reasoning_id == "planner-reasoning":
            return {
                "goal": "下一步做什么分析",
                "question_type": "next_analysis",
                "summary": "需要推荐下一步分析。",
                "requires_tools": True,
                "stop_condition": "推荐方向足够明确。",
                "evidence_focus": ["下一步分析方向"],
                "tool_selection_brief": "选择下一步分析推荐工具。",
            }
        raise RuntimeError("selector_bad_request")

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)

    snapshot = _snapshot_with_scope()
    plan = asyncio.run(
        plan_with_llm(
            messages=[AgentMessage(role="user", content="下一步做什么分析")],
            snapshot=snapshot,
            context=build_context_bundle(snapshot),
            registry=get_tool_registry(),
            memory=WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]}),
        )
    )

    assert calls == ["planner-reasoning", "tool-selector-reasoning"]
    assert any(step.tool_name == "rank_next_analysis_options" for step in plan.steps)
    assert any("tool_selector_failed" in warning for warning in plan.warnings)


def test_plan_with_llm_filters_unknown_tool_from_selector(monkeypatch):
    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, emit, phase, title
        if reasoning_id == "planner-reasoning":
            return {
                "goal": user_payload["latest_user_message"],
                "question_type": "area_character",
                "summary": "需要区域画像。",
                "requires_tools": True,
                "stop_condition": "区域画像证据足够。",
                "evidence_focus": ["区域调性"],
                "tool_selection_brief": "选择区域画像工具。",
            }
        return {
            "summary": "选择一个不存在的工具。",
            "requires_tools": True,
            "steps": [
                {
                    "tool_name": "imaginary_tool",
                    "arguments": {},
                    "reason": "错误工具。",
                    "evidence_goal": "错误证据",
                    "expected_artifacts": [],
                    "optional": False,
                }
            ],
        }

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)

    snapshot = _snapshot_with_scope()
    plan = asyncio.run(
        plan_with_llm(
            messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
            snapshot=snapshot,
            context=build_context_bundle(snapshot),
            registry=get_tool_registry(),
            memory=WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]}),
        )
    )

    assert all(step.tool_name != "imaginary_tool" for step in plan.steps)
    assert any(step.tool_name == "run_area_character_pack" for step in plan.steps)
    assert "tool_selector_unknown_tool:imaginary_tool" in plan.warnings


def test_audit_with_llm_sends_compact_tool_result_digest(monkeypatch):
    huge_points = [{"id": f"poi-{index}", "lng": 112.98 + index * 0.001, "lat": 28.19} for index in range(300)]
    huge_h3_features = [
        {"id": f"h3-{index}", "properties": {"poi_count": index, "label": f"cell-{index}"}}
        for index in range(300)
    ]
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    captured = {}

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, emit, phase, title, reasoning_id
        captured["user_payload"] = user_payload
        return {"status": "pass", "summary": "证据足够。", "issues": [], "missing_evidence": [], "should_answer": True}

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)

    verdict = asyncio.run(
        audit_with_llm(
            question="总结这个区域的商业特征",
            snapshot=snapshot,
            context=context,
            memory=WorkingMemory(
                artifacts={"scope_polygon": snapshot.scope["polygon"], "current_pois": huge_points},
                tool_results=[
                    ToolResult(
                        tool_name="read_current_results",
                        status="success",
                        result={"poi_count": 300, "raw_points": huge_points},
                        evidence=[{"field": f"poi.{index}", "value": f"evidence-{index}"} for index in range(20)],
                        warnings=[f"warning-{index}" for index in range(12)],
                        artifacts={
                            "current_pois": huge_points,
                            "current_poi_h3_grid": {"features": huge_h3_features, "summary": {"grid_count": 300}},
                            "current_frontend_analysis": {
                                "poi": {"raw_points": huge_points},
                                "h3": {"features": huge_h3_features},
                            },
                        },
                    )
                ],
            ),
            plan=PlanningResult(goal="回答问题", question_type="area_character"),
            rule_audit=AuditResult(),
            replan_count=0,
        )
    )

    assert verdict.status == "pass"
    tool_digest = captured["user_payload"]["tool_results"][0]
    encoded = json.dumps(captured["user_payload"], ensure_ascii=False)

    assert "artifacts" not in tool_digest
    assert "result" not in tool_digest
    assert "poi-299" not in encoded
    assert "h3-299" not in encoded
    assert tool_digest["artifact_keys"] == ["current_pois", "current_poi_h3_grid", "current_frontend_analysis"]
    assert tool_digest["artifact_shapes"]["current_pois"] == {"type": "array", "count": 300}
    assert tool_digest["artifact_shapes"]["current_poi_h3_grid"]["type"] == "object"
    assert tool_digest["artifact_shapes"]["current_poi_h3_grid"]["keys"] == ["features", "summary"]
    assert len(tool_digest["evidence_sample"]) == 8
    assert tool_digest["evidence_count"] == 20
    assert tool_digest["warnings"] == [f"warning-{index}" for index in range(8)]


def test_plan_with_llm_surfaces_llm_errors(monkeypatch):
    async def fail_invoke_json_role(**kwargs):
        del kwargs
        raise RuntimeError("llm_bad_request")

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fail_invoke_json_role)

    with pytest.raises(RuntimeError, match="llm_bad_request"):
        asyncio.run(
            plan_with_llm(
                messages=[AgentMessage(role="user", content="下一步做什么分析")],
                snapshot=_snapshot_with_scope(),
                context=build_context_bundle(_snapshot_with_scope()),
                registry=get_tool_registry(),
                memory=WorkingMemory(),
            )
        )


def test_audit_with_llm_surfaces_llm_errors(monkeypatch):
    async def fail_invoke_json_role(**kwargs):
        del kwargs
        raise RuntimeError("llm_bad_request")

    snapshot = _snapshot_with_scope()
    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fail_invoke_json_role)

    with pytest.raises(RuntimeError, match="llm_bad_request"):
        asyncio.run(
            audit_with_llm(
                question="下一步做什么分析",
                snapshot=snapshot,
                context=build_context_bundle(snapshot),
                memory=WorkingMemory(),
                plan=PlanningResult(goal="回答问题", question_type="next_analysis"),
                rule_audit=AuditResult(missing_evidence=["下一步分析方向"]),
                replan_count=0,
            )
        )


def test_run_gate_with_llm_preserves_llm_clarification_options(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, user_payload, emit, phase, title, reasoning_id
        return {
            "status": "clarify",
            "question_type": "area_character",
            "summary": "还需要先收窄分析方向。",
            "clarification_question": "你更想先看哪个方向？",
            "clarification_options": ["总结商业特征", "哪里适合补充餐饮", "为什么这里路网较弱"],
        }

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)

    decision = asyncio.run(
        run_gate_with_llm(
            messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
            snapshot=snapshot,
            context=context,
        )
    )

    assert decision.status == "clarify"
    assert decision.clarification_question == "你更想先看哪个方向？"
    assert decision.clarification_options == ["总结商业特征", "哪里适合补充餐饮", "为什么这里路网较弱"]


def test_run_gate_with_llm_backfills_missing_clarification_options(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, user_payload, emit, phase, title, reasoning_id
        return {
            "status": "clarify",
            "question_type": "area_character",
            "summary": "POI 口径还需要先收窄。",
            "clarification_questions": ["你更想先看商业、人口还是路网？"],
            "clarification_options": [],
        }

    monkeypatch.setattr("modules.agent.providers.llm_provider._invoke_json_role", fake_invoke_json_role)
    monkeypatch.setattr(
        "modules.agent.providers.llm_provider.run_gate",
        lambda messages, snapshot: GateDecision(status="pass", question_type="area_character", summary="问题已足够清晰。"),
    )

    decision = asyncio.run(
        run_gate_with_llm(
            messages=[AgentMessage(role="user", content="分析一下这个区域")],
            snapshot=snapshot,
            context=context,
        )
    )

    assert decision.status == "clarify"
    assert decision.clarification_question.startswith("1. ")
    assert decision.clarification_options == [
        "总结这个区域的商业特征",
        "哪里适合补充餐饮",
        "为什么这里夜间活力强",
    ]
