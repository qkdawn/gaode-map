import asyncio

import modules.agent.runtime as agent_runtime
from modules.agent.runtime import process_agent_turn, stream_agent_turn
from modules.agent.schemas import (
    AgentMessage,
    AgentTranslationPack,
    AgentTurnOutput,
    AgentTurnRequest,
    AnalysisSnapshot,
    GateDecision,
    PlanStep,
    ToolLoopResult,
    ToolResult,
)


def test_agent_turn_request_normalizes_thinking_mode_alias():
    request = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="继续分析这个区域")],
        analysis_snapshot={"scope": {"polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}},
        thinkingMode="deep",
    )

    assert request.thinking_mode == "deep"


def _snapshot_with_scope(**kwargs) -> AnalysisSnapshot:
    payload = {
        "scope": {
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        }
    }
    payload.update(kwargs)
    return AnalysisSnapshot(**payload)


def _install_runtime_stubs(monkeypatch, *, gate=None, loop_result=None, translation_pack=None, answer_output=None, captured=None):
    monkeypatch.setattr(agent_runtime, "is_llm_enabled", lambda: True)

    async def fake_gate(*, messages, snapshot, context, emit=None):
        del messages, snapshot, context, emit
        return gate or GateDecision(status="pass", question_type="general", summary="问题已明确。")

    async def fake_loop(
        *,
        messages,
        snapshot,
        context,
        registry,
        governance_mode,
        confirmed_tools=None,
        emit=None,
        include_secondary_tools=False,
        max_steps_override=None,
        max_errors_override=None,
        thinking_mode="quick",
    ):
        del messages, snapshot, context, registry, governance_mode, confirmed_tools, emit
        if captured is not None:
            captured["include_secondary_tools"] = include_secondary_tools
            captured["max_steps_override"] = max_steps_override
            captured["max_errors_override"] = max_errors_override
            captured["thinking_mode"] = thinking_mode
        return loop_result or ToolLoopResult(status="completed")

    async def fake_translation(*, messages, snapshot, context, answer_evidence_payload, thinking_mode="quick", emit=None):
        del messages, snapshot, context, answer_evidence_payload, emit
        if captured is not None:
            captured["translation_thinking_mode"] = thinking_mode
        return translation_pack or AgentTranslationPack(
            status="ready",
            summary="已将关键指标转译为空间体验与策划含义。",
            items=[
                {
                    "metric": "poi_count",
                    "raw_signal": "POI 样本量 12",
                    "spatial_phenomenon": "服务供给已有基础。",
                    "human_experience": "可支撑基础到访。",
                    "planning_implication": "适合继续判断社区服务补位。",
                    "action_hint": "继续核对业态结构。",
                    "confidence": "moderate",
                }
            ],
        )

    async def fake_answer(*, messages, snapshot, context, answer_evidence_payload, translation_pack=None, thinking_mode="quick", emit=None):
        del messages, snapshot, context, answer_evidence_payload, emit
        if captured is not None:
            captured["answer_thinking_mode"] = thinking_mode
            captured["answer_translation_pack"] = translation_pack
        return answer_output or AgentTurnOutput(answer="这是一个生活消费主导的综合商业区。")

    monkeypatch.setattr(agent_runtime, "run_gate_with_llm", fake_gate)
    monkeypatch.setattr(agent_runtime, "run_langgraph_react_loop", fake_loop)
    monkeypatch.setattr(agent_runtime, "generate_translation_pack_with_llm", fake_translation)
    monkeypatch.setattr(agent_runtime, "generate_answer_output_with_llm", fake_answer)


def test_runtime_requires_clarification_from_gate(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        gate=GateDecision(
            status="clarify",
            question_type="summary",
            summary="还缺少关键信息。",
            clarification_questions=["你更想总结商业结构、人口还是路网？"],
            clarification_options=["总结这个区域的商业特征", "为什么这里路网差"],
        ),
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="分析一下")],
                analysis_snapshot=_snapshot_with_scope(),
            )
        )
    )

    assert response.status == "requires_clarification"
    assert response.output.clarification_options == ["总结这个区域的商业特征", "为什么这里路网差"]
    assert response.stage == "requires_clarification"


def test_runtime_uses_tool_loop_then_answers(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(
            status="completed",
            steps=[
                PlanStep(tool_name="read_current_scope", reason="确认范围"),
                PlanStep(tool_name="read_current_results", reason="复用现有结果"),
            ],
            used_tools=["read_current_scope", "read_current_results"],
            execution_trace=[
                {"tool_name": "read_current_scope", "status": "success", "reason": "确认范围", "message": "执行成功"},
                {"tool_name": "read_current_results", "status": "success", "reason": "复用现有结果", "message": "执行成功"},
            ],
            tool_results=[
                ToolResult(tool_name="read_current_scope", status="success", artifacts={"scope_polygon": [[1, 1], [1, 2], [2, 2], [1, 1]]}),
                ToolResult(tool_name="read_current_results", status="success", artifacts={"current_poi_summary": {"total": 12}}),
            ],
            artifacts={"current_poi_summary": {"total": 12}},
        ),
        answer_output=AgentTurnOutput(answer="这里更接近生活服务导向的社区商业片区。"),
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(poi_summary={"total": 12}),
            )
        )
    )

    assert response.status == "answered"
    assert response.output.answer == "这里更接近生活服务导向的社区商业片区。"
    assert response.used_tools == ["read_current_scope", "read_current_results"]
    assert response.plan.steps[0].tool_name == "read_current_scope"
    assert "本轮按需调用工具补证据" in response.diagnostics.planning_summary
    assert response.diagnostics.translation_pack.status == "ready"
    assert response.diagnostics.translation_pack.items[0].planning_implication


