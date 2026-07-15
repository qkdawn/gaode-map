from __future__ import annotations

from typing import Any, Dict, List, Sequence

from modules.scope_datasets import ScopeDatasetService

from .context_ask_compaction import as_text, compact_evidence_nodes, compact_value
from .schemas import AgentContextAskRequest
from .selected_sources import (
    is_analysis_sources_type,
    selected_dataset_source_ids_from_items,
    source_items_from_target,
)


_DATASET_KEYWORDS: Sequence[tuple[str, Sequence[str]]] = (
    ("current:dataset:poi", ("poi", "业态", "商业", "餐饮", "设施", "配套", "供需", "店铺", "门店")),
    ("current:dataset:h3", ("h3", "六边形", "热点", "集聚", "热区", "冷区")),
    ("current:dataset:poi_grid", ("poi栅格", "poi网格", "规则栅格", "poi密度")),
    ("current:dataset:population", ("人口", "客群", "年龄", "常住", "承载", "人口密度")),
    ("current:dataset:nightlight", ("夜光", "夜间", "夜生活", "夜经济", "夜间活力")),
    ("current:dataset:road_edges", ("路网", "交通", "可达", "连通", "整合度", "选择度", "道路", "街巷", "通行")),
    ("current:dataset:road_grid", ("路网", "栅格", "网格", "道路密度", "路段密度")),
)
_NEGATIVE_TERMS = ("差", "低", "弱", "不足", "短板", "问题", "缺口", "不便", "不佳")


def _empty_context(*, planned_source_ids: List[str] | None = None, warnings: List[str] | None = None) -> Dict[str, Any]:
    return {
        "datasets": {},
        "warnings": list(warnings or []),
        "evidence_nodes": [],
        "citations": [],
        "planned_source_ids": list(planned_source_ids or []),
        "query_count": 0,
    }


def _plan_dataset_sources(question: str, selected_source_ids: List[str], *, limit: int = 2) -> List[str]:
    """Select only datasets explicitly needed by the question.

    Generic project positioning/update questions intentionally return no detailed dataset
    plan: their fast-path evidence should come from the project dossier and the compact
    source metrics already sent by the frontend.
    """
    text = as_text(question).lower()
    if not text:
        return []
    selected = set(selected_source_ids)
    ranked: List[tuple[int, int, str]] = []
    for source_id, keywords in _DATASET_KEYWORDS:
        if source_id not in selected:
            continue
        positions = [text.find(keyword.lower()) for keyword in keywords if keyword.lower() in text]
        if not positions:
            continue
        ranked.append((min(positions), -len(positions), source_id))
    ranked.sort()
    return [source_id for _, _, source_id in ranked[: max(0, int(limit))]]


def _target_field(source_id: str, question: str) -> str:
    text = as_text(question).lower()
    if source_id == "current:dataset:h3":
        return "poi_count" if "poi" in text or "数量" in text else "density"
    if source_id == "current:dataset:poi_grid":
        return "poi_count" if "数量" in text else "density"
    if source_id == "current:dataset:population":
        return "density" if "密度" in text else "population"
    if source_id == "current:dataset:nightlight":
        return "radiance"
    if source_id == "current:dataset:road_edges":
        if "选择" in text:
            return "choice_score"
        if "连通" in text:
            return "connectivity_score"
        if "深度" in text:
            return "depth_score"
        return "integration_score"
    if source_id == "current:dataset:road_grid":
        if "选择" in text:
            return "road_choice"
        if "连通" in text:
            return "road_connectivity"
        if "深度" in text:
            return "road_depth"
        if "密度" in text or "长度" in text:
            return "road_length_km_per_km2"
        return "road_integration"
    return ""


def _query_direction(source_id: str, field: str, question: str) -> str:
    text = as_text(question).lower()
    negative = any(term in text for term in _NEGATIVE_TERMS)
    if field == "depth":
        return "desc" if negative else "asc"
    return "asc" if negative else "desc"


def _dataset_example(
    service: ScopeDatasetService,
    *,
    history_id: str,
    source_id: str,
    question: str,
) -> Dict[str, Any]:
    if source_id == "current:dataset:poi":
        return service.query_scope_dataset(history_id=history_id, source_id=source_id, limit=5)
    field = _target_field(source_id, question)
    kwargs: Dict[str, Any] = {
        "history_id": history_id,
        "source_id": source_id,
        "sort": {"field": field, "direction": _query_direction(source_id, field, question)},
        "limit": 5,
    }
    if source_id == "current:dataset:road_edges":
        kwargs["filters"] = {"feature_kind": "road_edge"}
    return service.query_scope_dataset(**kwargs)


