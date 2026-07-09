from __future__ import annotations

import re
from typing import List

from modules.evidence_index.adapters.base import EvidenceSourceAdapter
from modules.evidence_index.manifests import manifest_from_source
from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, SourceIndexManifest
from modules.evidence_retrieval.adapters import evidence_node_from_node_payload
from modules.evidence_retrieval.adapters import evidence_node_payloads_from_source
from modules.evidence_retrieval.schemas import EvidenceNode, SourceRecord


class PackageEvidenceAdapter(EvidenceSourceAdapter):
    source_kind = "package"

    def __init__(self, source: SourceRecord):
        self._source = source

    def manifest(self, source: SourceRecord) -> SourceIndexManifest:
        declared = manifest_from_source(source)
        if declared is not None:
            return declared
        return SourceIndexManifest(
            source_id=source.source_id,
            source_kind="package",
            native_index_kind="spatial_package_index",
            node_count=int(source.evidence_count or 0),
            retrieval_modes=["keyword", "structured"],
            read_modes=["node_id", "carrier_id", "item_id", "locator"],
            storage_ref={"source_id": source.source_id},
            diagnostics=[] if source.evidence_count else ["spatial_package_index_empty"],
        )

    async def recall(self, query: EvidenceSearchQuery, manifest: SourceIndexManifest) -> List[EvidenceIndexRecord]:
        del manifest
        records: List[EvidenceIndexRecord] = []
        for node in self._nodes():
            keyword_score = _score_package_node(query.question, node)
            if keyword_score <= 0:
                continue
            node.score = keyword_score
            records.append(
                EvidenceIndexRecord(
                    record_id=_record_key(node),
                    source_id=node.source_id,
                    source_kind="package",
                    title=node.title,
                    summary=node.summary,
                    content_ref=node.locator or node.id,
                    metadata=dict(node.metadata or {}),
                    scores={"keyword": keyword_score, "total": keyword_score},
                    node=node,
                )
            )
        return records

    async def read(self, record_id: str, manifest: SourceIndexManifest) -> EvidenceNode | None:
        del manifest
        target = str(record_id or "").strip()
        if not target:
            return None
        for node in self._nodes():
            keys = {node.id, node.locator, _record_key(node)}
            metadata = node.metadata if isinstance(node.metadata, dict) else {}
            for key in ("id", "carrier_id", "item_id", "cell_id"):
                value = str(metadata.get(key) or "").strip()
                if value:
                    keys.add(value)
            if target in keys:
                return node
        return None

    def _nodes(self) -> List[EvidenceNode]:
        return [
            node
            for index, item in enumerate(evidence_node_payloads_from_source(self._source), start=1)
            for node in [evidence_node_from_node_payload("", self._source, item, index=index)]
            if node is not None and node.source_type == "package"
        ]


def _record_key(node: EvidenceNode) -> str:
    metadata = node.metadata if isinstance(node.metadata, dict) else {}
    if node.evidence_level == "package_carrier":
        carrier_id = str(metadata.get("carrier_id") or "").strip()
        if carrier_id:
            return carrier_id
    if node.evidence_level == "package_poi_sample":
        item_id = str(metadata.get("id") or metadata.get("item_id") or "").strip()
        if item_id:
            return item_id
    return node.locator or node.id


def _score_package_node(question: str, node: EvidenceNode) -> float:
    metadata = node.metadata if isinstance(node.metadata, dict) else {}
    haystack = " ".join(
        str(part or "")
        for part in [
            node.title,
            node.summary,
            node.content,
            node.locator,
            node.evidence_level,
            metadata.get("id"),
            metadata.get("name"),
            metadata.get("category"),
            metadata.get("subcategory"),
            metadata.get("address"),
            metadata.get("carrier_id"),
            metadata.get("carrier_type"),
            metadata.get("carrier_label"),
            metadata.get("cell_id"),
            metadata.get("intent"),
        ]
    ).lower()
    normalized_question = str(question or "").strip().lower()
    if not haystack or not normalized_question:
        return 0.0
    score = 0.0
    if normalized_question in haystack:
        score += 3.0
    for token in _query_tokens(normalized_question):
        if token and token in haystack:
            score += 1.0
    return score


def _query_tokens(question: str) -> List[str]:
    tokens = [part.strip() for part in re.split(r"[\s,，。；;：:\-_/|()（）]+", question) if part.strip()]
    if len(question) >= 4:
        tokens.append(question[:4])
    return list(dict.fromkeys(tokens))
