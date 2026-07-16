import asyncio

import pytest

from modules.spatial_action.report_orchestration import OrchestrationError, SpatialReportOrchestrator


QUESTION = {
    "question_id": "question:project-role",
    "text": "项目首期应承担什么角色？",
    "decision_target": "project_role",
    "hypotheses": [
        {
            "hypothesis_id": "hypothesis:bounded-role",
            "statement": "可逆的公共服务与文化展示适合作为首期角色。",
            "disconfirming_condition": "文件约束或试点反馈否定该角色。",
        }
    ],
}


def _blueprint(run_id="run:dynamic"):
    return {
        "schema_version": "2.0",
        "run_id": run_id,
        "blueprint_id": "blueprint:dynamic",
        "analysis_scope": "full_project",
        "source_snapshot_hash": "",
        "blueprint_hash": "",
        "report_title": "动态项目报告",
        "project_reading": "项目需要先验证低承诺角色。",
        "core_decisions": ["确定首期角色"],
        "decision_questions": [QUESTION],
        "evidence_plans": [
            {
                "decision_question_id": QUESTION["question_id"],
                "metric_plan_entry_ids": [],
                "document_evidence": [
                    {
                        "plan_id": "document-plan:role",
                        "objective": "核验项目目标和限制",
                        "required_source_ids": ["document:project"],
                        "method": "文档证据审查",
                        "decision_use": "界定首期角色",
                        "failure_effect": "只能保留为待验证方向",
                    }
                ],
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
                "analyst_role": "项目定位分析师",
                "purpose": "形成首期角色判断",
                "decision_question_ids": [QUESTION["question_id"]],
                "subsection_briefs": [
                    {
                        "subsection_id": "subsection:role",
                        "working_title": "首期基础方向",
                        "decision_objective": "解释首期基础方向",
                        "decision_question_ids": [QUESTION["question_id"]],
                        "target_min_characters": 600,
                        "target_max_characters": 1000,
                        "required_argument_elements": ["证据", "机制", "行动", "停止条件"],
                        "visual_intents": [],
                    }
                ],
                "dependencies": [],
                "required_evidence_families": ["document"],
                "visual_intents": [],
            }
        ],
        "excluded_topics": [],
        "report_logic": ["先约束后角色"],
        "shared_glossary": {"首期": "可逆验证阶段"},
        "completeness_rationale": "核心任务已转为问题、证据计划和章节。",
    }


