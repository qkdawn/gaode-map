from copy import deepcopy
from datetime import date

from modules.agent.quality_audit import audit_stage1_package
from modules.agent.stage1_data_quality import assess_stage1_data_quality
from modules.agent.stage1_hard_constraints import build_hard_constraint_screening
from modules.agent.stage1_provenance import (
    EvidenceProvenanceBinding,
    assess_provenance_bindings,
)


def complete_package():
    package = {
        "evidence_ledger": [
            {
                "id": "evidence-1",
                "claim": "项目范围内存在历史建筑院落",
                "evidence_type": "F",
                "status": "verified",
                "source_ref": "项目基础资料 p.12",
                "source_artifact_id": "document-node-12",
                "source_date": "2026-07-01",
                "source_locator": "document:project-doc#page=12&node=document-node-12",
                "method": "document_read",
                "scope": "项目红线",
                "comparison_baseline": "",
                "confidence": "high",
                "limitation": "建筑状态仍需逐栋勘察",
                "next_action": "开展结构安全鉴定",
                "executor": "fieldwork",
            }
        ],
        "workpacks": [
            {"type": "spatial", "evidence_refs": ["evidence-1"]},
            {"type": "audience", "evidence_refs": ["evidence-1"]},
            {"type": "culture_tourism", "evidence_refs": ["evidence-1"]},
            {"type": "renewal_operations", "evidence_refs": ["evidence-1"]},
        ],
        "strategy": {
            "recommended_option_id": "option-a",
            "options": [
                {
                    "id": option_id,
                    "evidence_refs": ["evidence-1"],
                    "counter_evidence": ["夜间开放边界待核实"],
                    "invalidation_conditions": ["居民协商无法达成"],
                    "recommendation_status": "conditional",
                    "hard_constraint_refs": [
                        "ownership", "fire_safety", "structural_condition",
                        "drainage_sewage", "parking_loading", "accessibility",
                        "resident_noise",
                    ],
                    "preconditions": ["完成硬约束核验"],
                    "validation_actions": ["执行硬约束筛选中的待办任务"],
                }
                for option_id in ("option-a", "option-b", "option-c")
            ],
        },
        "spatial_matrix": {
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
                    "map_binding": {
                        "status": "bound",
                        "spatial_object_id": "building:auditorium",
                        "object_type": "building",
                        "title": "原县政府礼堂",
                        "source_ref": "project_gis.buildings",
                        "source_locator": "project_gis.buildings/auditorium",
                        "feature": {
                            "type": "Feature",
                            "properties": {"id": "auditorium"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[112.0, 28.0], [112.01, 28.0], [112.01, 28.01], [112.0, 28.0]]],
                            },
                        },
                        "reason": "",
                    },
                    "space_name": "原县政府礼堂",
                    "future_role": "社区文化锚点",
                    "core_audiences": ["社区家庭", "青年社群"],
                    "movement_role": "主游线目的地",
                    "value_role": "公共服务与活动引流",
                    "current_state": {"use": "闲置礼堂"},
                    "change_logic": {"reason": "补足社区文化活动空间"},
                    "candidate_functions": [
                        {"id": "culture"},
                        {"id": "retail"},
                    ],
                    "preferred_function": {"id": "culture"},
                    "excluded_functions": [
                        {"id": "heavy-food", "reason": "消防与排烟受限"}
                    ],
                    "audience_scenarios": ["社区周末文化活动"],
                    "access_and_movement": {"visitor_entry": "南侧主入口"},
                    "operation_strategy": {"operator": "社区文化运营主体"},
                    "renovation_and_delivery": {"phase": "一期轻量改造"},
                    "preconditions": ["完成消防评估"],
                    "validation_actions": ["开展消防与结构核验"],
                    "evidence_refs": ["evidence-1"],
                    "hard_constraint_refs": [
                        "ownership", "fire_safety", "structural_condition",
                        "drainage_sewage", "parking_loading", "accessibility",
                        "resident_noise",
                    ],
                    "recommendation_status": "conditional",
                    "confidence": "medium",
                }
            ],
            "portfolio_checks": ["公共服务与经营功能保持平衡"],
        },
    }
    package["hard_constraint_screening"] = build_hard_constraint_screening(
        {}, evidence_ids={"evidence-1"}
    ).model_dump(mode="json")
    package["data_quality"] = assess_stage1_data_quality(
        package["evidence_ledger"], critical_evidence_ids={"evidence-1"}
    ).model_dump(mode="json")
    package["provenance_binding"] = assess_provenance_bindings(
        [
            EvidenceProvenanceBinding(
                evidence_id="evidence-1",
                status="verified",
                artifact_id="document-node-12",
                source_id="document:project-doc",
                source_kind="document",
                locator="document:project-doc#page=12&node=document-node-12",
                metadata_origin="project_evidence_dossier",
                matched_by="source_artifact_id",
            )
        ],
        critical_evidence_ids={"evidence-1"},
    ).model_dump(mode="json")
    return package


