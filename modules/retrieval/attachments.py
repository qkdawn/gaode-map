from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List
from uuid import uuid4

from core.config import settings
from modules.evidence_index import build_source_index_manifest_payload, persist_source_index_manifest_payload
from modules.evidence_index.schemas import SourceIndexManifest

from .ranker import rank_chunks
from .schemas import AttachmentChunk, AttachmentRecord, AttachmentSearchHit, KnowledgeChunk


_METADATA_FILENAME = "metadata.json"
_CHUNKS_FILENAME = "chunks.json"
_IMAGE_INDEX_FILENAME = "image_visual_index.json"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_segment(value: str, fallback: str) -> str:
    text = _SAFE_NAME_RE.sub("-", str(value or "").strip()).strip(".-")
    return text[:120] or fallback


def _attachment_root() -> Path:
    return Path(settings.agent_attachment_upload_dir).resolve()


def _conversation_dir(conversation_id: str) -> Path:
    return _attachment_root() / _safe_segment(conversation_id, "conversation")


def _metadata_path(attachment_dir: Path) -> Path:
    return attachment_dir / _METADATA_FILENAME


def _chunks_path(attachment_dir: Path) -> Path:
    return attachment_dir / _CHUNKS_FILENAME


def _image_index_path(attachment_dir: Path) -> Path:
    return attachment_dir / _IMAGE_INDEX_FILENAME


def _record_from_file(path: Path) -> AttachmentRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return AttachmentRecord(**payload)
    except Exception:
        return None


