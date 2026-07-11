from modules.agent.stage1_hard_constraints import (
    HARD_CONSTRAINT_DEFINITIONS,
    build_hard_constraint_screening,
)


def test_missing_constraint_categories_become_explicit_verification_tasks():
    screening = build_hard_constraint_screening({}, evidence_ids={"evidence-1"})

    assert screening.status == "conditional"
    assert {item.constraint_id for item in screening.assessments} == {
        item.constraint_id for item in HARD_CONSTRAINT_DEFINITIONS
    }
    assert screening.status_counts["unknown"] == len(HARD_CONSTRAINT_DEFINITIONS)
    assert len(screening.pending_actions) == len(HARD_CONSTRAINT_DEFINITIONS)
    assert all(item.decision_effect == "condition" for item in screening.assessments)


def test_verified_claims_keep_only_real_evidence_references():
    screening = build_hard_constraint_screening(
        {
            "assessments": [
                {
                    "constraint_id": "ownership",
                    "state": "verified",
                    "decision_effect": "allow",
                    "finding": "统一运营授权已有项目批复。",
                    "evidence_refs": ["evidence-1", "invented"],
                }
            ]
        },
        evidence_ids={"evidence-1"},
    )

    ownership = screening.assessments[0]
    assert ownership.evidence_refs == ["evidence-1"]
    assert screening.status == "conditional"
    assert screening.status_counts == {
        "verified": 1,
        "constrained": 0,
        "unknown": 6,
        "not_applicable": 0,
    }


def test_exclusion_effect_blocks_the_screening_contract():
    screening = build_hard_constraint_screening(
        {
            "assessments": [
                {
                    "constraint_id": "fire_safety",
                    "state": "constrained",
                    "decision_effect": "exclude",
                    "finding": "现状疏散能力不允许高密度活动。",
                    "evidence_refs": ["fire-report"],
                    "verification_action": "调整业态和容量后重新开展消防论证。",
                    "executor": "fieldwork",
                }
            ]
        },
        evidence_ids={"fire-report"},
    )

    assert screening.status == "blocked"
    fire = next(item for item in screening.assessments if item.constraint_id == "fire_safety")
    assert fire.decision_effect == "exclude"
    assert fire.verification_action
