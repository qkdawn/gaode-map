from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Annotated

import pytest
import modules.spatial_projects.mcp_server as mcp_server
from modules.spatial_projects.mcp_server import _StdioMcpFallback, _call
from pydantic import Field
from modules.scope_datasets.service import ScopeDatasetQueryError
from modules.spatial_projects.skill_tools import SpatialBusinessSkillTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture(autouse=True)
def _clear_spatial_evidence_cache():
    mcp_server._SPATIAL_EVIDENCE_CACHE.clear()
    yield
    mcp_server._SPATIAL_EVIDENCE_CACHE.clear()


def test_research_tool_descriptions_define_source_and_search_boundaries():
    spatial_agent = inspect.getdoc(mcp_server.analyze_spatial_question) or ""
    spatial_compute = inspect.getdoc(mcp_server.compute_spatial_evidence) or ""
    literature = inspect.getdoc(mcp_server.search_literature_evidence) or ""
    web_search = inspect.getdoc(mcp_server.search_public_web) or ""
    web_fetch = inspect.getdoc(mcp_server.fetch_public_web_page) or ""

    assert "multiple times" in spatial_agent
    assert "does not interpret a user question" in spatial_compute
    assert "methods, precedents, and mechanisms" in literature
    assert "location, exact object name" in web_search
    assert "fetch_public_web_page" in web_search
    assert "official or first-party pages" in web_fetch
    assert "does not replace project documents or saved spatial records" in web_fetch


def test_spatial_project_mcp_exposes_complete_data_tools():
    async def exercise() -> dict[str, dict]:
        root = Path(__file__).resolve().parents[2]
        params = StdioServerParameters(
            command="python",
            args=["-m", "modules.spatial_projects.mcp_server"],
            cwd=str(root),
        )
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                return {tool.name: tool.inputSchema for tool in result.tools}

    schemas = asyncio.run(exercise())
    assert list(schemas) == [
        "compute_spatial_evidence",
        "read_spatial_evidence_result",
        "analyze_spatial_question",
        "read_strategy_decisions",
        "read_project_document",
        "search_literature_evidence",
        "search_public_web",
        "fetch_public_web_page",
    ]
    query_schema = schemas["compute_spatial_evidence"]
    assert set(query_schema["required"]) == {"history_id", "analysis"}
    assert {"fact_domains", "evidence_dimensions", "selectors", "travel_time_bands_min", "neighbor_steps", "rank_order", "top_k", "record_refs"}.issubset(query_schema["properties"])
    assert "metric_ids" not in query_schema["properties"]
    domains_schema = next(item for item in query_schema["properties"]["fact_domains"]["anyOf"] if item.get("type") == "array")
    assert set(domains_schema["items"]["enum"]) == {"poi", "population", "nightlight", "road"}
    assert set(schemas["analyze_spatial_question"]["required"]) == {"history_id", "question"}
    assert "distance_bands_m" not in query_schema["properties"]
    assert "dataset_id" not in query_schema["properties"]
    assert "geometry" not in query_schema["properties"]
    assert "coordinates" not in query_schema["properties"]
    assert set(schemas["read_strategy_decisions"]["required"]) == {"run_id"}
    document_schema = schemas["read_project_document"]
    assert set(document_schema["required"]) == {"history_id", "document_id"}
    assert {"start_block", "max_blocks", "page_start", "page_end"}.issubset(document_schema["properties"])
    literature_schema = schemas["search_literature_evidence"]
    assert set(literature_schema["required"]) == {"history_id", "question"}
    assert {"mode", "top_k"}.issubset(literature_schema["properties"])
    assert set(schemas["search_public_web"]["required"]) == {"history_id", "query"}
    assert set(schemas["fetch_public_web_page"]["required"]) == {"history_id", "urls"}


def test_fallback_schema_preserves_annotated_constraints():
    schema = _StdioMcpFallback._annotation_schema(
        Annotated[list[mcp_server.SpatialEvidenceSelector] | None, Field(max_length=8)]
    )

    array_schema = next(item for item in schema["anyOf"] if item.get("type") == "array")
    assert array_schema["maxItems"] == 8
    selector_schema = array_schema["items"]
    assert set(selector_schema["properties"]["dimension"]["enum"]) == {
        "poi.category", "poi.subcategory", "population.sex", "population.age_band", "population.measure",
        "road.class", "road.radius", "road.object", "year",
    }
    assert "$ref" not in str(schema)


