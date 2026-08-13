from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from typing import Any

from modules.spatial_projects.data_contract import ProjectDataContractService
from modules.spatial_projects.service import SpatialProjectService


_PROJECTS = SpatialProjectService()
_DATA = ProjectDataContractService(projects=_PROJECTS)
_QUERY_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_QUERY_CACHE_LOCK = RLock()
_QUERY_CACHE_MAX_SIZE = 96

_STEP_DATASETS: dict[str, tuple[str, ...]] = {
    "step_01_policy_site": ("poi", "road_edges"),
    "step_02_regional_role": ("poi", "road_edges", "population"),
    "step_03_market_flow": ("poi", "road_edges", "population"),
    "step_04_supply_gap": ("poi",),
    "step_05_audience_use": ("population", "poi", "road_edges"),
    "step_06_theme_resources": ("poi",),
    "step_07_positioning": (),
    "step_08_product_mix": ("poi", "population"),
    "step_09_spatial_layout": ("road_edges", "poi", "population", "nightlight"),
    "step_10_operating_model": (),
    "step_11_financial_check": (),
    "step_12_phasing": (),
}

_AGGREGATES: dict[str, tuple[list[str], list[dict[str, str]]]] = {
    "poi": (["category"], [{"op": "count", "field": "*", "as": "poi_count"}]),
    "road_edges": (
        ["road_class"],
        [
            {"op": "count", "field": "*", "as": "edge_count"},
            {"op": "sum", "field": "length_m", "as": "length_m_sum"},
        ],
    ),
    "population": (
        [],
        [
            {"op": "count", "field": "*", "as": "cell_count"},
            {"op": "sum", "field": "population_total", "as": "population_total"},
            {"op": "sum", "field": "age_5_19", "as": "age_5_19"},
            {"op": "sum", "field": "age_30_39", "as": "age_30_39"},
            {"op": "sum", "field": "age_50_64", "as": "age_50_64"},
        ],
    ),
    "nightlight": (
        [],
        [
            {"op": "count", "field": "*", "as": "cell_count"},
            {"op": "avg", "field": "radiance", "as": "radiance_avg"},
            {"op": "min", "field": "radiance", "as": "radiance_min"},
            {"op": "max", "field": "radiance", "as": "radiance_max"},
        ],
    ),
}


