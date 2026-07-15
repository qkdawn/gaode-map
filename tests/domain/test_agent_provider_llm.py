import asyncio
import json

import httpx

from core.config import settings
from modules.agent.context_builder import build_context_bundle
from modules.agent.llm_digest import compact_context_summary_dump, context_digest, snapshot_digest, trim_messages
import modules.agent.providers.langgraph_react as langgraph_react
from modules.agent.providers.chat_parser import extract_json_object
from modules.agent.providers.llm_provider import (
    _invoke_json_role,
    _stream_chat_completion,
    _with_provider_thinking,
    generate_answer_output_with_llm,
    run_gate_with_llm,
)
from modules.agent.schemas import AgentMessage, AgentTranslationPack, AnalysisSnapshot, GateDecision, ToolLoopResult


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



def test_stream_chat_completion_forwards_content_deltas(monkeypatch):
    requests = []
    emitted = []
    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-fast-1",
                content="快速答案",
            )
        ],
    )

    async def emit(event_type, payload):
        emitted.append((event_type, payload))

    async def run():
        async with httpx.AsyncClient() as client:
            return await _stream_chat_completion(
                client=client,
                base_url="https://example.test/v1",
                headers={"Authorization": "Bearer test"},
                request_body={"model": "test-model", "messages": []},
                content_emit=emit,
                enable_thinking=False,
            )

    payload = asyncio.run(run())

    assert payload["choices"][0]["message"]["content"] == "快速答案"
    assert emitted == [("content_delta", {"delta": "快速答案"})]


def test_provider_thinking_uses_the_runtime_flag_not_global_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)

    disabled = _with_provider_thinking({"model": "glm-5.2"}, enabled=False)
    enabled = _with_provider_thinking({"model": "glm-5.2"}, enabled=True)

    assert "thinking" not in disabled
    assert enabled["thinking"] == {"type": "enabled"}


