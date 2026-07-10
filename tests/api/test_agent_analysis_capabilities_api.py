from fastapi import FastAPI
from fastapi.testclient import TestClient

from router.domains.agent import router as agent_router


def build_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def test_analysis_capability_catalog_exposes_stage1_outputs():
    with TestClient(build_app()) as client:
        response = client.get("/api/v1/analysis/agent/analysis-capabilities")

    assert response.status_code == 200
    capabilities = {item["id"]: item for item in response.json()}
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
