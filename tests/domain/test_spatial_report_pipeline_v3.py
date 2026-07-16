import asyncio

from modules.spatial_action.report_pipeline_v3 import (
    SpatialReportOrchestratorV3,
    build_evidence_snapshot,
    build_metric_execution_plan,
)
from tests.domain.test_spatial_business_report_contracts_v3 import _blueprint


def test_capability_plan_is_private_and_snapshot_keeps_terminal_lineage():
    blueprint = _blueprint()
    entries, mapping = build_metric_execution_plan(blueprint)
    assert entries[0]["metric_id"] == "project.document_constraints"
    assert mapping[entries[0]["plan_entry_id"]] == "requirement:documents"
    snapshot, assets = build_evidence_snapshot(
        blueprint=blueprint,
        metric_attempts=[{
            "plan_entry_id": entries[0]["plan_entry_id"],
            "metric_id": entries[0]["metric_id"],
            "execution_status": "succeeded",
            "evidence_node_ids": ["evidence:documents"],
        }],
        evidence_nodes=[{
            "id": "evidence:documents",
            "title": "项目约束",
            "evidence_state": "measured",
            "source_refs": ["document:project"],
            "scope": {"scope_id": "project"},
            "data": {"constraint_count": 2},
            "limitations": [],
        }],
        spatial_action_map={},
    )
    assert snapshot.evidence[0].state == "measured"
    assert snapshot.execution_lineage.attempts[0].metric_id == "project.document_constraints"
    assert "execution_lineage" not in snapshot.public_projection()
    assert assets == {}


def test_failed_capability_becomes_public_gap_not_positive_evidence():
    blueprint = _blueprint()
    entries, _ = build_metric_execution_plan(blueprint)
    snapshot, _ = build_evidence_snapshot(
        blueprint=blueprint,
        metric_attempts=[{
            "plan_entry_id": entries[0]["plan_entry_id"],
            "metric_id": entries[0]["metric_id"],
            "execution_status": "blocked",
            "reason": "missing source",
            "evidence_node_ids": [],
        }],
        evidence_nodes=[],
        spatial_action_map={},
    )
    assert snapshot.evidence == []
    assert snapshot.gaps[0].requirement_id == "requirement:documents"
    assert snapshot.question_readiness == {"question:role": "gap_bound"}


def test_planner_embeds_independent_review_and_seals_the_first_lock():
    class Provider:
        def __init__(self):
            self.responses = [
                {
                    "blueprint_id": "blueprint:test",
                    "analysis_scope": "full_project",
                    "report_title": "项目报告",
                    "project_judgment": "需要决定首期角色。",
                    "decision_questions": [_blueprint().decision_questions[0].model_dump(mode="json")],
                    "evidence_requirements": [_blueprint().evidence_requirements[0].model_dump(mode="json")],
                    "excluded_topics": [{"topic": "收入预测", "reason": "缺少直接证据"}],
                    "report_logic": ["先约束后方向"],
                    "shared_glossary": {},
                },
                {"status": "accepted", "findings": []},
            ]

        async def chat_json(self, **_kwargs):
            return self.responses.pop(0)

    result = asyncio.run(SpatialReportOrchestratorV3(provider=Provider()).plan_project_v3(
        run_id="run:planner",
        project_documents={"documents": []},
        source_versions=[],
        data_preview={},
    ))
    assert result.schema_version == "3.0"
    assert result.completeness_review.status == "accepted"
    assert result.lock.content_hash.startswith("sha256:")
