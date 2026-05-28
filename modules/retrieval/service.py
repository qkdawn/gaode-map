from __future__ import annotations

from typing import Any, Dict, List

from modules.agent.schemas import AnalysisSnapshot

from .index_store import RuntimeKnowledgeIndex
from .ranker import rank_chunks
from .schemas import KnowledgeChunk, SearchHit


class RetrievalService:
    def __init__(self, *, snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]):
        self._index = RuntimeKnowledgeIndex(snapshot=snapshot, artifacts=artifacts)

    def search_analysis_context(self, *, query: str, domains: List[str] | None = None, top_k: int = 8) -> List[SearchHit]:
        allowed = {str(item).strip() for item in (domains or []) if str(item).strip()}
        chunks = self._index.by_kind("analysis")
        if allowed:
            chunks = [chunk for chunk in chunks if chunk.domain in allowed]
        return rank_chunks(chunks, query, top_k=top_k)

    def read_analysis_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._index.find(chunk_id, kind="analysis")

    def search_report_context(self, *, query: str, top_k: int = 8) -> List[SearchHit]:
        return rank_chunks(self._index.by_kind("report"), query, top_k=top_k)

    def read_report_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._index.find(chunk_id, kind="report")

    def available_context_sources(self) -> List[str]:
        sources: List[str] = []
        for chunk in self._index.chunks:
            source = f"{chunk.kind}:{chunk.domain}"
            if source not in sources:
                sources.append(source)
        return sources