def _write_record(record: AttachmentRecord) -> None:
    attachment_dir = Path(record.working_dir).parent
    attachment_dir.mkdir(parents=True, exist_ok=True)
    _metadata_path(attachment_dir).write_text(
        record.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _allowed_extensions() -> set[str]:
    return {
        str(item or "").strip().lower()
        for item in (settings.agent_attachment_allowed_extensions or [])
        if str(item or "").strip()
    }


def _validate_upload(filename: str, size_bytes: int) -> None:
    suffix = Path(filename or "").suffix.lower()
    if not suffix or suffix not in _allowed_extensions():
        raise ValueError("unsupported_attachment_type")
    max_bytes = max(1, int(settings.agent_attachment_max_mb or 30)) * 1024 * 1024
    if size_bytes <= 0:
        raise ValueError("empty_attachment")
    if size_bytes > max_bytes:
        raise ValueError("attachment_too_large")


def _iter_conversation_records(conversation_id: str) -> List[AttachmentRecord]:
    base = _conversation_dir(conversation_id)
    if not base.exists():
        return []
    rows: List[AttachmentRecord] = []
    for metadata_path in base.glob(f"*/{_METADATA_FILENAME}"):
        record = _record_from_file(metadata_path)
        if record and record.conversation_id == conversation_id:
            rows.append(record)
    rows.sort(key=lambda item: item.created_at, reverse=True)
    return rows


def _find_record(conversation_id: str, attachment_id: str) -> AttachmentRecord | None:
    metadata_path = _conversation_dir(conversation_id) / _safe_segment(attachment_id, "attachment") / _METADATA_FILENAME
    record = _record_from_file(metadata_path)
    if record and record.conversation_id == conversation_id:
        return record
    return None


def save_attachment_upload(
    *,
    conversation_id: str,
    history_id: str,
    filename: str,
    content_type: str,
    fileobj: BinaryIO,
) -> AttachmentRecord:
    normalized_conversation_id = _safe_segment(conversation_id, "")
    if not normalized_conversation_id:
        raise ValueError("conversation_id_required")
    attachment_id = uuid4().hex
    safe_filename = _safe_segment(Path(filename or "attachment").name, f"attachment{Path(filename or '').suffix}")
    attachment_dir = _conversation_dir(normalized_conversation_id) / attachment_id
    source_dir = attachment_dir / "source"
    working_dir = attachment_dir / "image-index"
    output_dir = attachment_dir / "parsed"
    source_dir.mkdir(parents=True, exist_ok=True)
    file_path = source_dir / safe_filename

    with file_path.open("wb") as handle:
        shutil.copyfileobj(fileobj, handle)
    size_bytes = file_path.stat().st_size
    try:
        _validate_upload(safe_filename, size_bytes)
    except ValueError:
        shutil.rmtree(attachment_dir, ignore_errors=True)
        raise

    now = _utc_now()
    record = AttachmentRecord(
        attachment_id=attachment_id,
        conversation_id=normalized_conversation_id,
        history_id=str(history_id or "").strip(),
        filename=safe_filename,
        mime_type=str(content_type or mimetypes.guess_type(safe_filename)[0] or ""),
        size_bytes=size_bytes,
        status="uploaded",
        created_at=now,
        updated_at=now,
        file_path=str(file_path),
        working_dir=str(working_dir),
        output_dir=str(output_dir),
    )
    _write_record(record)
    return record


def list_attachments(conversation_id: str) -> List[AttachmentRecord]:
    normalized = _safe_segment(conversation_id, "")
    if not normalized:
        return []
    return _iter_conversation_records(normalized)


def get_attachments(conversation_id: str, attachment_ids: List[str] | None = None) -> List[AttachmentRecord]:
    allowed = {_safe_segment(item, "") for item in (attachment_ids or []) if _safe_segment(item, "")}
    rows = list_attachments(conversation_id)
    if allowed:
        rows = [record for record in rows if record.attachment_id in allowed]
    return rows


def delete_attachment(conversation_id: str, attachment_id: str) -> bool:
    record = _find_record(_safe_segment(conversation_id, ""), _safe_segment(attachment_id, ""))
    if not record:
        return False
    attachment_dir = Path(record.working_dir).parent
    shutil.rmtree(attachment_dir, ignore_errors=True)
    return True


def retry_attachment_ingest(conversation_id: str, attachment_id: str) -> AttachmentRecord | None:
    record = _find_record(_safe_segment(conversation_id, ""), _safe_segment(attachment_id, ""))
    if not record:
        return None
    current = record.model_copy(update={"status": "processing", "error": "", "updated_at": _utc_now()})
    _write_record(current)
    schedule_attachment_ingest(current)
    return current


async def ingest_attachment(record: AttachmentRecord) -> AttachmentRecord:
    current = record.model_copy(update={"status": "processing", "updated_at": _utc_now(), "error": ""})
    _write_record(current)
    try:
        chunks = await _process_attachment_for_index(current)
        if chunks:
            _write_chunks(current, chunks)
        summary = _summarize_chunks(chunks)
        warnings = list(current.warnings or [])
        if not chunks:
            warnings.append("附件索引未返回可检索上下文。")
        current = current.model_copy(
            update={
                "status": "ready",
                "summary": summary or "附件已建立索引，可用于聊天检索。",
                "warnings": warnings,
                "updated_at": _utc_now(),
            }
        )
    except Exception as exc:
        current = current.model_copy(
            update={
                "status": "failed",
                "error": str(exc),
                "warnings": list(current.warnings or []) + [f"附件解析失败: {exc}"],
                "updated_at": _utc_now(),
            }
        )
    _write_record(current)
    return current


def schedule_attachment_ingest(record: AttachmentRecord) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ingest_attachment(record))
    except RuntimeError:
        asyncio.run(ingest_attachment(record))


async def _process_attachment_for_index(record: AttachmentRecord) -> List[AttachmentChunk]:
    if _is_image_attachment(record):
        chunks = await _process_image_visual_index(record)
        _write_image_visual_index(record, chunks)
        try:
            _persist_attachment_image_manifest(record, chunks)
        except Exception:
            logger.exception("Image visual manifest artifact persist failed")
        return chunks
    return _process_text_attachment_index(record)


async def _process_image_visual_index(record: AttachmentRecord) -> List[AttachmentChunk]:
    return _build_image_visual_index(record)


def _build_image_visual_index(record: AttachmentRecord) -> List[AttachmentChunk]:
    metadata = {
        "conversation_id": record.conversation_id,
        "history_id": record.history_id,
        "mime_type": record.mime_type,
        "image_index_kind": "image_visual_index",
        "source_path": record.file_path,
        "open_source_stack": ["PaddleOCR/PP-Structure", "OpenCLIP", "Qdrant"],
    }
    dimensions = _read_image_dimensions(record.file_path)
    if dimensions:
        metadata["width"] = dimensions["width"]
        metadata["height"] = dimensions["height"]
    content = "图片已登记到 ImageVisualIndex。当前索引包含文件定位、格式和尺寸元数据；OCR/layout/caption/vector 节点需由 PaddleOCR/PP-Structure、OpenCLIP 和 Qdrant 处理器补充。"
    return [
        AttachmentChunk(
            chunk_id=f"attachment:{record.attachment_id}:image:metadata",
            attachment_id=record.attachment_id,
            filename=record.filename,
            title=f"{record.filename} 图片索引",
            content=content,
            locator="image:full",
            evidence_level="image_visual_metadata",
            warnings=["image_visual_index_processor_not_configured"],
            source_artifacts=[record.filename],
            metadata=metadata,
        )
    ]


