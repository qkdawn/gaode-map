from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_spatial_project_mcp_exposes_the_read_only_tool_catalog():
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
        "list_history_project_datasets",
        "query_history_project_dataset",
        "aggregate_history_project_dataset",
        "read_history_project_dataset_record",
    ]
    assert "history_id" in schemas["read_history_project"]["properties"]
    assert {"filters", "sort", "limit", "offset", "year"}.issubset(schemas["query_history_project_dataset"]["properties"])
    assert {"metrics", "filters", "top_k", "year"}.issubset(schemas["aggregate_history_project_dataset"]["properties"])
