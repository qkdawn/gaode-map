import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from modules.agent.analysis_runs import AnalysisRun
from modules.spatial_action.report_orchestration import (
    ArgumentUnit,
    AnalystChapterPackage,
    ChapterAssignment,
    EditorialReview,
    ProjectAnalysisBlueprint,
    ReportAssembly,
    ReportVisualCandidate,
    SpatialReportOrchestrator,
    StructuredBlock,
    _digest,
    build_evidence_execution_artifacts,
    build_first_lock_artifacts,
    build_accepted_claim_registry,
)


QUESTION = {
    "question_id": "question:role",
    "text": "首期项目角色是什么？",
    "decision_target": "project_role",
    "hypotheses": [
        {
            "hypothesis_id": "hypothesis:service",
            "statement": "社区服务适合作为首期基础。",
            "disconfirming_condition": "直接证据否定居民使用。",
        }
    ],
}


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fixture(tmp_path: Path):
    evidence = [
        {
            "id": "evidence:documents",
            "title": "项目文件",
            "summary": "文件确认居民持续存在并要求历史建筑活化。",
            "content": "文件确认居民持续存在并要求历史建筑活化。",
            "quality_flags": [],
        }
    ]
    blueprint = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "blueprint_id": "blueprint:1",
        "analysis_scope": "full_project",
        "source_snapshot_hash": "sha256:source",
        "blueprint_hash": "",
        "report_title": "动态章节项目报告",
        "project_reading": "项目需要从低承诺方向开始。",
        "core_decisions": ["确定首期角色"],
        "decision_questions": [QUESTION],
        "evidence_plans": [
            {
                "decision_question_id": "question:role",
                "metric_plan_entry_ids": ["plan:documents"],
                "document_evidence": [],
                "spatial_evidence": [],
                "comparisons": [],
                "evidence_gap_plans": [],
            }
        ],
        "chapter_intents": [
            {
                "chapter_id": "chapter:role",
                "order": 1,
                "working_title": "首期角色",
                "analyst_role": "定位分析师",
                "purpose": "形成首期角色判断",
                "decision_question_ids": ["question:role"],
                "subsection_briefs": [
                    {
                        "subsection_id": "subsection:role",
                        "working_title": "首期基础方向",
                        "decision_objective": "解释基础方向",
                        "decision_question_ids": ["question:role"],
                        "target_min_characters": 600,
                        "target_max_characters": 1000,
                        "required_argument_elements": ["证据", "基准", "机制", "行动", "停止条件"],
                        "visual_intents": [],
                    }
                ],
                "dependencies": [],
                "required_evidence_families": ["document"],
                "visual_intents": [],
            }
        ],
        "excluded_topics": [],
        "report_logic": ["先约束再定位"],
        "shared_glossary": {},
        "completeness_rationale": "目标、问题、证据计划和章节一一对应。",
    }
    blueprint["blueprint_hash"] = _digest({key: value for key, value in blueprint.items() if key != "blueprint_hash"})
    checks = [
        "project_goal_translation",
        "evidence_plan_coverage",
        "chapter_or_exclusion_coverage",
        "alternatives_risks_actions_limits",
        "source_issue_coverage",
        "task_answerability",
    ]
    completeness = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "review_id": "review:blueprint",
        "blueprint_id": "blueprint:1",
        "source_snapshot_hash": "sha256:source",
        "blueprint_hash": blueprint["blueprint_hash"],
        "checks": [
            {"obligation": item, "status": "passed", "rationale": "通过", "related_question_ids": ["question:role"]}
            for item in checks
        ],
        "uncovered_source_issues": [],
        "repair_instructions": [],
        "decision": "accepted",
    }
    evidence_hash = _digest(evidence)
    assignment = {
        **blueprint["chapter_intents"][0],
        "evidence_access": {
            "primary_refs": ["evidence:documents"],
            "shared_refs": [],
            "gap_refs": [],
            "visual_refs": [],
            "forbidden_refs": [],
        },
        "assignment_hash": "",
    }
    assignment["assignment_hash"] = _digest({key: value for key, value in assignment.items() if key != "assignment_hash"})
    publication = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "publication_blueprint_id": "publication:1",
        "blueprint_id": "blueprint:1",
        "blueprint_hash": blueprint["blueprint_hash"],
        "evidence_snapshot_hash": evidence_hash,
        "chapter_assignments": [assignment],
        "structure_rationale": "证据足以支持一个直接章节。",
        "assignment_bundle_hash": "",
    }
    publication["assignment_bundle_hash"] = _digest(
        {key: value for key, value in publication.items() if key != "assignment_bundle_hash"}
    )
    readiness = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "review_id": "review:readiness",
        "blueprint_id": "blueprint:1",
        "blueprint_hash": blueprint["blueprint_hash"],
        "evidence_snapshot_hash": evidence_hash,
        "question_readiness": [
            {
                "decision_question_id": "question:role",
                "status": "ready",
                "succeeded_evidence_ids": ["evidence:documents"],
                "blocked_plan_entry_ids": [],
                "publication_effect": "形成分析章节",
            }
        ],
        "structure_changes": [],
        "visual_availability": [],
        "decision": "ready",
        "reason": "文档证据可用。",
    }
    body = "项目文件确认居民持续存在并要求历史建筑活化，因此首期基础盘应先建立居民共生和可更新的文化解释机制，而不能直接宣布已经形成区域文化地标。[[cite:evidence:documents]]"
    chapter = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "chapter_id": "chapter:role",
        "chapter_version_id": "chapter:role:v1",
        "assignment_hash": assignment["assignment_hash"],
        "evidence_snapshot_hash": evidence_hash,
        "content_hash": "",
        "analyst_role": "定位分析师",
        "title": "首期角色与基础方向",
        "thesis": "以居民共生和历史文化展示形成低承诺基础盘。",
        "decision_question_ids": ["question:role"],
        "subsections": [
            {
                "subsection_id": "subsection:role",
                "title": "首期基础方向",
                "body": body,
                "decision_question_ids": ["question:role"],
                "evidence_ids": ["evidence:documents"],
                "object_ids": [],
                "finding_ids": ["finding:role"],
                "evidence_gap_ids": [],
                "argument_units": [
                    {
                        "argument_id": "claim:role",
                        "claim": "社区服务与历史文化展示适合作为首期基础盘。",
                        "evidence_refs": ["evidence:documents"],
                        "evidence_gap_refs": [],
                        "evidence_state": "inference",
                        "baseline": "与直接启动高投入目的地改造相比",
                        "mechanism": "居民共生和可更新内容能以较低承诺启动运营学习。",
                        "project_implication": "首期应选择可独立关闭和可逆布置的试点单元。",
                        "action": "建立居民协商、内容更新和封顶预算机制。",
                        "assumptions": ["试点空间通过安全核验"],
                        "stop_condition": "没有重复参与或居民共生失败时停止扩大。",
                    }
                ],
                "structured_blocks": [],
                "visual_refs": [],
            }
        ],
        "finding_packets": [
            {
                "finding_id": "finding:role",
                "decision_question_id": "question:role",
                "observed_pattern": "文件同时确认居民持续存在和历史建筑活化责任。",
                "evidence_ids": ["evidence:documents"],
                "evidence_state": "inference",
                "mechanism_hypothesis": "低承诺基础盘可以同时满足公共责任和运营学习。",
                "project_implication": "首期不能直接锁定高投入目的地。",
                "recommended_action": "开展可逆试点。",
                "critical_assumption": "居民共生机制可建立。",
                "disconfirming_test": "居民冲突或无重复参与。",
            }
        ],
        "option_comparisons": [
            {
                "option_id": "option:foundation",
                "option_name": "低承诺基础盘",
                "argument": "更符合现有证据和可逆原则。",
                "evidence_ids": ["evidence:documents"],
                "tradeoffs": ["短期不形成完整目的地"],
                "activation_conditions": ["安全条件可控"],
                "stop_condition": "无法建立居民共生。",
            }
        ],
        "evidence_gaps": [],
        "assumptions": ["试点空间可用"],
        "veto_conditions": ["安全核验失败"],
        "cross_chapter_dependencies": [],
        "unresolved_tensions": [],
    }
    chapter["content_hash"] = _digest({key: value for key, value in chapter.items() if key != "content_hash"})
    chapter_filename = "chapter-role.v1.json"
    index = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "chapters": [
            {
                "chapter_id": "chapter:role",
                "chapter_version_id": "chapter:role:v1",
                "filename": chapter_filename,
                "assignment_hash": assignment["assignment_hash"],
                "evidence_snapshot_hash": evidence_hash,
                "content_hash": chapter["content_hash"],
                "accepted": True,
            }
        ],
    }
    visual_catalog = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "catalog_id": "visual:catalog",
        "evidence_snapshot_hash": evidence_hash,
        "candidates": [],
    }
    review = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "review_id": "review:editorial",
        "chapter_decisions": [
            {"chapter_id": "chapter:role", "status": "accepted", "reason": "通过", "repair_instructions": []}
        ],
        "terminology_rules": {},
        "cross_chapter_conflicts": [],
        "executive_judgment": {"text": "首期先建立低承诺基础盘。", "claim_ids": ["claim:role"]},
        "integrated_recommendations": [
            {"text": "以可逆试点验证居民共生和内容更新。", "claim_ids": ["claim:role"]}
        ],
        "interpretation_boundaries": ["当前结论不等于直接需求和财务可行性已验证"],
        "chapter_order": ["chapter:role"],
        "transitions": [],
        "publication_decision": "ready",
    }
    registry = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "registry_id": "claims:1",
        "editorial_review_id": "review:editorial",
        "evidence_snapshot_hash": evidence_hash,
        "claims": [
            {
                "claim_id": "claim:role",
                "source_type": "argument_unit",
                "source_chapter_id": "chapter:role",
                "argument_id": "claim:role",
                "source_conflict_id": "",
                "claim": "社区服务与历史文化展示适合作为首期基础盘。",
                "evidence_refs": ["evidence:documents"],
                "evidence_gap_refs": [],
                "evidence_state": "inference",
                "baseline": "与直接启动高投入目的地改造相比",
                "scope": "question:role",
            }
        ],
        "registry_hash": "",
    }
    registry["registry_hash"] = _digest({key: value for key, value in registry.items() if key != "registry_hash"})
    assembly = {
        "schema_version": "2.0",
        "run_id": "run:dynamic",
        "assembly_id": "assembly:1",
        "authored_by": "main_agent_editor",
        "delivery_profile": "adaptive_project",
        "title": "动态章节项目报告",
        "blueprint_id": "blueprint:1",
        "editorial_review_id": "review:editorial",
        "accepted_claim_registry_id": "claims:1",
        "chapter_refs": [{"chapter_id": "chapter:role", "chapter_version_id": "chapter:role:v1"}],
        "executive_judgment": review["executive_judgment"],
        "integrated_recommendations": review["integrated_recommendations"],
        "interpretation_boundaries": review["interpretation_boundaries"],
        "transitions": [],
        "positioning_directions": [],
    }
    run = AnalysisRun.model_validate(
        {
            "run_id": "run:dynamic",
            "capability_id": "spatial-business-analyst",
            "manifest_sha256": "",
            "catalog_version": "2.0.0",
            "status": "completed_with_warnings",
            "decision_agenda": {
                "agenda_id": "blueprint:1",
                "user_question": "形成完整项目判断",
                "analysis_scope": "full_project",
                "decision_questions": [QUESTION],
            },
            "metric_plan": {
                "catalog_version": "2.0.0",
                "decision_questions": [QUESTION],
                "entries": [
                    {
                        "plan_entry_id": "plan:documents",
                        "metric_id": "project.document_constraints",
                        "role": "primary",
                        "decision_question_id": "question:role",
                        "hypothesis_ids": ["hypothesis:service"],
                        "planned_spatial_target": {"unit": "scope", "source": "project_documents", "runtime_parameters": []},
                        "selection_reason": "核验项目约束。",
                        "expected_decision_use": "界定首期角色。",
                        "required_source_ids": ["document:project"],
                        "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                        "exclusion_reason": "",
                    }
                ],
            },
            "metric_attempts": [
                {
                    "plan_entry_id": "plan:documents",
                    "metric_id": "project.document_constraints",
                    "spatial_target": {"unit": "scope", "target_id": "scope:project"},
                    "execution_status": "succeeded",
                    "reason": "",
                    "evidence_node_ids": ["evidence:documents"],
                }
            ],
            "created_at": "2026-07-16T00:00:00Z",
            "completed_at": "2026-07-16T00:01:00Z",
        }
    )
    run.manifest_sha256 = run.canonical_manifest_sha256()
    blueprint_model = ProjectAnalysisBlueprint.model_validate(blueprint)
    evidence_plan, question_lock = build_first_lock_artifacts(blueprint_model)
    evidence_attempts, evidence_gates = build_evidence_execution_artifacts(
        blueprint=blueprint_model,
        evidence_plan=evidence_plan,
        metric_plan_entries=[item.model_dump(mode="json") for item in run.metric_plan.entries],
        metric_attempts=[item.model_dump(mode="json") for item in run.metric_attempts],
        evidence_nodes=evidence,
    )
    paths = {
        "blueprint": tmp_path / "artifacts" / "project-analysis-blueprint.json",
        "completeness": tmp_path / "artifacts" / "blueprint-completeness-review.json",
        "evidence_plan": tmp_path / "artifacts" / "evidence-plan.json",
        "question_lock": tmp_path / "artifacts" / "question-evidence-plan-lock.json",
        "readiness": tmp_path / "artifacts" / "evidence-readiness-review.json",
        "publication": tmp_path / "artifacts" / "chapter-assignments.json",
        "index": tmp_path / "artifacts" / "analyst-chapters.json",
        "chapter": tmp_path / "chapters" / chapter_filename,
        "visuals": tmp_path / "artifacts" / "report-visual-catalog.json",
        "review": tmp_path / "artifacts" / "editorial-review.json",
        "registry": tmp_path / "artifacts" / "accepted-claim-registry.json",
        "assembly": tmp_path / "artifacts" / "report-assembly.json",
        "manifest": tmp_path / "analysis-run.json",
        "evidence": tmp_path / "evidence" / "evidence-nodes.json",
        "attempts": tmp_path / "diagnostics" / "metric-attempts.json",
        "evidence_attempts": tmp_path / "diagnostics" / "evidence-attempts.json",
        "evidence_gates": tmp_path / "evidence" / "evidence-gates.json",
        "output": tmp_path / "report" / "project-report.md",
    }
    for key, payload in (
        ("blueprint", blueprint), ("completeness", completeness),
        ("evidence_plan", evidence_plan.model_dump(mode="json")),
        ("question_lock", question_lock.model_dump(mode="json")), ("readiness", readiness),
        ("publication", publication), ("index", index), ("chapter", chapter), ("visuals", visual_catalog),
        ("review", review), ("registry", registry), ("assembly", assembly),
        ("manifest", run.model_dump(mode="json")), ("evidence", {"evidence_nodes": evidence}),
        ("attempts", {"metric_attempts": run.metric_attempts and [item.model_dump(mode="json") for item in run.metric_attempts]}),
        ("evidence_attempts", evidence_attempts.model_dump(mode="json")),
        ("evidence_gates", evidence_gates.model_dump(mode="json")),
    ):
        _write(paths[key], payload)
    return paths, body


