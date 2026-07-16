from __future__ import annotations

import importlib.util
from pathlib import Path

from shapely.geometry import LineString, Point, box

from modules.agent.analysis_runs import AnalysisRun
from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.project_context import ProjectSpatialAnalysisService
from modules.spatial_action import project_context as project_context_module

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "skills" / "spatial-business-analyst" / "scripts" / "run_latest_project_analysis_v3.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("latest_project_analysis_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(source_id: str, record_id: str, geometry, **properties) -> ScopeRecord:
    return ScopeRecord(source_id=source_id, record_id=record_id, title=record_id, content=record_id, properties=properties, raw={}, time_scope={}, locator=record_id, citation="fixture", geometry=geometry)


class _Datasets:
    def __init__(self):
        self.poi = {
            2020: [_record("current:dataset:poi", "poi-20", Point(112.0, 28.0), category="food")],
            2024: [_record("current:dataset:poi", "poi-24", Point(112.0, 28.0), category="food"), _record("current:dataset:poi", "poi-24b", Point(112.01, 28.01), category="culture")],
        }
        self.grid = [
            _record("current:dataset:poi_grid", "g1", box(112, 28, 112.01, 28.01), density_poi_per_km2=100, gi_star_z_score=1),
            _record("current:dataset:poi_grid", "g2", box(112.01, 28, 112.02, 28.01), density_poi_per_km2=90, gi_star_z_score=1),
            _record("current:dataset:poi_grid", "g3", box(112.02, 28, 112.03, 28.01), density_poi_per_km2=1, gi_star_z_score=-1),
        ]
        self.roads = [
            _record("current:dataset:road_edges", "r1", LineString([(112.005, 28.005), (112.018, 28.005)]), integration_score=9, choice_score=8, connectivity_score=4, depth_score=1),
            _record("current:dataset:road_edges", "r2", LineString([(112.02, 28.005), (112.03, 28.005)]), integration_score=1, choice_score=1, connectivity_score=1, depth_score=9),
        ]

    def list_scope_datasets(self, _history_id):
        return {"datasets": [{"source_id": source, "status": "ready"} for source in ("current:dataset:poi", "current:dataset:poi_grid", "current:dataset:road_edges")], "warnings": []}

    def load_scope_records(self, *, source_id, year=None, **_kwargs):
        if source_id == "current:dataset:poi":
            selected = 2024 if year is None else int(year)
            return self.poi[selected], [2020, 2024], selected
        if source_id == "current:dataset:poi_grid":
            return self.grid, [2024], 2024
        if source_id == "current:dataset:road_edges":
            return self.roads, [], None
        return [], [], None


def _documents():
    return {"project_name": "fixture project", "documents": [{"document_id": "d1", "title": "brief", "extracts": [{"text": "居民与消防待核验"}]}], "conflicts": []}


def _questions_and_plan():
    questions = [
        {
            "question_id": "question:context",
            "text": "哪些局部空间对象值得作为第一轮现场观察候选？",
            "decision_target": "public_space",
            "hypotheses": [
                {
                    "hypothesis_id": "hypothesis:context",
                    "statement": "局部 POI 高值与高句法路段的交叉可以形成踏勘优先级。",
                    "disconfirming_condition": "现场显示交叉区没有可进入或可停留的公共界面。",
                }
            ],
        }
    ]
    entries = []
    for index, (metric_id, unit, source, sources) in enumerate(
        [
            ("project.document_constraints", "scope", "project-documents", ["document:project-extracts"]),
            ("poi.category_count", "scope", "poi", ["current:dataset:poi"]),
            ("spatial.gi_star", "grid_cell", "poi-grid", ["current:dataset:poi_grid"]),
            ("road.integration", "road_segment", "road-edges", ["current:dataset:road_edges"]),
            ("road.entrance_distance", "entrance", "formal-entrances", ["history:isochrone"]),
            ("road.walk_detour_ratio", "origin_destination_pair", "validated-pairs", ["history:isochrone"]),
        ],
        start=1,
    ):
        entries.append(
            {
                "plan_entry_id": f"plan:{index}",
                "metric_id": metric_id,
                "role": "primary" if index == 1 else "supporting",
                "decision_question_id": "question:context",
                "hypothesis_ids": ["hypothesis:context"],
                "planned_spatial_target": {"unit": unit, "source": source, "runtime_parameters": []},
                "selection_reason": "fixture metric needed to inspect deterministic spatial objects",
                "expected_decision_use": "support the bounded field-observation decision",
                "required_source_ids": sources,
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "",
            }
        )
    return questions, entries


