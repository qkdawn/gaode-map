import asyncio

from modules.agent.providers.client import LLMRuntimeConfig
from modules.agent.schemas import AgentMessage, AgentTurnRequest, EffectiveExecutionProfile
import modules.agent.skills.urban_strategy_stage1 as stage1
from modules.agent.skills.urban_strategy_stage1 import evaluate_readiness, execute


def test_stage1_reports_structured_readiness_gaps_without_calling_model():
    payload = AgentTurnRequest(messages=[AgentMessage(role="user", content="生成报告")])
    runtime = LLMRuntimeConfig(
        provider="openai_compatible", base_url="https://example.test", api_key="unused", model="unused",
    )
    profile = EffectiveExecutionProfile(
        model_profile_id="personal-test", model_display_name="Test", model="unused",
        skill_id="urban-strategy-stage1", skill_display_name="城市区域策划第一阶段",
    )
    readiness = evaluate_readiness(payload)
    response = asyncio.run(execute(payload, runtime=runtime, profile=profile))
    assert readiness["ready"] is False
    assert "可识别的项目空间范围" in readiness["missing"]
    assert response.status == "requires_clarification"
    assert response.output.panel_payloads["stage1_readiness"]["ready"] is False
    assert response.effective_execution_profile.model_profile_id == "personal-test"


def test_stage1_ready_path_uses_one_runtime_for_all_model_phases(monkeypatch):
    runtime = LLMRuntimeConfig(
        provider="openai_compatible", base_url="https://example.test", api_key="secret", model="model-x",
    )
    profile = EffectiveExecutionProfile(
        model_profile_id="personal-test", model_display_name="Test", provider="openai_compatible", model="model-x",
        skill_id="urban-strategy-stage1", skill_display_name="城市区域策划第一阶段",
    )
    payload = AgentTurnRequest(
        messages=[AgentMessage(role="user", content="生成完整项目策划报告")],
        analysis_snapshot={
            "scope": {"polygon": [[112.0, 28.0], [112.1, 28.0], [112.0, 28.1]]},
            "context": {"project_summary": "长沙县政府原址城市更新项目，需要判断定位、运营和分期策略。"},
            "frontend_analysis": {"poi_total": 2635},
        },
    )
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs["reasoning_id"])
            if len(calls) == 1:
                return {"workpacks": [{"type": "spatial", "findings": ["院落空间"]}]}
            if len(calls) == 2:
                return {"options": [{"name": "文化体验目的地"}], "recommended_option": "文化体验目的地"}
            return {
                "answer": "# 推荐定位\n文化体验目的地",
                "claims": [{"claim": "采用小而精定位", "evidence": ["院落空间"], "status": "supported"}],
                "sources": ["analysis_snapshot.frontend_analysis"],
            }

    captured = []
    monkeypatch.setattr(stage1, "get_llm_provider_client", lambda *, runtime: captured.append(runtime) or FakeClient())
    response = asyncio.run(execute(payload, runtime=runtime, profile=profile))

    assert captured == [runtime]
    assert calls == ["stage1-workpacks-model", "stage1-options-model", "stage1-report-model"]
    assert response.status == "answered"
    assert response.output.panel_payloads["claim_evidence"][0]["status"] == "supported"
    assert response.output.panel_payloads["sources_used"] == ["analysis_snapshot.frontend_analysis"]
    assert response.effective_execution_profile == profile