def test_argument_unit_requires_baseline():
    with pytest.raises(ValidationError):
        ArgumentUnit.model_validate(
            {
                "argument_id": "claim:1", "claim": "判断", "evidence_refs": [], "evidence_gap_refs": [],
                "evidence_state": "experimental_assumption", "baseline": "", "mechanism": "机制",
                "project_implication": "影响", "action": "行动", "assumptions": ["假设"], "stop_condition": "停止",
            }
        )


def test_short_prose_is_not_a_schema_failure_when_argument_chain_is_complete():
    assert ArgumentUnit.model_validate(
        {
            "argument_id": "claim:1", "claim": "判断", "evidence_refs": [], "evidence_gap_refs": [],
            "evidence_state": "experimental_assumption", "baseline": "与高投入方案相比", "mechanism": "机制",
            "project_implication": "影响", "action": "行动", "assumptions": ["假设"], "stop_condition": "停止",
        }
    ).claim == "判断"


def test_blueprint_requires_one_evidence_plan_per_question(tmp_path: Path):
    payload = _fixture(tmp_path)[0]
    blueprint = json.loads(payload["blueprint"].read_text(encoding="utf-8"))
    blueprint["evidence_plans"] = []
    with pytest.raises(ValidationError):
        ProjectAnalysisBlueprint.model_validate(blueprint)


