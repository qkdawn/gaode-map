import asyncio
from copy import deepcopy

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
            "sources": [
                {
                    "source_id": "project-doc",
                    "title": "项目资料",
                    "source_kind": "analysis_source",
                    "source_date": "2026-07-01",
                }
            ]
        },
    )


def test_stage1_executor_rejects_service_capability_target():
    runtime, profile = runtime_and_profile()
    payload = ready_payload().model_copy(
        update={"target_capability_id": "ppt-planning"}
    )

    try:
        asyncio.run(execute(payload, runtime=runtime, profile=profile))
    except ValueError as exc:
        assert str(exc) == "capability_executor_mismatch"
    else:
        raise AssertionError(
            "service capability must not execute through the Stage 1 skill"
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


def hard_constraint_ids():
    return [
        "ownership",
        "fire_safety",
        "structural_condition",
        "drainage_sewage",
        "parking_loading",
        "accessibility",
        "resident_noise",
    ]


def valid_hard_constraint_screening():
    return {
        "assessments": [
            {
                "constraint_id": constraint_id,
                "state": "unknown",
                "decision_effect": "condition",
                "scope": "项目范围",
                "finding": f"{constraint_id} 尚待专项核验",
                "evidence_refs": [],
                "affected_space_ids": ["unit-1"],
                "verification_action": f"完成 {constraint_id} 专项核验",
                "executor": "fieldwork",
            }
            for constraint_id in hard_constraint_ids()
        ]
    }


def valid_workpacks():
    return {
        "workpacks": [
            {"type": "spatial", "evidence_refs": ["evidence-1"]},
            {"type": "audience", "evidence_refs": ["evidence-1"]},
            {"type": "culture_tourism", "evidence_refs": ["evidence-1"]},
            {"type": "renewal_operations", "evidence_refs": ["evidence-1"]},
        ],
        "hard_constraint_screening": valid_hard_constraint_screening(),
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
                "recommendation_status": "conditional",
                "hard_constraint_refs": hard_constraint_ids(),
                "preconditions": ["完成硬约束核验"],
                "validation_actions": ["执行硬约束筛选任务"],
            }
            for option_id in ("option-a", "option-b", "option-c")
        ],
    }


def valid_movement_routes(space_id="unit-1"):
    labels = {"visitor": "游客主游线", "resident": "居民日常流线", "service": "后勤流线", "fire": "消防应急流线"}
    reasons = {"visitor": "游客路径待测绘", "resident": "居民路径待访谈", "service": "后勤路径待运营核验", "fire": "消防路径待专项核验"}
    return [
        {
            "route_id": f"route-{movement_type}",
            "movement_type": movement_type,
            "title": labels[movement_type],
            "role": "连接入口与礼堂",
            "entry_or_origin": "南侧入口",
            "destinations": ["原县政府礼堂"],
            "affected_space_ids": [space_id],
            "operating_windows": ["日常开放时段"],
            "constraints": ["路径宽度与无障碍条件待核验"],
            "conflicts": [] if movement_type != "service" else ["后勤与游客到达可能交叉"],
            "evidence_refs": ["evidence-1"],
            "assumptions": [],
            "validation_actions": ["现场踏勘并复核流线"],
            "status": "proposed",
            "map_binding": {
                "status": "unavailable",
                "spatial_object_id": "",
                "reason": reasons[movement_type],
            },
        }
        for movement_type in ("visitor", "resident", "service", "fire")
    ]


