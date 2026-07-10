import asyncio
import json

from modules.agent import context_ask_service
from modules.agent.schemas import AgentContextAskRequest, ContextAskTarget


class FakeStreamingClient:
    def __init__(self):
        self.messages = []

    async def stream_text(self, *, messages, emit_delta, temperature=0.1, max_tokens=900):
        self.messages = messages
        assert temperature == 0.1
        assert max_tokens == 900
        await emit_delta("先看结论。")
        await emit_delta("再核对证据。")
        return "先看结论。再核对证据。"


def test_context_ask_stream_emits_first_token_and_server_owned_support(monkeypatch):
    client = FakeStreamingClient()
    monkeypatch.setattr(context_ask_service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(context_ask_service, "get_llm_provider_client", lambda: client)
    monkeypatch.setattr(
        context_ask_service,
        "build_scoped_dataset_context",
        lambda payload: {
            "datasets": {},
            "warnings": ["仅使用当前范围数据"],
            "evidence_nodes": [{"id": "node:latest", "title": "最新指标", "content": "POI 12 个"}],
            "citations": ["current:dataset:poi"],
        },
    )
    payload = AgentContextAskRequest(
        conversation_id="agent-1",
        history_id="history-new",
        question="现在有哪些机会？",
        require_ai=True,
        target=ContextAskTarget(
            type="analysis_sources",
            id="analysis-selected-sources",
            title="已选分析来源",
            source="analysis",
            evidence=[{"source_id": "current:scope", "text": "当前范围"}],
            artifact_refs=["current:scope"],
            payload={
                "sources": [
                    {
                        "source_id": "current:dataset:poi",
                        "title": "POI 基础数据",
                        "included": ["metrics"],
                        "metrics": [{"metric_id": "poi_total", "value": 12}],
                    }
                ]
            },
        ),
    )

    async def collect():
        return [event async for event in context_ask_service.stream_context_ask(payload)]

    events = asyncio.run(collect())

    assert [event[0] for event in events] == ["answer_delta", "answer_delta", "complete"]
    assert events[0][1]["delta"] == "先看结论。"
    assert events[-1][1]["answer"] == "先看结论。再核对证据。"
    assert events[-1][1]["citations"] == ["current:scope", "current:dataset:poi"]
    assert events[-1][1]["evidence"][-1]["id"] == "node:latest"
    assert events[-1][1]["warnings"] == ["仅使用当前范围数据"]

    user_payload = json.loads(client.messages[1]["content"])
    assert user_payload["history_id"] == "history-new"
    assert user_payload["target"]["payload"]["sources"][0]["metrics"][0]["value"] == 12
    assert "输出 JSON" not in client.messages[0]["content"]


def test_context_ask_stream_fails_before_model_when_ai_is_unavailable(monkeypatch):
    monkeypatch.setattr(context_ask_service, "is_llm_enabled", lambda: False)
    payload = AgentContextAskRequest(question="为什么？", require_ai=True)

    async def collect():
        return [event async for event in context_ask_service.stream_context_ask(payload)]

    events = asyncio.run(collect())
    assert events == [("error", {"error": "ai_unavailable", "message": "AI 未启用，无法回答。"})]
