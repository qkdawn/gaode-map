from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, SourceIndexManifest
from modules.evidence_retrieval.schemas import EvidenceNode, SourceRecord


class EvidenceSourceAdapter(ABC):
    source_kind = "unknown"

    @abstractmethod
    def manifest(self, source: SourceRecord) -> SourceIndexManifest:
        raise NotImplementedError

    @abstractmethod
    async def recall(self, query: EvidenceSearchQuery, manifest: SourceIndexManifest) -> List[EvidenceIndexRecord]:
        raise NotImplementedError

    async def read(self, record_id: str, manifest: SourceIndexManifest) -> EvidenceNode | None:
        del record_id, manifest
        return None
