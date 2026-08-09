import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.evidence_index.adapters.document_block import DocumentBlockAdapter
from modules.evidence_index.schemas import EvidenceSearchQuery
from modules.evidence_retrieval.schemas import SourceRecord
from store.ai_models import AiBase, DocumentBlock


def test_chinese_concept_matching_reads_original_document_block(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    AiBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as session:
        session.add_all(
            [
                DocumentBlock(
                    document_id="brief",
                    page_index=6,
                    block_index=0,
                    block_type="paragraph",
                    section_title="产权与住户安排",
                    text="三栋住宅涉及约102户居民，应保留居住并参与园区维护。",
                ),
                DocumentBlock(
                    document_id="brief",
                    page_index=8,
                    block_index=1,
                    block_type="paragraph",
                    section_title="交通条件",
                    text="周边道路与地铁站点情况。",
                ),
            ]
        )
        session.commit()
    monkeypatch.setattr("modules.evidence_index.adapters.document_block.SessionLocal", factory)

    adapter = DocumentBlockAdapter("brief")
    source = SourceRecord(
        source_id="document:brief",
        title="项目基本情况",
        source_kind="document",
        status="ready",
    )
    manifest = adapter.manifest(source)
    records = asyncio.run(
        adapter.recall(
            EvidenceSearchQuery(
                question="住宅居民如何处理",
                source_ids=[source.source_id],
                sources=[source],
            ),
            manifest,
        )
    )

    assert manifest.native_index_kind == "document_block_index"
    assert records
    assert records[0].node.data["block_id"] > 0
    assert records[0].score > 0
    assert "102户" in records[0].node.content
    assert records[0].node.citation.startswith("document:brief:p.7:block.")