def _stable_id(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"project:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]}"


def _query_data_cached(*, snapshot_key: str, **query: Any) -> dict[str, Any]:
    cache_key = _stable_id({"snapshot_key": snapshot_key, "query": query})
    with _QUERY_CACHE_LOCK:
        cached = _QUERY_CACHE.get(cache_key)
        if cached is not None:
            _QUERY_CACHE.move_to_end(cache_key)
            return deepcopy(cached)

    result = _DATA.query_data(**query)
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE[cache_key] = deepcopy(result)
        _QUERY_CACHE.move_to_end(cache_key)
        while len(_QUERY_CACHE) > _QUERY_CACHE_MAX_SIZE:
            _QUERY_CACHE.popitem(last=False)
    return result


def _resolve_history_id(history_id: str) -> str:
    normalized = str(history_id or "").strip()
    if normalized:
        return normalized
    projects = _PROJECTS.list_history_projects(limit=100)
    if not projects:
        raise LookupError("history_not_found")
    latest = max(projects, key=lambda item: str(item.get("created_at") or ""))
    resolved = str(latest.get("history_id") or "").strip()
    if not resolved:
        raise LookupError("history_not_found")
    return resolved


def read_project_context(history_id: str = "") -> dict[str, Any]:
    resolved = _resolve_history_id(history_id)
    context = _DATA.project_context(resolved)
    context["history_id"] = resolved
    return context


def _project_data_citation(
    *,
    history_id: str,
    dataset_id: str,
    title: str,
    content: str,
    source_locator: str,
    source_type: str,
    snapshot_id: str = "",
    dataset_checksum: str = "",
    complete: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "citation_id": _stable_id({history_id, dataset_id, source_locator, content}),
        "title": title,
        "section": extra.pop("section", ""),
        "page_start": extra.pop("page_start", None),
        "page_end": extra.pop("page_end", None),
        "source_url": "",
        "source_locator": source_locator,
        "content": content,
        "source_type": source_type,
        "history_id": history_id,
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "dataset_checksum": dataset_checksum,
        "complete": complete,
        **extra,
    }


def _dataset_ids(context: dict[str, Any], requested: str) -> list[str]:
    available = [str(item.get("dataset_id") or "") for item in context.get("datasets") or [] if isinstance(item, dict)]
    return [requested] if requested in available else []


def _aggregate_citation(history_id: str, dataset_id: str, result: dict[str, Any], title: str) -> dict[str, Any]:
    values = result.get("computed_results") or result.get("records") or []
    content = json.dumps(
        {
            "dataset_id": dataset_id,
            "operation": "aggregate",
            "complete": bool(result.get("complete")),
            "total_count": result.get("total_count"),
            "rows": values,
            "method": result.get("method") or [],
            "warnings": result.get("warnings") or [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return _project_data_citation(
        history_id=history_id,
        dataset_id=dataset_id,
        title=title,
        content=content,
        source_locator=f"project_data:{dataset_id}:aggregate",
        source_type="project_data",
        snapshot_id=str(result.get("snapshot_id") or ""),
        dataset_checksum=str(result.get("dataset_checksum") or ""),
        complete=bool(result.get("complete")),
        total_count=result.get("total_count"),
        operation="aggregate",
    )


def _record_citations(history_id: str, dataset_id: str, result: dict[str, Any], title: str) -> list[dict[str, Any]]:
    citations = []
    for index, record in enumerate(result.get("records") or []):
        if not isinstance(record, dict):
            continue
        record_key = str(record.get("id") or record.get("poi_id") or record.get("edge_id") or index)
        citations.append(
            _project_data_citation(
                history_id=history_id,
                dataset_id=dataset_id,
                title=str(record.get("name") or record.get("road_name") or title),
                content=json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str),
                source_locator=f"project_data:{dataset_id}:record:{record_key}",
                source_type="project_data_record",
                snapshot_id=str(result.get("snapshot_id") or ""),
                dataset_checksum=str(result.get("dataset_checksum") or ""),
                complete=True,
                operation="record",
                result_set_complete=bool(result.get("complete")),
                result_set_total_count=result.get("total_count"),
            )
        )
    return citations


def _computed_result_citations(history_id: str, results: list[Any]) -> list[dict[str, Any]]:
    citations = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        result_id = str(result.get("result_id") or result.get("id") or index)
        citations.append(
            _project_data_citation(
                history_id=history_id,
                dataset_id=str(result.get("dataset_id") or "computed"),
                title="项目计算结果",
                content=json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str),
                source_locator=f"project_computed:{result_id}",
                source_type="project_computed_result",
                complete=True,
                result_id=result_id,
            )
        )
    return citations


def read_step_project_data(
    *,
    history_id: str = "",
    step_key: str,
    project_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = _resolve_history_id(history_id)
    context = deepcopy(project_context) if isinstance(project_context, dict) and project_context.get("project") else read_project_context(resolved)
    citations: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    warnings = list(context.get("warnings") or [])
    requested = _STEP_DATASETS.get(str(step_key), ())
    citations.extend(_computed_result_citations(resolved, context.get("computed_results") or []))

    for requested_dataset in requested:
        for dataset_id in _dataset_ids(context, requested_dataset):
            try:
                descriptor = next(
                    (
                        item
                        for item in context.get("datasets") or []
                        if isinstance(item, dict) and item.get("dataset_id") == dataset_id
                    ),
                    {},
                )
                title = str(descriptor.get("title") or dataset_id)
                dataset_total_count = int(descriptor.get("total_count") or 0)
                snapshot_key = str(
                    descriptor.get("snapshot_id")
                    or descriptor.get("dataset_checksum")
                    or f"{dataset_id}:{dataset_total_count}"
                )
                group_by, metrics = _AGGREGATES.get(dataset_id, ([], [{"op": "count", "field": "*", "as": "record_count"}]))
                aggregate = _query_data_cached(
                    snapshot_key=snapshot_key,
                    history_id=resolved,
                    dataset_id=dataset_id,
                    operation="aggregate",
                    group_by=group_by,
                    metrics=metrics,
                )
                citations.append(_aggregate_citation(resolved, dataset_id, aggregate, f"{title} · 确定性聚合"))
                queries.append({"dataset_id": dataset_id, "operation": "aggregate", "complete": bool(aggregate.get("complete")), "total_count": aggregate.get("total_count")})

                if dataset_id in {"poi", "road_edges"} and dataset_total_count <= 200:
                    records = _query_data_cached(
                        snapshot_key=snapshot_key,
                        history_id=resolved,
                        dataset_id=dataset_id,
                        operation="records",
                        sort={"field": "name" if dataset_id == "poi" else "road_name", "direction": "asc"},
                    )
                    citations.extend(_record_citations(resolved, dataset_id, records, f"{title} · 具名记录"))
                    queries.append({"dataset_id": dataset_id, "operation": "records", "complete": bool(records.get("complete")), "total_count": records.get("total_count")})
                    warnings.append(f"{dataset_id}:具名记录用于个案核查；集合判断应引用确定性聚合")
                elif dataset_id in {"poi", "road_edges"}:
                    warnings.append(
                        f"{dataset_id}:具名记录共{dataset_total_count}条，超过200条；"
                        "本步仅使用确定性聚合，未将部分记录冒充全集"
                    )
            except (LookupError, ValueError) as exc:
                warnings.append(f"{dataset_id}:{exc}")

    return {
        "status": "success",
        "history_id": resolved,
        "step_key": str(step_key),
        "project": context.get("project") or {},
        "datasets": context.get("datasets") or [],
        "computed_results": context.get("computed_results") or [],
        "queries": queries,
        "citations": citations,
        "warnings": warnings,
    }
