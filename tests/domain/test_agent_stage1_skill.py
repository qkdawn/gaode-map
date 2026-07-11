import asyncio

import modules.agent.skills.urban_strategy_stage1 as stage1
from modules.agent.providers.client import LLMRuntimeConfig
from modules.agent.schemas import (
    AgentMessage,
    AgentTurnRequest,
    EffectiveExecutionProfile,
)
from modules.agent.skills.urban_strategy_stage1 import evaluate_readiness, execute


def runtime_and_profile():
    runtime = LLMRuntimeConfig(
        provider="openai_compatible",
        base_url="https://example.test",
        api_key="secret",
        model="model-x",
    )
    profile = EffectiveExecutionProfile(
        model_profile_id="personal-test",
        model_display_name="Test",
        provider="openai_compatible",
        model="model-x",
        skill_id="urban-strategy-stage1",
        skill_display_name="城市区域策划第一阶段",
    )
    return runtime, profile


def ready_payload():
    return AgentTurnRequest(
        messages=[AgentMessage(role="user", content="生成完整项目策划报告")],
        analysis_snapshot={
            "scope": {"polygon": [[112.0, 28.0], [112.1, 28.0], [112.0, 28.1]]},
            "context": {
                "project_summary": "长沙县政府原址城市更新项目，需要判断定位、运营和分期策略。"
            },
            "frontend_analysis": {"poi_total": 2635},
        },
        selected_sources_context={
            "sources": [{"source_id": "project-doc", "title": "项目资料"}]
        },
    )


def valid_evidence():
    return {
        "evidence_ledger": [
            {
                "id": "evidence-1",
                "claim": "项目包含历史建筑院落",
                "evidence_type": "F",
                "status": "verified",
                "source_ref": "项目资料 p.12",
                "scope": "项目红线",
                "comparison_baseline": "",
                "confidence": "high",
                "limitation": "仍需逐栋勘察",
                "next_action": "结构鉴定",
                "executor": "fieldwork",
            }
        ]
    }


def valid_workpacks():
    return {
        "workpacks": [
            {"type": "spatial", "evidence_refs": ["evidence-1"]},
            {"type": "audience", "evidence_refs": ["evidence-1"]},
            {"type": "culture_tourism", "evidence_refs": ["evidence-1"]},
            {"type": "renewal_operations", "evidence_refs": ["evidence-1"]},
        ]
    }


def valid_strategy():
    return {
        "recommended_option_id": "option-a",
        "options": [
            {
                "id": option_id,
                "evidence_refs": ["evidence-1"],
                "counter_evidence": ["夜间开放边界待核实"],
                "invalidation_conditions": ["居民协商无法达成"],
            }
            for option_id in ("option-a", "option-b", "option-c")
        ],
    }


def valid_matrix():
    return {
        "matrix_version": "1.0",
        "positioning_option_id": "option-a",
        "spatial_hierarchy": [
            {"id": "system-1", "level": "system"},
            {"id": "cluster-1", "level": "cluster"},
            {"id": "unit-1", "level": "unit"},
        ],
        "space_decisions": [
            {
                "space_id": "unit-1",
                "candidate_functions": [{"id": "culture"}, {"id": "retail"}],
                "preferred_function": {"id": "culture"},
                "excluded_functions": [{"id": "heavy-food"}],
                "audience_scenarios": ["社区周末活动"],
                "preconditions": ["完成消防评估"],
                "evidence_refs": ["evidence-1"],
                "recommendation_status": "conditional",
                "confidence": "medium",
            }
        ],
        "portfolio_checks": ["公共服务与经营功能平衡"],
    }


def test_stage1_reports_structured_readiness_gaps_without_calling_model():
    payload = AgentTurnRequest(messages=[AgentMessage(role="user", content="生成报告")])
    runtime, profile = runtime_and_profile()

    readiness = evaluate_readiness(payload)
    response = asyncio.run(execute(payload, runtime=runtime, profile=profile))

    assert readiness["ready"] is False
    assert "可识别的项目空间范围" in readiness["missing"]
    assert {item["target"] for item in readiness["actions"]} == {
        "scope-selection",
        "project-brief",
        "analysis-sources",
    }
    assert response.status == "requires_clarification"
    assert response.output.panel_payloads["stage1_readiness"]["ready"] is False
    assert response.effective_execution_profile.model_profile_id == "personal-test"


def test_stage1_evidence_gate_stops_before_professional_models(monkeypatch):
    runtime, profile = runtime_and_profile()
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs["reasoning_id"])
            return {"evidence_ledger": []}

    monkeypatch.setattr(stage1, "get_llm_provider_client", lambda *, runtime: FakeClient())
    response = asyncio.run(execute(ready_payload(), runtime=runtime, profile=profile))

    assert response.status == "requires_clarification"
    assert calls == ["stage1-evidence-model"]
    verification = response.output.panel_payloads["stage1_evidence_verification"]
    assert verification["status"] == "failed"
    assert verification["report_allowed"] is False
    assert "后续专业模型未被调用" in response.diagnostics.research_notes[0]


def test_stage1_quality_failure_stops_before_report_model(monkeypatch):
    runtime, profile = runtime_and_profile()
    responses = [
        valid_evidence(),
        valid_workpacks(),
        {"options": [{"id": "only-one"}], "recommended_option_id": "only-one"},
        valid_matrix(),
    ]
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs["reasoning_id"])
            return responses[len(calls) - 1]

    monkeypatch.setattr(
        stage1, "get_llm_provider_client", lambda *, runtime: FakeClient()
    )
    response = asyncio.run(execute(ready_payload(), runtime=runtime, profile=profile))

    assert response.status == "requires_clarification"
    assert calls == [
        "stage1-evidence-model",
        "stage1-workpacks-model",
        "stage1-options-model",
        "stage1-spatial-matrix-model",
    ]
    assert response.output.panel_payloads["stage1_quality_audit"]["status"] == "failed"
    assert response.output.panel_payloads["stage1_repair_tasks"]
    assert "最终报告模型未被调用" in response.diagnostics.research_notes[0]


def test_stage1_ready_path_uses_one_runtime_for_all_model_phases(monkeypatch):
    runtime, profile = runtime_and_profile()
    responses = [
        valid_evidence(),
        valid_workpacks(),
        valid_strategy(),
        valid_matrix(),
        {
            "answer": "# 推荐定位\n文化体验目的地",
            "sources": ["项目资料 p.12"],
        },
    ]
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs["reasoning_id"])
            return responses[len(calls) - 1]

    captured = []
    monkeypatch.setattr(
        stage1,
        "get_llm_provider_client",
        lambda *, runtime: captured.append(runtime) or FakeClient(),
    )
    response = asyncio.run(execute(ready_payload(), runtime=runtime, profile=profile))

    assert captured == [runtime]
    assert calls == [
        "stage1-evidence-model",
        "stage1-workpacks-model",
        "stage1-options-model",
        "stage1-spatial-matrix-model",
        "stage1-report-model",
    ]
    assert response.status == "answered"
    assert response.output.panel_payloads["stage1_quality_audit"]["status"] == "passed"
    assert response.output.panel_payloads["stage1_evidence_verification"]["status"] == "passed"
    assert response.output.panel_payloads["claim_evidence"][0]["status"] == "verified"
    assert response.output.panel_payloads["sources_used"] == ["项目资料 p.12"]
    assert response.effective_execution_profile == profile
