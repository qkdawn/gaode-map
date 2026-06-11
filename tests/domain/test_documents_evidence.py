from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.documents.evidence import build_evidence_chunks_from_blocks, build_evidence_with_llm, list_evidence_chunks, schedule_document_evidence_build
from modules.documents.service import DocumentNotFound
from store.ai_models import AiBase, Document, DocumentBlock, EvidenceChunk


@pytest.fixture()
def ai_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    AiBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("modules.documents.evidence.SessionLocal", factory)
    return factory


def _seed_document(session_factory, *, document_role: str = "evidence_document"):
    session = session_factory()
    try:
        session.add(
            Document(
                id="doc-1",
                title="空间诊断报告",
                file_name="report.pdf",
                file_type="pdf",
                file_path="/tmp/report.pdf",
                document_role=document_role,
                upload_time=datetime(2026, 6, 11, 12, 0, 0),
                status="parsed",
            )
        )
        session.commit()
    finally:
        session.close()


def _add_block(session, page: int, index: int, block_type: str, text: str, section: str = ""):
    session.add(
        DocumentBlock(
            document_id="doc-1",
            page_index=page,
            block_index=index,
            block_type=block_type,
            text=text,
            section_title=section,
        )
    )


def test_build_evidence_chunks_groups_paragraphs_within_section(ai_session):
    _seed_document(ai_session, document_role="planning_report")
    session = ai_session()
    try:
        _add_block(session, 0, 0, "title", "现状问题")
        _add_block(session, 0, 1, "paragraph", "甲" * 120, "现状问题")
        _add_block(session, 0, 2, "paragraph", "乙" * 120, "现状问题")
        _add_block(session, 1, 0, "paragraph", "丙" * 120, "现状问题")
        _add_block(session, 1, 1, "title", "设施清单")
        _add_block(session, 1, 2, "table", "| 指标 | 值 |\n| --- | --- |\n| POI | 3996 |", "设施清单")
        _add_block(session, 1, 3, "paragraph", "丁" * 90, "设施清单")
        session.commit()
    finally:
        session.close()

    chunks = build_evidence_chunks_from_blocks("doc-1")

    assert [chunk.chunk_type for chunk in chunks] == ["paragraph", "table", "paragraph"]
    assert chunks[0].text == "\n\n".join(["甲" * 120, "乙" * 120, "丙" * 120])
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2
    assert chunks[0].section_path == ["现状问题"]
    assert chunks[0].citation == "《空间诊断报告》p.1"
    assert chunks[0].document_role == "planning_report"
    assert chunks[0].summary == ""
    assert chunks[0].semantic_type == "background_statement"
    assert chunks[0].tags == []
    assert chunks[1].text.startswith("| 指标 | 值 |")
    assert chunks[1].section_path == ["设施清单"]
    assert chunks[2].text == "丁" * 90


def test_build_evidence_chunks_does_not_cross_sections_and_splits_near_upper_bound(ai_session):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "paragraph", "甲" * 420, "第一节")
        _add_block(session, 0, 1, "paragraph", "乙" * 420, "第一节")
        _add_block(session, 0, 2, "paragraph", "丙" * 80, "第二节")
        _add_block(session, 0, 3, "paragraph", "丁" * 80, "第一节")
        session.commit()
    finally:
        session.close()

    chunks = build_evidence_chunks_from_blocks("doc-1")

    assert [chunk.section_path for chunk in chunks] == [["第一节"], ["第一节"], ["第二节"], ["第一节"]]
    assert [len(chunk.text) for chunk in chunks] == [420, 420, 80, 80]


def test_build_evidence_chunks_keeps_title_only_sections(ai_session):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "title", "只有标题")
        _add_block(session, 1, 0, "title", "下一章")
        _add_block(session, 1, 1, "paragraph", "正文", "下一章")
        session.commit()
    finally:
        session.close()

    chunks = build_evidence_chunks_from_blocks("doc-1")

    assert [chunk.chunk_type for chunk in chunks] == ["title", "paragraph"]
    assert chunks[0].text == "只有标题"
    assert chunks[0].section_path == ["只有标题"]
    assert chunks[1].text == "正文"


def test_build_evidence_chunks_replaces_existing_chunks(ai_session):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "paragraph", "新证据", "章节")
        session.add(
            EvidenceChunk(
                document_id="doc-1",
                document_role="evidence_document",
                text="旧证据",
                summary="",
                page_start=1,
                page_end=1,
                section_path=["旧章节"],
                chunk_type="paragraph",
                semantic_type="background_statement",
                tags=[],
                citation="《空间诊断报告》p.1",
                created_at=datetime.utcnow(),
            )
        )
        session.commit()
    finally:
        session.close()

    chunks = build_evidence_chunks_from_blocks("doc-1")
    listed = list_evidence_chunks("doc-1")

    assert [chunk.text for chunk in chunks] == ["新证据"]
    assert [chunk.text for chunk in listed] == ["新证据"]


