"""Small public-web search adapter for Agent tools."""

from __future__ import annotations

from typing import Any, Dict

from modules.spatial_projects.public_web import PublicWebUnavailable, search_public_web as provider_search

from ..schemas import AnalysisSnapshot, ToolResult


def _history_id(arguments: Dict[str, Any], snapshot: AnalysisSnapshot) -> str:
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    return str(arguments.get("history_id") or context.get("history_id") or "").strip()


async def search_public_web(*, arguments: Dict[str, Any], snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], question: str) -> ToolResult:
    del artifacts, question
    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolResult(tool_name="search_public_web", status="failed", error="query_required")
    if not _history_id(arguments, snapshot):
        return ToolResult(tool_name="search_public_web", status="failed", error="history_id_required")

    limit = max(1, min(int(arguments.get("limit") or 8), 10))
    try:
        result = await provider_search(query, "anysearch", limit)
    except PublicWebUnavailable:
        try:
            result = await provider_search(query, "exa", limit)
        except PublicWebUnavailable as exc:
            return ToolResult(tool_name="search_public_web", status="failed", error=str(exc))
    payload = {
        "query": query,
        "provider": result["provider"],
        "results": list(result.get("content") or []),
    }
    return ToolResult(tool_name="search_public_web", status="success", result=payload, artifacts={"public_web_search": payload})
