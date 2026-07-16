import pytest
from pydantic import ValidationError

from modules.spatial_action.report_orchestration import (
    AnalysisBlueprint,
    AnalystChapterIndex,
    ArgumentUnit,
    ChapterAssignments,
    ChapterPackage,
    EditorialReviewDraft,
    EVIDENCE_CAPABILITY_REGISTRY_HASH,
    EvidenceSnapshot,
    ReportAssembly,
    _digest,
    build_editorial_review,
    validate_chapter_package,
    validate_v3_contracts,
)


QUESTION = {
    "question_id": "question:role",
    "text": "首期项目角色是什么？",
    "decision_target": "project_role",
    "hypotheses": [{
        "hypothesis_id": "hypothesis:service",
        "statement": "社区服务适合作为首期基础。",
        "disconfirming_condition": "直接证据否定居民使用。",
    }],
}


def _blueprint() -> AnalysisBlueprint:
    payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "blueprint_id": "blueprint:v3",
        "analysis_scope": "full_project",
        "report_title": "项目报告",
        "project_judgment": "需要决定首期角色。",
        "decision_questions": [QUESTION],
        "evidence_requirements": [{
            "question_id": "question:role",
            "items": [{
                "requirement_id": "requirement:documents",
                "kind": "document",
                "objective": "核验项目约束",
                "evidence_capability": "project_constraints",
                "required_sources": ["document:project"],
                "failure_effect": "不能判断首期角色",
            }],
        }],
        "excluded_topics": [{"topic": "营业额预测", "reason": "缺少客流与消费证据"}],
        "report_logic": ["先界定约束，再判断方向"],
        "shared_glossary": {},
        "completeness_review": {"status": "accepted", "findings": []},
        "lock": {
            "source_snapshot_hash": "sha256:source",
            "capability_registry_hash": EVIDENCE_CAPABILITY_REGISTRY_HASH,
            "content_hash": "",
            "locked_at": "2026-07-17T00:00:00Z",
        },
    }
    sealed = dict(payload)
    sealed["lock"] = dict(payload["lock"])
    sealed["lock"].pop("content_hash")
    payload["lock"]["content_hash"] = _digest(sealed)
    return AnalysisBlueprint.model_validate(payload)


def _snapshot() -> EvidenceSnapshot:
    blueprint_hash = _blueprint().lock.content_hash
    payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "snapshot_id": "snapshot:v3",
        "blueprint_hash": blueprint_hash,
        "evidence": [{
            "evidence_id": "evidence:documents",
            "requirement_id": "requirement:documents",
            "question_ids": ["question:role"],
            "state": "measured",
            "sources": ["document:project"],
            "scope": {"scope_id": "project"},
            "result": {"constraint_count": 2},
            "limitations": [],
        }],
        "gaps": [],
        "question_readiness": {"question:role": "ready"},
        "visuals": [{
            "visual_id": "visual:constraints",
            "visual_type": "bar",
            "title": "约束数量",
            "evidence_ids": ["evidence:documents"],
            "data_fields": ["constraint_count"],
            "transform": "identity",
            "filename": "constraints.svg",
            "spec_hash": "sha256:spec",
            "asset_hash": "sha256:asset",
        }],
        "execution_lineage": {
            "capability_registry_hash": EVIDENCE_CAPABILITY_REGISTRY_HASH,
            "attempts": [{
                "attempt_id": "attempt:documents",
                "requirement_id": "requirement:documents",
                "evidence_capability": "project_constraints",
                "adapter_id": "adapter:documents",
                "metric_id": "",
                "parameters": {},
                "execution_status": "succeeded",
                "evidence_ids": ["evidence:documents"],
                "gap_ids": [],
                "reason": "",
            }],
        },
        "snapshot_hash": "",
    }
    payload["snapshot_hash"] = _digest({key: value for key, value in payload.items() if key != "snapshot_hash"})
    return EvidenceSnapshot.model_validate(payload)