def test_langgraph_react_disables_llm_timeout(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        def bind_tools(self, tool_schemas):
            captured["tool_schema_count"] = len(tool_schemas)
            return self

    class FakeStateGraph:
        def __init__(self, state_type):
            del state_type

        def add_node(self, *args, **kwargs):
            del args, kwargs

        def set_entry_point(self, *args, **kwargs):
            del args, kwargs

        def add_conditional_edges(self, *args, **kwargs):
            del args, kwargs

        def add_edge(self, *args, **kwargs):
            del args, kwargs

        def compile(self):
            class FakeApp:
                async def ainvoke(self, state, config):
                    del config
                    return {"result": state["result"]}

            return FakeApp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr("langgraph.graph.StateGraph", FakeStateGraph)

    result = asyncio.run(langgraph_react.run_langgraph_react_loop(
        messages=[AgentMessage(role="user", content="深度分析")],
        snapshot=_snapshot_with_scope(),
        context=None,
        registry={},
        governance_mode="auto",
    ))

    assert isinstance(result, ToolLoopResult)
    assert captured["timeout"] is None


def test_langgraph_react_emits_deep_process_milestones(monkeypatch):
    captured_events = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def bind_tools(self, tool_schemas):
            del tool_schemas
            return self

        async def ainvoke(self, messages):
            del messages
            return type("FakeMessage", (), {"content": "已具备回答条件。", "tool_calls": []})()

    class FakeStateGraph:
        def __init__(self, state_type):
            del state_type
            self.nodes = {}

        def add_node(self, name, handler):
            self.nodes[name] = handler

        def set_entry_point(self, *args, **kwargs):
            del args, kwargs

        def add_conditional_edges(self, *args, **kwargs):
            del args, kwargs

        def add_edge(self, *args, **kwargs):
            del args, kwargs

        def compile(self):
            nodes = self.nodes

            class FakeApp:
                async def ainvoke(self, state, config):
                    del config
                    await nodes["preflight"](state)
                    await nodes["think"](state)
                    state["result"].status = "completed"
                    await nodes["assess"](state)
                    await nodes["finalize"](state)
                    return {"result": state["result"]}

            return FakeApp()

    async def fake_emit(event_type, payload):
        captured_events.append((event_type, payload))

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr("langgraph.graph.StateGraph", FakeStateGraph)

    asyncio.run(langgraph_react.run_langgraph_react_loop(
        messages=[AgentMessage(role="user", content="深度分析")],
        snapshot=_snapshot_with_scope(),
        context=None,
        registry={},
        governance_mode="auto",
        emit=fake_emit,
    ))

    thinking_titles = [payload.get("title") for event_type, payload in captured_events if event_type == "thinking"]
    assert "整理执行边界" in thinking_titles
    assert "判断下一步" in thinking_titles
    assert "检查证据是否足够" in thinking_titles
    assert "进入最终回答" in thinking_titles


def test_generate_answer_output_with_llm_parses_natural_answer(monkeypatch):
    requests = []
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-answer-1",
                reasoning_parts=["组织自然回答。"],
                content='{"answer":"这个区域商业较成熟，现有 POI 供给已经形成基本支撑，但如果要把判断说得更稳，仍建议补一轮路网复核。"}',
            )
        ],
    )

    output = asyncio.run(
        generate_answer_output_with_llm(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            answer_evidence_payload={"metrics": {"poi_count": 12}, "key_evidence": [{"metric": "poi_count"}]},
            translation_pack=AgentTranslationPack(
                status="ready",
                summary="POI 供给具备基础。",
                items=[
                    {
                        "metric": "poi_count",
                        "raw_signal": "POI 样本量 12",
                        "spatial_phenomenon": "服务设施已有基础。",
                        "human_experience": "能支撑基础到访需求。",
                        "planning_implication": "适合做社区级服务补充判断。",
                        "action_hint": "继续核对业态结构。",
                        "confidence": "moderate",
                    }
                ],
            ),
        )
    )

    assert output.answer.startswith("这个区域商业较成熟")
    system_prompt = requests[0]["json"]["messages"][0]["content"]
    user_payload = json.loads(requests[0]["json"]["messages"][1]["content"])
    assert '{"answer":"..."}' in system_prompt
    assert "城市空间与文旅商业策划分析顾问" in system_prompt
    assert "不是 GIS 指标解释器" in system_prompt
    assert "translation_pack.status=ready" in system_prompt
    assert "先直接回答用户问题" in system_prompt
    assert "文风跟问题类型走" in system_prompt
    assert "Markdown 风格的中文标题和分段" in system_prompt
    assert "按问题价值组织自然段或小标题" in system_prompt
    assert "高价值问题要充分展开，简单问题要保持简短" in system_prompt
    assert "不设置固定字数上限" in system_prompt
    assert "保留能支撑判断的关键数字" in system_prompt
    assert "空间主结构" in system_prompt
    assert "内圈/外圈" in system_prompt
    assert "动线" in system_prompt
    assert "不要按餐饮占比、科教占比、多核心、路网、夜光逐项翻译成指标总结" in system_prompt
    assert "谁围着谁、谁带动谁、哪里是内圈、哪里是外圈" in system_prompt
    assert "关键矛盾/机会 -> 为什么此动作重要 -> 用什么证据筛掉伪机会" in system_prompt
    assert "不要写成“系统可以跑哪些工具”的流程说明" in system_prompt
    assert "finalizer_evidence_pack" in system_prompt
    assert "evidence_nodes" in system_prompt
    assert "统一 EvidenceNode" in system_prompt
    assert "不要只改写压缩摘要" in system_prompt
    assert "不要固定成总判断/关键证据/边界下一步等模板" in system_prompt
    assert "coverage_domains" in system_prompt
    assert "不能只抓 POI" in system_prompt
    assert "学生高频低客单" in system_prompt
    assert "target_depth=full" in system_prompt
    assert "target_depth=concise" in system_prompt
    assert "只补最必要的证据支撑" not in system_prompt
    assert "3 到 5 个简短小标题或自然段" not in system_prompt
    assert "review_contract" not in system_prompt
    assert "cards" not in system_prompt
    assert "decision_strength" not in system_prompt
    assert "answer_evidence_payload" in user_payload
    assert user_payload["translation_pack"]["status"] == "ready"
    assert user_payload["translation_pack"]["items"][0]["spatial_phenomenon"] == "服务设施已有基础。"
    assert "synthesis_payload" not in user_payload


