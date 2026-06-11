from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, List

from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled
from modules.jobs import JobCreateResponse, create_job, schedule_job
from store.ai_database import SessionLocal
from store.ai_models import Document, DocumentBlock, EvidenceChunk

from .schemas import EvidenceChunkRecord
from .service import DocumentNotFound


logger = logging.getLogger(__name__)

_MIN_PARAGRAPH_CHARS = 300
_MAX_PARAGRAPH_CHARS = 800
_DEFAULT_SEMANTIC_TYPE = "background_statement"
_FALLBACK_SEMANTIC_TYPE = "background_statement"
_FALLBACK_TAGS = ["project_background"]

SEMANTIC_TYPES = {
    "background_statement",
    "problem_statement",
    "positioning_statement",
    "industry_direction",
    "public_service_requirement",
    "stakeholder_requirement",
    "constraint_statement",
    "strategy_suggestion",
    "policy_requirement",
    "operation_mode",
    "case_reference",
}

EVIDENCE_TAGS = {
    "project_background",
    "spatial_scope",
    "problem",
    "project_positioning",
    "industry",
    "public_service",
    "heritage_protection",
    "stakeholder",
    "constraint",
    "strategy",
    "policy",
    "demand",
    "transportation",
    "operation",
    "case_reference",
}


@dataclass
class _PendingParagraph:
    text_parts: List[str]
    page_start: int
    page_end: int
    section_path: List[str]

    @property
    def text(self) -> str:
        return "\n\n".join(self.text_parts).strip()

    @property
    def char_count(self) -> int:
        return len(self.text)


def build_evidence_chunks_from_blocks(document_id: str) -> List[EvidenceChunkRecord]:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")

    session = SessionLocal()
    try:
        document = session.get(Document, normalized_id)
        if document is None:
            raise DocumentNotFound("document_not_found")

        blocks = (
            session.query(DocumentBlock)
            .filter_by(document_id=normalized_id)
            .order_by(DocumentBlock.page_index.asc(), DocumentBlock.block_index.asc(), DocumentBlock.id.asc())
            .all()
        )

        session.query(EvidenceChunk).filter_by(document_id=normalized_id).delete()
        for chunk in _build_chunks(document, blocks):
            session.add(chunk)
        session.commit()

        rows = _ordered_chunks(session, normalized_id)
        return [_chunk_payload(row) for row in rows]
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def schedule_document_evidence_build(document_id: str) -> JobCreateResponse:
    normalized_id = _normalize_document_id(document_id)
    session = SessionLocal()
    try:
        document = session.get(Document, normalized_id)
        if document is None:
            raise DocumentNotFound("document_not_found")
    finally:
        session.close()

    job = create_job(job_type="build_evidence", target_type="document", target_id=normalized_id)
    schedule_job(job.id, build_evidence_with_llm)
    return JobCreateResponse(job_id=job.id, status=job.status)


async def build_evidence_with_llm(document_id: str) -> List[EvidenceChunkRecord]:
    normalized_id = _normalize_document_id(document_id)
    if not is_llm_enabled():
        raise RuntimeError("llm_not_enabled")

    document, blocks = _load_document_and_blocks(normalized_id)
    chunks = _build_chunks(document, blocks)
    for chunk in chunks:
        annotation = await _annotate_chunk_with_llm(document=document, chunk=chunk)
        chunk.summary = annotation.summary
        chunk.semantic_type = annotation.semantic_type
        chunk.tags = annotation.tags

    return _replace_evidence_chunks(normalized_id, chunks)


def list_evidence_chunks(document_id: str) -> List[EvidenceChunkRecord]:
    normalized_id = _normalize_document_id(document_id)

    session = SessionLocal()
    try:
        document = session.get(Document, normalized_id)
        if document is None:
            raise DocumentNotFound("document_not_found")
        return [_chunk_payload(row) for row in _ordered_chunks(session, normalized_id)]
    finally:
        session.close()


def _normalize_document_id(document_id: str) -> str:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    return normalized_id