def _assignments() -> ChapterAssignments:
    blueprint_hash = _blueprint().lock.content_hash
    snapshot_hash = _snapshot().snapshot_hash
    payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "assignment_set_id": "assignments:v3",
        "blueprint_hash": blueprint_hash,
        "evidence_snapshot_hash": snapshot_hash,
        "chapters": [{
            "chapter_id": "chapter:role",
            "order": 1,
            "title": "首期角色",
            "role": "定位分析师",
            "objective": "形成首期角色判断",
            "question_ids": ["question:role"],
            "subsection_tasks": [{
                "subsection_id": "subsection:role",
                "title": "首期基础方向",
                "objective": "解释首期方向",
                "question_ids": ["question:role"],
                "required_argument_units": ["claim:role"],
            }],
            "evidence_access": {
                "primary": ["evidence:documents"],
                "shared": [],
                "gaps": [],
                "visuals": ["visual:constraints"],
                "forbidden": [],
            },
            "dependencies": [],
            "assignment_hash": "",
        }],
        "content_hash": "",
    }
    assignment = payload["chapters"][0]
    assignment["assignment_hash"] = _digest({
        "blueprint_hash": blueprint_hash,
        "evidence_snapshot_hash": snapshot_hash,
        "assignment": {key: value for key, value in assignment.items() if key != "assignment_hash"},
    })
    payload["content_hash"] = _digest({key: value for key, value in payload.items() if key != "content_hash"})
    return ChapterAssignments.model_validate(payload)


def _chapter(claim_state: str = "inference") -> ChapterPackage:
    argument = {
        "argument_id": "claim:role",
        "claim": "社区服务与历史展示适合作为首期基础盘。",
        "evidence_refs": ["evidence:documents"],
        "evidence_result_refs": [],
        "evidence_gap_refs": [],
        "evidence_state": claim_state,
        "baseline": "与直接启动高投入改造相比",
        "mechanism": "低承诺服务能先验证居民使用并降低沉没成本。",
        "project_implication": "首期应围绕服务和展示原型组织。",
        "action": "启动可撤回试点。",
        "assumptions": ["居民仍持续使用场地"],
        "stop_condition": "直接需求证据否定居民使用时停止。",
    }
    payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "chapter_id": "chapter:role",
        "chapter_version_id": "chapter:role:v1",
        "assignment_hash": _assignments().chapters[0].assignment_hash,
        "evidence_snapshot_hash": _snapshot().snapshot_hash,
        "content_hash": "",
        "analyst_role": "定位分析师",
        "title": "首期角色",
        "thesis": "先形成低承诺基础盘。",
        "decision_question_ids": ["question:role"],
        "subsections": [{
            "subsection_id": "subsection:role",
            "title": "首期基础方向",
            "body": "短正文也允许，完整性由结构化论证链保证。",
            "decision_question_ids": ["question:role"],
            "evidence_ids": ["evidence:documents"],
            "object_ids": [],
            "finding_ids": ["finding:role"],
            "evidence_gap_ids": [],
            "argument_units": [argument],
            "structured_blocks": [],
            "visual_refs": [{
                "visual_id": "visual:constraints",
                "caption": "项目文件约束数量。",
                "interpretation": "只表达文件中已识别的约束，不代表市场需求。",
            }],
        }],
        "finding_packets": [{
            "finding_id": "finding:role",
            "decision_question_id": "question:role",
            "observed_pattern": "文件同时要求居民共生与历史资产活化。",
            "evidence_ids": ["evidence:documents"],
            "evidence_state": "measured",
            "mechanism_hypothesis": "低承诺服务可同时回应两类约束。",
            "project_implication": "首期不宜直接承诺高投入目的地改造。",
            "recommended_action": "先开展服务与展示试点。",
            "critical_assumption": "文件约束仍然有效。",
            "disconfirming_test": "权威主体撤销相关约束。",
        }],
        "option_comparisons": [],
        "evidence_gaps": [],
        "assumptions": ["文件仍有效"],
        "veto_conditions": ["项目权属或保护要求发生根本变化"],
        "cross_chapter_dependencies": [],
        "unresolved_tensions": [],
    }
    payload["content_hash"] = _digest({key: value for key, value in payload.items() if key != "content_hash"})
    return ChapterPackage.model_validate(payload)


def test_executable_requirement_rejects_unknown_capability():
    payload = _blueprint().model_dump(mode="json")
    payload["evidence_requirements"][0]["items"][0].update({
        "kind": "metric", "evidence_capability": "invented_metric",
    })
    with pytest.raises(ValidationError, match="unknown evidence_capability"):
        AnalysisBlueprint.model_validate(payload)


def test_snapshot_rejects_inference_as_deterministic_evidence():
    payload = _snapshot().model_dump(mode="json")
    payload["evidence"][0]["state"] = "inference"
    with pytest.raises(ValidationError):
        EvidenceSnapshot.model_validate(payload)


