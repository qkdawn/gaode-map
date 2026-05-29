import asyncio
import json

import httpx
import pytest

from core.config import settings
from modules.agent.context_builder import build_context_bundle
from modules.agent.providers.llm_provider import _invoke_json_role, audit_with_llm, generate_answer_output_with_llm, plan_with_llm, run_gate_with_llm, run_llm_tool_loop
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
    assert any(
        item["type"] == "trace" and item["payload"]["status"] == "skipped" and item["payload"]["message"] == "复用已有工具结果"
        for item in events
    )


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
        del emit, phase, title, reasoning_id
        captured["system_prompt"] = system_prompt
        captured["user_payload"] = user_payload
        return {
            "goal": user_payload["latest_user_message"],
            "question_type": "area_character",
            "summary": "优先走区域画像场景包，再按缺口补证。",
            "requires_tools": True,
            "stop_condition": "证据足够时停止。",
            "evidence_focus": ["区域调性"],
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
    assert "默认优先场景工具" in captured["system_prompt"]
    assert "区域画像/调性判断默认优先 run_area_character_pack" in captured["system_prompt"]
    assert "frontend_analysis 中键存在不等于有可用分析" in captured["system_prompt"]
    assert captured["user_payload"]["question_archetype"] == "metric"
    assert "fallback_plan" in captured["user_payload"]
    assert "artifact_digest" in captured["user_payload"]
    assert "tool_routing_hints" in captured["user_payload"]
    assert "current_poi_structure_analysis" in captured["user_payload"]["artifact_digest"]["analysis_artifacts"]
    assert captured["user_payload"]["artifact_digest"]["analysis_readiness"]["h3"] is False
    assert "h3" in captured["user_payload"]["artifact_digest"]["empty_analysis_dimensions"]
    assert "current_business_profile" in captured["user_payload"]["artifact_digest"]["derived_artifacts"]
    assert "area_character" in captured["user_payload"]["tool_routing_hints"]["question_routes"]
    assert "run_area_character_pack" in captured["user_payload"]["tool_routing_hints"]["layers"]["scenario"]
    tool_names = [item["name"] for item in captured["user_payload"]["available_tools"]]
    assert "run_area_character_pack" in tool_names
    assert "run_business_site_advice" not in tool_names


def test_plan_with_llm_uses_site_advice_archetype_for_target_supply_questions(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    registry = get_tool_registry()
    memory = WorkingMemory(artifacts={"scope_polygon": snapshot.scope["polygon"]})
    captured = {}

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id):
        del system_prompt, emit, phase, title, reasoning_id
        captured["user_payload"] = user_payload
        return {
            "goal": user_payload["latest_user_message"],
            "question_type": "site_selection",
            "summary": "围绕目标业态补证。",
            "requires_tools": True,
            "stop_condition": "目标业态证据足够时停止。",
            "evidence_focus": ["候选点排序"],
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
    assert captured["user_payload"]["question_archetype"] == "site_selection"


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