def test_spatial_agent_wrapper_accepts_only_project_and_question(monkeypatch):
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return {"question": kwargs["question"], "subquestions": []}

    monkeypatch.setattr(mcp_server, "_analyze_spatial_question", fake_agent)

    result = mcp_server.analyze_spatial_question("history-1", "主要联系方向在哪里？")

    assert captured == {"history_id": "history-1", "question": "主要联系方向在哪里？"}
    assert result["question"] == "主要联系方向在哪里？"


def test_deterministic_spatial_wrapper_does_not_forward_question(monkeypatch):
    captured = {}

    def fake_compute(**kwargs):
        captured.update(kwargs)
        return {"status": "available"}

    monkeypatch.setattr(mcp_server.spatial_evidence, "compute_domains", fake_compute)

    result = mcp_server.compute_spatial_evidence(
        history_id="history-1",
        analysis="direction",
        fact_domains=["population", "nightlight"],
        evidence_dimensions=["population.scale", "nightlight.intensity"],
        selectors=[{"dimension": "population.sex", "values": ["female"]}],
    )

    assert result == {"status": "available"}
    assert captured["history_id"] == "history-1"
    assert captured["request"]["analysis"] == "direction"
    assert captured["request"]["selectors"] == [
        {"dimension": "population.sex", "values": ["female"]},
    ]
    assert "question" not in captured["request"]


def test_compute_spatial_evidence_persists_addressable_result(monkeypatch):
    captured = {}
    expected = {
        "result_id": "spatial:test-result",
        "status": "available",
        "selectors": [{"dimension": "population.sex", "values": ["female"]}],
        "analysis": "scope",
    }

    monkeypatch.setattr(mcp_server.spatial_evidence, "compute_domains", lambda **_kwargs: expected)
    monkeypatch.setattr(
        mcp_server.spatial_evidence_result_store,
        "persist",
        lambda **kwargs: captured.update(kwargs),
    )

    assert mcp_server.compute_spatial_evidence("history-1", "scope") == expected
    assert captured == {"history_id": "history-1", "result": expected}


