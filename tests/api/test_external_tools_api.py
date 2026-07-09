from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import modules.agent.tool_service as tool_service
from modules.agent.schemas import ToolResult
from router.domains.agent import router as agent_router
from router.domains.tools import router as tools_router
from router.utils import deps as deps_module


@pytest.fixture(autouse=True)
def _install_test_api_key(monkeypatch):
    monkeypatch.setattr(deps_module.settings, "api_keys", ["test-tool-key"])


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(tools_router)
    app.include_router(agent_router)
    return app


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-tool-key"}


def test_external_tools_requires_api_key():
    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/tools")

    assert response.status_code == 401


def test_external_tools_lists_first_batch():
    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/tools", headers=_auth_headers())

    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"read_current_scope"} == names
    first = response.json()[0]
    assert "input_schema" in first
    assert "output_schema" in first
    assert "requires" in first
    assert "produces" in first


def test_internal_agent_tools_lists_source_analysis_registry():
    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/analysis/agent/tools")

    assert response.status_code == 200
    payload = response.json()
    names = [item["name"] for item in payload]
    assert names[:6] == [
        "read_current_scope",
        "read_current_results",
        "plan_business_analyst_analysis",
        "list_selected_sources",
        "search_selected_source_evidence",
        "read_selected_source_evidence_node",
    ]
    assert {"list_scope_datasets", "query_scope_dataset", "aggregate_scope_dataset", "read_scope_record"}.issubset(names)
    assert "search_database_context" not in names
    assert "read_database_record" not in names
    assert "fetch_pois_in_scope" not in names
    assert "run_business_site_advice" not in names


def test_external_tool_unknown_name_returns_404():
    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/tools/not_a_tool/run",
            headers=_auth_headers(),
            json={"arguments": {}},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "tool_not_found"


def test_external_tool_invalid_arguments_returns_failed_tool_result():
    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/tools/read_current_scope/run",
            headers=_auth_headers(),
            json={
                "arguments": {"unexpected": True},
                "analysis_snapshot": {
                    "scope": {
                        "polygon": [
                            [112.98, 28.19],
                            [112.99, 28.19],
                            [112.99, 28.20],
                            [112.98, 28.20],
                            [112.98, 28.19],
                        ]
                    }
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error"] == "invalid_arguments"
    assert "arguments.unexpected 不允许出现" in payload["warnings"]


def test_external_tool_missing_requirements_returns_tool_result():
    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/tools/fetch_pois_in_scope/run",
            headers=_auth_headers(),
            json={"arguments": {"source": "local"}},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "tool_not_found"


def test_external_tool_executes_via_registry_and_injects_snapshot(monkeypatch):
    seen = {}
    original_registry = tool_service.get_tool_registry()
    registered = original_registry["read_current_scope"]

    async def fake_runner(*, arguments, snapshot, artifacts, question):
        seen["arguments"] = arguments
        seen["scope_polygon"] = snapshot.scope.get("polygon")
        seen["question"] = question
        return ToolResult(
            tool_name="read_current_scope",
            status="success",
            result={"has_scope": True, "active_panel": ""},
            artifacts={"scope_polygon": snapshot.scope.get("polygon")},
        )

    def fake_registry():
        return {
            **original_registry,
            "read_current_scope": registered.__class__(spec=registered.spec, runner=fake_runner),
        }

    monkeypatch.setattr(tool_service, "get_tool_registry", fake_registry)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/tools/read_current_scope/run",
            headers=_auth_headers(),
            json={
                "arguments": {},
                "question": "分析这个范围",
                "analysis_snapshot": {
                    "scope": {
                        "polygon": [
                            [112.98, 28.19],
                            [112.99, 28.19],
                            [112.99, 28.20],
                            [112.98, 28.20],
                            [112.98, 28.19],
                        ]
                    }
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["result"]["has_scope"] is True
    assert seen["arguments"] == {}
    assert seen["question"] == "分析这个范围"
    assert seen["scope_polygon"][0] == [112.98, 28.19]
