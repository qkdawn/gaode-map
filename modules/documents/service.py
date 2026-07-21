from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, List
from uuid import uuid4

from core.config import settings
from modules.jobs import JobCreateResponse, create_job, schedule_job
from store.ai_database import SessionLocal
from store.ai_models import Document, DocumentBlock, DocumentIndexNode

from .docling_parser import ParsedDocumentBlock, parse_document_with_docling
from .schemas import DocumentBlockResponse, DocumentBlocksResponse, DocumentRecord, DocumentRole


_SAFE_NAME_RE = re.compile(r"[^\w._-]+", re.UNICODE)
_ALLOWED_TYPES = {
    ".pdf": {
        "file_type": "pdf",
        "mime_types": {"application/pdf"},
    },
    ".docx": {
        "file_type": "docx",
        "mime_types": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    },
}


class UnsupportedDocumentType(ValueError):
    pass


class EmptyDocument(ValueError):
    pass


class DocumentTooLarge(ValueError):
    pass


class DocumentNotFound(LookupError):
    pass


def _document_root() -> Path:
    return Path(settings.document_upload_dir).resolve()


def _safe_file_name(filename: str) -> str:
    source = Path(str(filename or "document")).name
    cleaned = _SAFE_NAME_RE.sub("-", source).strip(".-")
    return cleaned[:160] or "document"


def _normalize_title(title: str | None, file_name: str) -> str:
    raw = str(title or "").strip()
    if raw:
        return raw[:255]
    fallback = Path(file_name).stem.strip() or file_name
    return fallback[:255]


def _file_type_for(file_name: str, content_type: str) -> str:
    suffix = Path(file_name).suffix.lower()
    spec = _ALLOWED_TYPES.get(suffix)
    if spec is None:
        raise UnsupportedDocumentType("unsupported_document_type")
    normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type and normalized_content_type not in spec["mime_types"]:
        # Browsers and tests sometimes omit DOCX types, but a conflicting known type is rejected.
        if normalized_content_type not in {"application/octet-stream", "binary/octet-stream"}:
            raise UnsupportedDocumentType("unsupported_document_type")
    return str(spec["file_type"])


def _validate_size(path: Path) -> None:
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise EmptyDocument("empty_document")
    max_bytes = max(1, int(settings.document_max_mb or 50)) * 1024 * 1024
    if size_bytes > max_bytes:
        raise DocumentTooLarge("document_too_large")


def _record_payload(record: Document) -> DocumentRecord:
    return DocumentRecord.model_validate(record)


def _block_payload(record: DocumentBlock) -> DocumentBlockResponse:
    return DocumentBlockResponse(
        id=int(record.id),
        pageIndex=int(record.page_index or 0),
        blockIndex=int(record.block_index or 0),
        blockType=str(record.block_type or "paragraph"),
        text=str(record.text or ""),
        sectionTitle=str(record.section_title or ""),
    )


def create_document_upload(
    *,
    filename: str,
    content_type: str,
    fileobj: BinaryIO,
    document_role: DocumentRole,
    history_id: str = "",
    title: str | None = None,
) -> DocumentRecord:
    safe_name = _safe_file_name(filename)
    file_type = _file_type_for(safe_name, content_type)
    document_id = uuid4().hex
    source_dir = _document_root() / document_id / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    file_path = source_dir / safe_name

    try:
        with file_path.open("wb") as handle:
            shutil.copyfileobj(fileobj, handle)
        _validate_size(file_path)

        now = datetime.utcnow()
        record = Document(
            id=document_id,
            title=_normalize_title(title, safe_name),
            file_name=safe_name,
            file_type=file_type,
            file_path=str(file_path),
            history_id=str(history_id or "").strip() or None,
            document_role=document_role.value,
            upload_time=now,
            status="uploaded",
        )
        session = SessionLocal()
        try:
            session.add(record)
            session.commit()
            session.refresh(record)
            return _record_payload(record)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception:
        if file_path.exists():
            shutil.rmtree(source_dir.parent, ignore_errors=True)
        raise


def list_documents(history_id: str = "") -> List[DocumentRecord]:
    session = SessionLocal()
    try:
        query = session.query(Document)
        normalized_history_id = str(history_id or "").strip()
        if normalized_history_id:
            query = query.filter(Document.history_id == normalized_history_id)
        rows = query.order_by(Document.upload_time.desc(), Document.id.desc()).all()
        return [_record_payload(row) for row in rows]
    finally:
        session.close()


def get_document(document_id: str) -> DocumentRecord:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    session = SessionLocal()
    try:
        record = session.get(Document, normalized_id)
        if record is None:
            raise DocumentNotFound("document_not_found")
        return _record_payload(record)
    finally:
        session.close()


