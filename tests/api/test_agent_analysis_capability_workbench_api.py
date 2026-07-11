from fastapi import FastAPI
from fastapi.testclient import TestClient

from router.domains.agent import router as agent_router


def test_analysis_capability_workbench_exposes_recommendation_and_readiness_cards():
    app = FastAPI()
    app.include_router(agent_router)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analysis/agent/analysis-capabilities/workbench",
            json={"messages": [{"role": "user", "content": "检查当前能力"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert {item["capability_id"] for item in payload["cards"]} == {
        "urban-strategy-stage1",
        "spatial-programming-matrix",
        "evidence-audit",
        "ppt-planning",
    }
    assert payload["recommendation"]["capability_id"] == "urban-strategy-stage1"
    assert payload["recommendation"]["action"] == "resolve_inputs"
    assert payload["recommendation"]["missing_required"]
