import asyncio

import modules.agent.runtime as agent_runtime
from modules.agent.plan_steps import results_step, road_step, scope_step
from modules.agent.runtime import process_agent_turn, stream_agent_turn
from modules.agent.schemas import (
    AgentMessage,
    AgentTurnOutput,
    AgentTurnRequest,
    AnalysisSnapshot,
    AuditVerdict,
    GateDecision,
    PlanningResult,
    PlanStep,
    ToolResult,
    ToolSpec,
)
from modules.agent.tools import RegisteredTool


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


def _fake_registry():
    async def read_scope(*, arguments, snapshot, artifacts, question):
        del arguments, question
        polygon = snapshot.scope.get("polygon") or []
        return ToolResult(
            tool_name="read_current_scope",
            status="success",
            result={"has_scope": bool(polygon), "active_panel": snapshot.active_panel or ""},
            artifacts={"scope_polygon": polygon, "scope_data": snapshot.scope},
        )

    async def read_results(*, arguments, snapshot, artifacts, question):
        del arguments, question
        result = {
            "poi_count": (snapshot.poi_summary or {}).get("total"),
            "has_h3_summary": bool((snapshot.h3 or {}).get("summary")),
            "has_population_summary": bool((snapshot.population or {}).get("summary")),
            "has_nightlight_summary": bool((snapshot.nightlight or {}).get("summary")),
            "has_road_summary": bool((snapshot.road or {}).get("summary")),
        }
        return ToolResult(
            tool_name="read_current_results",
            status="success",
            result=result,
            artifacts={
                "current_pois": list(snapshot.pois or []),
                "current_poi_summary": dict(snapshot.poi_summary or {}),
                "current_poi_h3_summary": dict((snapshot.h3 or {}).get("summary") or {}),
                "current_population_summary": dict((snapshot.population or {}).get("summary") or {}),
                "current_nightlight_summary": dict((snapshot.nightlight or {}).get("summary") or {}),
                "current_road_summary": dict((snapshot.road or {}).get("summary") or {}),
            },
        )

    async def h3_runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="compute_h3_metrics_from_scope_and_pois",
            status="success",
            result={"grid_count": 18, "poi_count": 30},
            artifacts={"current_poi_h3_summary": {"grid_count": 18, "avg_density_poi_per_km2": 7.5}},
        )

    async def population_runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="compute_population_overview_from_scope",
            status="success",
            result={"total_population": 5200, "male_ratio": 0.49, "female_ratio": 0.51},
            artifacts={"current_population_summary": {"total_population": 5200, "male_ratio": 0.49, "female_ratio": 0.51}},
        )

    async def nightlight_runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="compute_nightlight_overview_from_scope",
            status="success",
            result={"mean_radiance": 8.0, "peak_radiance": 16.0},
            artifacts={"current_nightlight_summary": {"mean_radiance": 8.0, "max_radiance": 16.0, "lit_pixel_ratio": 1.0}},
        )

    async def road_runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="compute_road_syntax_from_scope",
            status="success",
            result={"node_count": 88, "edge_count": 132},
            artifacts={"current_road_summary": {"node_count": 88, "edge_count": 132, "avg_choice": 0.42}},
        )

    def tool(name, runner, produces, readonly=False, cost_level="safe"):
        return RegisteredTool(
            spec=ToolSpec(
                name=name,
                description=f"fake {name}",
                category="information" if readonly else "action",
                layer="L1",
                requires=[] if readonly else ["scope_polygon"],
                produces=produces,
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                readonly=readonly,
                cost_level=cost_level,
                risk_level="safe",
            ),
            runner=runner,
        )

    return {
        "read_current_scope": tool("read_current_scope", read_scope, ["scope_polygon", "scope_data"], readonly=True),
        "read_current_results": tool(
            "read_current_results",
            read_results,
            [
                "current_pois",
                "current_poi_summary",
                "current_poi_h3_summary",
                "current_population_summary",
                "current_nightlight_summary",
                "current_road_summary",
            ],
            readonly=True,
        ),
        "compute_h3_metrics_from_scope_and_pois": tool(
            "compute_h3_metrics_from_scope_and_pois",
            h3_runner,
            ["current_poi_h3_summary"],
            cost_level="normal",
        ),
        "compute_population_overview_from_scope": tool(
            "compute_population_overview_from_scope",
            population_runner,
            ["current_population_summary"],
            cost_level="normal",
        ),
        "compute_nightlight_overview_from_scope": tool(
            "compute_nightlight_overview_from_scope",
            nightlight_runner,
            ["current_nightlight_summary"],
            cost_level="normal",
        ),
        "compute_road_syntax_from_scope": tool(
            "compute_road_syntax_from_scope",
            road_runner,
            ["current_road_summary"],
            cost_level="expensive",
        ),
    }


