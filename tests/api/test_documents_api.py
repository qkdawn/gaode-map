from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from modules.documents.schemas import (
    DocumentBlocksResponse,
    DocumentRagSourceResponse,
    DocumentRecord,
    DocumentRole,
)
from modules.documents.service import DocumentTooLarge, EmptyDocument, UnsupportedDocumentType
from modules.jobs import JobCreateResponse
from router.domains import documents
from router.domains.documents import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _record(document_id="doc-1", *, title="报告", file_name="report.pdf", file_type="pdf"):
    return DocumentRecord(
        id=document_id,
        title=title,
        file_name=file_name,
        file_type=file_type,
        file_path=f"/tmp/{file_name}",
        upload_time=datetime(2026, 6, 11, 12, 0, 0),
        status="uploaded",
        document_role=DocumentRole.PROJECT_BRIEF,
    )


def test_document_upload_api_returns_metadata(monkeypatch):
    def fake_upload(**kwargs):
        assert kwargs["filename"] == "report.pdf"
        assert kwargs["title"] == "项目报告"
        assert kwargs["document_role"] == DocumentRole.PROJECT_BRIEF
        assert kwargs["history_id"] == "history-1"
        return _record(title=kwargs["title"])

    monkeypatch.setattr(documents, "create_document_upload", fake_upload)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/documents/upload",
            data={"title": "项目报告", "document_role": "project_brief", "history_id": "history-1"},
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "doc-1"
    assert payload["title"] == "项目报告"
    assert payload["file_type"] == "pdf"
    assert payload["document_role"] == "project_brief"


def test_document_upload_api_requires_valid_document_role(monkeypatch):
    monkeypatch.setattr(documents, "create_document_upload", lambda **kwargs: _record())
    with TestClient(_build_test_app()) as client:
        missing = client.post(
            "/documents/upload",
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )
        invalid = client.post(
            "/documents/upload",
            data={"document_role": "evidence_document"},
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )
    assert missing.status_code == 422
    assert invalid.status_code == 422


def test_document_upload_api_maps_validation_errors(monkeypatch):
    cases = [
        (UnsupportedDocumentType("unsupported_document_type"), 400, "unsupported_document_type"),
        (EmptyDocument("empty_document"), 400, "empty_document"),
        (DocumentTooLarge("document_too_large"), 413, "document_too_large"),
    ]

    for exc, status_code, detail in cases:
        def fake_upload(**_kwargs):
            raise exc

        monkeypatch.setattr(documents, "create_document_upload", fake_upload)
        with TestClient(_build_test_app()) as client:
            response = client.post(
                "/documents/upload",
                data={"document_role": "reference_document"},
                files={"file": ("report.pdf", b"%PDF", "application/pdf")},
            )

        assert response.status_code == status_code
        assert response.json()["detail"] == detail


def test_documents_api_lists_and_reads_records(monkeypatch):
    monkeypatch.setattr(documents, "list_documents", lambda: [_record("doc-2"), _record("doc-1")])
    monkeypatch.setattr(documents, "get_document", lambda document_id: _record(document_id))

    with TestClient(_build_test_app()) as client:
        listed = client.get("/documents")
        detail = client.get("/documents/doc-1")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == ["doc-2", "doc-1"]
    assert detail.status_code == 200
    assert detail.json()["id"] == "doc-1"


def test_documents_api_filters_by_history_id(monkeypatch):
    seen = {}

    def fake_list(*, history_id=""):
        seen["history_id"] = history_id
        return [_record("doc-1")]

    monkeypatch.setattr(documents, "list_documents", fake_list)
    with TestClient(_build_test_app()) as client:
        response = client.get("/documents", params={"history_id": "history-1"})

    assert response.status_code == 200
    assert seen["history_id"] == "history-1"
    assert response.json()[0]["id"] == "doc-1"


def test_document_delete_api_removes_document(monkeypatch):
    deleted = {}

    def fake_delete(document_id):
        deleted["document_id"] = document_id
        return _record(document_id)

    monkeypatch.setattr(documents, "delete_document", fake_delete)

    with TestClient(_build_test_app()) as client:
        response = client.delete("/documents/doc-1")

    assert response.status_code == 200
    assert deleted["document_id"] == "doc-1"
    assert response.json()["id"] == "doc-1"


