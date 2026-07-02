import asyncio

import modules.agent.runtime as agent_runtime
from modules.agent.runtime import process_agent_turn, stream_agent_turn
from modules.agent.schemas import (
    AgentMessage,
    AgentTranslationPack,
    AgentTurnOutput,
    AgentTurnRequest,
    AnalysisSnapshot,
    ExecutionTraceItem,
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


def test_agent_turn_request_accepts_visual_snapshots():
    request = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="总结这个区域")],
        visual_snapshots=[
            {
                "snapshot_id": "visual-1",
                "kind": "road_map",
                "title": "路网全图",
                "data_url": "data:image/jpeg;base64,abc",
                "bounds": {"west": 1, "south": 2, "east": 3, "north": 4},
            }
        ],
    )

    assert request.visual_snapshots[0].kind == "road_map"
    assert request.visual_snapshots[0].data_url.startswith("data:image/")


def test_agent_turn_request_accepts_map_search_context():
    request = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="总结这个区域")],
        map_search_context={
            "place_anchors": {"names": ["后湖", "湖南师范大学"]},
            "spatial_anchors": {"h3": {"top_cells": [{"h3_id": "h3-a"}]}},
        },
    )

    assert request.map_search_context["place_anchors"]["names"] == ["后湖", "湖南师范大学"]


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
        initial_artifacts=None,
    ):
        del messages, snapshot, context, registry, governance_mode, confirmed_tools, emit
        if captured is not None:
            captured["include_secondary_tools"] = include_secondary_tools
            captured["max_steps_override"] = max_steps_override
            captured["max_errors_override"] = max_errors_override
            captured["thinking_mode"] = thinking_mode
            captured["initial_artifacts"] = dict(initial_artifacts or {})
        return loop_result or ToolLoopResult(status="completed")

    async def fake_translation(*, messages, snapshot, context, answer_evidence_payload, image_inputs=None, thinking_mode="quick", emit=None):
        del messages, snapshot, context, emit
        if captured is not None:
            captured["translation_thinking_mode"] = thinking_mode
            captured["translation_image_inputs"] = image_inputs or []
            captured["translation_evidence_payload"] = answer_evidence_payload
        return translation_pack or AgentTranslationPack(
            status="ready",
            summary="已将关键指标转译为空间体验与策划含义。",
            items=[
                {
                    "metric": "poi_count",
                    "raw_signal": "POI 样本量 12",
                    "spatial_phenomenon": "服务供给已有基础。",
                    "human_experience": "可支撑基础到访。",
                    "planning_implication": "AI 生成的策划含义。",
                    "action_hint": "继续核对业态结构。",
                    "confidence": "moderate",
                }
            ],
        )

    async def fake_answer(*, messages, snapshot, context, answer_evidence_payload, translation_pack=None, image_inputs=None, thinking_mode="quick", emit=None):
        del messages, snapshot, context, emit
        if captured is not None:
            captured["answer_thinking_mode"] = thinking_mode
            captured["answer_translation_pack"] = translation_pack
            captured["answer_image_inputs"] = image_inputs or []
            captured["answer_evidence_payload"] = answer_evidence_payload
        return answer_output or AgentTurnOutput(answer="AI 生成的最终回答。")

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
    assert response.used_tools[:2] == ["read_current_scope", "read_current_results"]
    assert "search_analysis_context" in response.used_tools
    assert "read_analysis_evidence_node" in response.used_tools
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


def test_runtime_accepts_blocked_execution_trace_without_failing_turn(monkeypatch):
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(
            status="completed",
            used_tools=["compute_road_syntax_from_scope"],
            execution_trace=[
                ExecutionTraceItem(
                    tool_name="compute_road_syntax_from_scope",
                    status="blocked",
                    reason="需要确认高成本工具",
                    message="工具需要确认后重试。",
                )
            ],
        ),
        answer_output=AgentTurnOutput(answer="已保留被阻断工具的轨迹，并继续回答。"),
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
    assert response.diagnostics.execution_trace[0].status == "blocked"
    assert response.output.answer == "已保留被阻断工具的轨迹，并继续回答。"


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


def test_runtime_does_not_cap_quick_tool_loop_at_four(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_runtime.settings, "ai_max_tool_steps", 0)
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        captured=captured,
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="多跑几步把证据补齐")],
                analysis_snapshot=_snapshot_with_scope(),
                thinking_mode="quick",
            )
        )
    )

    assert response.status == "answered"
    assert captured["max_steps_override"] is None


def test_runtime_passes_visual_snapshots_only_to_translation_and_answer(monkeypatch):
    captured = {}
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        captured=captured,
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域")],
                analysis_snapshot=_snapshot_with_scope(),
                visual_snapshots=[
                    {
                        "snapshot_id": "visual-road",
                        "kind": "road_map",
                        "title": "路网分析全范围图层",
                        "data_url": "data:image/jpeg;base64,abc",
                    }
                ],
            )
        )
    )

    assert response.status == "answered"
    assert captured["translation_image_inputs"][0]["kind"] == "road_map"
    assert captured["answer_image_inputs"][0]["kind"] == "road_map"
    assert captured["answer_evidence_payload"]["frontend_visual_snapshots"]["available"][0]["kind"] == "road_map"
    assert "data_url" not in captured["answer_evidence_payload"]["frontend_visual_snapshots"]["available"][0]
    assert response.diagnostics.translation_pack.status == "ready"


