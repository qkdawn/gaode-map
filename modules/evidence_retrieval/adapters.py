from __future__ import annotations

import re
from typing import Any, List

from modules.retrieval.schemas import AttachmentChunk, KnowledgeChunk

from .schemas import EvidenceNode, SourceKind, SourceRecord


def canonical_source_kind(raw_kind: Any = "", source_id: Any = "") -> SourceKind:
    text = str(raw_kind or "").strip()
    normalized = text.lower()
    source = str(source_id or "").strip()
    if normalized in {"system", "document", "image", "web", "database", "package"}:
        return normalized  # type: ignore[return-value]
    if source.startswith("current:"):
        return "system"
    if source.startswith("document:"):
        return "document"
    if source.startswith("image:"):
        return "image"
    if source.startswith("web:"):
        return "web"
    if source.startswith("database:"):
        return "database"
    if source.startswith("package:"):
        return "package"
    return "unknown"


def evidence_nodes_from_source(question: str, source: SourceRecord) -> List[EvidenceNode]:
    nodes = [
        node
        for index, item in enumerate(evidence_node_payloads_from_source(source), start=1)
        for node in [evidence_node_from_node_payload(question, source, item, index=index)]
        if node is not None
    ]
    return nodes


def evidence_node_payloads_from_source(source: SourceRecord) -> List[Any]:
    meta = source.meta if isinstance(source.meta, dict) else {}
    ai_payload = meta.get("aiPayload") or meta.get("ai_payload")
    ai_payload = ai_payload if isinstance(ai_payload, dict) else {}
    nodes = ai_payload.get("evidence_nodes")
    return list(nodes) if isinstance(nodes, list) else []


def evidence_node_from_node_payload(question: str, source: SourceRecord, item: Any, *, index: int = 1) -> EvidenceNode | None:
    payload = item if isinstance(item, dict) else {}
    source_id = str(payload.get("source_id") or source.source_id).strip()
    if not source_id:
        return None
    source_kind = canonical_source_kind(payload.get("source_type") or source.source_kind, source_id)
    title = str(payload.get("title") or source.title or f"证据 {index}").strip()
    content = str(payload.get("content") or payload.get("text") or payload.get("summary") or "").strip()
    if not content:
        return None
    metadata = _safe_dict(payload.get("metadata") or payload.get("payload"))
    node_id = str(payload.get("id") or payload.get("node_id") or f"{source_id}:evidence:{index}").strip()
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    return EvidenceNode(
        id=node_id,
        source_id=source_id,
        source_type=source_kind,
        title=title,
        content=content[:1800],
        summary=str(payload.get("summary") or content[:260]),
        metadata=metadata,
        locator=str(payload.get("locator") or metadata.get("locator") or ""),
        score=float(payload.get("score") or _score_text(question, " ".join([title, content])) if question else payload.get("score") or 0.0),
        evidence_level=str(payload.get("evidence_level") or "source_evidence"),
        warnings=[str(item) for item in warnings],
        citation=str(payload.get("citation") or source.locator_summary or source.title),
    )


def evidence_node_from_knowledge_chunk(chunk: KnowledgeChunk, *, question: str = "", source_id: str = "") -> EvidenceNode:
    source_prefix = "current:report" if str(chunk.kind or "").strip() == "report" else "current:analysis"
    resolved_source_id = source_id or f"{source_prefix}:{chunk.domain}"
    content = str(chunk.content or "").strip()
    node_id = f"{resolved_source_id}:node:{chunk.chunk_id}"
    return EvidenceNode(
        id=node_id,
        source_id=resolved_source_id,
        source_type="system",
        title=str(chunk.title or chunk.domain or "当前分析证据"),
        content=content[:1800],
        summary=content[:260],
        metadata={
            "kind": chunk.kind,
            "domain": chunk.domain,
            "metrics": dict(chunk.metrics or {}),
            "source_artifacts": list(chunk.source_artifacts or []),
        },
        locator=f"node:{node_id}",
        score=float(_score_text(question, " ".join([chunk.title, content])) if question else 0.0),
        evidence_level=str(chunk.evidence_level or "derived_metric"),
        warnings=list(chunk.warnings or []),
        citation=str(chunk.title or node_id),
    )


