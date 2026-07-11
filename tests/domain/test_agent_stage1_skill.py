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
                "source_artifact_id": "document-node-12",
                "source_date": "2026-07-01",
                "source_locator": "document:project-doc#page=12&node=document-node-12",
                "method": "document_read",
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

    monkeypatch.setattr(
        stage1, "get_llm_provider_client", lambda *, runtime: FakeClient()
    )
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
    assert (
        response.output.panel_payloads["stage1_evidence_verification"]["status"]
        == "passed"
    )
    assert response.output.panel_payloads["claim_evidence"][0]["status"] == "verified"
    assert response.output.panel_payloads["sources_used"] == ["项目资料 p.12"]
    assert response.effective_execution_profile == profile


def test_stage1_stream_exposes_automatic_road_verification(monkeypatch):
    runtime, profile = runtime_and_profile()
    payload = ready_payload()
    payload.analysis_snapshot.road = {
        "summary": {
            "avg_intelligibility": 0.22,
            "avg_intelligibility_r2": 0.05,
            "node_count": 120,
        },
        "diagnostics": {"regression": {"r": 0.22, "r2": 0.05, "n": 120}},
    }
    responses = [
        {
            "evidence_ledger": [
                {
                    "id": "road-1",
                    "claim": "可理解度0.22（R²=0.05）属于极低水平",
                    "evidence_type": "G",
                    "status": "verified",
                    "source_ref": "analysis_snapshot.road",
                    "source_artifact_id": "road-analysis-1",
                    "scope": "项目周边路网",
                    "method": "space_syntax",
                    "metric": "network_intelligibility",
                    "value": 0.22,
                    "comparison_baseline": "",
                    "confidence": "high",
                    "limitation": "",
                    "next_action": "",
                    "executor": "agent",
                }
            ]
        },
        {"workpacks": []},
        {"options": [], "recommended_option_id": ""},
        {},
    ]
    calls = []
    events = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs["reasoning_id"])
            return responses[len(calls) - 1]

    async def emit(event, data):
        events.append((event, data))

    monkeypatch.setattr(
        stage1, "get_llm_provider_client", lambda *, runtime: FakeClient()
    )
    response = asyncio.run(
        execute(payload, runtime=runtime, profile=profile, emit=emit)
    )

    verification = response.output.panel_payloads["stage1_evidence_verification"]
    assert (
        verification["automated_checks"][0]["tool_id"] == "verify_road_analysis_claim"
    )
    phase = next(
        data
        for event, data in events
        if event == "thinking" and data["id"] == "stage1-evidence-verification"
    )
    assert "自动执行 1 项确定性核验" in phase["detail"]
    assert calls == [
        "stage1-evidence-model",
        "stage1-workpacks-model",
        "stage1-options-model",
        "stage1-spatial-matrix-model",
    ]


def test_stage1_exposes_context_conflicts_in_quality_panel(monkeypatch):
    runtime, profile = runtime_and_profile()
    payload = ready_payload()
    payload.analysis_snapshot.context["evidence_conflicts"] = [
        "项目摘要与旧版资料的居民户数不一致"
    ]
    responses = [
        valid_evidence(),
        valid_workpacks(),
        valid_strategy(),
        valid_matrix(),
        {"answer": "# 条件式建议", "sources": ["项目资料 p.12"]},
    ]
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

    monkeypatch.setattr(
        stage1, "get_llm_provider_client", lambda *, runtime: FakeClient()
    )

    response = asyncio.run(execute(payload, runtime=runtime, profile=profile))

    assert response.status == "answered"
    conflict = response.output.panel_payloads["stage1_conflict_register"][0]
    assert conflict["unresolved"] is True
    assert "居民户数不一致" in conflict["label"]
    audit = response.output.panel_payloads["stage1_quality_audit"]
    assert audit["status"] == "passed"
    data_quality = response.output.panel_payloads["stage1_data_quality"]
    assert data_quality["status"] == "passed"
    assert data_quality["coverage"]["source_locator"] == 1
    assert any(
        item["code"] == "unresolved_evidence_conflict" for item in audit["issues"]
    )
    assert calls[0]["user_payload"]["known_conflicts"][0]["unresolved"] is True
    assert "source_date" in calls[0]["system_prompt"]
    assert "sample_size" in calls[0]["system_prompt"]
    assert "data_quality" in calls[-1]["system_prompt"]
    assert (
        calls[2]["user_payload"]["conflict_register"][0]["label"] == conflict["label"]
    )


def test_stage1_conflict_register_reads_selected_project_documents(monkeypatch):
    captured = []

    class Conflict:
        def model_dump(self, *, mode):
            assert mode == "json"
            return {
                "metric_key": "households",
                "label": "居民户数",
                "values": ["102户", "120户"],
                "evidence_ids": ["node-a", "node-b"],
                "preferred_value": "",
                "preferred_evidence_id": "",
                "unresolved": True,
                "explanation": "同级项目摘要冲突。",
            }

    class Dossier:
        conflicts = [Conflict()]

    monkeypatch.setattr(
        stage1,
        "build_project_evidence_dossier",
        lambda sources, *, question: captured.append((sources, question)) or Dossier(),
    )

    register = stage1._conflict_register(
        [{"source_id": "document:brief", "title": "项目摘要"}],
        question="居民如何安置",
        context_conflicts=[],
    )

    assert captured[0][1] == "居民如何安置"
    assert register[0]["metric_key"] == "households"
    assert register[0]["evidence_ids"] == ["node-a", "node-b"]
