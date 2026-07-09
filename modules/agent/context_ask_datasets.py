from __future__ import annotations

from typing import Any, Dict, List

from modules.scope_datasets import ScopeDatasetService

from .context_ask_compaction import as_text, compact_evidence_nodes, compact_value
from .schemas import AgentContextAskRequest
from .selected_sources import (
    is_analysis_sources_type,
    selected_dataset_source_ids_from_items,
    source_items_from_target,
)


DATASET_FIELDS = {
    "current:dataset:poi": ["category", "type", "source", "year"],
    "current:dataset:h3": ["poi_count", "density", "lq"],
    "current:dataset:population": ["value", "population", "density"],
    "current:dataset:nightlight": ["value", "radiance"],
    "current:dataset:road": ["choice", "integration", "connectivity", "depth"],
}


def _metric_specs(fields: List[str]) -> List[Dict[str, str]]:
    specs: List[Dict[str, str]] = [{"op": "count", "field": "*", "as": "count"}]
    for field in fields:
        specs.extend([
            {"op": "min", "field": field, "as": f"min_{field}"},
            {"op": "avg", "field": field, "as": f"avg_{field}"},
            {"op": "max", "field": field, "as": f"max_{field}"},
        ])
    return specs


def _query_examples(service: ScopeDatasetService, *, history_id: str, source_id: str, field: str, direction: str, filters: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return service.query_scope_dataset(
        history_id=history_id,
        source_id=source_id,
        filters=filters or {},
        sort={"field": field, "direction": direction},
        limit=5,
    )


def _dataset_examples(service: ScopeDatasetService, *, history_id: str, source_id: str) -> List[Dict[str, Any]]:
    if source_id == "current:dataset:poi":
        return [
            service.query_scope_dataset(history_id=history_id, source_id=source_id, limit=8),
        ]
    if source_id == "current:dataset:road":
        examples = []
        for field, direction in [("connectivity", "asc"), ("integration", "asc"), ("depth", "desc"), ("choice", "asc")]:
            examples.append(
                _query_examples(
                    service,
                    history_id=history_id,
                    source_id=source_id,
                    field=field,
                    direction=direction,
                    filters={"feature_kind": "road"},
                )
            )
        return examples

    fields = DATASET_FIELDS.get(source_id, [])
    examples = []
    for field in fields[:2]:
        examples.append(_query_examples(service, history_id=history_id, source_id=source_id, field=field, direction="desc"))
        examples.append(_query_examples(service, history_id=history_id, source_id=source_id, field=field, direction="asc"))
    if not examples:
        examples.append(service.query_scope_dataset(history_id=history_id, source_id=source_id, limit=8))
    return examples


def _dataset_aggregate(service: ScopeDatasetService, *, history_id: str, source_id: str) -> Dict[str, Any]:
    if source_id == "current:dataset:poi":
        return service.aggregate_scope_dataset(
            history_id=history_id,
            source_id=source_id,
            group_by="category",
            metrics=[{"op": "count", "field": "*", "as": "count"}],
            top_k=12,
        )
    return service.aggregate_scope_dataset(
        history_id=history_id,
        source_id=source_id,
        metrics=_metric_specs(DATASET_FIELDS.get(source_id, [])),
        top_k=1,
    )


def _compact_dataset_query_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_id": result.get("source_id"),
        "total_count": result.get("total_count"),
        "limit": result.get("limit"),
        "offset": result.get("offset"),
        "has_more": result.get("has_more"),
        "records": compact_value(result.get("records") or [], depth=2, list_limit=5, string_limit=220),
        "evidence_nodes": compact_evidence_nodes(list(result.get("evidence_nodes") or []), limit=5),
        "warnings": list(result.get("warnings") or []),
    }


def build_scoped_dataset_context(payload: AgentContextAskRequest) -> Dict[str, Any]:
    target = payload.target
    if not is_analysis_sources_type(target.type):
        return {"datasets": {}, "warnings": [], "evidence_nodes": [], "citations": []}

    selected_source_ids = selected_dataset_source_ids_from_items(source_items_from_target(target))
    if not selected_source_ids:
        return {"datasets": {}, "warnings": [], "evidence_nodes": [], "citations": []}

    history_id = as_text(payload.history_id)
    if not history_id:
        return {
            "datasets": {},
            "warnings": ["已选来源包含当前范围数据源，但缺少 history_id，无法执行 scoped dataset 检索。"],
            "evidence_nodes": [],
            "citations": [],
        }

    service = ScopeDatasetService()
    warnings: List[str] = []
    evidence_nodes: List[Dict[str, Any]] = []
    citations: List[Any] = []
    datasets: Dict[str, Any] = {}

    try:
        listed = service.list_scope_datasets(history_id)
    except Exception as exc:
        return {
            "datasets": {},
            "warnings": [f"scoped dataset 列表读取失败：{type(exc).__name__}"],
            "evidence_nodes": [],
            "citations": [],
        }

    available = {
        as_text(item.get("source_id")): item
        for item in list(listed.get("datasets") or [])
        if isinstance(item, dict)
    }
    warnings.extend([as_text(item) for item in list(listed.get("warnings") or []) if as_text(item)])

    for source_id in selected_source_ids:
        manifest = available.get(source_id)
        if not manifest or not int(manifest.get("record_count") or 0):
            warnings.append(f"{source_id} 当前没有可检索的范围明细数据。")
            continue
        try:
            aggregate = _dataset_aggregate(service, history_id=history_id, source_id=source_id)
            raw_examples = _dataset_examples(service, history_id=history_id, source_id=source_id)
            examples = [_compact_dataset_query_result(item) for item in raw_examples]
        except Exception as exc:
            warnings.append(f"{source_id} scoped dataset 检索失败：{type(exc).__name__}")
            continue

        for result in raw_examples:
            warnings.extend([as_text(item) for item in list(result.get("warnings") or []) if as_text(item)])
            for node in list(result.get("evidence_nodes") or []):
                if isinstance(node, dict):
                    evidence_nodes.append(node)
                    citation = node.get("citation")
                    if citation not in (None, "", [], {}) and citation not in citations:
                        citations.append(citation)

        datasets[source_id] = {
            "manifest": compact_value(manifest, depth=3, list_limit=8, string_limit=240),
            "aggregate": compact_value(aggregate, depth=3, list_limit=12, string_limit=240),
            "examples": examples,
        }

    return {
        "datasets": datasets,
        "warnings": sorted(set(warnings)),
        "evidence_nodes": evidence_nodes[:20],
        "citations": citations[:20],
    }