def evidence_node_from_attachment_chunk(chunk: AttachmentChunk, *, question: str = "", source_id: str = "") -> EvidenceNode:
    source_kind = attachment_source_kind(chunk.filename, (chunk.metadata or {}).get("mime_type"))
    resolved_source_id = source_id or attachment_source_id(chunk.attachment_id, chunk.filename, (chunk.metadata or {}).get("mime_type"))
    content = str(chunk.content or "").strip()
    node_id = f"{resolved_source_id}:node:{chunk.chunk_id}"
    return EvidenceNode(
        id=node_id,
        source_id=resolved_source_id,
        source_type=source_kind,
        title=str(chunk.title or chunk.filename or "上传资料证据"),
        content=content[:1800],
        summary=content[:260],
        metadata={
            "attachment_id": chunk.attachment_id,
            "filename": chunk.filename,
            "source_artifacts": list(chunk.source_artifacts or []),
            **dict(chunk.metadata or {}),
        },
        locator=str(chunk.locator or f"node:{node_id}"),
        score=float(_score_text(question, " ".join([chunk.title, chunk.filename, content])) if question else 0.0),
        evidence_level=str(chunk.evidence_level or "uploaded_attachment"),
        warnings=list(chunk.warnings or []),
        citation=str(chunk.locator or chunk.filename or node_id),
    )


def attachment_source_kind(filename: Any = "", mime_type: Any = "") -> SourceKind:
    normalized_mime = str(mime_type or "").strip().lower()
    normalized_filename = str(filename or "").strip().lower()
    if normalized_mime.startswith("image/"):
        return "image"
    if normalized_filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        return "image"
    return "document"


def attachment_source_id(attachment_id: Any, filename: Any = "", mime_type: Any = "") -> str:
    prefix = attachment_source_kind(filename, mime_type)
    stable_id = str(attachment_id or "").strip() or "unknown"
    return f"{prefix}:{stable_id}"


def evidence_node_from_document_index_node(source_id: str, source_title: str, node: dict, *, index: int = 1) -> EvidenceNode | None:
    title = str(node.get("title") or f"文档章节 {index}").strip()
    content = str(node.get("summary") or node.get("text") or "").strip()
    if not content:
        return None
    node_id = str(node.get("node_id") or node.get("nodeId") or index).strip()
    page_start = node.get("page_start") or node.get("pageStart") or 0
    page_end = node.get("page_end") or node.get("pageEnd") or page_start or 0
    locator = f"pageindex:{page_start}" if page_start else f"pageindex:{node_id}"
    citation = f"PageIndex p.{page_start}" if page_start else source_title
    return EvidenceNode(
        id=f"{source_id}:pageindex:{node_id}",
        source_id=source_id,
        source_type="document",
        title=title,
        content=content[:1800],
        summary=str(node.get("summary") or content[:260]),
        metadata={
            "node_id": node_id,
            "parent_node_id": str(node.get("parent_node_id") or node.get("parentNodeId") or "").strip(),
            "level": node.get("level"),
            "page_start": page_start,
            "page_end": page_end,
        },
        locator=locator,
        evidence_level="pageindex_node",
        citation=citation,
    )


def evidence_nodes_from_package(source_id: str, source_title: str, package: dict) -> List[EvidenceNode]:
    payload = _safe_dict(package)
    nodes: List[EvidenceNode] = []
    summary = str(payload.get("summary") or "").strip()
    if summary:
        nodes.append(EvidenceNode(
            id=f"{source_id}:package:summary",
            source_id=source_id,
            source_type="package",
            title=str(payload.get("title") or source_title or "资料包摘要").strip(),
            content=summary[:1800],
            summary=summary[:260],
            metadata={
                "package_mode": str(payload.get("package_mode") or "").strip(),
                "intent": str(payload.get("intent") or "").strip(),
                "total": payload.get("total"),
                "carrier_summary": _safe_dict(payload.get("carrier_summary")),
                "alignment": _safe_dict(payload.get("alignment")),
                "source_ids": [str(item) for item in payload.get("source_ids", [])] if isinstance(payload.get("source_ids"), list) else [],
            },
            locator="package:summary",
            evidence_level="package_summary",
            warnings=[str(item) for item in payload.get("warnings", [])] if isinstance(payload.get("warnings"), list) else [],
            citation=source_title or "资料包",
        ))
    for index, item in enumerate(_safe_list(payload.get("items"))[:6], start=1):
        node = _evidence_node_from_package_item(source_id, source_title, item, index=index)
        if node is not None:
            nodes.append(node)
    for index, item in enumerate(_safe_list(payload.get("carriers"))[:8], start=1):
        node = _evidence_node_from_package_carrier(source_id, source_title, item, index=index)
        if node is not None:
            nodes.append(node)
    return nodes


def database_source_id(record_type: Any, record_id: Any, history_id: Any = "") -> str:
    scope = str(history_id or "").strip() or "global"
    record_kind = str(record_type or "").strip() or "record"
    stable_id = str(record_id or "").strip() or "unknown"
    return f"database:{scope}:{record_kind}:{stable_id}"