def _mock_roles(monkeypatch, *, gate=None, plans=None, audits=None, answer_output=None):
    monkeypatch.setattr(agent_runtime, "is_llm_enabled", lambda: True)
    gate_result = gate or GateDecision(status="pass", question_type="general", summary="问题已明确。")
    plan_queue = list(plans or [PlanningResult(goal="默认问题", question_type="general", summary="默认计划", steps=[])])
    audit_queue = list(audits or [AuditVerdict(status="pass", summary="审计通过。")])

    async def fake_gate(*, messages, snapshot, context, emit=None):
        del messages, snapshot, context, emit
        return gate_result

    async def fake_plan(*, messages, snapshot, context, registry, memory, audit_feedback=None, emit=None):
        del messages, snapshot, context, registry, memory, audit_feedback, emit
        index = 0 if len(plan_queue) == 1 else fake_plan.calls
        fake_plan.calls += 1
        return plan_queue[min(index, len(plan_queue) - 1)]

    fake_plan.calls = 0

    async def fake_audit(*, question, snapshot, context, memory, plan, rule_audit, replan_count, emit=None):
        del question, snapshot, context, memory, plan, rule_audit, replan_count, emit
        index = 0 if len(audit_queue) == 1 else fake_audit.calls
        fake_audit.calls += 1
        return audit_queue[min(index, len(audit_queue) - 1)]

    fake_audit.calls = 0

    async def fake_answer(*, messages, snapshot, context, synthesis_payload, emit=None):
        del messages, snapshot, context, synthesis_payload, emit
        return answer_output or AgentTurnOutput(
            cards=[
                {
                    "type": "summary",
                    "title": "核心判断",
                    "content": "这是一个生活消费主导的综合商业区。",
                    "items": [],
                }
            ],
            next_suggestions=["继续追问更具体的问题。"],
        )

    monkeypatch.setattr(agent_runtime, "run_gate_with_llm", fake_gate)
    monkeypatch.setattr(agent_runtime, "plan_with_llm", fake_plan)
    monkeypatch.setattr(agent_runtime, "audit_with_llm", fake_audit)
    monkeypatch.setattr(agent_runtime, "generate_answer_output_with_llm", fake_answer)
    monkeypatch.setattr(agent_runtime, "get_tool_registry", _fake_registry)


def test_runtime_requires_clarification_from_gate(monkeypatch):
    _mock_roles(
        monkeypatch,
        gate=GateDecision(
            status="clarify",
            question_type="summary",
            summary="还缺少关键信息。",
            clarification_questions=["你更想总结商业结构、人口还是路网？", "是否要聚焦某一类业态？"],
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
    assert "1." in response.clarification_question
    assert response.output.clarification_options == []
    assert response.stage == "requires_clarification"


def test_runtime_returns_clarification_options(monkeypatch):
    _mock_roles(
        monkeypatch,
        gate=GateDecision(
            status="clarify",
            question_type="summary",
            summary="问题还不够具体。",
            clarification_questions=["你更想看商业特征、人口还是路网？"],
            clarification_options=["总结这个区域的商业特征", "为什么这里路网差", "下一步做什么分析"],
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
    assert response.output.clarification_options == [
        "总结这个区域的商业特征",
        "为什么这里路网差",
        "下一步做什么分析",
    ]


def test_runtime_executes_plan_then_answers(monkeypatch):
    _mock_roles(
        monkeypatch,
        plans=[
            PlanningResult(
                goal="先复用已有结果回答下一步分析建议",
                question_type="next_step",
                summary="先读取已有范围和结果。",
                steps=[scope_step(), results_step("读取当前已有结果")],
            )
        ],
        audits=[AuditVerdict(status="pass", summary="当前证据足以回答。")],
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="下一步做什么分析")],
                analysis_snapshot=_snapshot_with_scope(
                    pois=[{"id": "poi-1"}],
                    poi_summary={"total": 1},
                    h3={"summary": {"grid_count": 12, "avg_density_poi_per_km2": 5.5}},
                ),
            )
        )
    )

    assert response.status == "answered"
    assert response.used_tools == ["read_current_scope", "read_current_results"]
    assert response.diagnostics.planning_summary == "先读取已有范围和结果。"
    assert response.diagnostics.audit_summary == "当前证据足以回答。"
    assert response.assistant_cards[0].content


