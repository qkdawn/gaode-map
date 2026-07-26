from __future__ import annotations

import asyncio
from pathlib import Path

import modules.spatial_projects.mcp_server as mcp_server
from modules.spatial_projects.mcp_server import _StdioMcpFallback, _call
from modules.spatial_projects.skill_tools import SpatialBusinessSkillTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.exc import SQLAlchemyError


def test_spatial_project_mcp_exposes_history_and_skill_first_metric_tools():
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
        "list_history_projects",
        "read_history_project",
        "list_history_project_documents",
        "get_history_project_document_resource",
        "list_history_project_datasets",
        "query_history_project_dataset",
        "create_history_project_dataset_query_snapshot",
        "aggregate_history_project_dataset",
        "read_history_project_dataset_record",
        "list_spatial_metric_results",
        "read_spatial_metric_result",
        "spatial_metric_catalog",
        "spatial_metric_detail",
        "execute_spatial_metric",
        "check_arcgis_report_status",
        "create_spatial_report_visual",
        "get_spatial_report_visual_asset",
        "read_spatial_report_visual_manifest",
        "report_visual_template_catalog",
        "render_report_vega_visuals",
        "get_report_vega_visual_asset",
        "read_report_vega_visual_manifest",
    ]
    assert "history_id" in schemas["read_history_project"]["properties"]
    assert set(schemas["get_history_project_document_resource"]["required"]) == {"history_id", "document_id"}
    assert {"filters", "sort", "spatial", "limit", "offset", "year"}.issubset(schemas["query_history_project_dataset"]["properties"])
    snapshot_schema = schemas["create_history_project_dataset_query_snapshot"]
    assert set(snapshot_schema["required"]) == {"history_id", "source_id"}
    assert {"filters", "spatial", "year"}.issubset(snapshot_schema["properties"])
    assert "limit" not in snapshot_schema["properties"] and "offset" not in snapshot_schema["properties"]
    assert {"history_id", "source_id", "spatial"}.issubset(schemas["create_history_project_dataset_query_snapshot"]["properties"])
    assert {"metrics", "filters", "spatial", "top_k", "year"}.issubset(schemas["aggregate_history_project_dataset"]["properties"])
    assert schemas["spatial_metric_catalog"].get("required", []) == []
    assert schemas["spatial_metric_detail"]["required"] == ["tool_id"]
    assert {"history_id", "tool_id", "parameters", "comparison_context"}.issubset(schemas["execute_spatial_metric"]["properties"])
    assert set(schemas["execute_spatial_metric"]["required"]) == {"history_id", "tool_id"}
    assert schemas["check_arcgis_report_status"].get("required", []) == []
    assert {"history_id", "visual_request"}.issubset(schemas["create_spatial_report_visual"]["properties"])
    assert set(schemas["create_spatial_report_visual"]["required"]) == {"history_id", "visual_request"}
    assert set(schemas["get_spatial_report_visual_asset"]["required"]) == {"history_id", "asset_id"}
    assert set(schemas["read_spatial_report_visual_manifest"]["required"]) == {"history_id", "asset_id"}
    assert schemas["report_visual_template_catalog"].get("required", []) == []
    assert set(schemas["render_report_vega_visuals"]["required"]) == {"history_id", "report_id", "report_markdown", "visual_plan"}
    assert set(schemas["get_report_vega_visual_asset"]["required"]) == {"history_id", "report_id", "asset_id"}
    assert set(schemas["read_report_vega_visual_manifest"]["required"]) == {"history_id", "report_id"}
    assert "publish_spatial_business_run" not in schemas
    assert schemas["query_history_project_dataset"]["properties"]["spatial"]["anyOf"]
    assert schemas["list_spatial_metric_results"]["required"] == ["history_id"]
    assert schemas["read_spatial_metric_result"]["required"] == ["history_id", "result_id"]


def test_history_project_document_list_mcp_output_is_an_object():
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
                return next(tool.outputSchema for tool in result.tools if tool.name == "list_history_project_documents")

    output_schema = asyncio.run(exercise())
    assert output_schema["type"] == "object"


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
