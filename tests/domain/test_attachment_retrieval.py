import asyncio

from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tool_adapters.retrieval_tools import (
    read_uploaded_attachment_context,
    search_uploaded_attachment_context,
)
from modules.agent.tools import get_tool_registry
from modules.retrieval.attachments import (
    get_attachments,
    ingest_attachment,
    read_attachment_context,
    save_attachment_upload,
    search_attachment_context,
)
from modules.retrieval.schemas import AttachmentChunk


def test_attachment_ingest_search_and_read_are_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.retrieval.attachments.settings.agent_attachment_upload_dir", str(tmp_path))

    async def fake_process(record):
        return [
            AttachmentChunk(
                chunk_id=f"attachment:{record.attachment_id}:chunk:1",
                attachment_id=record.attachment_id,
                filename=record.filename,
                title="规划图说明",
                content="这张规划图显示首层沿街商业和人行入口集中在北侧。",
                locator="page:1",
                source_artifacts=[record.filename],
            )
        ]

    monkeypatch.setattr("modules.retrieval.attachments._process_with_raganything", fake_process)
    source = tmp_path / "demo.txt"
    source.write_text("demo", encoding="utf-8")
    with source.open("rb") as handle:
        record = save_attachment_upload(
            conversation_id="conversation-a",
            history_id="history-a",
            filename="plan.txt",
            content_type="text/plain",
            fileobj=handle,
        )

    ready = asyncio.run(ingest_attachment(record))
    assert ready.status == "ready"

    hits = search_attachment_context(
        conversation_id="conversation-a",
        attachment_ids=[record.attachment_id],
        query="沿街商业 人行入口",
    )
    assert hits
    assert hits[0].filename == "plan.txt"

    chunk = read_attachment_context(
        conversation_id="conversation-a",
        attachment_ids=[record.attachment_id],
        chunk_id=hits[0].chunk_id,
    )
    assert chunk is not None
    assert "沿街商业" in chunk.content

    assert search_attachment_context(
        conversation_id="conversation-b",
        attachment_ids=[record.attachment_id],
        query="沿街商业",
    ) == []


def test_attachment_agent_tools_use_current_conversation_scope(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.retrieval.attachments.settings.agent_attachment_upload_dir", str(tmp_path))

    async def fake_process(record):
        return [
            AttachmentChunk(
                chunk_id=f"attachment:{record.attachment_id}:chunk:1",
                attachment_id=record.attachment_id,
                filename=record.filename,
                title="附件片段",
                content="表格列出了人口密度和商业入口。",
                source_artifacts=[record.filename],
            )
        ]

    monkeypatch.setattr("modules.retrieval.attachments._process_with_raganything", fake_process)
    source = tmp_path / "table.md"
    source.write_text("demo", encoding="utf-8")
    with source.open("rb") as handle:
        record = save_attachment_upload(
            conversation_id="agent-session",
            history_id="",
            filename="table.md",
            content_type="text/markdown",
            fileobj=handle,
        )
    asyncio.run(ingest_attachment(record))

    artifacts = {
        "uploaded_attachment_conversation_id": "agent-session",
        "uploaded_attachment_ids": [record.attachment_id],
    }
    search = asyncio.run(
        search_uploaded_attachment_context(
            arguments={"query": "人口密度", "top_k": 3},
            snapshot=AnalysisSnapshot(),
            artifacts=artifacts,
            question="附件说了什么",
        )
    )
    assert search.status == "success"
    chunk_id = search.result["hits"][0]["chunk_id"]

    read = asyncio.run(
        read_uploaded_attachment_context(
            arguments={"chunk_id": chunk_id},
            snapshot=AnalysisSnapshot(),
            artifacts=artifacts,
            question="读取附件",
        )
    )
    assert read.status == "success"
    assert read.result["filename"] == "table.md"


def test_attachment_tools_are_registered():
    registry = get_tool_registry()
    assert registry["search_uploaded_attachment_context"].spec.readonly is True
    assert registry["read_uploaded_attachment_context"].spec.input_schema["required"] == ["chunk_id"]