def test_build_evidence_chunks_rejects_missing_document(ai_session):
    with pytest.raises(DocumentNotFound):
        build_evidence_chunks_from_blocks("missing")


def test_build_evidence_with_llm_saves_validated_annotations(ai_session, monkeypatch):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "paragraph", "项目应补齐公共服务设施并优化慢行交通。", "策略建议")
        session.commit()
    finally:
        session.close()

    async def fake_invoke_json_role(**kwargs):
        assert kwargs["user_payload"]["output_format"] == {"summary": "string", "semantic_type": "string", "tags": ["string"]}
        return {
            "summary": "提出公共服务补齐与慢行交通优化建议。",
            "semantic_type": "strategy_suggestion",
            "tags": ["strategy", "transportation", "invalid_tag", "policy", "demand"],
        }

    monkeypatch.setattr("modules.documents.evidence.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.documents.evidence._invoke_json_role", fake_invoke_json_role)

    chunks = asyncio.run(build_evidence_with_llm("doc-1"))

    assert len(chunks) == 1
    assert chunks[0].summary == "提出公共服务补齐与慢行交通优化建议。"
    assert chunks[0].semantic_type == "strategy_suggestion"
    assert chunks[0].tags == ["strategy", "transportation", "policy"]
    assert list_evidence_chunks("doc-1")[0].summary == "提出公共服务补齐与慢行交通优化建议。"


def test_build_evidence_with_llm_falls_back_for_invalid_enums(ai_session, monkeypatch):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "paragraph", "片区位于核心展示范围，承担项目背景说明功能。", "项目背景")
        session.commit()
    finally:
        session.close()

    async def fake_invoke_json_role(**_kwargs):
        return {"summary": "", "semantic_type": "made_up", "tags": ["bad", "also_bad"]}

    monkeypatch.setattr("modules.documents.evidence.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.documents.evidence._invoke_json_role", fake_invoke_json_role)

    chunks = asyncio.run(build_evidence_with_llm("doc-1"))

    assert chunks[0].summary.startswith("片区位于核心展示范围")
    assert chunks[0].semantic_type == "background_statement"
    assert chunks[0].tags == ["project_background"]


def test_build_evidence_with_llm_does_not_replace_chunks_when_llm_disabled(ai_session, monkeypatch):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "paragraph", "新证据", "章节")
        session.add(
            EvidenceChunk(
                document_id="doc-1",
                document_role="evidence_document",
                text="旧证据",
                summary="旧摘要",
                page_start=1,
                page_end=1,
                section_path=["旧章节"],
                chunk_type="paragraph",
                semantic_type="problem_statement",
                tags=["problem"],
                citation="《空间诊断报告》p.1",
                created_at=datetime.utcnow(),
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr("modules.documents.evidence.is_llm_enabled", lambda: False)

    with pytest.raises(RuntimeError, match="llm_not_enabled"):
        asyncio.run(build_evidence_with_llm("doc-1"))

    listed = list_evidence_chunks("doc-1")
    assert [chunk.text for chunk in listed] == ["旧证据"]
    assert listed[0].summary == "旧摘要"


def test_build_evidence_with_llm_does_not_save_partial_chunks_when_annotation_fails(ai_session, monkeypatch):
    _seed_document(ai_session)
    session = ai_session()
    try:
        _add_block(session, 0, 0, "paragraph", "第一段证据", "章节")
        _add_block(session, 0, 1, "paragraph", "第二段证据" * 60, "章节二")
        session.commit()
    finally:
        session.close()

    calls = 0

    async def fake_invoke_json_role(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("llm failed")
        return {"summary": "第一段摘要", "semantic_type": "background_statement", "tags": ["project_background"]}

    monkeypatch.setattr("modules.documents.evidence.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.documents.evidence._invoke_json_role", fake_invoke_json_role)

    with pytest.raises(RuntimeError, match="llm failed"):
        asyncio.run(build_evidence_with_llm("doc-1"))

    assert list_evidence_chunks("doc-1") == []


def test_schedule_document_evidence_build_creates_build_job(ai_session, monkeypatch):
    _seed_document(ai_session)
    created = {}
    scheduled = {}

    def fake_create_job(**kwargs):
        created.update(kwargs)

        class Job:
            id = "job-1"
            status = "pending"

        return Job()

    def fake_schedule_job(job_id, handler):
        scheduled["job_id"] = job_id
        scheduled["handler"] = handler

    monkeypatch.setattr("modules.documents.evidence.create_job", fake_create_job)
    monkeypatch.setattr("modules.documents.evidence.schedule_job", fake_schedule_job)

    response = schedule_document_evidence_build("doc-1")

    assert response.job_id == "job-1"
    assert response.status == "pending"
    assert created == {"job_type": "build_evidence", "target_type": "document", "target_id": "doc-1"}
    assert scheduled == {"job_id": "job-1", "handler": build_evidence_with_llm}
