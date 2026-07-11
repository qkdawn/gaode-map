from copy import deepcopy

from modules.agent.quality_audit import audit_stage1_package


def complete_package():
    return {
        "evidence_ledger": [
            {
                "id": "evidence-1",
                "claim": "项目范围内存在历史建筑院落",
                "evidence_type": "F",
                "status": "verified",
                "source_ref": "项目基础资料 p.12",
                "source_artifact_id": "document-node-12",
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
                }
                for option_id in ("option-a", "option-b", "option-c")
            ],
        },
        "spatial_matrix": {
            "spatial_hierarchy": [
                {"id": "system-1", "level": "system"},
                {"id": "cluster-1", "level": "cluster"},
                {"id": "unit-1", "level": "unit"},
            ],
            "space_decisions": [
                {
                    "space_id": "unit-1",
                    "candidate_functions": [
                        {"id": "culture"},
                        {"id": "retail"},
                    ],
                    "preferred_function": {"id": "culture"},
                    "excluded_functions": [
                        {"id": "heavy-food", "reason": "消防与排烟受限"}
                    ],
                    "audience_scenarios": ["社区周末文化活动"],
                    "preconditions": ["完成消防评估"],
                    "evidence_refs": ["evidence-1"],
                    "recommendation_status": "conditional",
                    "confidence": "medium",
                }
            ],
            "portfolio_checks": ["公共服务与经营功能保持平衡"],
        },
    }


def test_complete_stage1_package_passes_quality_gate():
    result = audit_stage1_package(complete_package())

    assert result.status == "passed"
    assert result.score == 100
    assert result.blocking_issues == []


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
