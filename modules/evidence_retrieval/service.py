from __future__ import annotations

import json
import re
from typing import List

from modules.documents.pageindex import get_pageindex_document_structure, get_pageindex_page_content

from .adapters import evidence_nodes_from_source
from .schemas import EvidenceNode, EvidenceSearchRequest, EvidenceSearchResponse, SourceRecord


class EmptySearchQuestion(ValueError):
    pass


async def search_evidence(request: EvidenceSearchRequest) -> EvidenceSearchResponse:
    question = str(request.question or "").strip()
    if not question:
        raise EmptySearchQuestion("empty_search_question")
    nodes = _nodes_from_sources(question, request.sources, request.source_ids)
    nodes.extend(_search_document_pageindex(question, _document_ids_from_source_ids(request.source_ids)))
    nodes.sort(key=lambda item: item.score, reverse=True)
    top_k = max(1, min(int(request.top_k or 8), 50))
    return EvidenceSearchResponse(nodes=nodes[:top_k])


def _document_ids_from_source_ids(source_ids: List[str]) -> List[str]:
    document_ids: List[str] = []
    for source_id in source_ids or []:
        text = str(source_id or "").strip()
        if not text.startswith("document:"):
            continue
        document_id = text.split(":", 1)[1].strip()
        if document_id and document_id not in document_ids:
            document_ids.append(document_id)
    return document_ids


def _nodes_from_sources(question: str, sources: List[SourceRecord], source_ids: List[str]) -> List[EvidenceNode]:
    allowed = {str(item or "").strip() for item in (source_ids or []) if str(item or "").strip()}
    nodes: List[EvidenceNode] = []
    for source in sources or []:
        source_id = str(source.source_id or "").strip()
        if allowed and source_id not in allowed:
            continue
        nodes.extend(evidence_nodes_from_source(question, source))
    nodes.sort(key=lambda item: item.score, reverse=True)
    return [node for node in nodes if node.score > 0]


def _search_document_pageindex(question: str, document_ids: List[str]) -> List[EvidenceNode]:
    if not document_ids:
        return []
    nodes: List[EvidenceNode] = []
    for document_id in document_ids:
        try:
            structure = json.loads(get_pageindex_document_structure(document_id))
        except Exception:
            continue
        node_candidates = _pageindex_collect_nodes(structure)
        scored = sorted(
            (
                (
                    _pageindex_score(question, node),
                    node,
                )
                for node in node_candidates
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        for score, node in scored[:5]:
            if score <= 0:
                continue
            line_num = int(node.get("line_num") or 0)
            if line_num <= 0:
                continue
            try:
                content_payload = json.loads(get_pageindex_page_content(document_id, str(line_num)))
            except Exception:
                content_payload = []
            content = ""
            if isinstance(content_payload, list) and content_payload:
                content = str((content_payload[0] or {}).get("content") or "")
            text = str(node.get("text") or content or node.get("summary") or "")
            if not text.strip():
                continue
            nodes.append(
                EvidenceNode(
                    id=f"document:{document_id}:pageindex:{node.get('node_id') or line_num}",
                    source_id=f"document:{document_id}",
                    source_type="document",
                    title=str(node.get("title") or "PageIndex 节点"),
                    content=text[:1800],
                    summary=str(node.get("summary") or text[:260]),
                    metadata={
                        "document_id": document_id,
                        "node_id": node.get("node_id"),
                        "line_num": line_num,
                        "page_start": max(1, line_num),
                        "page_end": max(1, line_num),
                    },
                    locator=f"pageindex:{line_num}",
                    score=float(score),
                    evidence_level="pageindex_node",
                    citation=f"PageIndex line {line_num}",
                )
            )
    return nodes


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


def _score_text(question: str, text: str) -> float:
    haystack = _normalize_text(text)
    if not haystack:
        return 0.0
    score = 0.0
    normalized_question = _normalize_text(question)
    if normalized_question and normalized_question in haystack:
        score += 3.0
    for token in _pageindex_query_tokens(normalized_question):
        if token and token in haystack:
            score += 1.0
    return score


def _pageindex_query_tokens(question: str) -> List[str]:
    tokens = [part.strip() for part in re.split(r"[\s,，。；;：:\-_/|()（）]+", question) if part.strip()]
    if len(question) >= 4:
        tokens.append(question[:4])
    return list(dict.fromkeys(tokens))


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower()
