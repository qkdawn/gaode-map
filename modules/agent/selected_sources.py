from __future__ import annotations

from typing import Any, Dict, List

from modules.evidence_retrieval import SourceRecord

from .context_ask_compaction import as_text, compact_evidence_nodes, compact_value


ANALYSIS_SOURCES_TARGET_TYPE = "analysis_sources"

ANALYSIS_TO_DATASET_SOURCES = {
    "current:analysis:poi_h3": ["current:dataset:h3", "current:dataset:poi"],
    "current:analysis:population": ["current:dataset:population"],
    "current:analysis:nightlight": ["current:dataset:nightlight"],
    "current:analysis:road": ["current:dataset:road"],
}


def is_analysis_sources_type(value: Any) -> bool:
    return as_text(value) == ANALYSIS_SOURCES_TARGET_TYPE


def source_items_from_target(target: Any) -> List[Dict[str, Any]]:
    payload = getattr(target, "payload", None)
    if not isinstance(payload, dict):
        return []
    return [item for item in list(payload.get("sources") or []) if isinstance(item, dict)]


def source_items_from_artifacts(artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    context = artifacts.get("selected_sources_context") if isinstance(artifacts.get("selected_sources_context"), dict) else {}
    return [item for item in list(context.get("sources") or []) if isinstance(item, dict)]


def source_id_from_item(item: Dict[str, Any]) -> str:
    return as_text(item.get("source_id") or item.get("sourceId") or item.get("id"))


def source_kind_from_item(item: Dict[str, Any]) -> str:
    return as_text(item.get("source_kind") or item.get("sourceKind"))


def evidence_nodes_from_item(item: Dict[str, Any]) -> List[Any]:
    nodes = item.get("evidence_nodes") if isinstance(item.get("evidence_nodes"), list) else item.get("evidenceNodes")
    if isinstance(nodes, list):
        return nodes
    return []


def source_title_from_item(item: Dict[str, Any]) -> str:
    return as_text(item.get("title") or item.get("name") or source_id_from_item(item))


def source_summary_from_item(item: Dict[str, Any]) -> str:
    return as_text(item.get("summary") or item.get("description") or item.get("policy"))


def artifact_refs_from_item(item: Dict[str, Any]) -> List[str]:
    refs = item.get("artifact_refs") if isinstance(item.get("artifact_refs"), list) else item.get("artifactRefs")
    return [as_text(ref) for ref in list(refs or []) if as_text(ref)]


def analysis_sources_target_from_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    sources = [dict(item) for item in list(items or []) if isinstance(item, dict)]
    titles = [source_title_from_item(item) for item in sources if source_title_from_item(item)]
    evidence_nodes: List[Any] = []
    artifact_refs: List[str] = []
    summaries: List[str] = []
    for item in sources:
        evidence_nodes.extend(evidence_nodes_from_item(item)[:4])
        artifact_refs.extend(artifact_refs_from_item(item))
        summary = source_summary_from_item(item)
        if summary:
            summaries.append(summary)
    return {
        "type": ANALYSIS_SOURCES_TARGET_TYPE,
        "id": "analysis-selected-sources",
        "title": "、".join(titles[:3]) or "已选分析来源",
        "source": "analysis",
        "summary": "\n".join(summaries[:6]),
        "evidence": evidence_nodes[:24],
        "artifact_refs": artifact_refs[:24],
        "payload": {"sources": sources},
    }


def mapped_dataset_source_ids(source_id: str) -> List[str]:
    raw_id = as_text(source_id)
    if not raw_id:
        return []
    mapped = ANALYSIS_TO_DATASET_SOURCES.get(raw_id)
    if mapped:
        return list(mapped)
    return [raw_id] if raw_id.startswith("current:dataset:") else []


def selected_dataset_source_ids_from_items(items: List[Dict[str, Any]]) -> List[str]:
    selected: List[str] = []
    for item in list(items or []):
        for source_id in mapped_dataset_source_ids(source_id_from_item(item)):
            if source_id not in selected:
                selected.append(source_id)
    return selected


def source_records_from_items(items: List[Dict[str, Any]]) -> List[SourceRecord]:
    records: List[SourceRecord] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        source_id = source_id_from_item(item)
        if not source_id:
            continue
        records.append(
            SourceRecord.model_validate(
                {
                    "source_id": source_id,
                    "id": source_id,
                    "title": as_text(item.get("title")) or source_id,
                    "source_kind": source_kind_from_item(item),
                    "status": "ready",
                    "summary": as_text(item.get("summary") or item.get("policy")),
                    "evidence_count": len(evidence_nodes_from_item(item)),
                    "locator_summary": as_text(item.get("locator_summary") or item.get("locatorSummary")),
                    "availability": "selected",
                    "meta": {"aiPayload": dict(item)},
                }
            )
        )
    return records


def evidence_count_from_item(item: Dict[str, Any]) -> int:
    return len(evidence_nodes_from_item(item))


def selected_sources_summary_from_items(items: List[Dict[str, Any]], *, limit: int = 24) -> Dict[str, Any]:
    sources = [item for item in list(items or []) if isinstance(item, dict)]
    compacted_sources: List[Dict[str, Any]] = []
    for item in list(items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        evidence_nodes = evidence_nodes_from_item(item)
        compacted_sources.append(
            {
                "source_id": source_id_from_item(item),
                "title": as_text(item.get("title")),
                "source_kind": source_kind_from_item(item),
                "included": list(item.get("included") or [])[:8],
                "scope": compact_value(item.get("scope"), depth=2, list_limit=4, string_limit=200),
                "metrics": compact_value(item.get("metrics"), depth=1, list_limit=4, string_limit=160),
                "metric_gaps": compact_value(item.get("metric_gaps") or item.get("metricGaps"), depth=1, list_limit=4, string_limit=160),
                "evidence_count": len(evidence_nodes),
                "evidence_nodes": compact_evidence_nodes(evidence_nodes, limit=3),
                "visual_specs_count": len(list(item.get("visual_specs") or item.get("visualSpecs") or [])),
                "policy": as_text(item.get("policy"))[:240],
                "transport_status": as_text(item.get("transport_status") or item.get("transportStatus")),
            }
        )
    return {
        "source_count": len(sources),
        "sources": compacted_sources,
    }


def source_record_payload(source: SourceRecord, mapped_dataset_ids: List[str] | None = None) -> Dict[str, Any]:
    payload = {
        "source_id": source.source_id,
        "title": source.title,
        "source_kind": source.source_kind,
        "status": source.status,
        "summary": source.summary,
        "evidence_count": source.evidence_count,
        "locator_summary": source.locator_summary,
        "availability": source.availability,
    }
    if mapped_dataset_ids is not None:
        payload["mapped_dataset_source_ids"] = list(mapped_dataset_ids or [])
    return payload