def test_runtime_replans_after_audit_then_executes_missing_dimensions(monkeypatch):
    _mock_roles(
        monkeypatch,
        plans=[
            PlanningResult(
                goal="首轮只读取已有结果",
                question_type="summary",
                summary="先判断已有结果是否足够。",
                steps=[scope_step(), results_step("只读取已有结果")],
            ),
            PlanningResult(
                goal="补齐综合商业特征证据",
                question_type="summary",
                summary="补齐空间、人口、夜光和路网四类证据。",
                steps=[
                    PlanStep(tool_name="compute_h3_metrics_from_scope_and_pois", reason="补齐 H3", evidence_goal="POI H3 密度"),
                    PlanStep(tool_name="compute_population_overview_from_scope", reason="补齐人口", evidence_goal="人口概览"),
                    PlanStep(tool_name="compute_nightlight_overview_from_scope", reason="补齐夜光", evidence_goal="夜光概览"),
                    road_step("补齐路网"),
                ],
            ),
        ],
        audits=[
            AuditVerdict(
                status="replan",
                summary="首轮只有 POI，不足以回答商业特征总结。",
                missing_evidence=["POI H3 密度证据", "人口概览", "夜光概览", "路网概览"],
                replan_instructions="补齐四类证据后再回答。",
                should_answer=False,
            ),
            AuditVerdict(status="pass", summary="综合证据已齐，可以回答。"),
        ],
    )

    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域的商业特征")],
                analysis_snapshot=_snapshot_with_scope(
                    poi_summary={"total": 30},
                    frontend_analysis={
                        "poi": {
                            "category_stats": {
                                "labels": ["餐饮", "购物", "科教文化", "住宿"],
                                "values": [10, 8, 5, 4],
                            }
                        }
                    },
                ),
            )
        )
    )

    assert response.status == "answered"
    assert response.diagnostics.replan_count == 1
    assert response.plan.followup_applied is True
    assert [step.tool_name for step in response.plan.followup_steps] == [
        "compute_h3_metrics_from_scope_and_pois",
        "compute_population_overview_from_scope",
        "compute_nightlight_overview_from_scope",
        "compute_road_syntax_from_scope",
    ]
    assert response.used_tools[-4:] == [
        "compute_h3_metrics_from_scope_and_pois",
        "compute_population_overview_from_scope",
        "compute_nightlight_overview_from_scope",
        "compute_road_syntax_from_scope",
    ]


def test_runtime_readonly_blocks_non_readonly_plan_step(monkeypatch):
    _mock_roles(
        monkeypatch,
        plans=[
            PlanningResult(
                goal="解释路网可达性",
                question_type="road",
                summary="需要补跑路网句法。",
                steps=[scope_step(), road_step("补跑路网句法分析")],
            )
        ],
        audits=[AuditVerdict(status="pass", summary="通过。")],
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
    assert "readonly" in response.risk_prompt
    assert "compute_road_syntax_from_scope" in response.risk_prompt


def test_runtime_fails_when_ai_not_enabled(monkeypatch):
    monkeypatch.setattr(agent_runtime, "is_llm_enabled", lambda: False)
    response = asyncio.run(
        process_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="总结这个区域")],
                analysis_snapshot=_snapshot_with_scope(),
            )
        )
    )

    assert response.status == "failed"
    assert "多角色编排" in response.diagnostics.error


def test_stream_agent_turn_emits_new_stages(monkeypatch):
    _mock_roles(
        monkeypatch,
        gate=GateDecision(status="pass", question_type="next_step", summary="问题已明确，可以基于当前范围继续。"),
        plans=[
            PlanningResult(
                goal="读取已有结果",
                question_type="next_step",
                summary="先读取范围和已有结果。",
                steps=[scope_step(), results_step("读取当前已有结果")],
            )
        ],
        audits=[AuditVerdict(status="pass", summary="审计通过。")],
    )

    async def collect():
        items = []
        async for event in stream_agent_turn(
            AgentTurnRequest(
                messages=[AgentMessage(role="user", content="下一步做什么分析")],
                analysis_snapshot=_snapshot_with_scope(poi_summary={"total": 1}),
            )
        ):
            items.append(event)
        return items

    events = asyncio.run(collect())
    statuses = [event.payload.get("stage") for event in events if event.type == "status"]
    plans = [event.payload for event in events if event.type == "plan"]
    thinking = [event.payload for event in events if event.type == "thinking"]
    traces = [event.payload for event in events if event.type == "trace"]

    assert "gating" in statuses
    assert "planning" in statuses
    assert "executing" in statuses
    assert "auditing" in statuses
    assert "synthesizing" in statuses
    assert plans
    assert plans[0]["steps"][0]["tool_name"] == "read_current_scope"
    latest_thinking = {item["id"]: item for item in thinking}
    assert latest_thinking["gating-check"]["display_text"] == "问题已明确，可以基于当前范围继续。"
    assert latest_thinking["plan-0"]["display_text"] == "先读取范围和已有结果。"
    assert latest_thinking["audit-0"]["display_text"] == "审计通过。"
    assert latest_thinking["executing-0"].get("display_text", "") == ""
    start_trace = next(item for item in traces if item.get("tool_name") == "read_current_scope" and item.get("status") == "start")
    assert start_trace["display_text"] == "读取当前分析范围"
    success_trace = next(item for item in traces if item.get("tool_name") == "read_current_scope" and item.get("status") == "success")
    assert success_trace["display_text"]
    assert events[-1].type == "final"