def test_zero_metric_document_evidence_plan_has_a_deterministic_attempt(tmp_path: Path):
    paths, _ = _fixture(tmp_path)
    payload = json.loads(paths["blueprint"].read_text(encoding="utf-8"))
    payload["evidence_plans"] = [
        {
            "decision_question_id": "question:role",
            "metric_plan_entry_ids": [],
            "document_evidence": [
                {
                    "plan_id": "document-plan:role",
                    "objective": "核验项目文件中的居民与保护约束",
                    "required_source_ids": ["document:project-extracts"],
                    "method": "读取锁定的项目文件提取快照",
                    "decision_use": "界定首期角色",
                    "failure_effect": "缺少项目文件时不得形成首期定位判断",
                }
            ],
            "spatial_evidence": [],
            "comparisons": [],
            "evidence_gap_plans": [],
        }
    ]
    payload["blueprint_hash"] = ""
    payload["blueprint_hash"] = _digest({key: value for key, value in payload.items() if key != "blueprint_hash"})
    blueprint = ProjectAnalysisBlueprint.model_validate(payload)
    evidence_plan, question_lock = build_first_lock_artifacts(blueprint)
    attempts, gates = build_evidence_execution_artifacts(
        blueprint=blueprint,
        evidence_plan=evidence_plan,
        metric_plan_entries=[],
        metric_attempts=[],
        evidence_nodes=[
            {
                "id": "evidence:project-documents",
                "source_ids": ["document:project-extracts"],
            }
        ],
    )
    assert question_lock.evidence_plan_hash == evidence_plan.evidence_plan_hash
    assert attempts.attempts[0].execution_status == "succeeded"
    assert attempts.attempts[0].kind == "document"
    assert attempts.attempts[0].evidence_node_ids == ["evidence:project-documents"]
    assert gates.gates == []


