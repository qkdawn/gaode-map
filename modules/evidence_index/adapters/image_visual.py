from __future__ import annotations

import re
from typing import List

from modules.evidence_index.adapters.base import EvidenceSourceAdapter
from modules.evidence_index.manifests import manifest_from_source
from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, SourceIndexManifest
from modules.evidence_retrieval.adapters import evidence_node_from_node_payload
from modules.evidence_retrieval.adapters import evidence_node_payloads_from_source
from modules.evidence_retrieval.schemas import EvidenceNode, SourceRecord


class ImageVisualIndexAdapter(EvidenceSourceAdapter):
    source_kind = "image"

    def __init__(self, source: SourceRecord):
        self._source = source

    def manifest(self, source: SourceRecord) -> SourceIndexManifest:
        declared = manifest_from_source(source)
        if declared is not None:
            return declared
        return SourceIndexManifest(
            source_id=source.source_id,
            source_kind="image",
            native_index_kind="image_visual_index",
            node_count=int(source.evidence_count or 0),
            retrieval_modes=["keyword", "vector"],
            read_modes=["node_id", "attachment_id", "locator", "bbox"],
            storage_ref={"source_id": source.source_id},
            diagnostics=[] if source.evidence_count else ["image_visual_index_empty"],
        )

    async def recall(self, query: EvidenceSearchQuery, manifest: SourceIndexManifest) -> List[EvidenceIndexRecord]:
        del manifest
        records: List[EvidenceIndexRecord] = []
        for node in self._nodes():
            keyword_score = _score_image_node(query.question, node)
            if keyword_score <= 0:
                continue
            node.score = keyword_score
            records.append(
                EvidenceIndexRecord(
                    record_id=_record_key(node),
                    source_id=node.source_id,
                    source_kind="image",
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
            for key in ("attachment_id", "filename", "bbox_id", "region_id"):
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
            if node is not None and node.source_type == "image"
        ]


def _record_key(node: EvidenceNode) -> str:
    metadata = node.metadata if isinstance(node.metadata, dict) else {}
    for key in ("bbox_id", "region_id", "attachment_id"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return node.locator or node.id


def _score_image_node(question: str, node: EvidenceNode) -> float:
    metadata = node.metadata if isinstance(node.metadata, dict) else {}
    haystack = " ".join(
        str(part or "")
        for part in [
            node.title,
            node.summary,
            node.content,
            node.locator,
            node.evidence_level,
            metadata.get("filename"),
            metadata.get("mime_type"),
            metadata.get("ocr_engine"),
            metadata.get("caption_model"),
            metadata.get("attachment_id"),
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
