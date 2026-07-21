from fastapi import FastAPI
from fastapi.testclient import TestClient

from router.domains.agent import router as agent_router


def build_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def test_analysis_capability_catalog_exposes_only_app_owned_executors():
    with TestClient(build_app()) as client:
        response = client.get("/api/v1/analysis/agent/analysis-capabilities")

    assert response.status_code == 200
    capabilities = {item["id"]: item for item in response.json()}
    assert "spatial-business-analyst" not in capabilities
    stage1 = capabilities["urban-strategy-stage1"]
    assert stage1["status"] == "available"
    assert "质量审计" in stage1["output_contract"]
    assert stage1["executor_id"] == "urban-strategy-stage1"


def test_analysis_capability_readiness_returns_structured_actions():
    with TestClient(build_app()) as client:
        response = client.post(
            "/api/v1/analysis/agent/analysis-capabilities/urban-strategy-stage1/readiness",
            json={"messages": [{"role": "user", "content": "生成报告"}]},
        )

    assert response.status_code == 200
    readiness = response.json()
    assert readiness["status"] == "blocked"
    assert {item["target"] for item in readiness["actions"]} == {
        "scope-selection",
        "project-brief",
        "analysis-sources",
    }


def test_unknown_analysis_capability_returns_404():
    with TestClient(build_app()) as client:
        response = client.post(
            "/api/v1/analysis/agent/analysis-capabilities/not-real/readiness",
            json={"messages": []},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "analysis_capability_not_found"


def test_downstream_readiness_exposes_explicit_upstream_version_choices(monkeypatch):
    from modules.agent.capability_inputs import (
        CapabilityInputResolution,
        ResolvedCapabilityInputs,
    )

    monkeypatch.setattr(
        "modules.agent.capability_catalog.resolve_capability_inputs",
        lambda capability_id, payload: ResolvedCapabilityInputs(
            resolutions=[
                CapabilityInputResolution(
                    requirement_id="approved_report",
                    label="已审定报告或分析成果",
                    required=True,
                    upstream_capability_id="urban-strategy-stage1",
                    selection_mode="latest_successful",
                    state="missing",
                    diagnostics=["没有可用版本"],
                )
            ],
            blocking_diagnostics=["没有可用版本"],
        ),
    )
    with TestClient(build_app()) as client:
        response = client.post(
            "/api/v1/analysis/agent/analysis-capabilities/ppt-planning/readiness",
            json={
                "history_id": "history-without-stage1-runs",
                "target_capability_id": "ppt-planning",
                "messages": [{"role": "user", "content": "生成 PPT"}],
            },
        )

    assert response.status_code == 200
    readiness = response.json()
    assert readiness["status"] == "blocked"
    resolution = readiness["input_resolutions"][0]
    assert resolution["requirement_id"] == "approved_report"
    assert resolution["selection_mode"] == "latest_successful"
    assert resolution["state"] == "missing"
    assert resolution["available_versions"] == []


def test_analysis_capability_intent_resolves_explicit_workbench_navigation():
    with TestClient(build_app()) as client:
        response = client.post(
            "/api/v1/analysis/agent/analysis-capabilities/resolve-intent",
            json={"message": "请生成空间功能策划矩阵"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "matched": True,
        "capability_id": "spatial-programming-matrix",
        "action": "open_configuration",
        "matched_phrase": "生成空间功能策划矩阵",
        "reason": "已识别明确的能力执行意图；先打开统一配置页检查输入并锁定运行版本。",
    }


def test_analysis_capability_intent_does_not_hijack_general_questions():
    with TestClient(build_app()) as client:
        response = client.post(
            "/api/v1/analysis/agent/analysis-capabilities/resolve-intent",
            json={"message": "空间功能矩阵通常应该包含哪些字段？"},
        )

    assert response.status_code == 200
    assert response.json()["matched"] is False