def _resolve_document_source(document_id: str, *, history_id: str = "") -> tuple[DocumentRecord, Path]:
    record = get_document(document_id)
    normalized_history_id = str(history_id or "").strip()
    if normalized_history_id and record.history_id != normalized_history_id:
        raise DocumentNotFound("document_not_found")
    path = Path(record.file_path).resolve()
    root = _document_root()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DocumentNotFound("document_not_found") from exc
    if not path.is_file():
        raise DocumentNotFound("document_source_missing")
    _validate_size(path)
    return record, path


def get_document_source_metadata(document_id: str, *, history_id: str = "") -> dict[str, object]:
    """Describe one source file without exposing its server-side path."""
    record, path = _resolve_document_source(document_id, history_id=history_id)
    mime_type = _ALLOWED_TYPES[path.suffix.lower()]["mime_types"]
    preferred_mime = next(value for value in mime_type if value != "application/octet-stream")
    return {
        "document_id": record.id,
        "title": record.title,
        "file_name": record.file_name,
        "file_type": record.file_type,
        "mime_type": preferred_mime,
        "size": path.stat().st_size,
    }


def read_document_source(document_id: str, *, history_id: str = "") -> tuple[DocumentRecord, bytes]:
    """Read one uploaded source file after validating its project and storage boundary."""
    record, path = _resolve_document_source(document_id, history_id=history_id)
    return record, path.read_bytes()


def delete_document(document_id: str) -> DocumentRecord:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    session = SessionLocal()
    file_root: Path | None = None
    try:
        record = session.get(Document, normalized_id)
        if record is None:
            raise DocumentNotFound("document_not_found")
        payload = _record_payload(record)
        file_path = Path(str(record.file_path or "")).resolve() if record.file_path else None
        document_root = _document_root()
        if file_path:
            try:
                file_path.relative_to(document_root)
                file_root = file_path.parent.parent if file_path.parent.name == "source" else file_path.parent
            except ValueError:
                file_root = None
        session.query(DocumentIndexNode).filter_by(document_id=normalized_id).delete()
        session.query(DocumentBlock).filter_by(document_id=normalized_id).delete()
        session.delete(record)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    if file_root is not None and file_root.exists():
        shutil.rmtree(file_root, ignore_errors=True)
    return payload


def schedule_document_parse(document_id: str) -> JobCreateResponse:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    session = SessionLocal()
    try:
        record = session.get(Document, normalized_id)
        if record is None:
            raise DocumentNotFound("document_not_found")
    finally:
        session.close()

    job = create_job(job_type="parse_document", target_type="document", target_id=normalized_id)
    schedule_job(job.id, parse_document)
    return JobCreateResponse(job_id=job.id, status=job.status)


async def parse_document(document_id: str) -> DocumentRecord:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    session = SessionLocal()
    try:
        record = session.get(Document, normalized_id)
        if record is None:
            raise DocumentNotFound("document_not_found")
        record.status = "parsing"
        session.commit()
        file_path = str(record.file_path or "")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    try:
        parsed_blocks = await asyncio.to_thread(parse_document_with_docling, file_path)
    except Exception:
        _mark_document_failed(normalized_id)
        raise

    record = _replace_document_blocks(normalized_id, parsed_blocks)
    from .pageindex import rebuild_document_index

    await asyncio.to_thread(rebuild_document_index, normalized_id)
    return record


def _mark_document_failed(document_id: str) -> None:
    session = SessionLocal()
    try:
        record = session.get(Document, document_id)
        if record is not None:
            record.status = "failed"
        session.query(DocumentBlock).filter_by(document_id=document_id).delete()
        session.query(DocumentIndexNode).filter_by(document_id=document_id).delete()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _replace_document_blocks(document_id: str, blocks: List[ParsedDocumentBlock]) -> DocumentRecord:
    session = SessionLocal()
    try:
        record = session.get(Document, document_id)
        if record is None:
            raise DocumentNotFound("document_not_found")
        session.query(DocumentIndexNode).filter_by(document_id=document_id).delete()
        session.query(DocumentBlock).filter_by(document_id=document_id).delete()
        for block in blocks:
            session.add(
                DocumentBlock(
                    document_id=document_id,
                    page_index=int(block.page_index or 0),
                    block_index=int(block.block_index or 0),
                    block_type=str(block.block_type or "paragraph"),
                    text=str(block.text or ""),
                    section_title=str(block.section_title or "")[:255],
                )
            )
        record.status = "parsed"
        session.commit()
        session.refresh(record)
        return _record_payload(record)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_document_blocks(document_id: str) -> DocumentBlocksResponse:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    session = SessionLocal()
    try:
        record = session.get(Document, normalized_id)
        if record is None:
            raise DocumentNotFound("document_not_found")
        rows = (
            session.query(DocumentBlock)
            .filter_by(document_id=normalized_id)
            .order_by(DocumentBlock.page_index.asc(), DocumentBlock.block_index.asc(), DocumentBlock.id.asc())
            .all()
        )
        return DocumentBlocksResponse(
            document=_record_payload(record),
            status=record.status,
            blocks=[_block_payload(row) for row in rows],
        )
    finally:
        session.close()