def test_explicit_gap_plan_becomes_registered_attempt_and_evidence_gate(tmp_path: Path):
    paths, _ = _fixture(tmp_path)
    payload = json.loads(paths["blueprint"].read_text(encoding="utf-8"))
    payload["evidence_plans"] = [
        {
            "decision_question_id": "question:role",
            "metric_plan_entry_ids": [],
            "document_evidence": [],
            "spatial_evidence": [],
            "comparisons": [],
            "evidence_gap_plans": [
                {
                    "plan_id": "gap-plan:visits",
                    "objective": "补充分时客流",
                    "required_source_ids": ["survey:hourly-visits"],
                    "method": "连续工作日与周末现场计数",
                    "decision_use": "进入下一 Run 后判断运营时段",
                    "failure_effect": "当前不得推导营业额或高峰承载量",
                }
            ],
        }
    ]
    payload["blueprint_hash"] = ""
    payload["blueprint_hash"] = _digest({key: value for key, value in payload.items() if key != "blueprint_hash"})
    blueprint = ProjectAnalysisBlueprint.model_validate(payload)
    evidence_plan, _ = build_first_lock_artifacts(blueprint)
    attempts, gates = build_evidence_execution_artifacts(
        blueprint=blueprint,
        evidence_plan=evidence_plan,
        metric_plan_entries=[],
        metric_attempts=[],
        evidence_nodes=[],
    )
    assert attempts.attempts[0].execution_status == "registered_gap"
    assert gates.gates[0].plan_ref_ids == ["gap-plan:visits"]
    assert gates.gates[0].decision_limit == "当前不得推导营业额或高峰承载量"