def test_runtime_returns_risk_confirmation_from_tool_loop(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(
            status="requires_risk_confirmation",
            risk_prompt="工具 `compute_road_syntax_from_scope` 属于高成本执行，请确认后重试。",
            steps=[PlanStep(tool_name="compute_road_syntax_from_scope", reason="补齐路网证据")],
        ),
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                governance_mode="readonly",
                messages=[AgentMessage(role="user", content="为什么这里路网差")],
                analysis_snapshot=_snapshot_with_scope(),
            )
        )
    )

    assert response.status == "requires_risk_confirmation"
    assert "compute_road_syntax_from_scope" in response.output.risk_prompt
    assert response.plan.steps[0].tool_name == "compute_road_syntax_from_scope"


def test_runtime_passes_deep_thinking_mode_into_tool_loop_and_finalizer(monkeypatch):
    captured = {}
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        answer_output=AgentTurnOutput(answer="这里适合继续做更深一层判断。"),
        captured=captured,
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="继续分析这个区域")],
                analysis_snapshot=_snapshot_with_scope(),
                thinking_mode="deep",
            )
        )
    )

    assert response.status == "answered"
    assert captured["thinking_mode"] == "deep"
    assert captured["translation_thinking_mode"] == "deep"
    assert captured["answer_thinking_mode"] == "deep"
    assert captured["answer_translation_pack"].status == "ready"
    assert captured["include_secondary_tools"] is True


def test_runtime_falls_back_to_server_side_answer_when_finalizer_fails(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(
            status="completed",
            used_tools=["read_current_results"],
            tool_results=[ToolResult(tool_name="read_current_results", status="success", artifacts={"current_poi_summary": {"total": 12}})],
            artifacts={"current_poi_summary": {"total": 12}},
        ),
    )

    async def failing_answer(*, messages, snapshot, context, answer_evidence_payload, translation_pack=None, thinking_mode="quick", emit=None):
        del messages, snapshot, context, answer_evidence_payload, translation_pack, thinking_mode, emit
        raise RuntimeError("llm failed")

    monkeypatch.setattr(agent_runtime, "generate_answer_output_with_llm", failing_answer)

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(poi_summary={"total": 12}),
            )
        )
    )

    assert response.status == "answered"
    assert response.output.answer
    assert "服务端兜底" in response.diagnostics.error


def test_runtime_keeps_answering_when_translation_layer_fails(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(
            status="completed",
            used_tools=["read_current_results"],
            tool_results=[ToolResult(tool_name="read_current_results", status="success", artifacts={"current_poi_summary": {"total": 12}})],
            artifacts={"current_poi_summary": {"total": 12}},
        ),
        answer_output=AgentTurnOutput(answer="这里仍可基于原始证据形成方向性判断。"),
    )

    async def failing_translation(*, messages, snapshot, context, answer_evidence_payload, thinking_mode="quick", emit=None):
        del messages, snapshot, context, answer_evidence_payload, thinking_mode, emit
        raise RuntimeError("translation failed")

    monkeypatch.setattr(agent_runtime, "generate_translation_pack_with_llm", failing_translation)

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(poi_summary={"total": 12}),
            )
        )
    )

    assert response.status == "answered"
    assert response.output.answer == "这里仍可基于原始证据形成方向性判断。"
    assert response.diagnostics.translation_pack.status == "failed"
    assert "translation failed" in response.diagnostics.translation_pack.error


def test_stream_agent_turn_emits_gating_executing_and_final(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(
            status="completed",
            steps=[PlanStep(tool_name="read_current_results", reason="复用现有结果")],
            used_tools=["read_current_results"],
            execution_trace=[{"tool_name": "read_current_results", "status": "success", "reason": "复用现有结果", "message": "执行成功"}],
        ),
        answer_output=AgentTurnOutput(answer="这里以社区商业为主。"),
    )

    async def collect():
        return [event async for event in stream_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域")],
                analysis_snapshot=_snapshot_with_scope(),
            )
        )]

    events = asyncio.run(collect())
    event_types = [event.type for event in events]
    stages = [event.payload.get("stage") for event in events if event.type == "status"]

    assert "final" in event_types
    assert "gating" in stages
    assert "executing" in stages
    assert stages[-1] == "answered"
