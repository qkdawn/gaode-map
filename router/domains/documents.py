from __future__ import annotations

import logging
import json
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from modules.documents import (
    DocumentBlocksResponse,
    DocumentIndexResponse,
    DocumentNotFound,
    DocumentRecord,
    DocumentRole,
    DocumentTooLarge,
    DocumentUploadResponse,
    PageIndexContentResponse,
    EmptyDocument,
    UnsupportedDocumentType,
    create_document_upload,
    delete_document,
    get_document,
    get_pageindex_document,
    get_pageindex_document_structure,
    get_pageindex_page_content,
    list_document_blocks,
    list_document_index_nodes,
    list_documents,
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
    document_role: DocumentRole = Form(...),
    title: str = Form(""),
) -> DocumentUploadResponse:
    try:
        return create_document_upload(
            filename=file.filename or "document",
            content_type=file.content_type or "",
            fileobj=file.file,
            document_role=document_role,
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


@router.delete("/documents/{document_id}", response_model=DocumentRecord)
async def delete_document_detail(document_id: str) -> DocumentRecord:
    try:
        return delete_document(document_id)
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


@router.get("/documents/{document_id}/index", response_model=DocumentIndexResponse)
async def get_document_index(document_id: str) -> DocumentIndexResponse:
    try:
        return DocumentIndexResponse(document_id=document_id, nodes=list_document_index_nodes(document_id))
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.get("/documents/{document_id}/pageindex/document")
async def get_document_pageindex_metadata(document_id: str):
    try:
        return json.loads(get_pageindex_document(document_id))
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.get("/documents/{document_id}/pageindex/structure")
async def get_document_pageindex_structure(document_id: str):
    try:
        return json.loads(get_pageindex_document_structure(document_id))
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)


@router.get("/documents/{document_id}/pageindex/content", response_model=PageIndexContentResponse)
async def get_document_pageindex_content(document_id: str, pages: str) -> PageIndexContentResponse:
    try:
        items = json.loads(get_pageindex_page_content(document_id, pages))
        return PageIndexContentResponse(document_id=document_id, pages=pages, items=items if isinstance(items, list) else [])
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_pageindex_pages") from exc
    except SQLAlchemyError as exc:
        _raise_database_error(exc)
