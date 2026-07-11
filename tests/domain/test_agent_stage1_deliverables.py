from modules.agent.capability_runs import CapabilityRunRecorder
from modules.agent.stage1_deliverables import (
    build_design_handoff,
    build_evidence_appendix,
    compile_stage1_deliverables,
)


def package():
    return {
        "evidence_ledger": [
            {
                "id": "evidence-1",
                "claim": "历史院落是核心空间资产",
                "evidence_type": "F",
                "status": "verified",
                "source_ref": "项目摘要 p.12",
                "source_locator": "pageindex:node-12:p.12",
                "scope": "项目红线",
                "confidence": "high",
                "limitation": "结构状态待核验",
            },
            {
                "id": "fieldwork-1",
                "claim": "礼堂消防条件满足活动使用",
                "evidence_type": "V",
                "status": "fieldwork_required",
                "source_ref": "现场核验",
                "source_locator": "site:auditorium",
                "scope": "礼堂",
                "confidence": "low",
                "limitation": "缺少消防检测",
                "next_action": "消防专项检测",
                "executor": "fieldwork",
            },
        ],
        "conflict_register": [
            {
                "metric_key": "households",
                "label": "居民户数",
                "unresolved": True,
                "explanation": "两份项目摘要口径不一致。",
                "evidence_ids": ["evidence-1"],
            }
        ],
        "data_quality": {"status": "passed_with_gaps", "assessed_count": 2},
        "provenance_binding": {"status": "passed", "assessed_count": 2},
        "strategy": {
            "recommended_option_id": "option-a",
            "options": [
                {
                    "id": "option-a",
                    "name": "社区文化客厅",
                    "evidence_refs": ["evidence-1"],
                }
            ],
        },
        "spatial_matrix": {
            "matrix_version": "1.0",
            "positioning_option_id": "option-a",
            "spatial_hierarchy": [{"id": "unit-1", "level": "unit"}],
            "space_decisions": [
                {
                    "space_id": "unit-1",
                    "current_state": {"use": "闲置礼堂"},
                    "change_logic": {"reason": "补足社区文化活动空间"},
                    "preferred_function": {"id": "culture"},
                    "candidate_functions": [{"id": "culture"}, {"id": "retail"}],
                    "excluded_functions": [{"id": "heavy-food"}],
                    "audience_scenarios": ["社区周末活动"],
                    "access_and_movement": {"public_entry": "east"},
                    "operation_strategy": {"operator": "community_partner"},
                    "renovation_and_delivery": {"phase": 1},
                    "preconditions": ["完成消防评估"],
                    "assumptions": ["社区组织愿意参与"],
                    "validation_actions": ["访谈社区组织"],
                    "evidence_refs": ["evidence-1"],
                    "recommendation_status": "conditional",
                    "confidence": "medium",
                }
            ],
            "portfolio_checks": ["公共服务与经营功能平衡"],
        },
    }


def run_manifest():
    recorder = CapabilityRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context={"scope": {"scope_id": "scope-1"}},
        configuration_snapshot={"question": "形成 Stage 1 策划"},
        execution_profile={
            "model_profile_id": "model-1",
            "skill_id": "urban-strategy-stage1",
        },
        run_id="caprun-test",
        created_at="2026-07-12T00:00:00Z",
    )
    recorder.record_stage("formal-deliverables", "编译正式交付物")
    return recorder.finish("completed", current_stage="formal-deliverables")


def test_design_handoff_reuses_strategy_matrix_and_evidence_ids():
    handoff = build_design_handoff(package())

    assert handoff.positioning_option_id == "option-a"
    assert handoff.positioning_option["name"] == "社区文化客厅"
    assert handoff.space_requirements[0].evidence_refs == ["evidence-1"]
    assert handoff.evidence_ledger_ids == ["evidence-1", "fieldwork-1"]
    assert {item["type"] for item in handoff.unresolved_constraints} == {
        "evidence_conflict",
        "fieldwork_required",
    }


def test_evidence_appendix_preserves_locator_conflict_and_quality_status():
    appendix = build_evidence_appendix(package())

    assert "项目摘要 p.12" in appendix
    assert "pageindex:node-12:p.12" in appendix
    assert "居民户数" in appendix
    assert "passed_with_gaps" in appendix
    assert "真实资产绑定状态：passed" in appendix


def test_compiler_exposes_three_named_artifacts_from_one_source_contract():
    deliverables = compile_stage1_deliverables(
        package(),
        report_markdown="# Stage 1 主报告",
        run_manifest=run_manifest(),
    )

    assert deliverables.source_contract == "audited_stage1_package"
    assert [item.filename for item in deliverables.artifacts] == [
        "stage1_report.md",
        "evidence_appendix.md",
        "design_handoff.json",
        "run_manifest.json",
    ]
    assert deliverables.design_handoff.space_requirements[0].space_id == "unit-1"
    assert deliverables.run_manifest.run_id == "caprun-test"
