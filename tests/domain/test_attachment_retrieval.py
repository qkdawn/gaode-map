import asyncio

from modules.agent.tools import get_tool_registry
from modules.retrieval.attachments import (
    get_attachments,
    ingest_attachment,
    read_attachment_context,
    save_attachment_upload,
    search_attachment_context,
)
from modules.retrieval.schemas import AttachmentChunk
from modules.ppt_planning.data_tools import list_ppt_sources


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

    monkeypatch.setattr("modules.retrieval.attachments._process_attachment_for_index", fake_process)
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


def test_ppt_sources_include_ready_image_attachment_source(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.retrieval.attachments.settings.agent_attachment_upload_dir", str(tmp_path))
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: {"id": area_id, "params": {"center": [112.9, 28.2]}})
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: {"count": 0, "pois": []})
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", lambda *args, **kwargs: [])
    manifest_writes = []
    monkeypatch.setattr(
        "modules.retrieval.attachments.persist_source_index_manifest_payload",
        lambda history_id, manifest, source_payload=None: manifest_writes.append((history_id, manifest, source_payload)),
    )

    async def fake_process(record):
        return [
            AttachmentChunk(
                chunk_id=f"attachment:{record.attachment_id}:chunk:1",
                attachment_id=record.attachment_id,
                filename=record.filename,
                title="现场照片 OCR",
                content="OCR 识别到图中标注：主入口、沿街商业、停车场。",
                locator="image:full",
                evidence_level="ocr_text",
                source_artifacts=[record.filename],
                metadata={"mime_type": record.mime_type, "confidence": 0.91},
            )
        ]

    monkeypatch.setattr("modules.retrieval.attachments._process_image_visual_index", fake_process)
    source = tmp_path / "site-photo.png"
    source.write_bytes(b"fake-png")
    with source.open("rb") as handle:
        record = save_attachment_upload(
            conversation_id="ppt-tab-1",
            history_id="history-a",
            filename="site-photo.png",
            content_type="image/png",
            fileobj=handle,
        )
    asyncio.run(ingest_attachment(record))

    sources = {item.id: item for item in list_ppt_sources("history-a", conversation_id="ppt-tab-1")}
    image_source = sources[f"image:{record.attachment_id}"]

    assert image_source.source_kind == "image"
    assert image_source.status == "ready"
    assert image_source.evidence_count == 1
    assert image_source.availability == "available"
    assert image_source.meta["aiPayload"]["sourceKind"] == "image"
    assert image_source.meta["aiPayload"]["evidence_nodes"][0]["source_type"] == "image"
    assert image_source.meta["aiPayload"]["evidence_nodes"][0]["metadata"]["confidence"] == 0.91
    assert image_source.meta["aiPayload"]["index_manifest"]["native_index_kind"] == "image_visual_index"
    assert image_source.meta["aiPayload"]["index_manifest"]["model_versions"]["image_text_embedding"] == "openclip_target"
    assert "evidence" not in image_source.meta["aiPayload"]
    assert manifest_writes
    assert manifest_writes[0][0] == "history-a"
    assert manifest_writes[0][1].native_index_kind == "image_visual_index"


def test_attachment_tools_are_not_registered_as_agent_inputs():
    registry = get_tool_registry()
    assert "search_uploaded_attachment_context" not in registry
    assert "read_uploaded_attachment_context" not in registry