def test_accepted_claim_registry_includes_explicit_conflict_ruling(tmp_path: Path):
    paths, _ = _fixture(tmp_path)
    first_payload = json.loads(paths["chapter"].read_text(encoding="utf-8"))
    second_payload = copy.deepcopy(first_payload)
    second_payload["chapter_id"] = "chapter:role-2"
    second_payload["chapter_version_id"] = "chapter:role-2:v1"
    second_payload["subsections"][0]["argument_units"][0]["argument_id"] = "claim:role-2"
    second_payload["subsections"][0]["argument_units"][0]["claim"] = "高投入完整改造应立即启动。"
    second_payload["content_hash"] = ""
    chapters = [
        AnalystChapterPackage.model_validate(first_payload),
        AnalystChapterPackage.model_validate(second_payload),
    ]
    review = EditorialReview.model_validate(
        {
            "schema_version": "2.0",
            "run_id": "run:dynamic",
            "review_id": "review:conflict",
            "chapter_decisions": [
                {"chapter_id": "chapter:role", "status": "accepted", "reason": "通过", "repair_instructions": []},
                {"chapter_id": "chapter:role-2", "status": "accepted", "reason": "通过", "repair_instructions": []},
            ],
            "terminology_rules": {},
            "cross_chapter_conflicts": [
                {
                    "conflict_id": "conflict:commitment",
                    "chapter_ids": ["chapter:role", "chapter:role-2"],
                    "tension": "首期承诺水平冲突",
                    "evidence_ids": ["evidence:documents"],
                    "claim_ids": ["claim:role", "claim:role-2"],
                    "resolution": "采用低承诺试点，待直接需求证据形成后再升级。",
                    "repair_chapter_ids": [],
                }
            ],
            "executive_judgment": {"text": "先试点。", "claim_ids": ["claim:role"]},
            "integrated_recommendations": [{"text": "设置证据门。", "claim_ids": ["claim:role"]}],
            "interpretation_boundaries": ["当前缺少直接需求证据"],
            "chapter_order": ["chapter:role", "chapter:role-2"],
            "transitions": [],
            "publication_decision": "ready",
        }
    )
    registry = build_accepted_claim_registry(chapters, review, "sha256:evidence")
    ruling = next(item for item in registry.claims if item.source_type == "conflict_ruling")
    assert ruling.claim_id == "conflict:commitment"
    assert ruling.evidence_state == "inference"


