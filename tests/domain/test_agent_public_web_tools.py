import asyncio

import modules.agent.tool_adapters.public_web_tools as tools
from modules.agent.schemas import AnalysisSnapshot


def test_public_web_search_returns_one_simple_result_shape(monkeypatch):
    async def fake_search(query, provider, limit):
        return {"provider": provider, "content": [f"{query}:{limit}"]}

    monkeypatch.setattr(tools, "provider_search", fake_search)
    result = asyncio.run(tools.search_public_web(
        arguments={"history_id": "h-1", "query": "长沙 文化服务采购", "limit": 3},
        snapshot=AnalysisSnapshot(context={}), artifacts={}, question="test",
    ))

    assert result.status == "success"
    assert result.result == {"query": "长沙 文化服务采购", "provider": "anysearch", "results": ["长沙 文化服务采购:3"]}