def _process_text_attachment_index(record: AttachmentRecord) -> List[AttachmentChunk]:
    path = Path(record.file_path)
    content = ""
    if path.suffix.lower() in {".txt", ".md"}:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not content:
        return [
            AttachmentChunk(
                chunk_id=f"attachment:{record.attachment_id}:file:metadata",
                attachment_id=record.attachment_id,
                filename=record.filename,
                title=f"{record.filename} 附件索引",
                content="附件已登记到文件索引；当前仅保存文件定位和元数据，文档正文应通过文档库 PageIndex 或专用解析器进入证据层。",
                locator="file:metadata",
                evidence_level="attachment_metadata",
                warnings=["attachment_text_parser_not_configured"],
                source_artifacts=[record.filename],
                metadata={
                    "conversation_id": record.conversation_id,
                    "history_id": record.history_id,
                    "mime_type": record.mime_type,
                    "source_path": record.file_path,
                },
            )
        ]
    parts = [part.strip() for part in re.split(r"\n{2,}", content) if part.strip()]
    chunks: List[AttachmentChunk] = []
    for index, part in enumerate(parts[:40], start=1):
        chunks.append(
            AttachmentChunk(
                chunk_id=f"attachment:{record.attachment_id}:text:{index}",
                attachment_id=record.attachment_id,
                filename=record.filename,
                title=f"{record.filename} 文本片段 {index}",
                content=part[:4000],
                locator=f"text:{index}",
                evidence_level="attachment_text",
                source_artifacts=[record.filename],
                metadata={
                    "conversation_id": record.conversation_id,
                    "history_id": record.history_id,
                    "mime_type": record.mime_type,
                },
            )
        )
    return chunks