def evidence_node_from_database_record(record: dict, *, question: str = "") -> EvidenceNode:
    record_type = str(record.get("record_type") or "").strip()
    record_id = str(record.get("record_id") or "").strip()
    metadata = _safe_dict(record.get("metadata"))
    history_id = str(record.get("history_id") or metadata.get("history_id") or "").strip()
    source_id = database_source_id(record_type, record_id, history_id)
    content = str(record.get("content") or record.get("snippet") or "").strip()
    title = str(record.get("title") or record_id or record_type or "数据库记录").strip()
    warnings = record.get("warnings") if isinstance(record.get("warnings"), list) else []
    node_metadata = {
        **metadata,
        "record_type": record_type,
        "record_id": record_id,
        "history_id": history_id,
        "created_at": str(record.get("created_at") or "").strip(),
        "updated_at": str(record.get("updated_at") or "").strip(),
    }
    return EvidenceNode(
        id=f"{source_id}:record",
        source_id=source_id,
        source_type="database",
        title=title,
        content=content[:1800],
        summary=(str(record.get("summary") or record.get("snippet") or content)[:260]),
        metadata=node_metadata,
        locator=f"{record_type}:{record_id}",
        score=float(_score_text(question, " ".join([title, content])) if question else float(record.get("score") or 0.0)),
        evidence_level=str(record.get("evidence_level") or "database_record"),
        warnings=[str(item) for item in warnings],
        citation=f"数据库记录 {record_type}/{record_id}",
    )


def evidence_node_payload_from_node(node: EvidenceNode) -> dict:
    return {
        "id": node.id,
        "source_id": node.source_id,
        "source_type": node.source_type,
        "title": node.title,
        "content": node.content,
        "summary": node.summary,
        "metadata": dict(node.metadata or {}),
        "locator": node.locator,
        "score": float(node.score or 0.0),
        "evidence_level": node.evidence_level,
        "warnings": list(node.warnings or []),
        "citation": node.citation,
    }


def evidence_node_payloads_from_nodes(nodes: List[EvidenceNode]) -> List[dict]:
    return [evidence_node_payload_from_node(node) for node in nodes]


def _score_text(question: str, text: str) -> float:
    haystack = _normalize_text(text)
    if not haystack:
        return 0.0
    score = 0.0
    normalized_question = _normalize_text(question)
    if normalized_question and normalized_question in haystack:
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


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower()


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _evidence_node_from_package_item(source_id: str, source_title: str, item: Any, *, index: int = 1) -> EvidenceNode | None:
    payload = _safe_dict(item)
    title = str(payload.get("title") or payload.get("name") or f"资料包样本 {index}").strip()
    text_parts = [
        str(payload.get("summary") or "").strip(),
        str(payload.get("address") or "").strip(),
        str(payload.get("category") or "").strip(),
        str(payload.get("subcategory") or "").strip(),
    ]
    text = "；".join(part for part in text_parts if part)
    if not text:
        return None
    item_id = str(payload.get("id") or index).strip()
    metadata = {
        key: payload.get(key)
        for key in [
            "id",
            "name",
            "category",
            "subcategory",
            "address",
            "distance_m",
            "carrier_id",
            "carrier_label",
            "cell_id",
        ]
        if key in payload
    }
    return EvidenceNode(
        id=f"{source_id}:package:item:{item_id}",
        source_id=source_id,
        source_type="package",
        title=title,
        content=text[:1800],
        summary=text[:260],
        metadata=metadata,
        locator=f"package:item:{item_id}",
        evidence_level="package_poi_sample",
        citation=source_title or title,
    )


def _evidence_node_from_package_carrier(source_id: str, source_title: str, item: Any, *, index: int = 1) -> EvidenceNode | None:
    payload = _safe_dict(item)
    carrier_id = str(payload.get("carrier_id") or index).strip()
    title = str(payload.get("carrier_label") or payload.get("carrier_id") or f"空间载体 {index}").strip()
    text = str(payload.get("summary") or "").strip()
    if not text:
        return None
    metadata = {
        "carrier_id": carrier_id,
        "carrier_type": payload.get("carrier_type"),
        "carrier_label": payload.get("carrier_label"),
        "road_metrics": _safe_dict(payload.get("road_metrics")),
        "poi_metrics": _safe_dict(payload.get("poi_metrics")),
        "population_metrics": _safe_dict(payload.get("population_metrics")),
        "nightlight_metrics": _safe_dict(payload.get("nightlight_metrics")),
    }
    return EvidenceNode(
        id=f"{source_id}:package:carrier:{carrier_id}",
        source_id=source_id,
        source_type="package",
        title=title,
        content=text[:1800],
        summary=text[:260],
        metadata=metadata,
        locator=f"package:carrier:{carrier_id}",
        evidence_level="package_carrier",
        citation=source_title or title,
    )