def test_read_spatial_evidence_result_is_read_only(monkeypatch):
    captured = {}
    expected = {"result_id": "spatial:test-result", "status": "available"}

    def fake_read(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(mcp_server.spatial_evidence_result_store, "read", fake_read)

    assert mcp_server.read_spatial_evidence_result("history-1", "spatial:test-result") == expected
    assert captured == {"history_id": "history-1", "result_id": "spatial:test-result"}


def test_read_spatial_evidence_result_projects_internal_fields(monkeypatch):
    raw = {
        "result_id": "spatial:test-result",
        "status": "available",
        "selectors": [{"dimension": "population.sex", "values": ["female"]}],
        "used_metric_ids": ["spatial.gi_star"],
        "limitations": ["internal diagnostic"],
        "method": {
            "kind": "internal_algorithm",
            "routing_algorithm": "internal-router",
            "spatial_universe": "saved_isochrone",
        },
        "relationship": {
            "pattern_counts": {"joint_high": 1},
            "conflict": "population_high_nightlight_low",
            "joint_high": ["cell/1"],
            "unit_values": [{
                "record_ref": "cell/1",
                "values": {
                    "population.total": 120,
                    "nightlight.mean_radiance": 4.2,
                },
            }],
        },
        "metrics": [{"metric_id": "population.total"}],
        "brightness_context_level": "high",
        "hotspot_class": "core_hotspot",
        "equal_weight_facility_count": 3,
        "provenance": {
            "snapshot_id": "snapshot-1",
            "selected_years": {"current:dataset:population": 2025},
            "data_versions": {"current:dataset:population": {"data_version": "worldpop-v1"}},
        },
        "evidence": [{
            "metric_ids": ["population.total"],
            "source_locator": "spatial_evidence:snapshot:relationship:joint_high",
        }],
        "fact_domains": [{"domain": "population", "label": "人口", "description": "internal"}],
        "evidence_dimensions": [{"dimension": "population.scale", "label": "人口规模", "description": "internal"}],
    }
    monkeypatch.setattr(mcp_server.spatial_evidence_result_store, "read", lambda **_kwargs: raw)

    result = mcp_server.read_spatial_evidence_result("history-1", "spatial:test-result")

    assert "used_metric_ids" not in result
    assert "limitations" not in result
    assert "kind" not in result["method"]
    assert "routing_algorithm" not in result["method"]
    assert result["method"]["spatial_universe"] == "saved_isochrone"
    assert "pattern_counts" not in result["relationship"]
    assert result["relationship"]["unit_values"][0]["values"] == {
        "population_count": 120,
        "mean_radiance": 4.2,
    }
    assert "metrics" not in result
    assert "evidence" not in result
    assert "joint_high" not in str(result)
    assert "conflict" not in result["relationship"]
    assert "brightness_context_level" not in result
    assert "hotspot_class" not in result
    assert result["equal_weight_facility_count"] == 3
    assert result["provenance"]["selected_years"] == {"current:dataset:population": 2025}
    assert result["provenance"]["data_versions"]["current:dataset:population"]["data_version"] == "worldpop-v1"
    assert result["fact_domains"] == ["population"]
    assert result["evidence_dimensions"] == ["population.scale"]
    assert result["selectors"] == [{"dimension": "population.sex", "values": ["female"]}]


def test_compute_spatial_evidence_reuses_same_data_identity_and_invalidates_on_version(monkeypatch):
    state = {"version": "v1", "calls": 0}

    def project(**_kwargs):
        return {
            "history_id": "history-cache",
            "datasets": [{
                "source_id": "current:dataset:population",
                "status": "ready",
                "data_version": state["version"],
                "selected_year": 2025,
            }],
        }

    def compute(**_kwargs):
        state["calls"] += 1
        return {
            "result_id": f"spatial:cache-{state['version']}",
            "status": "available",
            "analysis": "scope",
        }

    monkeypatch.setattr(mcp_server.service, "read_history_project", project)
    monkeypatch.setattr(mcp_server.spatial_evidence, "compute_domains", compute)
    monkeypatch.setattr(mcp_server.spatial_evidence_result_store, "persist", lambda **_kwargs: None)

    first = mcp_server.compute_spatial_evidence("history-cache", "scope", ["population"], ["population.scale"])
    second = mcp_server.compute_spatial_evidence("history-cache", "scope", ["population"], ["population.scale"])
    assert first == second
    assert state["calls"] == 1

    state["version"] = "v2"
    third = mcp_server.compute_spatial_evidence("history-cache", "scope", ["population"], ["population.scale"])
    assert third["result_id"] == "spatial:cache-v2"
    assert state["calls"] == 2


def test_complete_data_mcp_outputs_are_objects():
    async def exercise() -> dict:
        root = Path(__file__).resolve().parents[2]
        params = StdioServerParameters(
            command="python",
            args=["-m", "modules.spatial_projects.mcp_server"],
            cwd=str(root),
        )
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.list_tools()
                return {tool.name: tool.outputSchema for tool in result.tools}

    output_schemas = asyncio.run(exercise())
    assert output_schemas["compute_spatial_evidence"]["type"] == "object"
    assert output_schemas["read_spatial_evidence_result"]["type"] == "object"
    assert output_schemas["analyze_spatial_question"]["type"] == "object"
    assert output_schemas["read_project_document"]["type"] == "object"
    assert output_schemas["search_literature_evidence"]["type"] == "object"
    assert output_schemas["search_public_web"]["type"] == "object"
    assert output_schemas["fetch_public_web_page"]["type"] == "object"


def test_public_web_mcp_tools_await_provider_calls(monkeypatch):
    monkeypatch.setattr(mcp_server, "_require_history_project", lambda history_id: None)

    async def fake_search(query, provider, limit):
        return {"status": "available", "provider": provider, "query": query, "limit": limit}

    async def fake_fetch(urls, provider, max_characters):
        return {
            "status": "available",
            "provider": provider,
            "urls": urls,
            "max_characters": max_characters,
        }

    monkeypatch.setattr(mcp_server, "_search_public_web", fake_search)
    monkeypatch.setattr(mcp_server, "_fetch_public_web_page", fake_fetch)

    async def exercise():
        search = await mcp_server.search_public_web("history-1", "  长沙县 城市更新  ", limit=20)
        fetch = await mcp_server.fetch_public_web_page(
            "history-1",
            ["https://example.gov.cn/page", "not-a-url"],
            max_characters=50_000,
        )
        return search, fetch

    search, fetch = asyncio.run(exercise())

    assert search == {
        "status": "available",
        "provider": "anysearch",
        "query": "长沙县 城市更新",
        "limit": 10,
        "history_id": "history-1",
    }
    assert fetch == {
        "status": "available",
        "provider": "anysearch",
        "urls": ["https://example.gov.cn/page"],
        "max_characters": 20_000,
        "history_id": "history-1",
    }


def test_literature_mcp_tool_keeps_web_search_separate(monkeypatch):
    monkeypatch.setattr(mcp_server, "_require_history_project", lambda history_id: None)
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return {"status": "available", "mode": kwargs["mode"], "evidence": []}

    monkeypatch.setattr(mcp_server.literature_evidence, "search", fake_search)

    result = mcp_server.search_literature_evidence(
        "history-1",
        "  Historic Urban Landscape  ",
        mode="synthesis",
        top_k=8,
    )

    assert result == {"status": "available", "mode": "synthesis", "evidence": []}
    assert captured == {
        "question": "  Historic Urban Landscape  ",
        "mode": "synthesis",
        "top_k": 8,
    }


def test_read_project_document_passes_explicit_range(monkeypatch):
    captured = {}

    def fake_read(**kwargs):
        captured.update(kwargs)
        return {"blocks": [], "complete": True}

    monkeypatch.setattr(mcp_server.data_contract, "read_project_document", fake_read)

    result = mcp_server.read_project_document(
        "history-1",
        "doc-1",
        start_block=20,
        max_blocks=10,
        page_start=3,
        page_end=5,
    )

    assert result == {"blocks": [], "complete": True}
    assert captured == {
        "history_id": "history-1",
        "document_id": "doc-1",
        "start_block": 20,
        "max_blocks": 10,
        "page_start": 3,
        "page_end": 5,
    }


def test_call_preserves_unsupported_schema_error_code():
    response = _call(
        lambda: (_ for _ in ()).throw(
            ScopeDatasetQueryError("schema_version_unsupported", "旧 artifact 必须重新计算")
        )
    )

    assert response == {
        "status": "invalid_request",
        "error": "schema_version_unsupported",
        "message": "旧 artifact 必须重新计算",
    }


def test_history_project_document_list_wraps_documents(monkeypatch):
    records = [{"document_id": "doc_1", "title": "source.docx"}]
    monkeypatch.setattr(mcp_server.service, "list_history_project_documents", lambda history_id: records)

    assert mcp_server.list_history_project_documents("history_1") == {"documents": records}


def test_fallback_schema_keeps_object_and_array_arguments_structured():
    def callback(spatial: dict | None = None, metrics: list[dict] | None = None):
        return {"spatial": spatial, "metrics": metrics}

    schema = _StdioMcpFallback._schema(callback)
    assert schema["properties"]["spatial"]["type"] == "object"
    assert schema["properties"]["metrics"]["type"] == "array"


def test_fallback_reads_resource_templates_with_arbitrary_parameters_and_mime_types():
    fallback = _StdioMcpFallback("test")

    @fallback.resource("spatial-document://{history_id}/{document_id}/original", mime_type="application/octet-stream")
    def document_resource(history_id: str, document_id: str) -> bytes:
        return f"{history_id}/{document_id}".encode("utf-8")

    @fallback.resource("spatial-report-visual://{history_id}/{asset_id}", mime_type="image/svg+xml")
    def visual_resource(history_id: str, asset_id: str) -> str:
        return f"<svg>{history_id}/{asset_id}</svg>"

    @fallback.resource("report-vega-visual://{history_id}/{report_id}/{asset_id}", mime_type="image/svg+xml")
    def vega_resource(history_id: str, report_id: str, asset_id: str) -> str:
        return f"<svg>{history_id}/{report_id}/{asset_id}</svg>"

    def read(uri: str) -> dict:
        response = fallback._handle({"id": 1, "method": "resources/read", "params": {"uri": uri}})
        assert response is not None
        return response

    document = read("spatial-document://history-1/document-1/original")["result"]["contents"][0]
    visual = read("spatial-report-visual://history-1/asset-1")["result"]["contents"][0]
    vega = read("report-vega-visual://history-1/report-1/asset-1")["result"]["contents"][0]

    assert document["mimeType"] == "application/octet-stream"
    assert document["blob"]
    assert visual == {
        "uri": "spatial-report-visual://history-1/asset-1",
        "mimeType": "image/svg+xml",
        "text": "<svg>history-1/asset-1</svg>",
    }
    assert vega == {
        "uri": "report-vega-visual://history-1/report-1/asset-1",
        "mimeType": "image/svg+xml",
        "text": "<svg>history-1/report-1/asset-1</svg>",
    }


def test_persisted_metric_results_are_read_without_execution():
    class FakeRunRepo:
        def list(self, history_id, *, capability_id=""):
            assert history_id == "history-1"
            return [{"run_id": "run-1", "capability_id": capability_id}]

        def get(self, run_id):
            assert run_id == "run-1"
            return {
                "artifacts": [{
                    "artifact": {"artifact_type": "source_index"},
                    "payload": {"items": [{
                        "resource_id": "metric-1",
                        "resource_type": "analysis_result",
                        "title": "poi_density",
                        "status": "available",
                        "summary": "POI 密度",
                        "payload": {"data": {"value": 12}},
                    }]},
                }]
            }

    tools = SpatialBusinessSkillTools(run_repo=FakeRunRepo())
    listed = tools.list_metric_results("history-1")
    assert listed["result"]["result_count"] == 1
    read = tools.read_metric_result("history-1", "metric-1")
    assert read["result"]["data"] == {"value": 12}


def test_database_failures_return_retryable_mcp_envelope():
    response = _call(lambda: (_ for _ in ()).throw(SQLAlchemyError("connection lost")))
    assert response == {
        "status": "unavailable",
        "error": "data_source_unavailable",
        "retryable": True,
        "limitations": ["项目数据源当前不可用，未执行或读取本次请求。"],
    }


def test_document_resource_tool_returns_mcp_resource_link(monkeypatch):
    monkeypatch.setattr(
        mcp_server.service,
        "get_history_project_document_resource",
        lambda **_kwargs: {
            "history_id": "history-1",
            "document_id": "document-1",
            "title": "项目原件",
            "file_name": "project.docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size": 128,
        },
    )
    link = mcp_server.get_history_project_document_resource("history-1", "document-1")
    assert link.type == "resource_link"
    assert str(link.uri) == "spatial-document://history-1/document-1/original"
    assert link.name == "project.docx"
    assert link.size == 128


def test_spatial_project_mcp_registers_original_document_resource_template():
    async def exercise():
        root = Path(__file__).resolve().parents[2]
        params = StdioServerParameters(command="python", args=["-m", "modules.spatial_projects.mcp_server"], cwd=str(root))
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                return await session.list_resource_templates()

    templates = asyncio.run(exercise()).resourceTemplates
    assert any(str(item.uriTemplate) == "spatial-document://{history_id}/{document_id}/original" for item in templates)
    assert any(str(item.uriTemplate) == "report-vega-visual://{history_id}/{report_id}/{asset_id}" for item in templates)
    assert any(str(item.uriTemplate) == "report-vega-report://{history_id}/{report_id}" for item in templates)
    assert any(str(item.uriTemplate) == "report-vega-visual-plan://{history_id}/{report_id}" for item in templates)
    assert any(str(item.uriTemplate) == "report-vega-visual-manifest://{history_id}/{report_id}" for item in templates)