def _dataset_aggregate(
    service: ScopeDatasetService,
    *,
    history_id: str,
    source_id: str,
    question: str,
) -> Dict[str, Any]:
    if source_id == "current:dataset:poi":
        return service.aggregate_scope_dataset(
            history_id=history_id,
            source_id=source_id,
            group_by="category",
            metrics=[{"op": "count", "field": "*", "as": "count"}],
            top_k=8,
        )
    field = _target_field(source_id, question)
    metrics: List[Dict[str, str]] = [{"op": "count", "field": "*", "as": "count"}]
    if field:
        metrics.extend(
            {"op": op, "field": field, "as": f"{op}_{field}"}
            for op in ("min", "avg", "max")
        )
    return service.aggregate_scope_dataset(
        history_id=history_id,
        source_id=source_id,
        metrics=metrics,
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
        return _empty_context()

    selected_source_ids = selected_dataset_source_ids_from_items(source_items_from_target(target))
    planned_source_ids = _plan_dataset_sources(payload.question, selected_source_ids)
    if not planned_source_ids:
        return _empty_context()

    history_id = as_text(payload.history_id)
    if not history_id:
        return _empty_context(
            planned_source_ids=planned_source_ids,
            warnings=["问题需要当前范围明细数据，但缺少 history_id，无法执行 scoped dataset 检索。"],
        )

    service = ScopeDatasetService()
    warnings: List[str] = []
    evidence_nodes: List[Dict[str, Any]] = []
    citations: List[Any] = []
    datasets: Dict[str, Any] = {}
    query_count = 0

    try:
        listed = service.list_scope_datasets(history_id)
    except Exception as exc:
        return _empty_context(
            planned_source_ids=planned_source_ids,
            warnings=[f"scoped dataset 列表读取失败：{type(exc).__name__}"],
        )

    available = {
        as_text(item.get("source_id")): item
        for item in list(listed.get("datasets") or [])
        if isinstance(item, dict)
    }
    warnings.extend([as_text(item) for item in list(listed.get("warnings") or []) if as_text(item)])

    for source_id in planned_source_ids:
        manifest = available.get(source_id)
        if not manifest or not int(manifest.get("record_count") or 0):
            warnings.append(f"{source_id} 当前没有可检索的范围明细数据。")
            continue
        try:
            aggregate = _dataset_aggregate(
                service,
                history_id=history_id,
                source_id=source_id,
                question=payload.question,
            )
            query_count += 1
            raw_example = _dataset_example(
                service,
                history_id=history_id,
                source_id=source_id,
                question=payload.question,
            )
            query_count += 1
        except Exception as exc:
            warnings.append(f"{source_id} scoped dataset 检索失败：{type(exc).__name__}")
            continue

        warnings.extend([as_text(item) for item in list(raw_example.get("warnings") or []) if as_text(item)])
        aggregate_node = aggregate.get("evidence_node") if isinstance(aggregate.get("evidence_node"), dict) else None
        if aggregate_node is not None:
            evidence_nodes.append(aggregate_node)
            citation = aggregate_node.get("citation")
            if citation not in (None, "", [], {}) and citation not in citations:
                citations.append(citation)
        for node in list(raw_example.get("evidence_nodes") or []):
            if not isinstance(node, dict):
                continue
            evidence_nodes.append(node)
            citation = node.get("citation")
            if citation not in (None, "", [], {}) and citation not in citations:
                citations.append(citation)

        datasets[source_id] = {
            "manifest": compact_value(manifest, depth=3, list_limit=8, string_limit=240),
            "aggregate": compact_value(aggregate, depth=3, list_limit=8, string_limit=240),
            "examples": [_compact_dataset_query_result(raw_example)],
        }

    return {
        "datasets": datasets,
        "warnings": sorted(set(warnings)),
        "evidence_nodes": evidence_nodes[:10],
        "citations": citations[:10],
        "planned_source_ids": planned_source_ids,
        "query_count": query_count,
    }
