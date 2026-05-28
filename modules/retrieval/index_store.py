from __future__ import annotations

from typing import Any, Dict, List

from modules.agent.schemas import AnalysisSnapshot

from .chunkers import build_analysis_chunks, build_report_chunks
from .schemas import KnowledgeChunk


class RuntimeKnowledgeIndex:
    def __init__(self, *, snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]):
        self._snapshot = snapshot
        self._artifacts = artifacts
        self._chunks: List[KnowledgeChunk] | None = None

    @property
    def chunks(self) -> List[KnowledgeChunk]:
        if self._chunks is None:
            self._chunks = [
                *build_analysis_chunks(self._snapshot, self._artifacts),
                *build_report_chunks(self._snapshot, self._artifacts),
            ]
        return self._chunks

    def by_kind(self, kind: str) -> List[KnowledgeChunk]:
        return [chunk for chunk in self.chunks if chunk.kind == kind]

    def find(self, chunk_id: str, *, kind: str) -> KnowledgeChunk | None:
        target = str(chunk_id or "").strip()
        return next((chunk for chunk in self.by_kind(kind) if chunk.chunk_id == target), None)
