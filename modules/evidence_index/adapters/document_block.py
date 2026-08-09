from __future__ import annotations

import re
from typing import List

from modules.evidence_index.adapters.base import EvidenceSourceAdapter
from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, SourceIndexManifest
from modules.evidence_retrieval.schemas import EvidenceNode, SourceRecord
from store.ai_database import SessionLocal
from store.ai_models import DocumentBlock


class DocumentBlockAdapter(EvidenceSourceAdapter):
    source_kind = "document"

    def __init__(self, document_id: str):
        self._document_id = str(document_id or "").strip()

    def manifest(self, source: SourceRecord) -> SourceIndexManifest:
        return SourceIndexManifest(
            source_id=source.source_id or f"document:{self._document_id}",
            source_kind="document",
            native_index_kind="document_block_index",
            node_count=int(source.evidence_count or 0),
            retrieval_modes=["keyword", "full_text"],
            read_modes=["block_id", "page", "locator"],
            storage_ref={"document_id": self._document_id},
        )

    async def recall(self, query: EvidenceSearchQuery, manifest: SourceIndexManifest) -> List[EvidenceIndexRecord]:
        rows = self._rows()
        scored = sorted(
            ((_score(query.question, row), row) for row in rows),
            key=lambda item: (item[0], -int(item[1].block_index or 0)),
            reverse=True,
        )
        records: List[EvidenceIndexRecord] = []
        for score, row in scored[: max(1, min(int(query.top_k or 8), 50))]:
            if score <= 0:
                continue
            node = self._node(row, manifest.source_id)
            records.append(
                EvidenceIndexRecord(
                    record_id=node.id,
                    source_id=node.source_ids[0],
                    source_kind="document",
                    title=node.title,
                    summary=node.summary,
                    content_ref=str(node.locator),
                    metadata=dict(node.data or {}),
                    scores={"keyword": float(score), "total": float(score)},
                    node=node,
                )
            )
        return records

    async def read(self, record_id: str, manifest: SourceIndexManifest) -> EvidenceNode | None:
        target = str(record_id or "").strip()
        raw_id = target.rsplit(":block:", 1)[-1] if ":block:" in target else target
        for row in self._rows():
            if str(row.id) == raw_id:
                return self._node(row, manifest.source_id)
        return None

    def _rows(self) -> List[DocumentBlock]:
        if not self._document_id:
            return []
        session = SessionLocal()
        try:
            return (
                session.query(DocumentBlock)
                .filter_by(document_id=self._document_id)
                .order_by(DocumentBlock.page_index.asc(), DocumentBlock.block_index.asc(), DocumentBlock.id.asc())
                .all()
            )
        finally:
            session.close()

    def _node(self, row: DocumentBlock, source_id: str) -> EvidenceNode:
        text = str(row.text or "").strip()
        page = max(1, int(row.page_index or 0) + 1)
        section = str(row.section_title or "").strip()
        title = section or (text[:120] if str(row.block_type or "") == "title" else f"第 {page} 页正文")
        return EvidenceNode(
            id=f"document:{self._document_id}:block:{row.id}",
            kind="document_excerpt",
            source_ids=[source_id or f"document:{self._document_id}"],
            title=title,
            content=text,
            summary=text[:260],
            data={
                "document_id": self._document_id,
                "block_id": int(row.id),
                "block_index": int(row.block_index or 0),
                "block_type": str(row.block_type or ""),
                "section": section,
            },
            locator={"page_start": page, "page_end": page, "block_id": int(row.id)},
            citation=f"document:{self._document_id}:p.{page}:block.{row.id}",
        )


def _score(question: str, row: DocumentBlock) -> float:
    haystack = f"{row.section_title or ''} {row.text or ''}".lower()
    score = 0.0
    for token in _query_tokens(question):
        if token in haystack:
            score += 1.0
    return score


def _query_tokens(question: str) -> List[str]:
    normalized = str(question or "").strip().lower()
    tokens = [
        part.strip()
        for part in re.split(r"[\s,，。；;：:\-_/|()（）]+", normalized)
        if len(part.strip()) >= 2
    ]
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        for size in (2, 3, 4):
            tokens.extend(run[index:index + size] for index in range(max(0, len(run) - size + 1)))
    return list(dict.fromkeys(token for token in tokens if token))[:100]
