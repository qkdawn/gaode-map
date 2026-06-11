from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from modules.documents.docling_parser import _normalize_blocks
from modules.documents.service import (
    DocumentNotFound,
    list_document_blocks,
    parse_document,
    schedule_document_parse,
)
from store.ai_models import Document, DocumentBlock


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def delete(self):
        if self.model is DocumentBlock:
            before = len(self.session.blocks)
            self.session.blocks = [row for row in self.session.blocks if not self._matches(row)]
            return before - len(self.session.blocks)
        return 0

    def order_by(self, *_args):
        return self

    def all(self):
        rows = self.session.blocks if self.model is DocumentBlock else self.session.documents
        result = [row for row in rows if self._matches(row)]
        result.sort(key=lambda row: (getattr(row, "page_index", 0), getattr(row, "block_index", 0), getattr(row, "id", 0)))
        return result

    def _matches(self, row):
        return all(getattr(row, key) == value for key, value in self.filters.items())


class FakeSession:
    def __init__(self, state):
        self.state = state
        self.documents = state["documents"]
        self.blocks = state["blocks"]
        self.closed = False
        self.rolled_back = False

    def get(self, model, record_id):
        if model is Document:
            for row in self.documents:
                if row.id == record_id:
                    return row
        return None

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, record):
        if isinstance(record, DocumentBlock):
            record.id = len(self.blocks) + 1
            self.blocks.append(record)

    def commit(self):
        self.state["blocks"] = self.blocks
        self.state["commits"] += 1

    def refresh(self, _record):
        pass

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _document(status="uploaded"):
    return SimpleNamespace(
        id="doc-1",
        title="报告",
        file_name="report.pdf",
        file_type="pdf",
        file_path="/tmp/report.pdf",
        upload_time=datetime(2026, 6, 11, 12, 0, 0),
        status=status,
    )


def test_docling_blocks_normalize_titles_paragraphs_and_markdown_tables():
    blocks = _normalize_blocks([
        {"label": "title", "text": "项目背景", "page_no": 1},
        {"label": "text", "text": "这是正文", "page_no": 1},
        {"label": "table", "rows": [["指标", "值"], ["POI", "3996"]], "page_no": 2},
    ])

    assert [item.block_type for item in blocks] == ["title", "paragraph", "table"]
    assert [item.block_index for item in blocks] == [0, 1, 2]
    assert blocks[1].section_title == "项目背景"
    assert blocks[2].page_index == 1
    assert blocks[2].text == "| 指标 | 值 |\n| --- | --- |\n| POI | 3996 |"


def test_schedule_document_parse_creates_parse_job(monkeypatch):
    state = {"documents": [_document()], "blocks": [], "commits": 0}
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: FakeSession(state))
    created = []
    scheduled = []

    def fake_create_job(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="job-1", status="pending")

    monkeypatch.setattr("modules.documents.service.create_job", fake_create_job)
    monkeypatch.setattr("modules.documents.service.schedule_job", lambda job_id, handler: scheduled.append((job_id, handler)))

    response = schedule_document_parse("doc-1")

    assert response.job_id == "job-1"
    assert response.status == "pending"
    assert state["documents"][0].status == "uploaded"
    assert created == [{"job_type": "parse_document", "target_type": "document", "target_id": "doc-1"}]
    assert scheduled == [("job-1", parse_document)]


def test_parse_document_replaces_blocks_and_marks_parsed(monkeypatch):
    state = {
        "documents": [_document("uploaded")],
        "blocks": [DocumentBlock(document_id="doc-1", page_index=0, block_index=0, block_type="paragraph", text="old", section_title="")],
        "commits": 0,
    }
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: FakeSession(state))
    monkeypatch.setattr(
        "modules.documents.service.parse_document_with_docling",
        lambda _file_path: _normalize_blocks([
            {"label": "title", "text": "新标题"},
            {"label": "text", "text": "新正文"},
        ]),
    )

    record = asyncio.run(parse_document("doc-1"))

    assert record.status == "parsed"
    assert state["documents"][0].status == "parsed"
    assert [row.text for row in state["blocks"]] == ["新标题", "新正文"]


def test_parse_document_failure_marks_failed_and_clears_blocks(monkeypatch):
    state = {
        "documents": [_document("uploaded")],
        "blocks": [DocumentBlock(document_id="doc-1", page_index=0, block_index=0, block_type="paragraph", text="old", section_title="")],
        "commits": 0,
    }
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: FakeSession(state))

    def fail(_file_path):
        raise RuntimeError("parse failed")

    monkeypatch.setattr("modules.documents.service.parse_document_with_docling", fail)

    with pytest.raises(RuntimeError):
        asyncio.run(parse_document("doc-1"))

    assert state["documents"][0].status == "failed"
    assert state["blocks"] == []


def test_list_document_blocks_returns_document_status_and_blocks(monkeypatch):
    state = {
        "documents": [_document("parsed")],
        "blocks": [
            DocumentBlock(document_id="doc-1", page_index=0, block_index=1, block_type="paragraph", text="正文", section_title="标题"),
            DocumentBlock(document_id="doc-1", page_index=0, block_index=0, block_type="title", text="标题", section_title=""),
        ],
        "commits": 0,
    }
    state["blocks"][0].id = 2
    state["blocks"][1].id = 1
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: FakeSession(state))

    response = list_document_blocks("doc-1")

    assert response.status == "parsed"
    assert [item.blockIndex for item in response.blocks] == [0, 1]
    assert response.blocks[1].sectionTitle == "标题"


def test_schedule_document_parse_missing_document(monkeypatch):
    state = {"documents": [], "blocks": [], "commits": 0}
    monkeypatch.setattr("modules.documents.service.SessionLocal", lambda: FakeSession(state))

    with pytest.raises(DocumentNotFound):
        schedule_document_parse("missing")
