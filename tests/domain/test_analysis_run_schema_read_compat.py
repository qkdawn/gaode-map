import pytest

from modules.agent.analysis_run_service import get_analysis_run, list_analysis_runs
from modules.agent.analysis_runs import (
    AnalysisRun,
    AnalysisRunV3,
    LegacyAnalysisRunV2View,
    LegacyAnalysisRunView,
)


LEGACY_MANIFEST = {
    "run_id": "legacy-run",
    "capability_id": "spatial-business-analyst",
    "status": "completed",
    "current_stage": "published",
    "created_at": "2026-07-15T00:00:00Z",
    "completed_at": "2026-07-15T00:01:00Z",
    "decision_agenda": {
        "analysis_scope": "full_project",
        "decision_questions": [
            {
                "question_id": "question:legacy",
                "agenda_area": "hard_constraints",
                "text": "旧问题",
                "decision_target": "legacy",
                "hypotheses": [],
            }
        ],
    },
}


class Repo:
    def list(self, history_id, capability_id=""):
        del history_id, capability_id
        return [LEGACY_MANIFEST]

    def get(self, run_id):
        assert run_id == "legacy-run"
        return {"history_id": "history:1", "run": LEGACY_MANIFEST, "artifacts": []}


def test_schema_v1_run_is_exposed_as_read_only_without_entering_v2_model():
    run = list_analysis_runs("history:1", repo=Repo())[0]
    assert isinstance(run, LegacyAnalysisRunView)
    assert run.schema_version == "1.0"
    assert run.read_only is True
    assert run.decision_agenda["decision_questions"][0]["agenda_area"] == "hard_constraints"


def test_schema_v1_detail_remains_viewable_but_not_a_writable_analysis_run():
    detail = get_analysis_run("legacy-run", repo=Repo())
    assert detail is not None
    assert isinstance(detail.run, LegacyAnalysisRunView)
    assert not isinstance(detail.run, AnalysisRun)
    assert detail.run.run_id == "legacy-run"


def test_schema_v2_run_is_exposed_as_read_only_legacy_view():
    manifest = {
        "schema_version": "2.0",
        "run_id": "v2-run",
        "capability_id": "spatial-business-analyst",
        "status": "completed",
        "created_at": "2026-07-16T00:00:00Z",
    }

    class V2Repo(Repo):
        def list(self, history_id, capability_id=""):
            del history_id, capability_id
            return [manifest]

        def changed_input_artifact_ids(self, **kwargs):
            del kwargs
            return []

    run = list_analysis_runs("history:1", repo=V2Repo())[0]
    assert isinstance(run, LegacyAnalysisRunV2View)
    assert run.read_only is True
    assert not isinstance(run, AnalysisRunV3)


def test_schema_v3_run_is_the_only_current_writable_read_model():
    manifest = {
        "schema_version": "3.0",
        "run_id": "v3-run",
        "capability_id": "spatial-business-analyst",
        "status": "running",
        "created_at": "2026-07-17T00:00:00Z",
    }

    class V3Repo(Repo):
        def list(self, history_id, capability_id=""):
            del history_id, capability_id
            return [manifest]

    run = list_analysis_runs("history:1", repo=V3Repo())[0]
    assert isinstance(run, AnalysisRunV3)
    assert run.read_only is False
    assert not hasattr(run, "metric_plan")
    assert not hasattr(run, "metric_attempts")


def test_schema_v3_rejects_public_metric_plan_and_attempt_fields():
    with pytest.raises(ValueError):
        AnalysisRunV3.model_validate(
            {
                "schema_version": "3.0",
                "run_id": "v3-invalid",
                "capability_id": "spatial-business-analyst",
                "status": "running",
                "created_at": "2026-07-17T00:00:00Z",
                "metric_plan": {},
                "metric_attempts": [],
            }
        )
