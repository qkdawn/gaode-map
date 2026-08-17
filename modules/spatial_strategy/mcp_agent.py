from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from core.config import settings
from .previous_chapter import read_previous_chapter  # noqa: F401


_ALLOWED_TOOLS = {
    "analyze_spatial_evidence",
    "read_project_document",
    "read_previous_chapter",
    "search_literature_evidence",
    "search_public_web",
    "fetch_public_web_page",
}
def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


async def call_spatial_mcp_tool(*, history_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in _ALLOWED_TOOLS:
        raise ValueError("spatial_mcp_tool_not_allowed")
    payload = dict(arguments or {})
    payload["history_id"] = history_id
    async with streamablehttp_client(
        str(settings.spatial_mcp_url).rstrip("/"),
        timeout=float(settings.spatial_mcp_timeout_s),
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, payload)
            structured_content = _jsonable(getattr(result, "structuredContent", None))
            return {
                "tool_name": tool_name,
                "is_error": bool(getattr(result, "isError", False)),
                # The decision workflow consumes the canonical structured result. Keeping the
                # MCP text mirror would transmit the same data a second time on every tool turn.
                "content": [] if structured_content is not None else _jsonable(getattr(result, "content", [])),
                "structured_content": structured_content,
            }
