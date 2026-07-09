from __future__ import annotations

import json
import re
from typing import Callable, List

from modules.documents.pageindex import get_pageindex_document_structure as default_get_pageindex_document_structure
from modules.documents.pageindex import get_pageindex_page_content as default_get_pageindex_page_content
from modules.evidence_index.adapters.base import EvidenceSourceAdapter
from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, SourceIndexManifest
from modules.evidence_retrieval.schemas import EvidenceNode, SourceRecord


class DocumentPageIndexAdapter(EvidenceSourceAdapter):
    source_kind = "document"

    def __init__(
        self,
        document_id: str,
        *,
        get_structure: Callable[[str], str] = default_get_pageindex_document_structure,
        get_content: Callable[[str, str], str] = default_get_pageindex_page_content,
    ):
        self._document_id = str(document_id or "").strip()
        self._get_structure = get_structure
        self._get_content = get_content

    def manifest(self, source: SourceRecord) -> SourceIndexManifest:
        return SourceIndexManifest(
            source_id=source.source_id or f"document:{self._document_id}",
            source_kind="document",
            native_index_kind="pageindex",
            node_count=int(source.evidence_count or 0),
            retrieval_modes=["structure", "keyword"],
            read_modes=["node_id", "page"],
            storage_ref={"document_id": self._document_id},
        )

    async def recall(self, query: EvidenceSearchQuery, manifest: SourceIndexManifest) -> List[EvidenceIndexRecord]:
        if not self._document_id:
            return []
        try:
            structure = json.loads(self._get_structure(self._document_id))
        except Exception:
            return []
        node_candidates = _pageindex_collect_nodes(structure)
        scored = sorted(
            ((_pageindex_score(query.question, node), node) for node in node_candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        records: List[EvidenceIndexRecord] = []
        for score, node in scored[:5]:
            if score <= 0:
                continue
            evidence_node = self._node_from_pageindex_hit(node, float(score), manifest.source_id)
            if evidence_node is None:
                continue
            records.append(
                EvidenceIndexRecord(
                    record_id=evidence_node.id,
                    source_id=evidence_node.source_id,
                    source_kind="document",
                    title=evidence_node.title,
                    summary=evidence_node.summary,
                    content_ref=evidence_node.locator,
                    metadata=dict(evidence_node.metadata or {}),
                    scores={"structure": float(score), "total": float(score)},
                    node=evidence_node,
                )
            )
        return records

    async def read(self, record_id: str, manifest: SourceIndexManifest) -> EvidenceNode | None:
        del manifest
        if not self._document_id:
            return None
        try:
            structure = json.loads(self._get_structure(self._document_id))
        except Exception:
            return None
        expected_prefix = f"document:{self._document_id}:pageindex:"
        raw_node_id = record_id[len(expected_prefix):] if record_id.startswith(expected_prefix) else record_id
        for node in _pageindex_collect_nodes(structure):
            if str(node.get("node_id") or node.get("line_num") or "").strip() == raw_node_id:
                return self._node_from_pageindex_hit(node, 0.0, f"document:{self._document_id}")
        return None

    def _node_from_pageindex_hit(self, node: dict, score: float, source_id: str) -> EvidenceNode | None:
        line_num = int(node.get("line_num") or 0)
        if line_num <= 0:
            return None
        try:
            content_payload = json.loads(self._get_content(self._document_id, str(line_num)))
        except Exception:
            content_payload = []
        content = ""
        if isinstance(content_payload, list) and content_payload:
            content = str((content_payload[0] or {}).get("content") or "")
        text = str(node.get("text") or content or node.get("summary") or "")
        if not text.strip():
            return None
        return EvidenceNode(
            id=f"document:{self._document_id}:pageindex:{node.get('node_id') or line_num}",
            source_id=source_id or f"document:{self._document_id}",
            source_type="document",
            title=str(node.get("title") or "PageIndex 节点"),
            content=text[:1800],
            summary=str(node.get("summary") or text[:260]),
            metadata={
                "document_id": self._document_id,
                "node_id": node.get("node_id"),
                "line_num": line_num,
                "page_start": max(1, line_num),
                "page_end": max(1, line_num),
            },
            locator=f"pageindex:{line_num}",
            score=score,
            evidence_level="pageindex_node",
            citation=f"PageIndex line {line_num}",
        )


def _pageindex_collect_nodes(structure: object) -> List[dict]:
    results: List[dict] = []

    def walk(nodes: object) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("title"):
                results.append(node)
            if node.get("nodes"):
                walk(node.get("nodes"))

    walk(structure)
    return results


def _pageindex_score(question: str, node: dict) -> float:
    q = _normalize_text(question)
    title = _normalize_text(node.get("title"))
    summary = _normalize_text(node.get("summary"))
    text = _normalize_text(node.get("text"))
    haystack = " ".join(part for part in [title, summary, text] if part)
    if not haystack:
        return 0.0
    score = 0.0
    for token in _pageindex_query_tokens(q):
        if token and token in haystack:
            score += 1.0
    if title and title in q:
        score += 2.0
    if summary and summary in q:
        score += 1.0
    return score


def _pageindex_query_tokens(question: str) -> List[str]:
    tokens = [part.strip() for part in re.split(r"[\s,，。；;：:\-_/|()（）]+", question) if part.strip()]
    if len(question) >= 4:
        tokens.append(question[:4])
    return list(dict.fromkeys(tokens))


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower()