def test_complete_stage1_package_passes_quality_gate():
    result = audit_stage1_package(complete_package())

    assert result.status == "passed"
    assert result.score == 100
    assert result.blocking_issues == []


def test_matrix_must_bind_to_the_recommended_strategy_option():
    package = complete_package()
    package["spatial_matrix"]["positioning_option_id"] = "option-b"

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "matrix_positioning_mismatch" in {
        issue.code for issue in result.blocking_issues
    }


def test_space_decision_requires_management_summary_dimensions():
    package = complete_package()
    decision = package["spatial_matrix"]["space_decisions"][0]
    decision["future_role"] = ""
    decision["core_audiences"] = []
    decision["movement_role"] = ""

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "space_decisions_incomplete" in {
        issue.code for issue in result.blocking_issues
    }


def test_space_decision_must_be_ready_for_design_handoff():
    package = complete_package()
    package["spatial_matrix"]["space_decisions"][0]["operation_strategy"] = {}
    package["spatial_matrix"]["space_decisions"][0]["validation_actions"] = []

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "space_design_handoff_incomplete" in {
        issue.code for issue in result.blocking_issues
    }


def test_missing_falsification_and_space_alternatives_block_delivery():
    package = complete_package()
    package["strategy"]["options"][0]["counter_evidence"] = []
    package["spatial_matrix"]["space_decisions"][0]["candidate_functions"] = [
        {"id": "culture"}
    ]

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert {issue.code for issue in result.blocking_issues} >= {
        "strategy_falsification_missing",
        "space_decisions_incomplete",
    }


def test_proxy_overreach_is_rejected():
    package = complete_package()
    package["workpacks"][0]["finding"] = "夜光代表客流，足以证明需求"

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "proxy_overreach" in {issue.code for issue in result.blocking_issues}


def test_evidence_requires_scope_limitation_and_validation_status():
    package = deepcopy(complete_package())
    package["evidence_ledger"][0].update(
        {"scope": "", "limitation": "", "status": "supported"}
    )

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert result.blocking_issues[0].code == "evidence_contract_invalid"


def test_unknown_evidence_reference_blocks_delivery():
    package = complete_package()
    package["strategy"]["options"][0]["evidence_refs"] = ["missing-evidence"]

    result = audit_stage1_package(package)

    assert result.status == "failed"
    issue = next(
        item
        for item in result.blocking_issues
        if item.code == "evidence_reference_invalid"
    )
    assert "missing-evidence" in issue.message


def test_duplicate_evidence_ids_and_missing_provenance_block_delivery():
    package = complete_package()
    duplicate = deepcopy(package["evidence_ledger"][0])
    duplicate["source_artifact_id"] = ""
    package["evidence_ledger"].append(duplicate)

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert {issue.code for issue in result.blocking_issues} >= {
        "evidence_id_duplicate",
        "evidence_provenance_incomplete",
    }


