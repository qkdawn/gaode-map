from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import store.analysis_run_repo as analysis_run_repo_module  # noqa: E402
from store.models import Base  # noqa: E402
from store.analysis_run_storage import AnalysisRunStorage  # noqa: E402

_AGENT_ROUTE_PATH = ROOT_DIR / "router" / "domains" / "agent.py"
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location(
    "test_agent_analysis_run_route_module",
    _AGENT_ROUTE_PATH,
)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)


def _install_run_store(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(analysis_run_repo_module, "SessionLocal", factory)
    monkeypatch.setattr(
        analysis_run_repo_module.analysis_run_repo,
        "storage",
        AnalysisRunStorage(tmp_path / "analysis-runs"),
    )
    return analysis_run_repo_module.analysis_run_repo


def _app():
    app = FastAPI()
    app.include_router(agent_router_module.router)
    return app


def _manifest(run_id: str, capability_id: str = "urban-strategy-stage1"):
    return {
        "run_id": run_id,
        "capability_id": capability_id,
        "project_context": {},
        "configuration_snapshot": {"history_id": "history-api"},
        "execution_profile": {},
        "input_artifact_refs": [],
        "status": "completed",
        "current_stage": "report",
        "stage_records": [],
        "diagnostics": [],
        "stale_input_artifact_ids": [],
        "output_artifact_refs": [
            {
                "artifact_id": "stage1-report",
                "artifact_type": "report",
                "title": "第一阶段报告",
                "version": run_id,
                "filename": "stage1-report.md",
                "source_run_id": run_id,
                "source_artifact_refs": [],
                "evidence_refs": [],
                "content_digest": "sha256:test",
                "created_at": "2026-07-12T00:00:00Z",
            }
        ],
        "created_at": "2026-07-12T00:00:00Z",
        "completed_at": "2026-07-12T00:01:00Z",
    }


def _v3_manifest(run_id: str):
    root_specs = [
        ("blueprint", "analysis_blueprint", "analysis-blueprint.json"),
        ("evidence", "evidence_snapshot", "evidence-snapshot.json"),
        ("assignments", "chapter_assignments", "chapter-assignments.json"),
        ("chapter-index", "analyst_chapters", "analyst-chapters.json"),
        ("review", "editorial_review", "editorial-review.json"),
        ("assembly", "report_assembly", "report-assembly.json"),
    ]
    refs = [
        {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "title": artifact_id,
            "filename": filename,
            "content_digest": f"sha256:{run_id}:{artifact_id}",
        }
        for artifact_id, artifact_type, filename in root_specs
    ]
    refs.extend([
        {"artifact_id": "chapter-market-v1", "artifact_type": "report_chapter", "title": "市场章节", "filename": "market.v1.json", "content_digest": f"sha256:{run_id}:chapter"},
        {"artifact_id": "project-report", "artifact_type": "report", "title": "项目报告", "filename": "project-report.md", "content_digest": f"sha256:{run_id}:report"},
    ])
    return {
        "schema_version": "3.0",
        "run_id": run_id,
        "capability_id": "spatial-business-analyst",
        "configuration_snapshot": {"history_id": "history-api"},
        "input_artifact_refs": [],
        "status": "completed",
        "current_stage": "published",
        "output_artifact_refs": refs,
        "created_at": "2026-07-17T00:00:00Z",
        "completed_at": "2026-07-17T00:01:00Z",
    }


def _v3_payloads(report_text: str):
    return {
        "blueprint": {},
        "evidence": {"execution_lineage": {"attempts": []}, "gaps": [], "question_readiness": {}},
        "assignments": {},
        "chapter-index": {},
        "review": {"publication_decision": "ready"},
        "assembly": {},
        "chapter-market-v1": {},
        "project-report": report_text,
    }


def test_analysis_run_list_and_detail_api(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(
        history_id="history-api",
        manifest=_manifest("run-api"),
        artifact_payloads={"stage1-report": "# 已审计报告"},
    )
    repo.save(
        history_id="history-api",
        manifest=_manifest("run-other", "other-capability"),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/analysis/agent/analysis/runs",
            params={
                "history_id": "history-api",
                "capability_id": "urban-strategy-stage1",
            },
        )
        assert response.status_code == 200
        assert [item["run_id"] for item in response.json()] == ["run-api"]

        detail = client.get(
            "/api/v1/analysis/agent/analysis/runs/run-api"
        )
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["history_id"] == "history-api"
        assert payload["run"]["run_id"] == "run-api"
        assert payload["artifacts"][0]["payload"] == "# 已审计报告"


def test_analysis_run_api_rejects_missing_history_and_unknown_run(monkeypatch, tmp_path):
    _install_run_store(monkeypatch, tmp_path)

    with TestClient(_app()) as client:
        missing_history = client.get(
            "/api/v1/analysis/agent/analysis/runs",
            params={"history_id": ""},
        )
        assert missing_history.status_code == 422
        assert missing_history.json()["detail"] == "history_id_required"

        missing_run = client.get(
            "/api/v1/analysis/agent/analysis/runs/unknown"
        )
        assert missing_run.status_code == 404
        assert missing_run.json()["detail"] == "analysis_run_not_found"


def test_v3_detail_uses_evidence_lineage_diagnostics_without_public_metric_plan(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    payloads = _v3_payloads("# 报告")
    payloads["evidence"] = {
        "execution_lineage": {
            "attempts": [
                {"execution_status": "succeeded"},
                {"execution_status": "blocked"},
            ]
        },
        "gaps": [{"gap_id": "gap-1"}],
        "question_readiness": {"question-1": "conditional"},
    }
    repo.save(
        history_id="history-api",
        manifest=_v3_manifest("run-v3-detail"),
        artifact_payloads=payloads,
    )

    with TestClient(_app()) as client:
        response = client.get("/api/v1/analysis/agent/analysis/runs/run-v3-detail")

    assert response.status_code == 200
    body = response.json()
    assert "metric_plan" not in body["run"]
    assert "metric_attempts" not in body["run"]
    assert body["evidence_diagnostics"] == {
        "execution_status_counts": {"blocked": 1, "succeeded": 1},
        "gap_count": 1,
        "question_readiness_counts": {"conditional": 1},
        "publication_decision": "ready",
    }

def test_analysis_run_comparison_api_returns_structured_diff(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    base = _v3_manifest("run-base")
    target = _v3_manifest("run-target")
    base["configuration_snapshot"]["question"] = "形成初稿"
    target["configuration_snapshot"]["question"] = "补充约束后复算"
    base["output_artifact_refs"][-1]["content_digest"] = "sha256:base"
    target["output_artifact_refs"][-1]["content_digest"] = "sha256:target"
    repo.save(
        history_id="history-api",
        manifest=base,
        artifact_payloads=_v3_payloads("# 初稿"),
    )
    repo.save(
        history_id="history-api",
        manifest=target,
        artifact_payloads=_v3_payloads("# 复算稿"),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={
                "base_run_id": "run-base",
                "target_run_id": "run-target",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_run"]["run_id"] == "run-base"
    assert payload["target_run"]["run_id"] == "run-target"
    assert payload["has_changes"] is True
    assert payload["configuration_changes"][0]["field"] == "configuration_snapshot.question"
    assert any(item["artifact_id"] == "project-report" for item in payload["artifact_changes"])


def test_analysis_run_comparison_api_rejects_unknown_or_same_run(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(
        history_id="history-api",
        manifest=_v3_manifest("run-one"),
        artifact_payloads=_v3_payloads("# 报告"),
    )

    with TestClient(_app()) as client:
        missing = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={"base_run_id": "run-one", "target_run_id": "unknown"},
        )
        same = client.get(
            "/api/v1/analysis/agent/analysis/run-comparisons",
            params={"base_run_id": "run-one", "target_run_id": "run-one"},
        )

    assert missing.status_code == 404
    assert missing.json()["detail"] == "analysis_run_not_found"
    assert same.status_code == 422
    assert same.json()["detail"] == "analysis_run_comparison_requires_distinct_runs"



def _planned_manifest(run_id: str):
    manifest = _manifest(run_id)
    manifest.update(
        {
            "status": "running",
            "completed_at": "",
            "source_versions": [
                {
                    "source_id": "current:dataset:poi",
                    "year": 2024,
                    "sha256": "sha256:poi",
                    "record_count": 20,
                },
                {
                    "source_id": "current:dataset:road",
                    "year": 2024,
                    "sha256": "sha256:road",
                    "record_count": 8,
                },
            ],
            "metric_plan": {
                "catalog_version": "2.0.0",
                "decision_questions": [
                    {
                        "question_id": "question:daily-entrance",
                        "text": "哪个入口最适合作为日常入口？",
                        "decision_target": "entrance",
                        "hypotheses": [
                            {
                                "hypothesis_id": "hypothesis:north",
                                "statement": "北侧入口具有更稳定的日常接触机会。",
                                "disconfirming_condition": "入口观测不支持北侧。",
                            }
                        ],
                    }
                ],
                "entries": [
                    {
                        "plan_entry_id": "plan:primary",
                        "metric_id": "road.entrance_distance",
                        "role": "primary",
                        "decision_question_id": "question:daily-entrance",
                        "hypothesis_ids": ["hypothesis:north"],
                        "planned_spatial_target": {
                            "unit": "entrance",
                            "source": "project entrance anchors",
                            "runtime_parameters": [],
                        },
                        "selection_reason": "直接比较入口路网挂接条件。",
                        "expected_decision_use": "改变首选日常入口。",
                        "required_source_ids": ["current:dataset:road"],
                        "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                        "exclusion_reason": "",
                    },
                    {
                        "plan_entry_id": "plan:supporting",
                        "metric_id": "poi.count",
                        "role": "supporting",
                        "decision_question_id": "question:daily-entrance",
                        "hypothesis_ids": ["hypothesis:north"],
                        "planned_spatial_target": {
                            "unit": "catchment",
                            "source": "entrance catchments",
                            "runtime_parameters": [],
                        },
                        "selection_reason": "解释入口周边日常设施暴露。",
                        "expected_decision_use": "交叉印证入口方向。",
                        "required_source_ids": ["current:dataset:poi"],
                        "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                        "exclusion_reason": "",
                    },
                    {
                        "plan_entry_id": "plan:diagnostic",
                        "metric_id": "road.integration",
                        "role": "diagnostic",
                        "decision_question_id": "question:daily-entrance",
                        "hypothesis_ids": [],
                        "planned_spatial_target": {
                            "unit": "entrance",
                            "source": "snapped entrance road segment",
                            "runtime_parameters": [],
                        },
                        "selection_reason": "检查入口与局部路网的关系。",
                        "expected_decision_use": "诊断入口路网解释是否成立。",
                        "required_source_ids": ["current:dataset:road"],
                        "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                        "exclusion_reason": "",
                    },
                    {
                        "plan_entry_id": "plan:excluded",
                        "metric_id": "nightlight.mean",
                        "role": "excluded",
                        "decision_question_id": "question:daily-entrance",
                        "hypothesis_ids": [],
                        "planned_spatial_target": {
                            "unit": "scope",
                            "source": "project scope",
                            "runtime_parameters": [],
                        },
                        "selection_reason": "",
                        "expected_decision_use": "",
                        "required_source_ids": [],
                        "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                        "exclusion_reason": "全局夜光不能定位具体入口。",
                    },
                ],
            },
            "metric_attempts": [
                {
                    "plan_entry_id": "plan:primary",
                    "metric_id": "road.entrance_distance",
                    "spatial_target": {"unit": "entrance", "target_id": "entrance:north"},
                    "execution_status": "blocked",
                    "reason": "road graph unavailable",
                    "evidence_node_ids": [],
                },
                {
                    "plan_entry_id": "plan:diagnostic",
                    "metric_id": "road.integration",
                    "spatial_target": {"unit": "entrance", "target_id": "entrance:north"},
                    "execution_status": "succeeded",
                    "reason": "",
                    "evidence_node_ids": ["evidence:integration:north"],
                },
            ],
        }
    )
    manifest["decision_agenda"] = {
        "agenda_id": f"agenda:{run_id}",
        "user_question": "选择日常入口",
        "analysis_scope": "focused_diagnostic",
        "decision_questions": manifest["metric_plan"]["decision_questions"],
    }
    return manifest


def test_analysis_run_detail_returns_metric_plan_diagnostics(monkeypatch, tmp_path):
    repo = _install_run_store(monkeypatch, tmp_path)
    repo.save(history_id="history-api", manifest=_planned_manifest("run-plan"))

    with TestClient(_app()) as client:
        response = client.get("/api/v1/analysis/agent/analysis/runs/run-plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["metric_plan"]["entries"][0]["role"] == "primary"
    assert payload["metric_plan_diagnostics"] == {
        "role_counts": {
            "diagnostic": 1,
            "excluded": 1,
            "primary": 1,
            "supporting": 1,
        },
        "blocked_primary_entry_ids": ["plan:primary"],
        "missing_attempt_entry_ids": ["plan:supporting"],
        "unplanned_attempt_entry_ids": [],
        "excluded_entry_ids": ["plan:excluded"],
    }