def test_structured_block_renderer_preserves_domain_specific_item_fields():
    compiler_path = Path(__file__).resolve().parents[2] / "skills" / "spatial-business-analyst" / "scripts" / "compile_project_report.py"
    spec = importlib.util.spec_from_file_location("spatial_report_compiler_test", compiler_path)
    assert spec and spec.loader
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    payload = {
            "block_id": "block:gates",
            "kind": "evidence_gate",
            "title": "三道证据门",
            "purpose": "避免结构块字段丢失",
            "evidence_ids": ["evidence:one"],
            "evidence_gap_ids": [],
            "columns": [],
            "rows": [],
            "items": [
                {
                    "gate": "正式边界与入口",
                    "collect": "红线、入口坐标和开放限制",
                    "pass": "由权威主体确认",
                    "blocks": "入口排名与永久工程",
                }
            ],
        }
    block = StructuredBlock.model_validate(payload)
    rendered = "\n".join(compiler._render_structured_block(block, {"evidence:one": "E1"}))
    assert "**正式边界与入口**" in rendered
    assert "补证动作：红线、入口坐标和开放限制" in rendered
    assert "通过标准：由权威主体确认" in rendered
    assert "阻止的决策：入口排名与永久工程" in rendered
    reordered = copy.deepcopy(payload)
    reordered["items"] = [dict(reversed(list(payload["items"][0].items())))]
    reordered_rendered = "\n".join(
        compiler._render_structured_block(
            StructuredBlock.model_validate(reordered), {"evidence:one": "E1"}
        )
    )
    assert reordered_rendered == rendered


def test_chapter_must_place_every_assigned_visual(tmp_path: Path):
    paths, _ = _fixture(tmp_path)
    publication = json.loads(paths["publication"].read_text(encoding="utf-8"))
    assignment_payload = publication["chapter_assignments"][0]
    assignment_payload["evidence_access"]["visual_refs"] = ["visual:one"]
    assignment = ChapterAssignment.model_validate(assignment_payload)
    chapter = AnalystChapterPackage.model_validate(
        json.loads(paths["chapter"].read_text(encoding="utf-8"))
    )
    visual = ReportVisualCandidate.model_validate(
        {
            "schema_version": "2.0",
            "run_id": "run:dynamic",
            "visual_id": "visual:one",
            "visual_type": "bar",
            "title": "项目文件证据",
            "purpose": "支持首期角色判断",
            "evidence_ids": ["evidence:documents"],
            "source_artifact": "evidence-nodes.json",
            "object_ids": [],
            "filename": "visual-one.svg",
            "metric_attempt_ids": ["plan:documents"],
            "transform": "identity",
            "coordinate_system": "",
            "extent": [],
            "geometry_sources": [],
            "spec_hash": "sha256:spec",
            "asset_hash": "sha256:asset",
            "data": {"categories": ["文件"], "values": [1]},
        }
    )
    with pytest.raises(ValueError, match="place and interpret every assigned visual"):
        SpatialReportOrchestrator._validate_chapter(
            chapter,
            assignment=assignment,
            plan_ref_questions={"plan:documents": "question:role"},
            successful_evidence_ids={"evidence:documents"},
            blocked_attempts={},
            object_ids=set(),
            visual_by_id={"visual:one": visual},
            evidence_snapshot_hash="sha256:evidence",
            run_id="run:dynamic",
            expected_revision=1,
        )


def test_report_assembly_rejects_main_agent_chapter_body(tmp_path: Path):
    paths, _ = _fixture(tmp_path)
    assembly = json.loads(paths["assembly"].read_text(encoding="utf-8"))
    assembly["sections"] = [{"title": "不允许", "body": "主 Agent 代写"}]
    with pytest.raises(ValidationError):
        ReportAssembly.model_validate(assembly)


def test_compiler_public_cli_accepts_only_the_schema_v3_run_directory():
    command = [
        sys.executable,
        "skills/spatial-business-analyst/scripts/compile_project_report.py",
        "--help",
    ]
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--run-dir" in result.stdout
    assert "--validate-only" in result.stdout
    assert "--evidence-plan" not in result.stdout
    assert "--claim-registry" not in result.stdout
