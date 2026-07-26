import asyncio

import pytest

from modules.agent.context_builder import build_context_bundle
from modules.agent.memory import create_working_memory
from modules.agent.runtime import (
    _run_formal_specialist_roles,
    _run_market_product_recheck,
    _run_required_skill_dependencies,
)
from modules.agent.schemas import (
    AgentMessage,
    AgentTurnRequest,
    EffectiveExecutionProfile,
    ToolAllocationDecision,
    ToolLoopResult,
)
from modules.agent.skill_dependencies import resolve_skill_dependencies
from modules.agent.providers.tool_loop import tool_allocation_candidates
from modules.agent.tools import get_tool_registry


def _payload(text: str) -> AgentTurnRequest:
    return AgentTurnRequest(
        history_id="history-latest",
        messages=[AgentMessage(role="user", content=text)],
    )


def _confirmed_payload(text: str) -> AgentTurnRequest:
    payload = _payload(text)
    payload.analysis_snapshot.context["problem_map"] = {"status": "confirmed"}
    return payload


def _public_web_sources(*, categories=None):
    categories = categories or [
        "统计",
        "政策规划",
        "文保档案",
        "片区供给",
        "直接及区域竞品",
        "文化机构或机构采购",
        "公开价格与活动",
    ]
    return {
        "coverage_status": "usable_sources_found",
        "category_coverage": [
            {"category": category, "coverage_status": "searched_no_usable_source"}
            for category in categories
        ],
    }


def _market_artifact():
    return {
        "stage": "market_discovery",
        "status": "completed",
        "artifacts": {"public_web_sources": _public_web_sources()},
    }


def _product_inventory(*product_ids):
    return {
        "status": "draft",
        "products": [
            {"product_id": product_id, "name": f"产品 {product_id}"}
            for product_id in product_ids
        ],
    }


