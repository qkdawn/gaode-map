from __future__ import annotations

import asyncio
from types import SimpleNamespace

from openai_codex import ApprovalMode, Sandbox

from modules.agent_conversation.schemas import ConversationTurnRequest
from modules.agent_conversation.service import CodexConversationService, _thread_messages


class FakeRepo:
    def __init__(self):
        self.records = {}

    def list_records(self):
        return list(self.records.values())

    def get_record(self, session_id):
        return self.records.get(session_id)

    def upsert_record(self, session_id, **payload):
        record = {
            "id": session_id,
            "is_pinned": False,
            "created_at": None,
            "updated_at": None,
            "pinned_at": None,
            **payload,
        }
        self.records[session_id] = record
        return record

    def update_metadata(self, session_id, **payload):
        if session_id not in self.records:
            return None
        self.records[session_id].update(
            {key: value for key, value in payload.items() if value is not None}
        )
        return self.records[session_id]

    def delete_record(self, session_id):
        return self.records.pop(session_id, None) is not None


class FakeRequest:
    def __init__(self, disconnected=False):
        self.disconnected = disconnected

    async def is_disconnected(self):
        return self.disconnected


class FakePayload:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeNotification:
    def __init__(self, method, payload):
        self.method = method
        self.payload = payload


class FakeTurn:
    def __init__(self, events):
        self.id = "turn-1"
        self.events = events
        self.interrupted = False

    async def stream(self):
        for event in self.events:
            yield event

    async def interrupt(self):
        self.interrupted = True


class FakeThread:
    def __init__(self, events):
        self.id = "thread-1"
        self.events = events
        self.turn_inputs = []
        self.names = []

    async def set_name(self, name):
        self.names.append(name)

    async def turn(self, value):
        self.turn_inputs.append(value)
        return FakeTurn(self.events)


class FakeCodex:
    def __init__(self, events):
        self.thread = FakeThread(events)
        self.started = 0
        self.start_options = []
        self.resumed = []
        self.resume_options = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.close()

    async def close(self):
        self.closed = True

    async def thread_start(self, **kwargs):
        self.started += 1
        self.start_options.append(kwargs)
        return self.thread

    async def thread_resume(self, thread_id, **kwargs):
        self.resumed.append(thread_id)
        self.resume_options.append(kwargs)
        return self.thread


def completed_events(answer="明确结论"):
    started_item = SimpleNamespace(
        model_dump=lambda **_kwargs: {
            "id": "message-1",
            "type": "agentMessage",
            "text": "",
            "phase": "final_answer",
        }
    )
    agent_item = SimpleNamespace(
        model_dump=lambda **_kwargs: {
            "id": "message-1",
            "type": "agentMessage",
            "text": answer,
            "phase": "final_answer",
        }
    )
    return [
        FakeNotification("turn/started", FakePayload()),
        FakeNotification("item/started", FakePayload(item=started_item)),
        FakeNotification(
            "item/agentMessage/delta",
            FakePayload(delta=answer, item_id="message-1"),
        ),
        FakeNotification("item/completed", FakePayload(item=agent_item)),
        FakeNotification(
            "turn/completed",
            FakePayload(
                turn=FakePayload(status=SimpleNamespace(value="completed"), error=None)
            ),
        ),
    ]


def test_new_turn_creates_thread_and_persists_only_binding_metadata():
    repo = FakeRepo()
    codex = FakeCodex(completed_events())
    service = CodexConversationService(repo=repo, codex_factory=lambda: codex)
    payload = ConversationTurnRequest(
        conversation_id="conversation-1",
        history_id="history-1",
        message="这个区域适合什么功能？",
        map_context={"active_panel": "poi"},
    )

    async def collect():
        return [event async for event in service.stream_turn(FakeRequest(), payload)]

    events = asyncio.run(collect())

    assert codex.started == 1
    assert codex.resumed == []
    assert codex.start_options[0]["approval_mode"] == ApprovalMode.auto_review
    assert codex.start_options[0]["sandbox"] == Sandbox.read_only
    assert codex.thread.turn_inputs == [payload.message]
    assert [event[0] for event in events] == [
        "thread",
        "turn_started",
        "item_started",
        "message_delta",
        "item_completed",
        "turn_completed",
    ]
    assert repo.records["conversation-1"]["codex_thread_id"] == "thread-1"
    assert repo.records["conversation-1"]["status"] == "answered"
    assert "snapshot" not in repo.records["conversation-1"]
    assert "messages" not in repo.records["conversation-1"]