class Provider:
    async def chat_json(self, *, phase, user_payload, **_kwargs):
        if phase == "spatial-project-blueprint":
            return {"blueprint": _blueprint(user_payload["run_id"]), "entries": []}
        if phase == "spatial-blueprint-completeness":
            blueprint = user_payload["project_analysis_blueprint"]
            obligations = [
                "project_goal_translation",
                "evidence_plan_coverage",
                "chapter_or_exclusion_coverage",
                "alternatives_risks_actions_limits",
                "source_issue_coverage",
                "task_answerability",
            ]
            return {
                "schema_version": "2.0",
                "run_id": blueprint["run_id"],
                "review_id": "review:blueprint",
                "blueprint_id": blueprint["blueprint_id"],
                "source_snapshot_hash": blueprint["source_snapshot_hash"],
                "blueprint_hash": blueprint["blueprint_hash"],
                "checks": [
                    {
                        "obligation": item,
                        "status": "passed",
                        "rationale": "已覆盖",
                        "related_question_ids": [QUESTION["question_id"]],
                    }
                    for item in obligations
                ],
                "uncovered_source_issues": [],
                "repair_instructions": [],
                "decision": "accepted",
            }
        if phase == "spatial-evidence-readiness":
            blueprint = user_payload["project_analysis_blueprint"]
            evidence_hash = user_payload["report_visual_catalog"]["evidence_snapshot_hash"]
            assignment = {
                **blueprint["chapter_intents"][0],
                "evidence_access": {
                    "primary_refs": [],
                    "shared_refs": [],
                    "gap_refs": ["document-plan:role"],
                    "visual_refs": [],
                    "forbidden_refs": [],
                },
                "assignment_hash": "",
            }
            return {
                "review": {
                    "schema_version": "2.0",
                    "run_id": blueprint["run_id"],
                    "review_id": "review:readiness",
                    "blueprint_id": blueprint["blueprint_id"],
                    "blueprint_hash": blueprint["blueprint_hash"],
                    "evidence_snapshot_hash": evidence_hash,
                    "question_readiness": [
                        {
                            "decision_question_id": QUESTION["question_id"],
                            "status": "gap_bound",
                            "succeeded_evidence_ids": [],
                            "blocked_plan_entry_ids": ["document-plan:role"],
                            "publication_effect": "作为实验性判断出版",
                        }
                    ],
                    "structure_changes": [],
                    "visual_availability": [],
                    "decision": "ready",
                    "reason": "可使用实验假设继续。",
                },
                "publication_blueprint": {
                    "schema_version": "2.0",
                    "run_id": blueprint["run_id"],
                    "publication_blueprint_id": "publication:dynamic",
                    "blueprint_id": blueprint["blueprint_id"],
                    "blueprint_hash": blueprint["blueprint_hash"],
                    "evidence_snapshot_hash": evidence_hash,
                    "chapter_assignments": [assignment],
                    "structure_rationale": "保留唯一核心问题。",
                    "assignment_bundle_hash": "",
                },
            }
        if phase == "spatial-analyst-chapter":
            assignment = user_payload["chapter_assignment"]
            return {
                "schema_version": "2.0",
                "run_id": user_payload["project_analysis_blueprint"]["run_id"],
                "chapter_id": assignment["chapter_id"],
                "chapter_version_id": "chapter:role:v1",
                "assignment_hash": "",
                "evidence_snapshot_hash": "",
                "content_hash": "",
                "analyst_role": assignment["analyst_role"],
                "title": "首期角色",
                "thesis": "先做可逆验证，不把方向包装成既成事实。",
                "decision_question_ids": [QUESTION["question_id"]],
                "subsections": [
                    {
                        "subsection_id": "subsection:role",
                        "title": "首期基础方向",
                        "body": "社区服务与历史文化展示可作为实验性基础盘；当前没有直接需求和财务证据，因此只能通过可逆试点验证。",
                        "decision_question_ids": [QUESTION["question_id"]],
                        "evidence_ids": [],
                        "object_ids": [],
                        "finding_ids": ["finding:role"],
                        "evidence_gap_ids": ["gap:role-documents"],
                        "argument_units": [
                            {
                                "argument_id": "claim:role",
                                "claim": "首期应采用低承诺基础盘。",
                                "evidence_refs": [],
                                "evidence_gap_refs": ["gap:role-documents"],
                                "evidence_state": "recommendation",
                                "baseline": "与一次性高投入完整改造相比",
                                "mechanism": "可逆试点降低不可逆投入并产生直接反馈。",
                                "project_implication": "先形成小规模公共内容和居民参与原型。",
                                "action": "设置封顶预算和阶段复盘。",
                                "assumptions": ["居民和内容合作方愿意参与"],
                                "stop_condition": "连续试点没有重复参与时停止扩大。",
                            }
                        ],
                        "structured_blocks": [],
                        "visual_refs": [],
                    }
                ],
                "finding_packets": [
                    {
                        "finding_id": "finding:role",
                        "decision_question_id": QUESTION["question_id"],
                        "observed_pattern": "当前方向仍待验证。",
                        "evidence_ids": [],
                        "evidence_state": "experimental_assumption",
                        "mechanism_hypothesis": "可逆试点能够降低承诺。",
                        "project_implication": "首期不应一次性锁定完整业态。",
                        "recommended_action": "启动小规模试点。",
                        "critical_assumption": "试点可以被持续记录。",
                        "disconfirming_test": "没有重复参与则否定。",
                    }
                ],
                "option_comparisons": [
                    {
                        "option_id": "option:pilot",
                        "option_name": "可逆试点",
                        "argument": "投资和组织承诺较低。",
                        "evidence_ids": [],
                        "tradeoffs": ["不能立即形成完整目的地"],
                        "activation_conditions": ["存在基本安全空间"],
                        "stop_condition": "无法形成重复使用。",
                    }
                ],
                "evidence_gaps": [
                    {
                        "gap_id": "gap:role-documents",
                        "decision_question_id": QUESTION["question_id"],
                        "blocked_plan_entry_ids": ["document-plan:role"],
                        "missing_inputs": ["document:project"],
                        "decision_limit": "只能保留为待验证方向",
                        "collection_action": "补充锁定项目文件",
                        "stop_condition": "缺少文件时不得升级为确定定位",
                        "next_run_trigger": "文件进入新 Run",
                    }
                ],
                "assumptions": ["试点空间可用"],
                "veto_conditions": ["安全条件不成立"],
                "cross_chapter_dependencies": [],
                "unresolved_tensions": [],
            }
        if phase == "spatial-editorial-review":
            return {
                "schema_version": "2.0",
                "run_id": user_payload["project_analysis_blueprint"]["run_id"],
                "review_id": "review:editorial",
                "chapter_decisions": [
                    {"chapter_id": "chapter:role", "status": "accepted", "reason": "论证链完整", "repair_instructions": []}
                ],
                "terminology_rules": {},
                "cross_chapter_conflicts": [],
                "executive_judgment": {"text": "先验证再扩大。", "claim_ids": ["claim:role"]},
                "integrated_recommendations": [
                    {"text": "使用封顶预算启动试点。", "claim_ids": ["claim:role"]}
                ],
                "interpretation_boundaries": ["实验假设不是已验证需求"],
                "chapter_order": ["chapter:role"],
                "transitions": [],
                "publication_decision": "ready",
            }
        raise AssertionError(phase)