def test_project_spatial_analysis_executes_only_a_locked_plan_and_preserves_anchor_gap():
    questions, entries = _questions_and_plan()
    result = ProjectSpatialAnalysisService(datasets=_Datasets()).analyze_history_snapshot(
        history_id="history:test",
        history_detail={"params": {"center": [112.0, 28.0], "coord_type": "wgs84"}},
        project_documents=_documents(),
        decision_questions=questions,
        metric_plan_entries=entries,
    )
    assert len(result.spatial_action_map["localized_patterns"][0]["zones"]) >= 1
    assert result.spatial_action_map["road_corridors"]
    assert result.spatial_action_map["action_candidates"]
    assert result.coordinate_alignment["distance_to_project_reference_m"] is None
    assert result.coordinate_alignment["project_reference_proxy"] is None
    assert result.coordinate_alignment["coordinate_consistency"] == "normalized_without_mixed_coordinate_distance"
    attempts = {item["metric_id"]: item for item in result.metric_attempts}
    assert attempts["road.entrance_distance"]["execution_status"] == "blocked"
    assert attempts["road.walk_detour_ratio"]["execution_status"] == "not_applicable"
    assert result.spatial_action_map["diagnostics"]["analysis_center_used_as_entrance"] is False
    assert "report" not in result.__dict__
    assert "finding" not in result.__dict__
    run = AnalysisRun.model_validate({"run_id": "run:fixture", "capability_id": "spatial-business-analyst", "catalog_version": "2.0.0", "source_versions": result.source_versions, "decision_agenda": {"agenda_id": "a", "user_question": "q", "analysis_scope": "focused_diagnostic", "decision_questions": questions}, "metric_plan": {"catalog_version": "2.0.0", "decision_questions": questions, "entries": entries}, "metric_attempts": result.metric_attempts, "status": "completed_with_warnings", "created_at": "2026-07-16T00:00:00Z", "completed_at": "2026-07-16T00:01:00Z"})
    assert run.metric_plan.entries


def test_snapshot_inspection_is_non_evidentiary_and_declares_local_capabilities():
    inspection = ProjectSpatialAnalysisService(datasets=_Datasets()).inspect_history_snapshot(
        history_id="history:test", project_documents=_documents()
    )
    assert inspection["data_preview"]["poi"]["record_count"] == 2
    assert "spatial.gi_star" in inspection["execution_capabilities"]
    assert "evidence" not in str(inspection).lower()


def test_population_and_nightlight_plan_entries_execute_when_sources_are_available(monkeypatch):
    questions, entries = _questions_and_plan()
    for index, (metric_id, source_id) in enumerate(
        [
            ("population.total", "current:dataset:population"),
            ("nightlight.activity_level", "current:dataset:nightlight"),
        ],
        start=20,
    ):
        entries.append(
            {
                "plan_entry_id": f"plan:{index}",
                "metric_id": metric_id,
                "role": "supporting",
                "decision_question_id": "question:context",
                "hypothesis_ids": ["hypothesis:context"],
                "planned_spatial_target": {"unit": "scope", "source": "history-polygon", "runtime_parameters": []},
                "selection_reason": "fixture source adapter",
                "expected_decision_use": "verify project report evidence integration",
                "required_source_ids": [source_id],
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "",
            }
        )
    monkeypatch.setattr(
        ProjectSpatialAnalysisService,
        "_external_source_versions",
        staticmethod(
            lambda: [
                {"source_id": "current:dataset:population", "year": 2026, "sha256": "population", "record_count": 0},
                {"source_id": "current:dataset:nightlight", "year": 2025, "sha256": "nightlight", "record_count": 0},
            ]
        ),
    )
    monkeypatch.setattr(
        project_context_module,
        "get_population_overview",
        lambda *_args, **_kwargs: {"summary": {"total_population": 1234}, "age_distribution": []},
    )
    monkeypatch.setattr(
        project_context_module,
        "get_nightlight_layer",
        lambda *_args, **_kwargs: {"year": 2025, "summary": {"mean_radiance": 8.5}, "analysis": {"activity_level": "medium"}},
    )
    result = ProjectSpatialAnalysisService(datasets=_Datasets()).analyze_history_snapshot(
        history_id="history:test",
        history_detail={"params": {"center": [112.0, 28.0], "coord_type": "wgs84"}, "polygon": [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.0]]},
        project_documents=_documents(),
        decision_questions=questions,
        metric_plan_entries=entries,
    )
    attempts = {item["metric_id"]: item for item in result.metric_attempts}
    assert attempts["population.total"]["execution_status"] == "succeeded"
    assert attempts["nightlight.activity_level"]["execution_status"] == "succeeded"
    assert {node["id"] for node in result.evidence_nodes} >= {
        "evidence:population:scope-profile",
        "evidence:nightlight:scope-profile",
    }


