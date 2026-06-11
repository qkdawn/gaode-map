from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from modules.documents import (
    DocumentBlocksResponse,
    DocumentNotFound,
    DocumentRecord,
    DocumentTooLarge,
    DocumentUploadResponse,
    EvidenceChunksResponse,
    EmptyDocument,
    UnsupportedDocumentType,
    create_document_upload,
    get_document,
    list_evidence_chunks,
    list_document_blocks,
    list_documents,
    schedule_document_evidence_build,
    schedule_document_parse,
)
from modules.jobs import JobCreateResponse


router = APIRouter()
logger = logging.getLogger(__name__)


def _raise_database_error(exc: SQLAlchemyError) -> None:
    logger.warning("Document database request failed", exc_info=exc)
    raise HTTPException(status_code=503, detail="document_database_unavailable") from exc


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def post_document_upload(
    file: UploadFile = File(...),
    title: str = Form(""),
) -> DocumentUploadResponse:
    try:
        return create_document_upload(
            filename=file.filename or "document",
            content_type=file.content_type or "",
            fileobj=file.file,
            title=title,
        )
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=400, detail="unsupported_document_type") from exc
    except EmptyDocument as exc:
        raise HTTPException(status_code=400, detail="empty_document") from exc
    except DocumentTooLarge as exc:
        raise HTTPException(status_code=413, detail="document_too_large") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
    finally:
        await file.close()


@router.get("/documents", response_model=List[DocumentRecord])
async def get_documents() -> List[DocumentRecord]:
    try:
        return list_documents()
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.get("/documents/{document_id}", response_model=DocumentRecord)
async def get_document_detail(document_id: str) -> DocumentRecord:
    try:
        return get_document(document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.post("/documents/{document_id}/parse", response_model=JobCreateResponse)
async def post_document_parse(document_id: str) -> JobCreateResponse:
    try:
        return schedule_document_parse(document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.get("/documents/{document_id}/blocks", response_model=DocumentBlocksResponse)
async def get_document_blocks(document_id: str) -> DocumentBlocksResponse:
    try:
        return list_document_blocks(document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.post("/documents/{document_id}/build-evidence", response_model=JobCreateResponse)
async def post_document_build_evidence(document_id: str) -> JobCreateResponse:
    try:
        return schedule_document_evidence_build(document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.get("/documents/{document_id}/evidence", response_model=EvidenceChunksResponse)
async def get_document_evidence(document_id: str) -> EvidenceChunksResponse:
    try:
        return EvidenceChunksResponse(document_id=document_id, chunks=list_evidence_chunks(document_id))
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