def test_generate_answer_output_with_llm_accepts_plain_answer_only(monkeypatch):
    requests = []
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", True)

    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-answer-missing-card-content",
                reasoning_parts=["组织自然回答。"],
                content='{"answer":"可以先形成方向性判断，但还需要补一轮路网证据，才能进一步解释可达性差异。"}',
            )
        ],
    )

    output = asyncio.run(
        generate_answer_output_with_llm(
            messages=[AgentMessage(role="user", content="总结这个区域")],
            snapshot=snapshot,
            context=context,
            answer_evidence_payload={"metrics": {"poi_count": 12}},
        )
    )

    assert output.answer == "可以先形成方向性判断，但还需要补一轮路网证据，才能进一步解释可达性差异。"


def test_invoke_json_role_requests_json_object_response(monkeypatch):
    requests = []
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", False)
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


def test_invoke_json_role_sends_visual_snapshots_as_image_url(monkeypatch):
    requests = []
    monkeypatch.setattr(settings, "ai_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")
    monkeypatch.setattr(settings, "ai_thinking_enabled", False)
    _mock_streams(
        monkeypatch,
        requests,
        [
            _completion_stream(
                response_id="resp-json-image-1",
                content='{"ok":true}',
            )
        ],
    )

    result = asyncio.run(_invoke_json_role(
        system_prompt="只输出 json",
        user_payload={"task": "unit_test"},
        image_inputs=[{"data_url": "data:image/jpeg;base64,abc", "kind": "road_map"}],
        emit=None,
        phase="unit",
        title="JSON unit",
        reasoning_id="json-unit",
    ))

    user_content = requests[0]["json"]["messages"][1]["content"]
    assert result == {"ok": True}
    assert user_content[0]["type"] == "text"
    assert json.loads(user_content[0]["text"]) == {"task": "unit_test"}
    assert user_content[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}}


def test_extract_json_object_repairs_trailing_commas():
    parsed = extract_json_object(
        """
        ```json
        {
          "answer": "继续看路网，",
        }
        ```
        """
    )

    assert parsed["answer"] == "继续看路网，"


def test_extract_json_object_accepts_llm_control_characters_in_strings():
    parsed = extract_json_object('{"answer":"第一行\n第二行"}')

    assert parsed["answer"] == "第一行\n第二行"


def test_extract_json_object_repairs_unescaped_quotes_from_model_output():
    parsed = extract_json_object(
        '{"answer":"证据说明**"仅用于连通性验证"**，不能推断整体结论。", "evidence": []}'
    )

    assert parsed["answer"] == '证据说明**"仅用于连通性验证"**，不能推断整体结论。'
    assert parsed["evidence"] == []


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

    payload = {
        "analysis_snapshot_digest": snapshot_digest(snapshot),
        "context_digest": context_digest(context),
        "context_summary": compact_context_summary_dump(context.context_summary),
    }
    encoded = json.dumps(payload, ensure_ascii=False)

    assert len(encoded) < 30000
    assert "poi-299" not in encoded
    assert payload["context_digest"]["analysis"]["frontend_analysis"] == {
        "available_sections": ["poi", "road"],
        "section_count": 2,
    }
    assert payload["analysis_snapshot_digest"]["current_filters"]["poi_details"]["count"] == 300
    assert payload["context_summary"]["filters_digest"]["poi_details"]["count"] == 300


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


def test_run_gate_with_llm_preserves_llm_clarification_options(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id, runtime):
        del system_prompt, user_payload, emit, phase, title, reasoning_id, runtime
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

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id, runtime):
        del system_prompt, user_payload, emit, phase, title, reasoning_id, runtime
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


def test_run_gate_with_llm_normalizes_null_gate_fields(monkeypatch):
    snapshot = _snapshot_with_scope()
    context = build_context_bundle(snapshot)

    async def fake_invoke_json_role(*, system_prompt, user_payload, emit, phase, title, reasoning_id, runtime):
        del system_prompt, user_payload, emit, phase, title, reasoning_id, runtime
        return {
            "status": "pass",
            "question_type": "area_character",
            "summary": None,
            "clarification_questions": None,
            "clarification_options": None,
            "missing_information": None,
            "clarification_question": None,
            "blocked_reason": None,
            "research_notes": None,
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

    assert decision.status == "pass"
    assert decision.summary == "问题已足够清晰。"
    assert decision.blocked_reason == ""
    assert decision.clarification_question == ""
    assert decision.clarification_questions == []
    assert decision.clarification_options == []
    assert decision.missing_information == []
    assert decision.research_notes == []
