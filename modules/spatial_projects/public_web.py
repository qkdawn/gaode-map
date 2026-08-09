"""Public-web providers exposed through the history-project MCP server."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from core.config import settings

ANYSEARCH_MCP_URL = "https://api.anysearch.com/mcp"
EXA_MCP_URL = "https://mcp.exa.ai/mcp"
ProviderName = Literal["anysearch", "exa"]


class PublicWebUnavailable(RuntimeError):
    """Raised when an external research provider cannot complete a request."""


def _text_blocks(result: Any) -> list[str]:
    return [
        str(getattr(item, "text", "") or "").strip()
        for item in getattr(result, "content", [])
        if str(getattr(item, "type", "") or "") == "text" and str(getattr(item, "text", "") or "").strip()
    ]


async def _call_exa(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    timeout_seconds = max(1, int(getattr(settings, "anysearch_timeout_ms", 12000) or 12000))
    try:
        async with streamablehttp_client(EXA_MCP_URL, timeout=timeout_seconds) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _text_blocks(await session.call_tool(tool_name, arguments))
    except Exception as exc:  # Network/provider failures are normalized at the MCP boundary.
        raise PublicWebUnavailable("exa_unavailable") from exc


async def _call_anysearch(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    headers = {"Content-Type": "application/json", "X-Anysearch-Client": "gaode-map/1.0"}
    api_key = str(getattr(settings, "anysearch_api_key", "") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}
    timeout_seconds = max(1, int(getattr(settings, "anysearch_timeout_ms", 12000) or 12000))
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, trust_env=False) as client:
            response = await client.post(ANYSEARCH_MCP_URL, json=payload, headers=headers)
            response.raise_for_status()
            content = (response.json().get("result") or {}).get("content") or []
    except Exception as exc:
        raise PublicWebUnavailable("anysearch_unavailable") from exc
    return [
        str(item.get("text") or "").strip()
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and str(item.get("text") or "").strip()
    ]


async def search_public_web(query: str, provider: ProviderName, limit: int) -> dict[str, Any]:
    if provider == "exa":
        content = await _call_exa("web_search_exa", {"query": query, "numResults": limit})
    else:
        content = await _call_anysearch("search", {"query": query, "max_results": limit})
    return {
        "status": "available",
        "provider": provider,
        "query": query,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "content": content,
        "limitations": ["搜索结果用于发现与交叉核验；在读取原页面前不得作为项目事实证据。"],
    }


async def fetch_public_web_page(urls: list[str], provider: ProviderName, max_characters: int) -> dict[str, Any]:
    if provider == "exa":
        content = await _call_exa("web_fetch_exa", {"urls": urls, "maxCharacters": max_characters})
    else:
        pages: list[str] = []
        for url in urls:
            pages.extend(await _call_anysearch("extract", {"url": url}))
        content = pages
    return {
        "status": "available",
        "provider": provider,
        "urls": urls,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "content": content,
        "limitations": ["网页正文需结合发布主体、日期、适用范围与项目原始材料判断，不能单独替代项目级记录。"],
    }


def run(coroutine: Any) -> dict[str, Any]:
    """Run provider I/O from the synchronous FastMCP callback boundary."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("public_web_call_requires_sync_mcp_boundary")