def valid_matrix():
    return {
        "matrix_version": "2.0",
        "positioning_option_id": "option-a",
        "spatial_hierarchy": [
            {
                "id": "system-1",
                "title": "一院",
                "level": "system",
                "parent_id": "",
                "role": "公共文化与核心体验系统",
                "member_space_ids": [],
            },
            {
                "id": "cluster-1",
                "title": "公共文化组团",
                "level": "cluster",
                "parent_id": "system-1",
                "role": "形成可独立运营的公共文化体验",
                "member_space_ids": [],
            },
            {
                "id": "unit-1",
                "title": "礼堂单元",
                "level": "unit",
                "parent_id": "cluster-1",
                "role": "承载社区文化活动",
                "member_space_ids": ["unit-1"],
            },
        ],
        "space_decisions": [
            {
                "space_id": "unit-1",
                "hierarchy_id": "unit-1",
                "space_name": "原县政府礼堂",
                "future_role": "社区文化锚点",
                "core_audiences": ["社区家庭", "青年社群"],
                "movement_role": "主游线目的地",
                "value_role": "公共服务与活动引流",
                "current_state_category": "vacant",
                "current_state": {"summary": "闲置礼堂"},
                "change_logic": {"reason": "补足社区文化活动空间"},
                "candidate_functions": [
                    {"id": "culture", "name": "文化活动"},
                    {"id": "retail", "name": "社区零售"},
                ],
                "preferred_function": {"id": "culture", "name": "文化活动"},
                "compatible_functions": [{"id": "exhibition", "name": "社区展览"}],
                "excluded_functions": [{"id": "heavy-food", "name": "重餐饮"}],
                "audience_scenarios": ["社区周末活动"],
                "access_and_movement": {"visitor_entry": "南侧主入口"},
                "operation_strategy": {"operator": "社区文化运营主体"},
                "renovation_and_delivery": {"scope": "轻量改造"},
                "implementation_phase": "phase_1",
                "risk_level": "high",
                "risk_summary": "消防和结构条件尚待核验",
                "preconditions": ["完成消防评估"],
                "validation_actions": ["开展消防与结构核验"],
                "evidence_refs": ["evidence-1"],
                "hard_constraint_refs": hard_constraint_ids(),
                "assumptions": [],
                "recommendation_status": "conditional",
                "confidence": "medium",
                "map_binding": {
                    "status": "unavailable",
                    "spatial_object_id": "",
                    "reason": "样例未提供权威建筑几何",
                },
            }
        ],
        "movement_routes": valid_movement_routes(),
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
    run = response.output.panel_payloads["capability_run"]
    assert run["status"] == "waiting_for_user"
    assert run["current_stage"] == "readiness"
    assert run["configuration_snapshot"]["question"] == "生成报告"
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
    run = response.output.panel_payloads["capability_run"]
    assert run["status"] == "waiting_for_user"
    assert run["current_stage"] == "evidence-verification"
    assert [item["artifact_id"] for item in run["output_artifact_refs"]] == [
        "stage1-project-brief",
        "stage1-source-readiness",
        "stage1-evidence-ledger",
        "stage1-conflict-register",
    ]
    assert "后续专业模型未被调用" in response.diagnostics.research_notes[0]


def test_stage1_invalid_spatial_matrix_fails_with_contract_diagnostics(monkeypatch):
    runtime, profile = runtime_and_profile()
    responses = [
        valid_evidence(),
        valid_workpacks(),
        valid_strategy(),
        {"matrix_version": "2.0"},
        {"matrix_version": "2.0"},
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

    assert response.status == "failed"
    assert calls[-2:] == [
        "stage1-spatial-matrix-model",
        "stage1-spatial-matrix-contract-repair-model",
    ]
    repair = response.output.panel_payloads["stage1_spatial_matrix_repair"]
    assert repair["status"] == "failed"
    assert repair["attempts"][0]["initial_diagnostics"]
    assert repair["attempts"][0]["final_diagnostics"]
    diagnostic = response.output.panel_payloads["stage1_spatial_matrix_diagnostic"]
    assert diagnostic["status"] == "failed"
    assert any("spatial_hierarchy" in item for item in diagnostic["diagnostics"])
    run = response.output.panel_payloads["capability_run"]
    assert run["status"] == "failed"
    assert run["current_stage"] == "spatial-decision-matrix"
    assert run["stage_records"][-1]["status"] == "failed"


def test_stage1_repairs_spatial_matrix_contract_once_before_audit(monkeypatch):
    runtime, profile = runtime_and_profile()
    responses = [
        valid_evidence(),
        valid_workpacks(),
        valid_strategy(),
        {"matrix_version": "2.0"},
        valid_matrix(),
        {"answer": "# 契约修复后报告", "sources": ["项目资料 p.12"]},
    ]
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

    monkeypatch.setattr(
        stage1, "get_llm_provider_client", lambda *, runtime: FakeClient()
    )

    response = asyncio.run(execute(ready_payload(), runtime=runtime, profile=profile))

    assert response.status == "answered"
    assert [item["reasoning_id"] for item in calls][-3:] == [
        "stage1-spatial-matrix-model",
        "stage1-spatial-matrix-contract-repair-model",
        "stage1-report-model",
    ]
    repair_call = calls[-2]
    assert repair_call["user_payload"]["contract_diagnostics"]
    assert repair_call["user_payload"]["allowed_evidence_ids"] == ["evidence-1"]
    repair = response.output.panel_payloads["stage1_spatial_matrix_repair"]
    assert repair["status"] == "passed"
    assert repair["attempts"][0]["initial_diagnostics"]
    assert repair["attempts"][0]["final_diagnostics"] == []
    run = response.output.panel_payloads["capability_run"]
    assert any(
        item["stage_id"] == "spatial-decision-matrix-repair"
        for item in run["stage_records"]
    )
    artifacts = {
        item["artifact_id"]: item for item in run["output_artifact_refs"]
    }
    assert artifacts["stage1-spatial-matrix-repair"]["filename"] == (
        "spatial_matrix_repair.json"
    )
    assert "stage1-spatial-matrix-repair" in artifacts["stage1-decision-matrix"][
        "source_artifact_refs"
    ]


def test_stage1_quality_failure_stops_before_report_model(monkeypatch):
    runtime, profile = runtime_and_profile()
    responses = [
        valid_evidence(),
        valid_workpacks(),
        {"options": [{"id": "only-one"}], "recommended_option_id": "only-one"},
        valid_matrix(),
        {},
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
        "stage1-quality-repair-model",
    ]
    assert response.output.panel_payloads["stage1_quality_audit"]["status"] == "failed"
    assert response.output.panel_payloads["stage1_repair_tasks"]
    assert response.output.panel_payloads["stage1_repair_plan"]["status"] == "automatic"
    attempts = response.output.panel_payloads["stage1_repair_attempts"]
    assert attempts[0]["status"] == "failed"
    assert any("workpacks" in item for item in attempts[0]["diagnostics"])
    run = response.output.panel_payloads["capability_run"]
    assert run["status"] == "waiting_for_user"
    assert run["current_stage"] == "quality-audit"
    assert {"stage1-decision-matrix", "stage1-quality-audit"} <= {
        item["artifact_id"] for item in run["output_artifact_refs"]
    }
    assert "最终报告模型未被调用" in response.diagnostics.research_notes[0]


def test_stage1_automatically_repairs_model_output_before_report(monkeypatch):
    runtime, profile = runtime_and_profile()
    repaired_workpacks = valid_workpacks()
    responses = [
        valid_evidence(),
        repaired_workpacks,
        {"options": [{"id": "only-one"}], "recommended_option_id": "only-one"},
        valid_matrix(),
        {
            "workpacks": repaired_workpacks["workpacks"],
            "hard_constraint_screening": repaired_workpacks["hard_constraint_screening"],
            "strategy": valid_strategy(),
            "spatial_matrix": valid_matrix(),
        },
        {"answer": "# 修复后报告", "sources": ["项目资料 p.12"]},
    ]
    calls = []

    class FakeClient:
        async def chat_json(self, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

    monkeypatch.setattr(
        stage1, "get_llm_provider_client", lambda *, runtime: FakeClient()
    )

    response = asyncio.run(execute(ready_payload(), runtime=runtime, profile=profile))

    assert response.status == "answered"
    assert [item["reasoning_id"] for item in calls][-2:] == [
        "stage1-quality-repair-model",
        "stage1-report-model",
    ]
    repair_call = calls[-2]
    assert repair_call["user_payload"]["repair_tasks"]
    assert "evidence-1" in repair_call["user_payload"]["allowed_evidence_ids"]
    attempts = response.output.panel_payloads["stage1_repair_attempts"]
    assert attempts[0]["status"] == "passed"
    assert attempts[0]["after_audit"]["score"] > attempts[0]["before_audit"]["score"]
    assert response.output.panel_payloads["stage1_quality_audit"]["status"] == "passed"
    run = response.output.panel_payloads["capability_run"]
    assert any(item["stage_id"] == "quality-repair" for item in run["stage_records"])
    artifacts = {
        item["artifact_id"]: item for item in run["output_artifact_refs"]
    }
    assert artifacts["stage1-quality-repair"]["filename"] == "quality_repair.json"
    assert "stage1-decision-matrix" in artifacts["stage1-quality-repair"][
        "source_artifact_refs"
    ]
    assert "stage1-quality-repair" in artifacts["stage1-quality-audit"][
        "source_artifact_refs"
    ]


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
        response.output.panel_payloads["stage1_hard_constraint_screening"]["status"]
        == "conditional"
    )
    assert (
        response.output.panel_payloads["stage1_evidence_verification"]["status"]
        == "passed"
    )
    assert response.output.panel_payloads["claim_evidence"][0]["status"] == "verified"
    assert response.output.panel_payloads["sources_used"] == ["项目资料 p.12"]
    deliverables = response.output.panel_payloads["stage1_deliverables"]
    assert [item["filename"] for item in deliverables["artifacts"]] == [
        "stage1_report.md",
        "evidence_appendix.md",
        "design_handoff.json",
        "run_manifest.json",
    ]
    run = response.output.panel_payloads["capability_run"]
    assert run["run_id"] == deliverables["run_manifest"]["run_id"]
    assert run["capability_id"] == "urban-strategy-stage1"
    assert run["status"] == "completed_with_warnings"
    assert run["execution_profile"]["model_profile_id"] == "personal-test"
    assert run["execution_profile"]["skill_id"] == "urban-strategy-stage1"
    assert run["input_artifact_refs"]
    assert [item["stage_id"] for item in run["stage_records"]][-2:] == [
        "stage1-report",
        "formal-deliverables",
    ]
    output_filenames = {item["filename"] for item in run["output_artifact_refs"]}
    assert {
        "project_brief.json",
        "source_readiness.json",
        "evidence_ledger.jsonl",
        "conflict_register.json",
        "hard_constraint_screening.json",
        "quality_audit.json",
        "strategy_options.json",
        "spatial_object_registry.json",
        "decision_matrix.json",
        "stage1_report.md",
        "evidence_appendix.md",
        "design_handoff.json",
        "run_manifest.json",
    } <= output_filenames
    assert deliverables["design_handoff"]["positioning_option_id"] == "option-a"
    assert (
        deliverables["design_handoff"]["space_requirements"][0]["space_id"] == "unit-1"
    )
    assert "项目资料 p.12" in deliverables["evidence_appendix_markdown"]
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
        valid_matrix(),
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
        "stage1-quality-repair-model",
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
        calls[-1]["user_payload"]["design_handoff"]["positioning_option_id"]
        == "option-a"
    )
    assert "Claim—Evidence Ledger" in calls[-1]["user_payload"]["evidence_appendix"]
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


def test_hard_constraint_evidence_enters_the_critical_quality_chain():
    critical = stage1._critical_evidence_ids(
        valid_strategy(),
        valid_matrix(),
        {
            "assessments": [
                {
                    "constraint_id": "fire_safety",
                    "evidence_refs": ["fire-report"],
                }
            ]
        },
    )

    assert critical == {"evidence-1", "fire-report"}


def test_stage1_resolves_map_binding_from_authoritative_snapshot_objects(monkeypatch):
    runtime, profile = runtime_and_profile()
    payload = ready_payload()
    payload.analysis_snapshot.spatial_objects = [
        {
            "spatial_object_id": "road:south-entry",
            "object_type": "road_segment",
            "title": "南侧入口道路",
            "source_ref": "analysis_snapshot.road.features",
            "source_locator": "analysis_snapshot.road.features/south-entry",
            "feature": {
                "type": "Feature",
                "properties": {"road_id": "south-entry"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[112.0, 28.0], [112.01, 28.01]],
                },
            },
        }
    ]
    matrix = deepcopy(valid_matrix())
    matrix["movement_routes"][0]["map_binding"] = {
        "status": "bound",
        "spatial_object_id": "road:south-entry",
    }
    matrix["space_decisions"][0]["map_binding"] = {
        "status": "bound",
        "spatial_object_id": "road:south-entry",
        "feature": {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        },
    }
    responses = [
        valid_evidence(),
        valid_workpacks(),
        valid_strategy(),
        matrix,
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

    matrix_call = next(
        item for item in calls if item["reasoning_id"] == "stage1-spatial-matrix-model"
    )
    catalog = matrix_call["user_payload"]["authoritative_spatial_objects"]
    assert catalog == [
        {
            "spatial_object_id": "road:south-entry",
            "object_type": "road_segment",
            "title": "南侧入口道路",
            "source_ref": "analysis_snapshot.road.features",
            "source_locator": "analysis_snapshot.road.features/south-entry",
        }
    ]
    assert all("feature" not in item and "coordinates" not in item for item in catalog)
    registry_panel = response.output.panel_payloads["stage1_spatial_object_registry"]
    assert registry_panel["status"] == "ready"
    assert registry_panel["binding_capabilities"] == {
        "space_decisions": True,
        "movement_routes": True,
    }
    assert registry_panel["catalog"] == catalog
    assert "registry" not in registry_panel
    assert all("feature" not in item and "coordinates" not in item for item in registry_panel["catalog"])
    run_artifacts = {
        item["artifact_id"]: item
        for item in response.output.panel_payloads["capability_run"]["output_artifact_refs"]
    }
    assert run_artifacts["stage1-spatial-object-registry"]["filename"] == "spatial_object_registry.json"
    assert "stage1-spatial-object-registry" in run_artifacts["stage1-decision-matrix"][
        "source_artifact_refs"
    ]
    binding = response.output.panel_payloads["stage1_spatial_matrix"][
        "space_decisions"
    ][0]["map_binding"]
    assert binding["status"] == "bound"
    assert binding["feature"]["geometry"]["type"] == "LineString"
    movement_binding = response.output.panel_payloads["stage1_spatial_matrix"][
        "movement_routes"
    ][0]["map_binding"]
    assert movement_binding["status"] == "bound"
    assert movement_binding["feature"]["geometry"]["type"] == "LineString"
    handoff_binding = response.output.panel_payloads["stage1_deliverables"][
        "design_handoff"
    ]["space_requirements"][0]["map_binding"]
    assert handoff_binding == binding
