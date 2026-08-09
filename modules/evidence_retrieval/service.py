from __future__ import annotations

from modules.evidence_index.schemas import EvidenceSearchQuery
from modules.evidence_index.service import EvidenceIndexService

from .schemas import EvidenceSearchRequest, EvidenceSearchResponse


class EmptySearchQuestion(ValueError):
    pass


async def search_evidence(request: EvidenceSearchRequest) -> EvidenceSearchResponse:
    question = str(request.question or "").strip()
    if not question:
        raise EmptySearchQuestion("empty_search_question")
    service = EvidenceIndexService()
    return await service.search(EvidenceSearchQuery.from_request(request))
