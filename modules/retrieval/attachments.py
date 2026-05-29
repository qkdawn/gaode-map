from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import shutil
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, BinaryIO, Dict, List
from uuid import uuid4

from core.config import settings

from .ranker import rank_chunks
from .schemas import AttachmentChunk, AttachmentRecord, AttachmentSearchHit, KnowledgeChunk


_METADATA_FILENAME = "metadata.json"
_CHUNKS_FILENAME = "chunks.json"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


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
    working_dir = attachment_dir / "rag"
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


async def ingest_attachment(record: AttachmentRecord) -> AttachmentRecord:
    current = record.model_copy(update={"status": "processing", "updated_at": _utc_now(), "error": ""})
    _write_record(current)
    try:
        chunks = await _process_with_raganything(current)
        if chunks:
            _write_chunks(current, chunks)
        summary = _summarize_chunks(chunks)
        warnings = list(current.warnings or [])
        if not chunks:
            warnings.append("RAG-Anything 已完成处理，但未返回可检索上下文。")
        current = current.model_copy(
            update={
                "status": "ready",
                "summary": summary or "附件已解析，可用于聊天检索。",
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


async def _process_with_raganything(record: AttachmentRecord) -> List[AttachmentChunk]:
    try:
        from raganything import RAGAnything, RAGAnythingConfig
        from lightrag.llm.openai import openai_complete_if_cache, openai_embed
        from lightrag.utils import EmbeddingFunc
    except Exception as exc:
        raise RuntimeError("raganything_all_dependency_unavailable") from exc

    api_key = str(settings.ai_api_key or "").strip()
    base_url = str(settings.ai_base_url or "").strip() or None
    model = str(settings.ai_model or "").strip()
    embedding_model = str(settings.raganything_embedding_model or "").strip()
    if not (api_key and model and embedding_model):
        raise RuntimeError("raganything_provider_not_configured")

    def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return openai_complete_if_cache(
            model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    def vision_model_func(prompt, system_prompt=None, history_messages=None, image_data=None, messages=None, **kwargs):
        if messages:
            return openai_complete_if_cache(
                model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        if image_data:
            return openai_complete_if_cache(
                model,
                "",
                system_prompt=None,
                history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                        ],
                    },
                ],
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        return llm_model_func(prompt, system_prompt, history_messages or [], **kwargs)

    embedding_func = EmbeddingFunc(
        embedding_dim=int(settings.raganything_embedding_dim or 3072),
        max_token_size=8192,
        func=partial(
            openai_embed.func,
            model=embedding_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )
    config = RAGAnythingConfig(
        working_dir=record.working_dir,
        parser_output_dir=record.output_dir,
        parser=str(settings.raganything_parser or "mineru"),
        parse_method=str(settings.raganything_parse_method or "auto"),
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
        display_content_stats=False,
    )
    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=embedding_func,
    )
    try:
        await rag.process_document_complete(
            file_path=record.file_path,
            output_dir=record.output_dir,
            parse_method=str(settings.raganything_parse_method or "auto"),
            doc_id=record.attachment_id,
            file_name=record.filename,
        )
        context = await rag.aquery(
            "提取这份附件中最重要的文本、图片、表格、公式和页码线索，保留可作为后续问答引用的原文上下文。",
            mode="hybrid",
            only_need_context=True,
            top_k=20,
        )
        return _chunks_from_context(record, str(context or ""))
    finally:
        try:
            await rag.finalize_storages()
        except Exception:
            pass


def _chunks_from_context(record: AttachmentRecord, context: str) -> List[AttachmentChunk]:
    text = str(context or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not parts:
        parts = [text]
    chunks: List[AttachmentChunk] = []
    for index, part in enumerate(parts[:40], start=1):
        chunks.append(
            AttachmentChunk(
                chunk_id=f"attachment:{record.attachment_id}:chunk:{index}",
                attachment_id=record.attachment_id,
                filename=record.filename,
                title=f"{record.filename} 片段 {index}",
                content=part[:4000],
                locator=_extract_locator(part),
                source_artifacts=[record.filename],
                metadata={"conversation_id": record.conversation_id},
            )
        )
    return chunks


def _extract_locator(text: str) -> str:
    match = re.search(r"(?:page|页码|第)\s*[:：]?\s*(\d+)", str(text or ""), re.IGNORECASE)
    return f"page:{match.group(1)}" if match else ""


def _write_chunks(record: AttachmentRecord, chunks: List[AttachmentChunk]) -> None:
    attachment_dir = Path(record.working_dir).parent
    attachment_dir.mkdir(parents=True, exist_ok=True)
    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    _chunks_path(attachment_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_chunks(record: AttachmentRecord) -> List[AttachmentChunk]:
    path = _chunks_path(Path(record.working_dir).parent)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [AttachmentChunk(**item) for item in payload if isinstance(item, dict)]
    except Exception:
        return []


def _summarize_chunks(chunks: List[AttachmentChunk]) -> str:
    if not chunks:
        return ""
    text = " ".join(chunk.content for chunk in chunks[:3])
    return re.sub(r"\s+", " ", text).strip()[:180]


def _search_hit_from_chunk(chunk: AttachmentChunk, *, score: float, snippet: str) -> AttachmentSearchHit:
    return AttachmentSearchHit(
        chunk_id=chunk.chunk_id,
        attachment_id=chunk.attachment_id,
        filename=chunk.filename,
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
