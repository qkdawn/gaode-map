import httpx

import modules.spatial_strategy.mcp_agent as mcp_agent
from modules.spatial_strategy.mcp_agent import _ALLOWED_TOOLS


def test_spatial_strategy_agent_allows_project_and_public_web_tools():
    assert _ALLOWED_TOOLS == {
        "analyze_spatial_evidence",
        "read_project_document",
        "search_literature_evidence",
        "search_public_web",
        "fetch_public_web_page",
    }


def test_local_mcp_client_bypasses_windows_system_proxy(monkeypatch):
    captured = {}
    sentinel = object()

    def fake_client(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(mcp_agent.httpx, "AsyncClient", fake_client)
    timeout = httpx.Timeout(12.0)

    client = mcp_agent._direct_mcp_http_client(headers={"X-Test": "1"}, timeout=timeout)

    assert client is sentinel
    assert captured == {
        "headers": {"X-Test": "1"},
        "timeout": timeout,
        "auth": None,
        "follow_redirects": True,
        "trust_env": False,
    }