class RevisionProvider(Provider):
    def __init__(self, *, reject_final: bool = False):
        self.reject_final = reject_final

    async def chat_json(self, *, phase, user_payload, **kwargs):
        if phase == "spatial-editorial-review":
            response = await super().chat_json(phase=phase, user_payload=user_payload, **kwargs)
            response["chapter_decisions"] = [
                {
                    "chapter_id": "chapter:role",
                    "status": "revise",
                    "reason": "需要补足停止条件表述",
                    "repair_instructions": ["明确停止条件"],
                }
            ]
            response["publication_decision"] = "revise"
            return response
        if phase == "spatial-analyst-chapter-repair":
            chapter = dict(user_payload["previous_chapter"])
            chapter["chapter_version_id"] = "chapter:role:v2"
            chapter["content_hash"] = ""
            chapter["thesis"] = "先做可逆验证，并以明确停止条件约束扩大。"
            return chapter
        if phase == "spatial-editorial-review-final":
            response = await super().chat_json(
                phase="spatial-editorial-review", user_payload=user_payload, **kwargs
            )
            if self.reject_final:
                response["chapter_decisions"] = [
                    {
                        "chapter_id": "chapter:role",
                        "status": "revise",
                        "reason": "仍不合格",
                        "repair_instructions": ["再次修订"],
                    }
                ]
                response["publication_decision"] = "revise"
            return response
        return await super().chat_json(phase=phase, user_payload=user_payload, **kwargs)


def test_dynamic_blueprint_and_direct_chapter_flow_without_report_draft():
    orchestrator = SpatialReportOrchestrator(provider=Provider())
    blueprint, completeness, agenda, entries = asyncio.run(
        orchestrator.plan_project(
            project_documents={"project_name": "示例项目"},
            source_versions=[],
            data_preview={},
            run_id="run:dynamic",
            user_question="形成完整项目判断",
        )
    )
    assert entries == []
    assert completeness["decision"] == "accepted"
    result = asyncio.run(
        orchestrator.author_and_assemble(
            project_analysis_blueprint=blueprint,
            blueprint_completeness_review=completeness,
            decision_agenda=agenda,
            metric_plan_entries=entries,
            metric_attempts=[],
            evidence_nodes=[],
            spatial_action_map={},
            project_documents={"project_name": "示例项目"},
            diagnostics=[],
        )
    )
    chapters, chapter_versions, _visuals, readiness, publication, review, claims, assembly = result
    assert chapters[0]["subsections"][0]["body"].startswith("社区服务")
    assert chapter_versions == chapters
    assert readiness["decision"] == "ready"
    assert publication["chapter_assignments"][0]["assignment_hash"]
    assert claims["claims"][0]["claim_id"] == "claim:role"
    assert assembly["authored_by"] == "main_agent_editor"
    assert "sections" not in assembly
    assert review["publication_decision"] == "ready"


def _run_revision_flow(provider):
    orchestrator = SpatialReportOrchestrator(provider=provider)
    blueprint, completeness, agenda, entries = asyncio.run(
        orchestrator.plan_project(
            project_documents={"project_name": "示例项目"},
            source_versions=[],
            data_preview={},
            run_id="run:dynamic",
            user_question="形成完整项目判断",
        )
    )
    return asyncio.run(
        orchestrator.author_and_assemble(
            project_analysis_blueprint=blueprint,
            blueprint_completeness_review=completeness,
            decision_agenda=agenda,
            metric_plan_entries=entries,
            metric_attempts=[],
            evidence_nodes=[],
            spatial_action_map={},
            project_documents={"project_name": "示例项目"},
            diagnostics=[],
        )
    )


def test_targeted_revision_preserves_v1_and_accepts_v2():
    accepted, versions, *_rest = _run_revision_flow(RevisionProvider())
    assert [item["chapter_version_id"] for item in versions] == [
        "chapter:role:v1",
        "chapter:role:v2",
    ]
    assert accepted[0]["chapter_version_id"] == "chapter:role:v2"


def test_second_editorial_failure_sets_chapter_failed():
    with pytest.raises(OrchestrationError) as exc_info:
        _run_revision_flow(RevisionProvider(reject_final=True))
    assert exc_info.value.run_status == "chapter_failed"