def test_followup_resumes_same_thread_without_resending_history():
    repo = FakeRepo()
    repo.upsert_record(
        "conversation-1",
        codex_thread_id="thread-existing",
        title="已有对话",
        preview="上一轮",
        status="answered",
        history_id="history-1",
        panel_kind="analysis",
    )
    codex = FakeCodex(completed_events("第二轮回答"))
    service = CodexConversationService(repo=repo, codex_factory=lambda: codex)
    payload = ConversationTurnRequest(
        conversation_id="conversation-1",
        history_id="history-1",
        message="继续说明",
    )

    async def collect():
        return [event async for event in service.stream_turn(FakeRequest(), payload)]

    _ = asyncio.run(collect())

    assert codex.started == 0
    assert codex.resumed == ["thread-existing"]
    assert codex.resume_options[0]["approval_mode"] == ApprovalMode.auto_review
    assert codex.resume_options[0]["sandbox"] == Sandbox.read_only
    assert codex.thread.turn_inputs == ["继续说明"]


def test_disconnect_interrupts_active_turn():
    repo = FakeRepo()
    codex = FakeCodex(completed_events())
    service = CodexConversationService(repo=repo, codex_factory=lambda: codex)
    payload = ConversationTurnRequest(
        conversation_id="conversation-1",
        history_id="history-1",
        message="开始分析",
    )

    async def collect():
        return [event async for event in service.stream_turn(FakeRequest(True), payload)]

    events = asyncio.run(collect())

    assert events == [("thread", {"conversation_id": "conversation-1"})]
    assert repo.records["conversation-1"]["status"] == "idle"


def test_thread_history_projects_wrapped_items_and_omits_commentary():
    def wrapped_item(**payload):
        return SimpleNamespace(model_dump=lambda **_kwargs: payload)

    thread = SimpleNamespace(
        turns=[
            SimpleNamespace(
                items=[
                    wrapped_item(
                        id="user-1",
                        type="userMessage",
                        content=[{"type": "text", "text": "用户问题"}],
                    ),
                    wrapped_item(
                        id="commentary-1",
                        type="agentMessage",
                        phase="commentary",
                        text="我会先读取项目。",
                    ),
                    wrapped_item(
                        id="answer-1",
                        type="agentMessage",
                        phase="final_answer",
                        text="最终回答",
                    ),
                ]
            )
        ]
    )

    messages = _thread_messages(thread)

    assert [message.model_dump() for message in messages] == [
        {"id": "user-1", "role": "user", "content": "用户问题"},
        {"id": "answer-1", "role": "assistant", "content": "最终回答"},
    ]


def test_followup_rejects_panel_kind_change():
    repo = FakeRepo()
    repo.upsert_record(
        "conversation-1",
        codex_thread_id="thread-existing",
        title="已有对话",
        preview="上一轮",
        status="answered",
        history_id="history-1",
        panel_kind="analysis",
    )
    codex = FakeCodex(completed_events())
    service = CodexConversationService(repo=repo, codex_factory=lambda: codex)
    payload = ConversationTurnRequest(
        conversation_id="conversation-1",
        history_id="history-1",
        panel_kind="ppt_planning",
        message="继续说明",
    )

    async def collect():
        return [event async for event in service.stream_turn(FakeRequest(), payload)]

    events = asyncio.run(collect())

    assert events == [("error", {"message": "会话类型与当前面板不一致"})]
    assert codex.resumed == []


def test_task_cancellation_interrupts_active_turn_and_restores_idle():
    repo = FakeRepo()
    codex = FakeCodex([])
    turn_started = asyncio.Event()
    release_stream = asyncio.Event()

    async def blocking_stream():
        turn_started.set()
        await release_stream.wait()
        if False:
            yield None

    async def blocking_turn(_value):
        turn = FakeTurn([])
        turn.stream = blocking_stream
        codex.thread.last_turn = turn
        return turn

    codex.thread.turn = blocking_turn
    service = CodexConversationService(repo=repo, codex_factory=lambda: codex)
    payload = ConversationTurnRequest(
        conversation_id="conversation-1",
        history_id="history-1",
        message="开始分析",
    )

    async def run_and_cancel():
        generator = service.stream_turn(FakeRequest(), payload)
        assert await anext(generator) == (
            "thread",
            {"conversation_id": "conversation-1"},
        )
        task = asyncio.create_task(anext(generator))
        await turn_started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await generator.aclose()

    asyncio.run(run_and_cancel())

    assert codex.thread.last_turn.interrupted is True
    assert repo.records["conversation-1"]["status"] == "idle"