@pytest.fixture(autouse=True)
def _allocated_tools(monkeypatch):
    async def allocate(**kwargs):
        return ToolAllocationDecision(
            agent_role=kwargs["agent_role"],
            allowed_tools=[kwargs["candidate_tools"][0]["name"]],
            rationale="测试授权",
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_tool_allocator_with_llm", allocate)


def test_spatial_business_skill_triggers_cultural_dependency_for_tourism_project():
    deps = resolve_skill_dependencies(
        _payload("请分析这个历史建筑文旅活化项目"),
        EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
    )
    assert [(item.skill_id, item.when) for item in deps] == [
        ("cultural-tourism-theme-research", "cultural_heritage_or_destination_activation")
    ]


def test_spatial_business_skill_does_not_trigger_dependency_for_plain_metric_question():
    deps = resolve_skill_dependencies(
        _payload("请分析这个区域的夜光和路网结构"),
        EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
    )
    assert deps == []


def test_confirmed_problem_map_starts_market_discovery_after_preflight_dependencies():
    deps = resolve_skill_dependencies(
        _payload("问题地图已确认，请继续完成正式综合报告"),
        EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
    )
    assert deps == []


def test_unconfirmed_problem_map_text_cannot_unlock_market_discovery():
    deps = resolve_skill_dependencies(
        _payload("问题地图待确认，不要开始正式研究"),
        EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
    )

    assert deps == []


def test_confirmed_problem_map_status_starts_market_discovery():
    payload = _payload("继续正式报告")
    payload.analysis_snapshot.context["problem_map"] = {"status": "confirmed"}

    deps = resolve_skill_dependencies(payload, EffectiveExecutionProfile(skill_id="spatial-business-analyst"))

    assert [(item.skill_id, item.stage) for item in deps] == [
        ("spatial-market-audience-research", "market_discovery"),
    ]


def test_market_research_tool_candidates_cover_public_project_poi_and_scope_evidence():
    candidates = tool_allocation_candidates(get_tool_registry(), agent_role="market_audience_research")

    assert {"search_public_web", "read_project_context", "query_current_pois", "list_scope_datasets"}.issubset(candidates)


def test_formal_specialist_tool_candidates_are_role_bounded():
    registry = get_tool_registry()

    assert "search_public_web" not in tool_allocation_candidates(registry, agent_role="spatial_structure")
    assert "list_scope_datasets" not in tool_allocation_candidates(registry, agent_role="positioning_product")
    assert "query_current_pois" not in tool_allocation_candidates(registry, agent_role="operations_phasing")


def test_dependency_artifact_is_published_before_parent_loop(monkeypatch):
    calls = []

    async def fake_loop(**kwargs):
        calls.append(kwargs["system_instruction"])
        return ToolLoopResult(
            status="completed",
            assistant_summary="八类资源已完成本轮调研，保留待验证缺口。",
            artifacts={"research_report": "current-turn"},
            used_tools=["query_history_project_dataset"],
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()
    events = []

    async def emit_thinking(item, item_id):
        events.append((item_id, item["state"]))

    error = asyncio.run(
        _run_required_skill_dependencies(
            payload=_payload("这个地方有历史建筑和非遗，先做文旅资源普查"),
            effective_profile=EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert error == ""
    assert calls and "cultural-tourism-theme-research" in calls[0]
    assert memory.artifacts["cultural_tourism_research"]["status"] == "completed"
    assert memory.artifacts["cultural_tourism_research"]["summary"].startswith("八类资源")
    assert events[-1] == ("dependency-complete:cultural-tourism-theme-research:preflight", "completed")


def test_market_discovery_artifact_is_published_before_parent_loop(monkeypatch):
    calls = []

    async def fake_loop(**kwargs):
        calls.append(kwargs)
        return ToolLoopResult(
            status="completed",
            assistant_summary="市场发现已完成",
            artifacts={"market_report": "current-turn", "public_web_sources": _public_web_sources()},
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_required_skill_dependencies(
            payload=_confirmed_payload("问题地图已确认，请继续正式报告"),
            effective_profile=EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert error == ""
    assert "market_discovery" in calls[0]["messages"][-1].content
    assert memory.artifacts["market_audience_research"]["stage"] == "market_discovery"
    assert memory.artifacts["market_audience_research"]["recheck_status"] == "pending_parent_drafts"


def test_market_discovery_rejects_partial_public_web_category_coverage(monkeypatch):
    async def fake_loop(**_kwargs):
        return ToolLoopResult(
            status="completed",
            assistant_summary="只完成了部分市场检索",
            artifacts={"public_web_sources": _public_web_sources(categories=["统计"])},
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_required_skill_dependencies(
            payload=_confirmed_payload("问题地图已确认，请继续正式报告"),
            effective_profile=EffectiveExecutionProfile(skill_id="spatial-business-analyst"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert "类别覆盖不完整" in error
    assert "market_audience_research" not in memory.artifacts


def test_formal_specialists_run_in_order_with_independent_tool_allocations(monkeypatch):
    loop_roles = []
    allocated_roles = []

    async def fake_allocate(**kwargs):
        allocated_roles.append(kwargs["agent_role"])
        return ToolAllocationDecision(
            agent_role=kwargs["agent_role"],
            allowed_tools=[item["name"] for item in kwargs["candidate_tools"][:1]],
            rationale="测试授权",
        )

    async def fake_loop(**kwargs):
        role = kwargs["initial_artifacts"]["formal_specialist_role"]
        loop_roles.append(role)
        if role == "positioning_product":
            assert "spatial_structure" in kwargs["initial_artifacts"]["formal_specialist_upstream"]
        artifacts = {"draft": role}
        if role == "positioning_product":
            artifacts["product_inventory"] = _product_inventory("PP-01")
        return ToolLoopResult(status="completed", assistant_summary=f"{role} 完成", artifacts=artifacts)

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_tool_allocator_with_llm", fake_allocate)
    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()
    memory.artifacts["market_audience_research"] = _market_artifact()

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_formal_specialist_roles(
            payload=_payload("问题地图已确认，继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    expected = ["spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"]
    assert error == ""
    assert loop_roles == expected
    assert allocated_roles == expected
    assert all(memory.artifacts[role]["current_version"] == 1 for role in expected)


def test_formal_specialists_require_completed_market_discovery_and_allocator(monkeypatch):
    import modules.agent.runtime as runtime

    memory = create_working_memory()
    memory.artifacts["market_audience_research"] = {**_market_artifact(), "status": "running"}

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_formal_specialist_roles(
            payload=_payload("继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )
    assert "尚未完成" in error

    memory.artifacts["market_audience_research"] = _market_artifact()

    async def allocator_failure(**_kwargs):
        raise RuntimeError("allocator unavailable")

    monkeypatch.setattr(runtime, "run_tool_allocator_with_llm", allocator_failure)
    error = asyncio.run(
        _run_formal_specialist_roles(
            payload=_payload("继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )
    assert "工具授权失败" in error
    assert "spatial_structure" not in memory.artifacts


def test_market_product_recheck_rejects_generic_main_summary_drafts():
    memory = create_working_memory()
    memory.artifacts["market_audience_research"] = _market_artifact()

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_market_product_recheck(
            payload=_payload("问题地图已确认，继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            parent_drafts={"status": "ready_for_product_recheck", "summary": "main analysis summary", "artifacts": {}},
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert "缺少本轮专项草案" in error


def test_market_product_recheck_runs_first_check_one_revision_and_final_check(monkeypatch):
    calls = []

    async def fake_loop(**kwargs):
        calls.append(kwargs)
        prompt = kwargs["messages"][-1].content
        if kwargs["initial_artifacts"].get("formal_specialist_role"):
            role = kwargs["initial_artifacts"]["formal_specialist_role"]
            summary = f"{role} 已完成定向返写"
            artifacts = {"revised_draft": role}
            if role == "positioning_product":
                artifacts["product_inventory"] = _product_inventory("PP-01", "PP-02")
        elif kwargs["initial_artifacts"].get("product_recheck_number") == 1:
            summary = "第一次校核只要求定位角色缩减产品"
            artifacts = {
                "first_product_recheck": {
                    "status": "first",
                    "products": [
                        {
                            "product_id": "PP-01",
                            "verdict": "缩减",
                            "rationale": "定位边界过宽",
                            "revision_required": True,
                            "owner_roles": ["positioning_product"],
                        },
                        {
                            "product_id": "PP-02",
                            "verdict": "成立",
                            "rationale": "当前证据成立",
                            "revision_required": False,
                            "owner_roles": [],
                        },
                    ],
                }
            }
        else:
            summary = (
                '{"status":"final","products":['
                '{"product_id":"PP-01","verdict":"缩减","rationale":"按当前证据缩减","conditions":[]},'
                '{"product_id":"PP-02","verdict":"成立","rationale":"维持成立","conditions":[]}'
                "]}"
            )
            artifacts = {}
        return ToolLoopResult(
            status="completed",
            assistant_summary=summary,
            artifacts=artifacts,
            used_tools=["search_public_web", "query_current_pois"],
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()
    memory.artifacts["market_audience_research"] = {**_market_artifact(), "revision_budget": 1}
    for role in ["spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"]:
        artifacts = {"draft": role}
        if role == "positioning_product":
            artifacts["product_inventory"] = _product_inventory("PP-01", "PP-02")
        memory.artifacts[role] = {
            "role": role,
            "status": "completed",
            "current_version": 1,
            "summary": "初稿",
            "artifacts": artifacts,
            "versions": [{"version": 1, "used_tools": []}],
        }

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_market_product_recheck(
            payload=_payload("问题地图已确认，继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            parent_drafts={
                "status": "ready_for_product_recheck",
                "artifacts": {
                    role: memory.artifacts[role]
                    for role in ["spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"]
                },
            },
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert error == ""
    assert len(calls) == 3
    assert "product_recheck" in calls[0]["messages"][-1].content
    assert set(calls[0]["initial_artifacts"]["parent_drafts"]["artifacts"]) == {
        "spatial_structure",
        "positioning_product",
        "spatial_function_programming",
        "operations_phasing",
    }
    assert [call["initial_artifacts"].get("formal_specialist_role") for call in calls[1:2]] == ["positioning_product"]
    assert "第二次且最终校核" in calls[2]["messages"][-1].content
    recheck = memory.artifacts["market_audience_research"]["product_recheck"]
    assert recheck["revision_budget"] == 0
    assert recheck["recheck_status"] == "second_check_completed"
    assert [item["number"] for item in recheck["checks"]] == [1, 2]
    assert recheck["revision"]["status"] == "revised_for_final_product_recheck"
    assert recheck["revision_roles"] == ["positioning_product"]
    assert {item["product_id"] for item in recheck["final_decision"]["products"]} == {"PP-01", "PP-02"}
    assert recheck["final_decision"]["products"][0]["verdict"] == "缩减"
    assert {"search_public_web", "query_current_pois"}.issubset(recheck["used_tools"])
    assert len(memory.artifacts["tool_allocations"]["market_audience_research"]) == 2


def test_market_product_recheck_rejects_non_terminal_second_result(monkeypatch):
    async def fake_loop(**kwargs):
        if kwargs["initial_artifacts"].get("formal_specialist_role"):
            return ToolLoopResult(status="completed", artifacts={"revised_draft": "ready"})
        if kwargs["initial_artifacts"].get("product_recheck_number") == 1:
            return ToolLoopResult(status="completed", artifacts={
                "first_product_recheck": {
                    "status": "first",
                    "products": [{
                        "product_id": "PP-01",
                        "verdict": "延后",
                        "rationale": "证据不足",
                        "revision_required": False,
                        "owner_roles": [],
                    }],
                }
            })
        return ToolLoopResult(
            status="completed",
            assistant_summary="仍需 third rewrite",
            artifacts={
                "final_product_recheck": {
                    "status": "final",
                    "products": [
                        {"product_id": "PP-01", "verdict": "延后", "rationale": "证据不足", "conditions": []}
                    ],
                }
            },
        )

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()
    memory.artifacts["market_audience_research"] = _market_artifact()
    for role in ["spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"]:
        artifacts = {"product_inventory": _product_inventory("PP-01")} if role == "positioning_product" else {}
        memory.artifacts[role] = {"role": role, "status": "completed", "artifacts": artifacts, "versions": []}

    async def emit_thinking(*_args):
        return None

    error = asyncio.run(
        _run_market_product_recheck(
            payload=_payload("问题地图已确认，继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            parent_drafts={
                "status": "ready_for_product_recheck",
                "artifacts": {
                    role: memory.artifacts[role]
                    for role in ["spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"]
                },
            },
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert "禁止的返写信号" in error
    assert "product_recheck" not in memory.artifacts["market_audience_research"]


@pytest.mark.parametrize(
    ("first_ids", "final_ids", "expected_error"),
    [
        (("PP-01",), ("PP-01",), "必须覆盖定位草案的完整产品清单"),
        (("PP-01", "PP-02"), ("PP-01",), "必须覆盖首轮同一组产品"),
    ],
)
def test_market_product_recheck_rejects_silently_dropped_product(
    monkeypatch, first_ids, final_ids, expected_error
):
    async def fake_loop(**kwargs):
        if kwargs["initial_artifacts"].get("product_recheck_number") == 1:
            return ToolLoopResult(status="completed", artifacts={
                "first_product_recheck": {
                    "status": "first",
                    "products": [
                        {
                            "product_id": product_id,
                            "verdict": "成立",
                            "rationale": "首轮保留",
                            "revision_required": False,
                            "owner_roles": [],
                        }
                        for product_id in first_ids
                    ],
                }
            })
        return ToolLoopResult(status="completed", artifacts={
            "final_product_recheck": {
                "status": "final",
                "products": [
                    {"product_id": product_id, "verdict": "成立", "rationale": "成立", "conditions": []}
                    for product_id in final_ids
                ],
            }
        })

    import modules.agent.runtime as runtime

    monkeypatch.setattr(runtime, "run_langgraph_react_loop", fake_loop)
    memory = create_working_memory()
    memory.artifacts["market_audience_research"] = _market_artifact()
    for role in ["spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"]:
        artifacts = {"product_inventory": _product_inventory("PP-01", "PP-02")} if role == "positioning_product" else {}
        memory.artifacts[role] = {"role": role, "status": "completed", "artifacts": artifacts, "versions": []}

    async def emit_thinking(*_args):
        return None

    drafts = {role: memory.artifacts[role] for role in (
        "spatial_structure", "positioning_product", "spatial_function_programming", "operations_phasing"
    )}
    error = asyncio.run(
        _run_market_product_recheck(
            payload=_payload("继续正式报告"),
            context=build_context_bundle(_payload("x").analysis_snapshot),
            memory=memory,
            parent_drafts={"status": "ready_for_product_recheck", "artifacts": drafts},
            llm_runtime=None,
            emit_thinking=emit_thinking,
        )
    )

    assert expected_error in error
    assert "PP-02" in error