def test_recommended_option_requires_direct_verified_evidence():
    package = complete_package()
    package["evidence_ledger"][0]["status"] = "inferred"
    package["evidence_ledger"][0]["confidence"] = "medium"

    result = audit_stage1_package(package)

    issue = next(
        item
        for item in result.blocking_issues
        if item.code == "decision_evidence_strength_invalid"
    )
    assert "缺少 verified/cross_checked" in issue.message


def test_unresolved_conflict_cannot_support_recommended_option():
    package = complete_package()
    package["conflict_register"] = [
        {
            "metric_key": "households",
            "label": "居民户数",
            "values": ["102户", "120户"],
            "evidence_ids": ["document-node-12", "document-node-18"],
            "unresolved": True,
            "explanation": "同级项目摘要口径冲突，需人工核实。",
        }
    ]

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "引用了未解决冲突证据" in next(
        item.message
        for item in result.blocking_issues
        if item.code == "decision_evidence_strength_invalid"
    )
    conflict_issue = next(
        item for item in result.issues if item.code == "unresolved_evidence_conflict"
    )
    assert conflict_issue.severity == "warning"
    assert "居民户数" in conflict_issue.message


def test_unlinked_conflict_is_exposed_without_blocking_unrelated_decision():
    package = complete_package()
    package["conflict_register"] = [
        {
            "metric_key": "households",
            "label": "居民户数",
            "values": ["102户", "120户"],
            "evidence_ids": ["other-document-node"],
            "unresolved": True,
            "explanation": "保留冲突。",
        }
    ]

    result = audit_stage1_package(package)

    assert result.status == "passed"
    assert result.score == 100
    assert [item.code for item in result.issues] == ["unresolved_evidence_conflict"]


def test_critical_analytic_evidence_requires_fresh_sample_and_spatial_metadata():
    package = complete_package()
    evidence = package["evidence_ledger"][0]
    evidence.update(
        {
            "evidence_type": "G",
            "source_date": "2020",
            "analysis_date": "",
            "sample_size": None,
            "missing_count": None,
            "duplicate_count": None,
            "anomaly_count": None,
            "coordinate_system": "",
        }
    )
    package["data_quality"] = assess_stage1_data_quality(
        package["evidence_ledger"], critical_evidence_ids={"evidence-1"}
    ).model_dump(mode="json")

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert {item.code for item in result.blocking_issues} >= {
        "analytic_source_stale",
        "analysis_date_missing",
        "sample_diagnostics_missing",
        "coordinate_system_missing",
    }


def test_unreferenced_data_quality_gap_is_warning_not_delivery_blocker():
    package = complete_package()
    package["evidence_ledger"].append(
        {
            "id": "background-1",
            "claim": "旧版背景数据仅用于历史参照",
            "evidence_type": "G",
            "status": "inferred",
            "source_ref": "旧版统计表",
            "source_artifact_id": "old-table",
            "source_date": "unknown",
            "source_locator": "",
            "method": "table_read",
            "scope": "行政区",
            "comparison_baseline": "",
            "confidence": "low",
            "limitation": "不支撑推荐方案",
        }
    )
    package["data_quality"] = assess_stage1_data_quality(
        package["evidence_ledger"], critical_evidence_ids={"evidence-1"}
    ).model_dump(mode="json")
    package["provenance_binding"]["bindings"].append(
        {
            "evidence_id": "background-1",
            "status": "unverifiable",
            "message": "背景证据未绑定",
        }
    )

    result = audit_stage1_package(package)

    assert result.status == "passed"
    assert any(item.code == "source_date_missing" for item in result.issues)
    assert all(item.severity == "warning" for item in result.issues)