def _load_document_and_blocks(document_id: str) -> tuple[Document, List[DocumentBlock]]:
    session = SessionLocal()
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNotFound("document_not_found")
        blocks = (
            session.query(DocumentBlock)
            .filter_by(document_id=document_id)
            .order_by(DocumentBlock.page_index.asc(), DocumentBlock.block_index.asc(), DocumentBlock.id.asc())
            .all()
        )
        session.expunge(document)
        for block in blocks:
            session.expunge(block)
        return document, blocks
    finally:
        session.close()


def _replace_evidence_chunks(document_id: str, chunks: List[EvidenceChunk]) -> List[EvidenceChunkRecord]:
    session = SessionLocal()
    try:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNotFound("document_not_found")
        session.query(EvidenceChunk).filter_by(document_id=document_id).delete()
        for chunk in chunks:
            session.add(chunk)
        session.commit()
        rows = _ordered_chunks(session, document_id)
        return [_chunk_payload(row) for row in rows]
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ordered_chunks(session, document_id: str) -> List[EvidenceChunk]:
    return (
        session.query(EvidenceChunk)
        .filter_by(document_id=document_id)
        .order_by(EvidenceChunk.page_start.asc(), EvidenceChunk.id.asc())
        .all()
    )


@dataclass(frozen=True)
class _EvidenceAnnotation:
    summary: str
    semantic_type: str
    tags: List[str]


async def _annotate_chunk_with_llm(*, document: Document, chunk: EvidenceChunk) -> _EvidenceAnnotation:
    payload = await _invoke_json_role(
        system_prompt=_evidence_annotation_system_prompt(),
        user_payload={
            "document": {
                "id": str(document.id),
                "title": str(document.title or document.file_name or ""),
                "file_type": str(document.file_type or ""),
                "document_role": str(document.document_role or "evidence_document"),
            },
            "chunk": {
                "text": str(chunk.text or ""),
                "chunk_type": str(chunk.chunk_type or "paragraph"),
                "section_path": list(chunk.section_path or []),
                "page_start": int(chunk.page_start or 1),
                "page_end": int(chunk.page_end or chunk.page_start or 1),
                "citation": str(chunk.citation or ""),
            },
            "allowed_semantic_types": sorted(SEMANTIC_TYPES),
            "allowed_tags": sorted(EVIDENCE_TAGS),
            "output_format": {"summary": "string", "semantic_type": "string", "tags": ["string"]},
        },
        emit=None,
        phase="document_evidence",
        title="标注文档证据",
        reasoning_id=f"document-evidence-{document.id}-{chunk.page_start}-{chunk.page_end}",
    )
    return _normalize_annotation(payload, source_text=str(chunk.text or ""))


def _evidence_annotation_system_prompt() -> str:
    return (
        "你是城市空间分析工作台的文档证据标注器。"
        "只输出 JSON 对象，格式必须为 {\"summary\":\"...\",\"semantic_type\":\"...\",\"tags\":[\"...\"]}。"
        "summary 用中文概括该证据块的可引用信息，避免夸大，不生成原文没有的指标。"
        "semantic_type 和 tags 必须从用户提供的枚举中选择；tags 最多 3 个。"
    )


def _normalize_annotation(raw: Any, *, source_text: str) -> _EvidenceAnnotation:
    data = raw if isinstance(raw, dict) else {}
    summary = str(data.get("summary") or "").strip()
    if not summary:
        summary = _fallback_summary(source_text)

    semantic_type = str(data.get("semantic_type") or "").strip()
    if semantic_type not in SEMANTIC_TYPES:
        semantic_type = _FALLBACK_SEMANTIC_TYPE

    raw_tags = data.get("tags")
    tags: List[str] = []
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            normalized = str(tag or "").strip()
            if normalized in EVIDENCE_TAGS and normalized not in tags:
                tags.append(normalized)
            if len(tags) >= 3:
                break
    if not tags:
        tags = list(_FALLBACK_TAGS)
    return _EvidenceAnnotation(summary=summary[:1000], semantic_type=semantic_type, tags=tags)


