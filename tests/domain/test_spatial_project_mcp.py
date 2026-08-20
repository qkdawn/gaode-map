from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import modules.spatial_projects.mcp_server as mcp_server
from modules.spatial_projects.mcp_server import _StdioMcpFallback, _call
from modules.scope_datasets.service import ScopeDatasetQueryError
from modules.spatial_projects.skill_tools import SpatialBusinessSkillTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.exc import SQLAlchemyError


def test_research_tool_descriptions_define_source_and_search_boundaries():
    spatial = inspect.getdoc(mcp_server.analyze_spatial_evidence) or ""
    literature = inspect.getdoc(mcp_server.search_literature_evidence) or ""
    web_search = inspect.getdoc(mcp_server.search_public_web) or ""
    web_fetch = inspect.getdoc(mcp_server.fetch_public_web_page) or ""

    assert "scope" in spatial and "inspect" in spatial and "saved spatial snapshot" in spatial
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
        "analyze_spatial_evidence",
        "read_strategy_decisions",
        "read_project_document",
        "search_literature_evidence",
        "search_public_web",
        "fetch_public_web_page",
    ]
    query_schema = schemas["analyze_spatial_evidence"]
    assert set(query_schema["required"]) == {"history_id", "analysis"}
    assert {"metric_ids", "selectors", "travel_time_bands_min", "neighbor_steps", "rank_order", "top_k", "record_refs"}.issubset(query_schema["properties"])
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
    assert output_schemas["analyze_spatial_evidence"]["type"] == "object"
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
