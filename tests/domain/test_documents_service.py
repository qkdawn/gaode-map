from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest

from modules.documents.service import (
    DocumentNotFound,
    DocumentTooLarge,
    EmptyDocument,
    UnsupportedDocumentType,
    create_document_upload,
    get_document,
    list_documents,
)


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_args):
        self.rows.sort(key=lambda row: (row.upload_time, row.id), reverse=True)
        return self

    def all(self):
        return list(self.rows)


class FakeSession:
    def __init__(self):
        self.rows = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def add(self, record):
        self.rows.append(record)

    def commit(self):
        self.committed = True

    def refresh(self, _record):
        pass

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def query(self, _model):
        return FakeQuery(self.rows)

    def get(self, _model, document_id):
        for row in self.rows:
            if row.id == document_id:
                return row
        return None


def test_document_upload_saves_safe_file_and_metadata(monkeypatch, tmp_path):
    fake_session = FakeSession()
    monkeypatch.setattr("modules.documents.service.settings.document_upload_dir", str(tmp_path))
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: fake_session)

    record = create_document_upload(
        filename="../城市更新 报告.pdf",
        content_type="application/pdf",
        fileobj=BytesIO(b"%PDF-1.4 fake"),
        title="长沙城市更新报告",
    )

    assert record.title == "长沙城市更新报告"
    assert record.file_name == "城市更新-报告.pdf"
    assert record.file_type == "pdf"
    assert record.status == "uploaded"
    assert record.file_path.startswith(str(tmp_path))
    assert (tmp_path / record.id / "source" / record.file_name).read_bytes() == b"%PDF-1.4 fake"
    assert fake_session.committed is True


def test_document_upload_defaults_title_to_file_stem(monkeypatch, tmp_path):
    fake_session = FakeSession()
    monkeypatch.setattr("modules.documents.service.settings.document_upload_dir", str(tmp_path))
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: fake_session)

    record = create_document_upload(
        filename="strategy.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        fileobj=BytesIO(b"docx bytes"),
    )

    assert record.title == "strategy"
    assert record.file_type == "docx"


def test_document_upload_rejects_unsupported_empty_and_large(monkeypatch, tmp_path):
    fake_session = FakeSession()
    monkeypatch.setattr("modules.documents.service.settings.document_upload_dir", str(tmp_path))
    monkeypatch.setattr("modules.documents.service.settings.document_max_mb", 1)
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: fake_session)

    with pytest.raises(UnsupportedDocumentType):
        create_document_upload(
            filename="script.exe",
            content_type="application/octet-stream",
            fileobj=BytesIO(b"nope"),
        )

    with pytest.raises(EmptyDocument):
        create_document_upload(
            filename="empty.pdf",
            content_type="application/pdf",
            fileobj=BytesIO(b""),
        )

    with pytest.raises(DocumentTooLarge):
        create_document_upload(
            filename="large.pdf",
            content_type="application/pdf",
            fileobj=BytesIO(b"x" * (1024 * 1024 + 1)),
        )


def test_document_list_and_get_use_metadata_order(monkeypatch):
    fake_session = FakeSession()
    older = SimpleNamespace(
        id="doc-1",
        title="older",
        file_name="older.pdf",
        file_type="pdf",
        file_path="/tmp/older.pdf",
        upload_time=datetime.utcnow() - timedelta(days=1),
        status="uploaded",
    )
    newer = SimpleNamespace(
        id="doc-2",
        title="newer",
        file_name="newer.docx",
        file_type="docx",
        file_path="/tmp/newer.docx",
        upload_time=datetime.utcnow(),
        status="uploaded",
    )
    fake_session.rows.extend([older, newer])
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: fake_session)

    assert [item.id for item in list_documents()] == ["doc-2", "doc-1"]
    assert get_document("doc-1").title == "older"
    with pytest.raises(DocumentNotFound):
        get_document("missing")