def _fallback_summary(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed[:240] or "该证据块缺少可概括文本。"


def _build_chunks(document: Document, blocks: Iterable[DocumentBlock]) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    pending: _PendingParagraph | None = None
    current_section: List[str] = []
    title_without_body: tuple[str, int, List[str]] | None = None

    for block in blocks:
        block_type = _normalize_block_type(block.block_type)
        text = str(block.text or "").strip()
        if not text:
            continue

        section_path = _section_path(block, current_section)
        page = _one_based_page(block)

        if block_type == "title":
            if title_without_body is not None:
                chunks.append(_make_chunk(document, "title", title_without_body[0], title_without_body[1], title_without_body[1], title_without_body[2]))
            pending = _flush_pending(document, chunks, pending)
            current_section = [text[:255]]
            title_without_body = (text, page, list(current_section))
            continue

        if block_type in {"table", "figure", "caption"}:
            pending = _flush_pending(document, chunks, pending)
            title_without_body = None
            chunks.append(_make_chunk(document, block_type, text, page, page, section_path))
            continue

        title_without_body = None
        if pending is None or pending.section_path != section_path:
            pending = _flush_pending(document, chunks, pending)
            pending = _PendingParagraph([text], page, page, section_path)
            continue

        if pending.char_count >= _MIN_PARAGRAPH_CHARS and pending.char_count + len(text) > _MAX_PARAGRAPH_CHARS:
            pending = _flush_pending(document, chunks, pending)
            pending = _PendingParagraph([text], page, page, section_path)
            continue

        pending.text_parts.append(text)
        pending.page_end = max(pending.page_end, page)

        if pending.char_count >= _MAX_PARAGRAPH_CHARS:
            pending = _flush_pending(document, chunks, pending)

    if title_without_body is not None:
        chunks.append(_make_chunk(document, "title", title_without_body[0], title_without_body[1], title_without_body[1], title_without_body[2]))
    _flush_pending(document, chunks, pending)
    return chunks


def _flush_pending(document: Document, chunks: List[EvidenceChunk], pending: _PendingParagraph | None) -> None:
    if pending is None:
        return None
    chunks.append(_make_chunk(document, "paragraph", pending.text, pending.page_start, pending.page_end, pending.section_path))
    return None


def _make_chunk(
    document: Document,
    chunk_type: str,
    text: str,
    page_start: int,
    page_end: int,
    section_path: List[str],
) -> EvidenceChunk:
    title = str(document.title or document.file_name or "文档").strip() or "文档"
    document_role = str(getattr(document, "document_role", "") or "evidence_document")
    return EvidenceChunk(
        document_id=document.id,
        document_role=document_role,
        text=text,
        summary="",
        page_start=page_start,
        page_end=max(page_start, page_end),
        section_path=section_path,
        chunk_type=chunk_type,
        semantic_type=_DEFAULT_SEMANTIC_TYPE,
        tags=[],
        citation=f"《{title}》p.{page_start}",
        created_at=datetime.utcnow(),
    )


def _chunk_payload(record: EvidenceChunk) -> EvidenceChunkRecord:
    return EvidenceChunkRecord(
        id=int(record.id),
        document_id=str(record.document_id),
        document_role=str(record.document_role or "evidence_document"),
        text=str(record.text or ""),
        summary=str(record.summary or ""),
        page_start=int(record.page_start or 1),
        page_end=int(record.page_end or record.page_start or 1),
        section_path=list(record.section_path or []),
        chunk_type=str(record.chunk_type or "paragraph"),
        semantic_type=str(record.semantic_type or _DEFAULT_SEMANTIC_TYPE),
        tags=list(record.tags or []),
        citation=str(record.citation or ""),
        created_at=record.created_at,
    )


def _normalize_block_type(block_type: str) -> str:
    normalized = str(block_type or "paragraph").strip().lower()
    if normalized in {"title", "table", "figure", "caption"}:
        return normalized
    return "paragraph"


def _section_path(block: DocumentBlock, current_section: List[str]) -> List[str]:
    explicit = str(block.section_title or "").strip()
    if explicit:
        return [explicit[:255]]
    return list(current_section)


def _one_based_page(block: DocumentBlock) -> int:
    return max(1, int(block.page_index or 0) + 1)
