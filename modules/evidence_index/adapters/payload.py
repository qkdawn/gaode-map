from __future__ import annotations

from typing import List

from modules.evidence_index.adapters.base import EvidenceSourceAdapter
from modules.evidence_index.manifests import manifest_from_source
from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, SourceIndexManifest
from modules.evidence_retrieval.adapters import evidence_nodes_from_source
from modules.evidence_retrieval.adapters import evidence_search_score
from modules.evidence_retrieval.adapters import evidence_node_from_node_payload
from modules.evidence_retrieval.adapters import evidence_node_payloads_from_source
from modules.evidence_retrieval.schemas import SourceRecord


class PayloadEvidenceAdapter(EvidenceSourceAdapter):
    source_kind = "payload"

    def __init__(self, source: SourceRecord):
        self._source = source

    def manifest(self, source: SourceRecord) -> SourceIndexManifest:
        declared = manifest_from_source(source)
        if declared is not None:
            return declared
        return SourceIndexManifest(
            source_id=source.source_id,
            source_kind=source.source_kind,
            native_index_kind="payload_index",
            node_count=int(source.evidence_count or 0),
            retrieval_modes=["keyword"],
            read_modes=["node_id"],
            storage_ref={"source_id": source.source_id},
            diagnostics=[] if source.evidence_count else ["payload_evidence_empty"],
        )

    async def recall(self, query: EvidenceSearchQuery, manifest: SourceIndexManifest) -> List[EvidenceIndexRecord]:
        del manifest
        records: List[EvidenceIndexRecord] = []
        for node in evidence_nodes_from_source(query.question, self._source):
            score = evidence_search_score(query.question, node)
            if score <= 0:
                continue
            records.append(
                EvidenceIndexRecord(
                    record_id=node.id,
                    source_id=node.source_ids[0],
                    source_kind=self._source.source_kind,
                    title=node.title,
                    summary=node.summary,
                    content_ref=str(node.locator or node.id),
                    metadata=dict(node.data or {}),
                    scores={"keyword": score, "total": score},
                    node=node,
                )
            )
        return records

    async def read(self, record_id: str, manifest: SourceIndexManifest):
        del manifest
        for index, item in enumerate(evidence_node_payloads_from_source(self._source), start=1):
            node = evidence_node_from_node_payload("", self._source, item, index=index)
            if node is not None and node.id == record_id:
                return node
        return None