def test_missing_population_and_nightlight_sources_remain_planned_and_blocked(monkeypatch):
    questions, entries = _questions_and_plan()
    for index, (metric_id, source_id) in enumerate(
        [("population.total", "current:dataset:population"), ("nightlight.activity_level", "current:dataset:nightlight")],
        start=30,
    ):
        entries.append(
            {
                "plan_entry_id": f"plan:{index}",
                "metric_id": metric_id,
                "role": "supporting",
                "decision_question_id": "question:context",
                "hypothesis_ids": ["hypothesis:context"],
                "planned_spatial_target": {"unit": "scope", "source": "history-polygon", "runtime_parameters": []},
                "selection_reason": "decision-critical even when unavailable",
                "expected_decision_use": "produce an explicit evidence gap",
                "required_source_ids": [source_id],
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "",
            }
        )
    monkeypatch.setattr(ProjectSpatialAnalysisService, "_external_source_versions", staticmethod(lambda: []))
    result = ProjectSpatialAnalysisService(datasets=_Datasets()).analyze_history_snapshot(
        history_id="history:test",
        history_detail={"params": {"center": [112.0, 28.0], "coord_type": "wgs84"}, "polygon": [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.0]]},
        project_documents=_documents(),
        decision_questions=questions,
        metric_plan_entries=entries,
    )
    attempts = {item["metric_id"]: item for item in result.metric_attempts}
    assert attempts["population.total"]["execution_status"] == "blocked"
    assert attempts["nightlight.activity_level"]["execution_status"] == "blocked"
    assert "缺少计划要求的数据源" in attempts["population.total"]["reason"]


def test_runner_is_only_an_orchestration_boundary():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "ProjectSpatialAnalysisService" in source
    assert "run_latest_entrance_scope_diagnostic" not in source
    assert "make_metric_plan" not in source
    assert "def finding_packets" not in source
    assert "orchestrator.plan_project_v3(" in source
    assert "run_id=run_id" in source
    assert "orchestrator.assign_chapters_v3(" in source
    assert "orchestrator.author_chapters_v3(" in source
    assert "orchestrator.assemble_with_main_agent_v3(" in source
    for filename in (
        "analysis-blueprint.json",
        "evidence-snapshot.json",
        "chapter-assignments.json",
        "editorial-review.json",
        "report-assembly.json",
        "analyst-chapters.json",
    ):
        assert f'"{filename}"' in source
    assert '"report_chapter"' in source
    assert '"report_visual"' in source
    assert '"run_id": run_id' in source
    assert '"--run-dir"' in source
    assert '"--evidence-plan"' not in source
    assert '"--claim-registry"' not in source
    assert '"analyst-memos.json"' not in source
    assert '"synthesis-brief.json"' not in source
    assert '"report-draft.json"' not in source
    assert '"finding-packets.json"' not in source
    assert "长沙县人民政府驻长沙市办事处" not in source


def test_runner_maps_orchestration_statuses_without_collapsing_to_waiting_for_user():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    for status in ("waiting_for_user", "chapter_failed", "publication_blocked", "system_failed"):
        assert f'"{status}"' in source
    assert "exc.run_status" in source


def test_runner_builds_v3_chapter_index_and_only_assigned_visual_assets():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "ChapterVersionRecord" in source
    assert "ChapterVersionRef" in source
    assert '"schema_version": "3.0"' in source
    assert "accepted_version_id" in source
    assert "assigned_visual_ids" in source