def test_data_quality_blocks_unrecorded_coordinate_conversion_on_critical_evidence():
    ledger = []
    for evidence_id, coordinate_system in (("geo-1", "EPSG:4490"), ("geo-2", "GCJ-02")):
        ledger.append(
            {
                "id": evidence_id,
                "evidence_type": "G",
                "source_date": "2026-01-01",
                "source_locator": f"artifact:{evidence_id}#result",
                "analysis_date": "2026-07-01",
                "sample_size": 100,
                "missing_count": 0,
                "duplicate_count": 0,
                "anomaly_count": 0,
                "coordinate_system": coordinate_system,
                "coordinate_transform": "",
            }
        )

    summary = assess_stage1_data_quality(
        ledger, critical_evidence_ids={"geo-1"}, as_of=date(2026, 7, 12)
    )

    assert summary.status == "failed"
    mismatch = next(
        item
        for item in summary.blocking_issues
        if item.code == "coordinate_system_mismatch"
    )
    assert "EPSG:4490" in mismatch.message
    assert "GCJ-02" in mismatch.message


def test_data_quality_treats_unknown_critical_source_locator_as_blocking():
    summary = assess_stage1_data_quality(
        [
            {
                "id": "fact-1",
                "evidence_type": "F",
                "source_date": "unknown",
                "source_locator": "not_applicable",
            }
        ],
        critical_evidence_ids={"fact-1"},
    )

    assert summary.status == "failed"
    assert {item.code for item in summary.blocking_issues} == {
        "source_date_missing",
        "source_locator_missing",
    }


def test_hard_constraint_screening_must_cover_all_required_categories():
    package = complete_package()
    package["hard_constraint_screening"]["assessments"] = package["hard_constraint_screening"]["assessments"][:-1]

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "hard_constraint_screening_invalid" in {item.code for item in result.blocking_issues}


def test_unknown_constraints_require_conditional_recommendations_and_refs():
    package = complete_package()
    package["strategy"]["options"][0]["recommendation_status"] = "strong"
    package["spatial_matrix"]["space_decisions"][0]["hard_constraint_refs"] = ["fire_safety"]

    result = audit_stage1_package(package)

    issue = next(item for item in result.blocking_issues if item.code == "hard_constraint_application_invalid")
    assert "未逐项响应硬约束" in issue.message
    assert "未降级" in issue.message


def test_excluded_hard_constraint_blocks_delivery():
    package = complete_package()
    package["hard_constraint_screening"] = build_hard_constraint_screening(
        {
            "assessments": [
                {
                    "constraint_id": "fire_safety",
                    "state": "constrained",
                    "decision_effect": "exclude",
                    "finding": "现状疏散能力不允许当前活动容量。",
                    "evidence_refs": ["evidence-1"],
                    "verification_action": "调整容量并重新开展消防论证。",
                }
            ]
        },
        evidence_ids={"evidence-1"},
    ).model_dump(mode="json")

    result = audit_stage1_package(package)

    issue = next(item for item in result.blocking_issues if item.code == "hard_constraint_application_invalid")
    assert "不可交付" in issue.message


def test_stage1_quality_gate_reports_truthful_unavailable_map_binding_as_warning():
    package = complete_package()
    package["spatial_matrix"]["space_decisions"][0]["map_binding"] = {
        "status": "unavailable",
        "reason": "尚未提供礼堂建筑轮廓",
    }

    result = audit_stage1_package(package)

    assert result.status == "passed"
    issue = next(item for item in result.issues if item.code == "spatial_map_binding_incomplete")
    assert issue.severity == "warning"
    assert "1 个空间决策" in issue.message


def test_stage1_quality_gate_rejects_unverifiable_bound_map_object():
    package = complete_package()
    package["spatial_matrix"]["space_decisions"][0]["map_binding"] = {
        "status": "bound",
        "spatial_object_id": "invented-building",
        "object_type": "building",
        "source_ref": "",
        "source_locator": "",
        "feature": None,
    }

    result = audit_stage1_package(package)

    assert result.status == "failed"
    assert "spatial_map_binding_invalid" in {
        issue.code for issue in result.blocking_issues
    }