def test_specialist_projection_is_authorized_and_hides_execution_lineage():
    projection = _assignments().specialist_projection("chapter:role", _snapshot())
    assert "execution_lineage" not in projection["evidence_snapshot"]
    assert [item["evidence_id"] for item in projection["evidence_snapshot"]["evidence"]] == ["evidence:documents"]
    assert [item["visual_id"] for item in projection["evidence_snapshot"]["visuals"]] == ["visual:constraints"]


def test_cross_contract_validation_requires_complete_lineage_and_bindings():
    validate_v3_contracts(_blueprint(), _snapshot(), _assignments())
    snapshot = _snapshot()
    attempt = snapshot.execution_lineage.attempts[0].model_copy(update={"requirement_id": "requirement:other"})
    lineage = snapshot.execution_lineage.model_copy(update={"attempts": [attempt]})
    mutated = snapshot.model_copy(update={"execution_lineage": lineage})
    with pytest.raises(ValueError, match="every evidence requirement"):
        validate_v3_contracts(_blueprint(), mutated, _assignments())


def test_editorial_review_generates_claims_and_agent_draft_cannot_supply_them():
    draft_payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "review_id": "review:v3",
        "chapter_decisions": [{
            "chapter_id": "chapter:role",
            "chapter_version_id": "chapter:role:v1",
            "status": "accepted",
            "reason": "论证链完整。",
            "repair_instructions": [],
        }],
        "conflicts": [],
        "terminology_rules": {},
        "publication_decision": "ready",
    }
    with pytest.raises(ValidationError):
        EditorialReviewDraft.model_validate(draft_payload | {"accepted_claims": []})
    review = build_editorial_review(EditorialReviewDraft.model_validate(draft_payload), [_chapter()])
    assert review.accepted_claims[0].claim_id == "claim:role"
    assert review.accepted_claims[0].evidence_state == "inference"


def test_chapter_package_must_match_assignment_whitelist_and_place_visuals():
    assignment = _assignments().chapters[0]
    validate_chapter_package(_chapter(), assignment, _snapshot(), expected_revision=1)
    package = _chapter().model_copy(update={
        "subsections": [
            _chapter().subsections[0].model_copy(update={"visual_refs": []})
        ]
    })
    with pytest.raises(ValueError, match="every assigned visual"):
        validate_chapter_package(package, assignment, _snapshot(), expected_revision=1)


def test_report_assembly_forbids_professional_chapter_body():
    payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "assembly_id": "assembly:v3",
        "title": "项目报告",
        "accepted_chapters": [{
            "chapter_id": "chapter:role",
            "chapter_version_id": "chapter:role:v1",
            "content_hash": "sha256:chapter",
        }],
        "chapter_order": ["chapter:role"],
        "executive_summary": {"text": "先试点。", "claim_ids": ["claim:role"]},
        "transitions": [],
        "integrated_recommendations": [],
        "conflict_references": [],
        "content_hash": "",
    }
    payload["content_hash"] = _digest({key: value for key, value in payload.items() if key != "content_hash"})
    ReportAssembly.model_validate(payload)
    with pytest.raises(ValidationError):
        ReportAssembly.model_validate(payload | {"chapter_body": "主分析师代写正文"})


def test_chapter_index_preserves_v1_and_optional_v2_without_overwrite():
    payload = {
        "schema_version": "3.0",
        "run_id": "run:v3",
        "chapters": [{
            "chapter_id": "market",
            "versions": [
                {
                    "chapter_version_id": "market:v1",
                    "revision": 1,
                    "filename": "market.v1.json",
                    "assignment_hash": "sha256:assignment",
                    "evidence_snapshot_hash": "sha256:snapshot",
                    "content_hash": "sha256:v1",
                },
                {
                    "chapter_version_id": "market:v2",
                    "revision": 2,
                    "filename": "market.v2.json",
                    "assignment_hash": "sha256:assignment",
                    "evidence_snapshot_hash": "sha256:snapshot",
                    "content_hash": "sha256:v2",
                },
            ],
            "accepted_version_id": "market:v2",
        }],
        "content_hash": "",
    }
    payload["content_hash"] = _digest({key: value for key, value in payload.items() if key != "content_hash"})
    index = AnalystChapterIndex.model_validate(payload)
    assert [item.revision for item in index.chapters[0].versions] == [1, 2]


def test_short_chapter_body_is_not_a_hard_schema_failure():
    assert len(_chapter().subsections[0].body) < 600
