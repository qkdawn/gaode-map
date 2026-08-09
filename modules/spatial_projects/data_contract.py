from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from typing import Any, Callable, Literal

from modules.documents.service import list_document_blocks
from modules.spatial_projects.service import SpatialProjectService


SCHEMA_VERSION = "spatial_records/v1"
MAX_RESULT_SIZE = 500

DATASET_SOURCES = {
    "poi": "current:dataset:poi",
    "road_nodes": "current:dataset:road_nodes",
    "road_edges": "current:dataset:road_edges",
    "population": "current:dataset:population",
    "nightlight": "current:dataset:nightlight",
}

DATASET_SCHEMAS: dict[str, dict[str, Any]] = {
    "poi": {
        "fields": ["poi_id", "name", "category", "subcategory", "typecode", "address", "location", "year", "source"],
        "geometry_type": "Point",
    },
    "road_nodes": {
        "fields": ["node_id", "location", "geometry", "degree"],
        "geometry_type": "Point",
    },
    "road_edges": {
        "fields": ["edge_id", "road_name", "road_class", "from_node", "to_node", "length_m", "geometry", "metrics"],
        "geometry_type": "LineString",
        "units": {"length_m": "m"},
    },
    "population": {
        "fields": ["cell_id", "geometry", "year", "population_total", "age_5_19", "age_30_39", "age_50_64", "source"],
        "geometry_type": "Polygon",
        "units": {"population_total": "person", "age_5_19": "person", "age_30_39": "person", "age_50_64": "person"},
    },
    "nightlight": {
        "fields": ["cell_id", "geometry", "year", "radiance", "unit", "has_data", "source"],
        "geometry_type": "Polygon",
        "units": {"radiance": "nW/(cm2 sr)"},
    },
    "document": {
        "fields": ["chunk_id", "document_id", "filename", "page", "heading", "text", "block_type", "source_locator"],
        "geometry_type": "",
    },
}

