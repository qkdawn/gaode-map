from __future__ import annotations

import json
import re
from typing import List

from modules.documents.pageindex import get_pageindex_document_structure, get_pageindex_page_content

from .schemas import EvidenceSearchRequest, EvidenceSearchResponse, EvidenceSearchResult


class EmptySearchQuestion(ValueError):
    pass


async def search_evidence(request: EvidenceSearchRequest) -> EvidenceSearchResponse:
    question = str(request.question or "").strip()
    if not question:
        raise EmptySearchQuestion("empty_search_question")
    pageindex_results = _search_document_pageindex(question, [item for item in (str(value).strip() for value in request.document_ids or []) if item])
    return EvidenceSearchResponse(results=pageindex_results[: max(1, min(int(request.top_k or 8), 50))])


def _search_document_pageindex(question: str, document_ids: List[str]) -> List[EvidenceSearchResult]:
    if not document_ids:
        return []
    results: List[EvidenceSearchResult] = []
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
            results.append(
                EvidenceSearchResult(
                    evidence_id=abs(hash((document_id, node.get("node_id"), line_num))) % 1000000,
                    document_id=document_id,
                    text=text[:1800],
                    summary=str(node.get("summary") or text[:260]),
                    semantic_type="pageindex_node",
                    tags=["pageindex", "document"],
                    page_start=max(1, line_num),
                    page_end=max(1, line_num),
                    citation=f"PageIndex line {line_num}",
                    score=float(score),
                )
            )
    return results


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
