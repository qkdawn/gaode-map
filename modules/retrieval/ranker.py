from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List

from .schemas import KnowledgeChunk, SearchHit


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    return [item.lower() for item in TOKEN_RE.findall(str(text or "")) if item.strip()]


def _snippet(content: str, query_tokens: Iterable[str], max_len: int = 120) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= max_len:
        return text
    lowered = text.lower()
    positions = [lowered.find(token) for token in query_tokens if token and lowered.find(token) >= 0]
    start = max(0, min(positions) - 30) if positions else 0
    return text[start : start + max_len].strip() + "..."


def rank_chunks(chunks: List[KnowledgeChunk], query: str, *, top_k: int = 8) -> List[SearchHit]:
    limited_top_k = max(1, min(int(top_k or 8), 20))
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    docs = [
        tokenize(" ".join([chunk.title, chunk.domain, chunk.content, " ".join(chunk.source_artifacts)]))
        for chunk in chunks
    ]
    doc_count = max(1, len(docs))
    dfs = Counter(token for tokens in docs for token in set(tokens))
    scored: List[SearchHit] = []
    for chunk, tokens in zip(chunks, docs):
        counts = Counter(tokens)
        length_norm = 1.0 + math.log(max(1, len(tokens)))
        score = 0.0
        for token in query_tokens:
            tf = counts.get(token, 0)
            if tf <= 0:
                continue
            idf = math.log(1 + (doc_count - dfs[token] + 0.5) / (dfs[token] + 0.5))
            score += (tf * idf) / length_norm
        if score <= 0:
            continue
        scored.append(
            SearchHit(
                chunk_id=chunk.chunk_id,
                title=chunk.title,
                domain=chunk.domain,
                snippet=_snippet(chunk.content, query_tokens),
                evidence_level=chunk.evidence_level,
                score=round(score, 4),
            )
        )
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limited_top_k]
