from modules.agent.analysis_runs import AnalysisRunRecorder
from modules.agent.stage1_deliverables import (
    build_design_handoff,
    build_evidence_appendix,
    compile_stage1_deliverables,
)
from modules.agent.stage1_hard_constraints import build_hard_constraint_screening


def movement_routes():
    labels = {"visitor": "游客主游线", "resident": "居民日常流线", "service": "后勤流线", "fire": "消防应急流线"}
    return [
        {
            "route_id": f"route-{movement_type}",
            "movement_type": movement_type,
            "title": labels[movement_type],
            "role": "连接入口与礼堂",
            "entry_or_origin": "南侧入口",
            "destinations": ["原县政府礼堂"],
            "affected_space_ids": ["space-auditorium"],
            "operating_windows": ["日常开放时段"],
            "constraints": ["道路阻隔与无障碍待核验"],
            "conflicts": [] if movement_type != "service" else ["后勤与游客流线可能交叉"],
            "evidence_refs": ["evidence-1"],
            "assumptions": [],
            "validation_actions": ["现场踏勘并复核路径"],
            "status": "proposed",
            "map_binding": {
                "status": "unavailable",
                "spatial_object_id": "",
                "reason": f"{labels[movement_type]}尚无权威路径几何",
            },
        }
        for movement_type in ("visitor", "resident", "service", "fire")
    ]


def package():
    payload = {
        "evidence_nodes": [
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
            "matrix_version": "2.0",
            "positioning_option_id": "option-a",
            "spatial_hierarchy": [
                {
                    "id": "system-1",
                    "title": "一院",
                    "level": "system",
                    "parent_id": "",
                    "role": "公共文化系统",
                    "member_space_ids": [],
                },
                {
                    "id": "cluster-1",
                    "title": "公共文化组团",
                    "level": "cluster",
                    "parent_id": "system-1",
                    "role": "公共文化体验组团",
                    "member_space_ids": [],
                },
                {
                    "id": "unit-1",
                    "title": "礼堂单元",
                    "level": "unit",
                    "parent_id": "cluster-1",
                    "role": "社区活动单元",
                    "member_space_ids": ["space-auditorium"],
                },
            ],
            "space_decisions": [
                {
                    "space_id": "space-auditorium",
                    "hierarchy_id": "unit-1",
                    "space_name": "原县政府礼堂",
                    "current_state_category": "vacant",
                    "current_state": {"summary": "闲置礼堂"},
                    "change_logic": {"reason": "补足社区文化活动空间"},
                    "preferred_function": {"id": "culture", "name": "文化活动"},
                    "candidate_functions": [{"id": "culture"}, {"id": "retail"}],
                    "compatible_functions": [{"id": "exhibition"}],
                    "excluded_functions": [{"id": "heavy-food"}],
                    "audience_scenarios": ["社区周末活动"],
                    "access_and_movement": {"public_entry": "east"},
                    "operation_strategy": {"operator": "community_partner"},
                    "renovation_and_delivery": {"scope": "轻量改造"},
                    "implementation_phase": "phase_1",
                    "risk_level": "high",
                    "risk_summary": "消防条件尚待专项核验",
                    "preconditions": ["完成消防评估"],
                    "assumptions": ["社区组织愿意参与"],
                    "validation_actions": ["访谈社区组织"],
                    "evidence_refs": ["evidence-1"],
                    "hard_constraint_refs": [
                        "ownership",
                        "fire_safety",
                        "structural_condition",
                        "drainage_sewage",
                        "parking_loading",
                        "accessibility",
                        "resident_noise",
                    ],
                    "recommendation_status": "conditional",
                    "confidence": "medium",
                    "map_binding": {
                        "status": "unavailable",
                        "spatial_object_id": "",
                        "reason": "未提供权威建筑轮廓",
                    },
                }
            ],
            "movement_routes": movement_routes(),
            "portfolio_checks": ["公共服务与经营功能平衡"],
        },
    }
    payload["hard_constraint_screening"] = build_hard_constraint_screening(
        {}, evidence_ids={"evidence-1", "fieldwork-1"}
    ).model_dump(mode="json")
    return payload


def run_manifest():
    recorder = AnalysisRunRecorder(
        capability_id="urban-strategy-stage1",
        project_context={"scope": {"scope_id": "scope-1"}},
        configuration_snapshot={"question": "形成 Stage 1 策划"},
        execution_profile={
            "model_profile_id": "model-1",
            "skill_id": "urban-strategy-stage1",
        },
        run_id="run-test",
        created_at="2026-07-12T00:00:00Z",
    )
    recorder.record_stage("formal-deliverables", "编译正式交付物")
    return recorder.finish("completed", current_stage="formal-deliverables")


def test_design_handoff_reuses_strategy_matrix_and_evidence_ids():
    handoff = build_design_handoff(package())

    assert handoff.contract_version == "2.0"
    assert handoff.positioning_option_id == "option-a"
    assert handoff.positioning_option["name"] == "社区文化客厅"
    assert handoff.space_requirements[0].evidence_refs == ["evidence-1"]
    requirement = handoff.space_requirements[0]
    assert requirement.hierarchy_level == "unit"
    assert requirement.current_state["summary"] == "闲置礼堂"
    assert requirement.change_logic["reason"] == "补足社区文化活动空间"
    assert requirement.implementation_phase == "phase_1"
    assert requirement.risk_level == "high"
    assert requirement.risk_summary == "消防条件尚待专项核验"
    assert handoff.evidence_node_ids == ["evidence-1", "fieldwork-1"]
    assert {item.movement_type for item in handoff.movement_requirements} == {
        "visitor",
        "resident",
        "service",
        "fire",
    }
    service = next(
        item for item in handoff.movement_requirements if item.movement_type == "service"
    )
    assert service.conflicts == ["后勤与游客流线可能交叉"]
    assert service.affected_space_ids == ["space-auditorium"]
    assert handoff.hard_constraint_screening["status"] == "conditional"
    assert handoff.space_requirements[0].hard_constraint_refs[0] == "ownership"
    assert {item["type"] for item in handoff.unresolved_constraints} == {
        "evidence_conflict",
        "fieldwork_required",
        "hard_constraint",
    }


def test_evidence_appendix_preserves_locator_conflict_and_quality_status():
    appendix = build_evidence_appendix(package())

    assert "项目摘要 p.12" in appendix
    assert "pageindex:node-12:p.12" in appendix
    assert "居民户数" in appendix
    assert "硬约束筛选" in appendix
    assert "产权与使用权" in appendix
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
    assert (
        deliverables.design_handoff.space_requirements[0].space_id == "space-auditorium"
    )
    assert deliverables.run_manifest.run_id == "run-test"