def _write_chunks(record: AttachmentRecord, chunks: List[AttachmentChunk]) -> None:
    attachment_dir = Path(record.working_dir).parent
    attachment_dir.mkdir(parents=True, exist_ok=True)
    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    _chunks_path(attachment_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_image_visual_index(record: AttachmentRecord, chunks: List[AttachmentChunk]) -> None:
    attachment_dir = Path(record.working_dir).parent
    attachment_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "image_visual_index_v1",
        "attachment_id": record.attachment_id,
        "filename": record.filename,
        "mime_type": record.mime_type,
        "source_path": record.file_path,
        "nodes": [chunk.model_dump(mode="json") for chunk in chunks],
        "model_versions": {
            "ocr_layout": "paddleocr_ppstructure_target",
            "image_text_embedding": "openclip_target",
            "vector_store": "qdrant_target",
        },
        "diagnostics": [] if chunks else ["image_visual_index_empty"],
    }
    _image_index_path(attachment_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _persist_attachment_image_manifest(record: AttachmentRecord, chunks: List[AttachmentChunk]) -> None:
    history_id = str(record.history_id or "").strip()
    if not history_id:
        return
    source_id = f"image:{record.attachment_id}"
    manifest_payload = build_source_index_manifest_payload(
        source_id=source_id,
        source_kind="image",
        native_index_kind="image_visual_index",
        node_count=len(chunks),
        retrieval_modes=["keyword", "vector"],
        read_modes=["node_id", "attachment_id", "locator", "bbox"],
        storage_ref={
            "attachment_id": record.attachment_id,
            "working_dir": record.working_dir,
            "image_visual_index": str(_image_index_path(Path(record.working_dir).parent)),
        },
        model_versions={
            "ocr_layout": "paddleocr_ppstructure_target",
            "image_text_embedding": "openclip_target",
            "vector_store": "qdrant_target",
        },
        diagnostics=[] if chunks else ["image_visual_index_empty"],
    )
    persist_source_index_manifest_payload(
        history_id,
        SourceIndexManifest.model_validate(manifest_payload),
        source_payload={
            "id": source_id,
            "title": record.filename,
            "source_kind": "image",
            "status": "ready",
            "evidence_count": len(chunks),
            "locator_summary": record.filename,
        },
    )


def _read_chunks(record: AttachmentRecord) -> List[AttachmentChunk]:
    path = _chunks_path(Path(record.working_dir).parent)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [AttachmentChunk(**item) for item in payload if isinstance(item, dict)]
    except Exception:
        return []


def read_attachment_chunks(record: AttachmentRecord) -> List[AttachmentChunk]:
    return _read_chunks(record)


def _summarize_chunks(chunks: List[AttachmentChunk]) -> str:
    if not chunks:
        return ""
    text = " ".join(chunk.content for chunk in chunks[:3])
    return re.sub(r"\s+", " ", text).strip()[:180]


def _is_image_attachment(record: AttachmentRecord) -> bool:
    mime_type = str(record.mime_type or "").strip().lower()
    suffix = Path(record.filename or record.file_path or "").suffix.lower()
    return mime_type.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def _read_image_dimensions(file_path: str) -> Dict[str, int]:
    try:
        from PIL import Image
    except Exception:
        return {}
    try:
        with Image.open(file_path) as image:
            width, height = image.size
            return {"width": int(width), "height": int(height)}
    except Exception:
        return {}


def _search_hit_from_chunk(chunk: AttachmentChunk, *, score: float, snippet: str) -> AttachmentSearchHit:
    return AttachmentSearchHit(
        chunk_id=chunk.chunk_id,
        attachment_id=chunk.attachment_id,
        filename=chunk.filename,
        mime_type=str((chunk.metadata or {}).get("mime_type") or ""),
        snippet=snippet,
        evidence_level=chunk.evidence_level,
        score=score,
        locator=chunk.locator,
        warnings=list(chunk.warnings or []),
    )


def search_attachment_context(
    *,
    conversation_id: str,
    attachment_ids: List[str] | None,
    query: str,
    top_k: int = 8,
) -> List[AttachmentSearchHit]:
    chunks: List[AttachmentChunk] = []
    warnings_by_id: Dict[str, List[str]] = {}
    for record in get_attachments(conversation_id, attachment_ids):
        if record.status != "ready":
            warnings_by_id[record.attachment_id] = list(record.warnings or []) or [f"附件状态为 {record.status}，暂不可检索。"]
            continue
        chunks.extend(_read_chunks(record))
    knowledge_chunks = [
        KnowledgeChunk(
            chunk_id=chunk.chunk_id,
            kind="report",
            domain="attachment",
            title=chunk.title,
            content=chunk.content,
            source_artifacts=chunk.source_artifacts,
            warnings=chunk.warnings,
            evidence_level=chunk.evidence_level,
        )
        for chunk in chunks
    ]
    ranked = rank_chunks(knowledge_chunks, query, top_k=max(1, min(int(top_k or 8), 20)))
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    hits: List[AttachmentSearchHit] = []
    for hit in ranked:
        chunk = chunk_by_id.get(hit.chunk_id)
        if not chunk:
            continue
        hits.append(_search_hit_from_chunk(chunk, score=hit.score, snippet=hit.snippet))
    if not hits and warnings_by_id:
        for attachment_id, warnings in list(warnings_by_id.items())[:3]:
            record = _find_record(_safe_segment(conversation_id, ""), attachment_id)
            if not record:
                continue
            hits.append(
                AttachmentSearchHit(
                    chunk_id=f"attachment:{attachment_id}:status",
                    attachment_id=attachment_id,
                    filename=record.filename,
                    snippet="；".join(warnings),
                    score=0.0,
                    warnings=warnings,
                )
            )
    return hits


def read_attachment_context(
    *,
    conversation_id: str,
    attachment_ids: List[str] | None,
    chunk_id: str,
) -> AttachmentChunk | None:
    allowed = {_safe_segment(item, "") for item in (attachment_ids or []) if _safe_segment(item, "")}
    for record in get_attachments(conversation_id, list(allowed) if allowed else None):
        if record.status != "ready":
            continue
        for chunk in _read_chunks(record):
            if chunk.chunk_id == chunk_id:
                return chunk
    return None
