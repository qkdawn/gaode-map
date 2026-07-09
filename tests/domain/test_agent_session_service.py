import asyncio

from modules.agent.schemas import AgentMessage, AgentTurnDiagnostics, AgentTurnRequest, AgentTurnResponse
import modules.agent.session_service as service


class BrokenRepo:
    def get_record(self, _session_id):
        raise RuntimeError("db down")


def test_persist_streamed_main_agent_loop_response_returns_final_when_persist_fails():
    payload = AgentTurnRequest(
        conversation_id="agent-1",
        history_id="history-1",
        messages=[AgentMessage(role="user", content="深度分析")],
    )
    response = AgentTurnResponse(
        status="answered",
        stage="answered",
        diagnostics=AgentTurnDiagnostics(research_notes=["已有说明"]),
    )

    result = asyncio.run(service.persist_streamed_main_agent_loop_response(payload, response, BrokenRepo()))

    assert result.status == "answered"
    assert result.diagnostics.error == "main_agent_loop_persist_failed:RuntimeError"
    assert result.diagnostics.research_notes == [
        "已有说明",
        "Agent 会话保存失败，本次回答未写入历史：RuntimeError",
    ]