def test_runtime_puts_map_search_context_only_in_working_memory_artifacts(monkeypatch):
    captured = {}
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        captured=captured,
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(context={"mode": "walking"}),
                map_search_context={
                    "place_anchors": {"names": ["后湖", "湖南师范大学"]},
                    "spatial_anchors": {"road": {"metric_keys": ["choice_score"]}},
                },
            )
        )
    )

    assert response.status == "answered"
    assert captured["initial_artifacts"]["frontend_map_search_context"]["place_anchors"]["names"] == ["后湖", "湖南师范大学"]
    assert "place_anchors" not in captured["answer_evidence_payload"]
    assert captured["answer_evidence_payload"]["map_search_context"]["available"] is True
    assert "analysis:frontend_map_search_context" in response.context_summary.available_context_sources


def test_runtime_reads_finalizer_evidence_for_high_value_map_questions(monkeypatch):
    captured = {}
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        captured=captured,
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(context={"mode": "walking"}),
                map_search_context={
                    "place_anchors": {"names": ["后湖", "湖南师范大学", "中南大学"]},
                    "spatial_anchors": {
                        "h3": {"feature_count": 1, "top_cells": [{"h3_id": "h3-a", "poi_count": 18}]},
                        "road": {
                            "feature_count": 2,
                            "metric_keys": ["choice_score", "integration_score"],
                            "sample_segments": [{"name": "麓山南路", "choice_score": 0.72}],
                        },
                        "population": {"cell_count": 1, "top_cells": [{"cell_id": "pop-1", "value": 1200}]},
                        "nightlight": {"cell_count": 1, "top_cells": [{"cell_id": "ntl-1", "radiance": 31.2}]},
                    },
                },
            )
        )
    )

    pack = captured["answer_evidence_payload"]["finalizer_evidence_pack"]
    assert response.status == "answered"
    assert pack["status"] == "ready"
    assert pack["search_queries"]
    assert pack["evidence_nodes"]
    assert set(pack["coverage_domains"]) == {"poi", "h3", "road", "population", "nightlight"}
    assert {node["metadata"]["domain"] for node in pack["evidence_nodes"]}.issuperset({"poi", "h3", "road", "population", "nightlight"})
    assert any(node["title"] == "POI 地名锚点" for node in pack["evidence_nodes"])
    assert all(node.get("source_type") == "system" for node in pack["evidence_nodes"])
    assert "search_analysis_context" in response.diagnostics.used_tools
    assert "read_analysis_evidence_node" in response.diagnostics.used_tools
    assert any(item.id == "finalizer-evidence" and item.meta.get("read_count", 0) > 0 for item in response.diagnostics.thinking_timeline)


def test_runtime_skips_finalizer_evidence_for_simple_metric_questions(monkeypatch):
    captured = {}
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        captured=captured,
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="夜光均值是什么意思")],
                analysis_snapshot=_snapshot_with_scope(),
                map_search_context={
                    "place_anchors": {"names": ["后湖", "湖南师范大学"]},
                    "spatial_anchors": {"nightlight": {"cell_count": 1, "top_cells": [{"cell_id": "ntl-1"}]}},
                },
            )
        )
    )

    pack = captured["answer_evidence_payload"]["finalizer_evidence_pack"]
    assert response.status == "answered"
    assert pack["status"] == "skipped"
    assert pack["reason"] == "not_required"
    assert pack["evidence_nodes"] == []


def test_runtime_continues_when_finalizer_evidence_retrieval_fails(monkeypatch):
    captured = {}
    _install_runtime_stubs(
        monkeypatch,
        loop_result=ToolLoopResult(status="completed"),
        captured=captured,
    )

    def explode(*, question, snapshot, artifacts, answer_evidence_payload):
        del question, snapshot, artifacts, answer_evidence_payload
        raise RuntimeError("retrieval failed")

    monkeypatch.setattr(agent_runtime, "build_finalizer_evidence_pack", explode)

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(),
            )
        )
    )

    pack = captured["answer_evidence_payload"]["finalizer_evidence_pack"]
    assert response.status == "answered"
    assert pack["status"] == "failed"
    assert "最终证据检索失败" in pack["warnings"][0]
    assert any("最终证据检索失败" in note for note in response.diagnostics.research_notes)


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

    async def failing_answer(*, messages, snapshot, context, answer_evidence_payload, translation_pack=None, image_inputs=None, thinking_mode="quick", emit=None):
        del messages, snapshot, context, answer_evidence_payload, translation_pack, image_inputs, thinking_mode, emit
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

    async def failing_translation(*, messages, snapshot, context, answer_evidence_payload, image_inputs=None, thinking_mode="quick", emit=None):
        del messages, snapshot, context, answer_evidence_payload, image_inputs, thinking_mode, emit
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