_AGGREGATE_OPS = {
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "area_weighted_sum",
    "area_weighted_avg",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _checksum(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


def _continuation_encode(payload: dict[str, Any]) -> str:
    raw = _canonical(payload)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _continuation_decode(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_continue_token") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_continue_token")
    return payload


class ProjectDataContractService:
    """Expose complete project facts behind two small MCP operations."""

    def __init__(
        self,
        *,
        projects: SpatialProjectService | None = None,
        metric_results: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.projects = projects or SpatialProjectService()
        self.metric_results = metric_results

    def project_context(self, history_id: str) -> dict[str, Any]:
        project = self.projects.read_history_project(history_id)
        listing = self.projects.list_history_project_datasets(history_id)
        listed = {item["source_id"]: item for item in listing.get("datasets", [])}
        datasets = []
        computed_results = []
        for dataset_id, source_id in DATASET_SOURCES.items():
            metadata = listed.get(source_id)
            if not metadata:
                continue
            records = self._all_spatial_records(history_id, dataset_id)
            datasets.append(self._descriptor(dataset_id, metadata, records))
            summary = metadata.get("summary")
            if isinstance(summary, dict) and summary:
                computed_results.append({
                    "result_id": f"computed:{dataset_id}:summary",
                    "result_type": "dataset_summary",
                    "dataset_ids": [dataset_id],
                    "year": metadata.get("selected_year"),
                    "method": "persisted_analysis_summary",
                    "data": deepcopy(summary),
                })

        for document in self.projects.list_history_project_documents(history_id):
            dataset_id = f"document:{document['document_id']}"
            chunks = self._document_chunks(history_id, dataset_id)
            datasets.append({
                "dataset_id": dataset_id,
                "title": document.get("title") or document.get("file_name") or dataset_id,
                "schema_version": SCHEMA_VERSION,
                "total_count": len(chunks),
                "year": None,
                "coord_type": None,
                "geometry_type": "",
                "fields": list(DATASET_SCHEMAS["document"]["fields"]),
                "units": {},
                "dataset_checksum": _checksum(chunks),
                "status": document.get("status"),
                "operations": ["records"],
                "content_mode": "complete_document_blocks",
                "original_resource_uri": self._document_resource_uri(history_id, str(document["document_id"])),
                "query_capabilities": {
                    "filter_fields": list(DATASET_SCHEMAS["document"]["fields"]),
                    "sort_fields": list(DATASET_SCHEMAS["document"]["fields"]),
                    "spatial_relations": [],
                    "spatial_aggregations": [],
                },
            })

        computed_results.extend(self._persisted_metric_results(history_id))
        return {
            "schema_version": SCHEMA_VERSION,
            "project": {
                "history_id": history_id,
                "name": project.get("project_name"),
                "description": project.get("description"),
                "created_at": project.get("created_at"),
                "scope": deepcopy(project.get("scope") or {}),
                "coord_type": "wgs84",
            },
            "datasets": datasets,
            "computed_results": computed_results,
            "warnings": list(listing.get("warnings") or []),
        }

    def query_data(
        self,
        *,
        history_id: str,
        dataset_id: str,
        operation: Literal["records", "aggregate"] = "records",
        filters: dict[str, Any] | None = None,
        spatial: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        group_by: list[str] | None = None,
        metrics: list[dict[str, Any]] | None = None,
        continue_token: str = "",
    ) -> dict[str, Any]:
        normalized_dataset_id = str(dataset_id or "").strip()
        if normalized_dataset_id not in DATASET_SOURCES and not normalized_dataset_id.startswith("document:"):
            raise ValueError("dataset_not_found")
        if operation not in {"records", "aggregate"}:
            raise ValueError("invalid_operation")
        if spatial and str(spatial.get("coord_type") or "wgs84").lower() != "wgs84":
            raise ValueError("spatial_coord_type_must_be_wgs84")

        self._validate_query_contract(
            dataset_id=normalized_dataset_id,
            operation=operation,
            filters=filters,
            sort=sort,
            group_by=group_by,
            metrics=metrics,
        )

        query_contract = {
            "history_id": history_id,
            "dataset_id": normalized_dataset_id,
            "operation": operation,
            "filters": filters or {},
            "spatial": spatial or {},
            "sort": sort or {},
            "group_by": group_by or [],
            "metrics": metrics or [],
        }
        query_checksum = _checksum(query_contract)
        all_records = self._all_records(history_id, normalized_dataset_id)
        dataset_checksum = _checksum(all_records)
        snapshot_id = f"snapshot:{dataset_checksum.removeprefix('sha256:')}"

        if normalized_dataset_id.startswith("document:"):
            if operation == "aggregate" or spatial:
                raise ValueError("document_operation_unsupported")
            if continue_token:
                raise ValueError("document_continue_token_unsupported")
            matched = self._query_documents(all_records, filters or {}, sort or {})
            full_text = "\n\n".join(str(record.get("text") or "") for record in matched)
            document_id = normalized_dataset_id.removeprefix("document:")
            return {
                "schema_version": SCHEMA_VERSION,
                "history_id": history_id,
                "dataset_id": normalized_dataset_id,
                "operation": operation,
                "snapshot_id": snapshot_id,
                "dataset_checksum": dataset_checksum,
                "result_checksum": _checksum(matched),
                "total_count": len(matched),
                "complete": True,
                "continue_token": None,
                "records": matched,
                "full_text": full_text,
                "full_text_checksum": _checksum(full_text),
                "content_mode": "complete_document_blocks",
                "original_resource_uri": self._document_resource_uri(history_id, document_id),
                "computed_results": [],
                "warnings": [],
            }

        offset = self._continuation_offset(continue_token, normalized_dataset_id, snapshot_id, query_checksum)
        source_id = DATASET_SOURCES[normalized_dataset_id]
        if operation == "aggregate":
            result = self.projects.datasets.aggregate_scope_dataset(
                history_id=history_id,
                source_id=source_id,
                group_by=group_by or [],
                metrics=metrics,
                filters=filters,
                spatial=spatial,
                top_k=None,
            )
            response = self._page_response(
                history_id=history_id,
                dataset_id=normalized_dataset_id,
                operation=operation,
                values=list(result.get("rows") or []),
                offset=offset,
                snapshot_id=snapshot_id,
                dataset_checksum=dataset_checksum,
                query_checksum=query_checksum,
                computed=True,
            )
            response["method"] = deepcopy(result.get("metric_methods") or [])
            response["spatial_summary"] = deepcopy(result.get("spatial_summary") or {})
            response["warnings"] = list(result.get("warnings") or [])
            return response

        page = self.projects.datasets.query_scope_dataset(
            history_id=history_id,
            source_id=source_id,
            filters=filters,
            sort=sort,
            spatial=spatial,
            limit=MAX_RESULT_SIZE,
            offset=offset,
        )
        records = [
            self._public_spatial_record(normalized_dataset_id, item)
            for item in page.get("records") or []
            if isinstance(item, dict)
        ]
        total_count = int(page.get("total_count") or 0)
        next_offset = offset + len(records)
        return {
            "schema_version": SCHEMA_VERSION,
            "history_id": history_id,
            "dataset_id": normalized_dataset_id,
            "operation": operation,
            "snapshot_id": snapshot_id,
            "dataset_checksum": dataset_checksum,
            "result_checksum": _checksum(records),
            "total_count": total_count,
            "complete": next_offset >= total_count,
            "continue_token": self._continue_token(normalized_dataset_id, snapshot_id, query_checksum, next_offset) if next_offset < total_count else None,
            "records": records,
            "computed_results": [],
            "spatial_diagnostics": deepcopy(page.get("spatial_diagnostics") or {}),
            "warnings": list(page.get("warnings") or []),
        }

    @staticmethod
    def _validate_query_contract(
        *,
        dataset_id: str,
        operation: str,
        filters: dict[str, Any] | None,
        sort: dict[str, Any] | None,
        group_by: list[str] | None,
        metrics: list[dict[str, Any]] | None,
    ) -> None:
        schema_key = "document" if dataset_id.startswith("document:") else dataset_id
        fields = set(DATASET_SCHEMAS[schema_key]["fields"])

        if filters is not None and not isinstance(filters, dict):
            raise ValueError("filters_must_be_object")
        unsupported_filters = sorted(set((filters or {}).keys()) - fields)
        if unsupported_filters:
            raise ValueError("unsupported_filter_field:" + ",".join(unsupported_filters))

        if sort is not None and not isinstance(sort, dict):
            raise ValueError("sort_must_be_object")
        unexpected_sort_keys = sorted(set(sort or {}) - {"field", "direction"})
        if unexpected_sort_keys:
            raise ValueError("unsupported_sort_property:" + ",".join(unexpected_sort_keys))
        sort_field = str((sort or {}).get("field") or "").strip()
        if sort_field and sort_field not in fields:
            raise ValueError(f"unsupported_sort_field:{sort_field}")
        sort_direction = str((sort or {}).get("direction") or "asc").strip().lower()
        if sort_field and sort_direction not in {"asc", "desc"}:
            raise ValueError("invalid_sort_direction")

        if group_by is not None and not isinstance(group_by, list):
            raise ValueError("group_by_must_be_array")
        groups = [str(field or "").strip() for field in (group_by or []) if str(field or "").strip()]
        unsupported_groups = sorted(set(groups) - fields)
        if unsupported_groups:
            raise ValueError("unsupported_group_by_field:" + ",".join(unsupported_groups))

        if operation == "records":
            if groups or metrics:
                raise ValueError("records_operation_rejects_aggregation_fields")
            return

        if metrics is not None and not isinstance(metrics, list):
            raise ValueError("metrics_must_be_array")
        for metric in metrics or []:
            if not isinstance(metric, dict):
                raise ValueError("metric_must_be_object")
            unexpected = sorted(set(metric) - {"op", "field", "as"})
            if unexpected:
                raise ValueError("unsupported_metric_property:" + ",".join(unexpected))
            op = str(metric.get("op") or "count").strip().lower()
            field = str(metric.get("field") or "*").strip()
            if op not in _AGGREGATE_OPS:
                raise ValueError(f"unsupported_metric_operation:{op}")
            if field == "*" and op != "count":
                raise ValueError(f"metric_field_required:{op}")
            if field != "*" and field not in fields:
                raise ValueError(f"unsupported_metric_field:{field}")

    def _descriptor(self, dataset_id: str, metadata: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        contract = DATASET_SCHEMAS[dataset_id]
        query_capabilities = deepcopy(metadata.get("query_capabilities") or {})
        query_capabilities["input_coord_types"] = ["wgs84"]
        return {
            "dataset_id": dataset_id,
            "title": metadata.get("title") or dataset_id,
            "schema_version": SCHEMA_VERSION,
            "total_count": len(records),
            "year": metadata.get("selected_year"),
            "coord_type": "wgs84",
            "geometry_type": contract.get("geometry_type") or metadata.get("geometry_type"),
            "fields": list(contract["fields"]),
            "units": deepcopy(contract.get("units") or {}),
            "dataset_checksum": _checksum(records),
            "status": metadata.get("status"),
            "operations": ["records", "aggregate"],
            "query_capabilities": query_capabilities,
        }

    def _persisted_metric_results(self, history_id: str) -> list[dict[str, Any]]:
        if self.metric_results is None:
            return []
        envelope = self.metric_results(history_id=history_id)
        values = envelope.get("result", {}).get("results", []) if isinstance(envelope, dict) else []
        return [deepcopy(item) for item in values if isinstance(item, dict)]

    def _all_records(self, history_id: str, dataset_id: str) -> list[dict[str, Any]]:
        if dataset_id.startswith("document:"):
            return self._document_chunks(history_id, dataset_id)
        return self._all_spatial_records(history_id, dataset_id)

    def _all_spatial_records(self, history_id: str, dataset_id: str) -> list[dict[str, Any]]:
        source_id = DATASET_SOURCES[dataset_id]
        records, _, _ = self.projects.datasets.load_scope_records(history_id=history_id, source_id=source_id)
        return [
            self._public_spatial_record(dataset_id, record.as_payload())
            for record in sorted(records, key=lambda item: item.record_id)
        ]

    @staticmethod
    def _public_spatial_record(dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        public = {}
        for field in DATASET_SCHEMAS[dataset_id]["fields"]:
            if field == "geometry":
                public[field] = deepcopy(payload.get("geometry"))
            else:
                public[field] = deepcopy(properties.get(field))
        return public

    def _document_chunks(self, history_id: str, dataset_id: str) -> list[dict[str, Any]]:
        document_id = dataset_id.removeprefix("document:")
        documents = self.projects.list_history_project_documents(history_id)
        document = next((item for item in documents if item.get("document_id") == document_id), None)
        if document is None:
            raise LookupError("document_not_found")
        blocks = list_document_blocks(document_id)
        chunks = []
        page_ordinals: dict[int, int] = {}
        for block in blocks.blocks:
            page = int(block.pageIndex or 0) + 1
            page_ordinals[page] = page_ordinals.get(page, 0) + 1
            block_number = page_ordinals[page]
            chunks.append({
                "chunk_id": f"chunk:{block.id}",
                "document_id": document_id,
                "filename": document.get("file_name") or blocks.document.file_name,
                "page": page,
                "heading": str(block.sectionTitle or (block.text if block.blockType == "title" else "")),
                "text": str(block.text or ""),
                "block_type": str(block.blockType),
                "source_locator": f"page:{page} block:{block_number}",
            })
        return chunks

    @staticmethod
    def _document_resource_uri(history_id: str, document_id: str) -> str:
        return f"spatial-document://{history_id}/{document_id}/original"

    @staticmethod
    def _continuation_offset(continue_token: str, dataset_id: str, snapshot_id: str, query_checksum: str) -> int:
        if not continue_token:
            return 0
        payload = _continuation_decode(continue_token)
        if payload.get("dataset_id") != dataset_id or payload.get("query_checksum") != query_checksum:
            raise ValueError("continue_token_query_mismatch")
        if payload.get("snapshot_id") != snapshot_id:
            raise ValueError("snapshot_changed")
        try:
            return max(0, int(payload.get("offset") or 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_continue_token") from exc

    @staticmethod
    def _continue_token(dataset_id: str, snapshot_id: str, query_checksum: str, offset: int) -> str:
        return _continuation_encode({
            "dataset_id": dataset_id,
            "snapshot_id": snapshot_id,
            "query_checksum": query_checksum,
            "offset": offset,
        })

    def _page_response(
        self,
        *,
        history_id: str,
        dataset_id: str,
        operation: str,
        values: list[dict[str, Any]],
        offset: int,
        snapshot_id: str,
        dataset_checksum: str,
        query_checksum: str,
        computed: bool,
    ) -> dict[str, Any]:
        result_values = values[offset:offset + MAX_RESULT_SIZE]
        next_offset = offset + len(result_values)
        return {
            "schema_version": SCHEMA_VERSION,
            "history_id": history_id,
            "dataset_id": dataset_id,
            "operation": operation,
            "snapshot_id": snapshot_id,
            "dataset_checksum": dataset_checksum,
            "result_checksum": _checksum(result_values),
            "total_count": len(values),
            "complete": next_offset >= len(values),
            "continue_token": self._continue_token(dataset_id, snapshot_id, query_checksum, next_offset) if next_offset < len(values) else None,
            "records": [] if computed else result_values,
            "computed_results": result_values if computed else [],
            "warnings": [],
        }

    @staticmethod
    def _query_documents(records: list[dict[str, Any]], filters: dict[str, Any], sort: dict[str, Any]) -> list[dict[str, Any]]:
        def matches(record: dict[str, Any]) -> bool:
            for field, predicate in filters.items():
                value = record.get(field)
                if isinstance(predicate, dict):
                    if "eq" in predicate and value != predicate["eq"]:
                        return False
                    if "contains" in predicate and str(predicate["contains"]) not in str(value or ""):
                        return False
                elif value != predicate:
                    return False
            return True

        selected = [record for record in records if matches(record)]
        field = str(sort.get("field") or "") if isinstance(sort, dict) else ""
        if field:
            reverse = str(sort.get("direction") or "asc").lower() == "desc"
            selected.sort(key=lambda item: (item.get(field) is None, item.get(field)), reverse=reverse)
        return selected
