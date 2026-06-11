from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from modules.documents.schemas import DocumentBlocksResponse, DocumentRecord
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
    )


def test_document_upload_api_returns_metadata(monkeypatch):
    def fake_upload(**kwargs):
        assert kwargs["filename"] == "report.pdf"
        assert kwargs["title"] == "项目报告"
        return _record(title=kwargs["title"])

    monkeypatch.setattr(documents, "create_document_upload", fake_upload)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/documents/upload",
            data={"title": "项目报告"},
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "doc-1"
    assert payload["title"] == "项目报告"
    assert payload["file_type"] == "pdf"


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


def test_document_build_evidence_api_schedules_background_job(monkeypatch):
    def fake_schedule(document_id):
        assert document_id == "doc-1"
        return JobCreateResponse(job_id="job-2", status="pending")

    monkeypatch.setattr(documents, "schedule_document_evidence_build", fake_schedule)

    with TestClient(_build_test_app()) as client:
        response = client.post("/documents/doc-1/build-evidence")

    assert response.status_code == 200
    assert response.json() == {"job_id": "job-2", "status": "pending"}


def test_document_build_evidence_api_maps_missing_document(monkeypatch):
    def fake_schedule(_document_id):
        from modules.documents.service import DocumentNotFound

        raise DocumentNotFound("document_not_found")

    monkeypatch.setattr(documents, "schedule_document_evidence_build", fake_schedule)

    with TestClient(_build_test_app()) as client:
        response = client.post("/documents/missing/build-evidence")

    assert response.status_code == 404
    assert response.json()["detail"] == "document_not_found"


def test_document_evidence_api_returns_query_contract(monkeypatch):
    from modules.documents.schemas import EvidenceChunkRecord

    monkeypatch.setattr(
        documents,
        "list_evidence_chunks",
        lambda document_id: [
            EvidenceChunkRecord(
                id=1,
                document_id=document_id,
                document_role="evidence_document",
                text="原文",
                summary="摘要",
                page_start=1,
                page_end=2,
                section_path=["背景"],
                chunk_type="paragraph",
                semantic_type="background_statement",
                tags=["project_background"],
                citation="《报告》p.1",
                created_at=datetime(2026, 6, 12, 1, 0, 0),
            )
        ],
    )

    with TestClient(_build_test_app()) as client:
        response = client.get("/documents/doc-1/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == "doc-1"
    assert payload["chunks"][0]["summary"] == "摘要"
    assert payload["chunks"][0]["semantic_type"] == "background_statement"
    assert payload["chunks"][0]["tags"] == ["project_background"]
    assert payload["chunks"][0]["page_start"] == 1
    assert payload["chunks"][0]["page_end"] == 2
    assert payload["chunks"][0]["citation"] == "《报告》p.1"