def test_documents_api_maps_not_found_and_database_errors(monkeypatch):
    def fake_get(_document_id):
        from modules.documents.service import DocumentNotFound

        raise DocumentNotFound("document_not_found")

    monkeypatch.setattr(documents, "get_document", fake_get)
    with TestClient(_build_test_app()) as client:
        missing = client.get("/documents/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "document_not_found"

    def fake_list():
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(documents, "list_documents", fake_list)
    with TestClient(_build_test_app()) as client:
        failed = client.get("/documents")
    assert failed.status_code == 503
    assert failed.json()["detail"] == "document_database_unavailable"


def test_document_parse_api_schedules_background_parse(monkeypatch):
    def fake_schedule(document_id):
        assert document_id == "doc-1"
        return JobCreateResponse(job_id="job-1", status="pending")

    monkeypatch.setattr(documents, "schedule_document_parse", fake_schedule)

    with TestClient(_build_test_app()) as client:
        response = client.post("/documents/doc-1/parse")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"job_id": "job-1", "status": "pending"}


def test_document_parse_api_maps_missing_document(monkeypatch):
    def fake_schedule(_document_id):
        from modules.documents.service import DocumentNotFound

        raise DocumentNotFound("document_not_found")

    monkeypatch.setattr(documents, "schedule_document_parse", fake_schedule)

    with TestClient(_build_test_app()) as client:
        response = client.post("/documents/missing/parse")

    assert response.status_code == 404
    assert response.json()["detail"] == "document_not_found"


def test_document_blocks_api_returns_status_object(monkeypatch):
    def fake_blocks(document_id):
        return DocumentBlocksResponse(
            document=_record(document_id),
            status="parsed",
            blocks=[
                {
                    "id": 1,
                    "pageIndex": 0,
                    "blockIndex": 0,
                    "blockType": "title",
                    "text": "项目背景",
                    "sectionTitle": "",
                }
            ],
        )

    monkeypatch.setattr(documents, "list_document_blocks", fake_blocks)

    with TestClient(_build_test_app()) as client:
        response = client.get("/documents/doc-1/blocks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "parsed"
    assert payload["blocks"][0]["pageIndex"] == 0
    assert payload["blocks"][0]["blockType"] == "title"


def test_document_rag_source_api_parses_then_returns_direct_chunk_contract(monkeypatch):
    parsed = _record()
    parsed.status = "uploaded"
    parse_calls = []

    async def fake_parse(document_id):
        parse_calls.append(document_id)
        return _record(document_id)

    def fake_rag_source(document_id, options):
        assert document_id == "doc-1"
        assert options.tenant_id == "tenant-1"
        assert options.access_groups == ["planning"]
        return DocumentRagSourceResponse.model_validate(
            {
                "document": {
                    "source_key": "document:doc-1",
                    "title": "报告",
                    "source_type": "project_document",
                    "object_key": "documents/doc-1/source/report.pdf",
                    "version": 1,
                    "checksum": "a" * 64,
                    "tenant_id": "tenant-1",
                    "visibility": "restricted",
                    "access_groups": ["planning"],
                    "metadata": {"parse_contract": "document-blocks-v1"},
                    "chunks": [
                        {
                            "ordinal": 0,
                            "page_start": 1,
                            "page_end": 1,
                            "section": "背景",
                            "content": "原始正文",
                            "search_terms": "背景 原始正文",
                            "metadata": {"source_locator": "document:doc-1:p.1"},
                        }
                    ],
                }
            }
        )

    monkeypatch.setattr(documents, "get_document", lambda _document_id: parsed)
    monkeypatch.setattr(documents, "parse_document", fake_parse)
    monkeypatch.setattr(documents, "build_document_rag_source", fake_rag_source)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/documents/doc-1/rag-source",
            json={"tenant_id": "tenant-1", "access_groups": ["planning"]},
        )

    assert response.status_code == 200
    assert parse_calls == ["doc-1"]
    assert response.json()["document"]["chunks"][0]["metadata"]["source_locator"] == "document:doc-1:p.1"
