from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from modules.scope_datasets.service import ScopeDatasetService
from modules.documents.service import get_document_source_metadata, list_documents
from modules.spatial_projects.query_snapshot_store import SpatialQuerySnapshotStore
from store.history_repo import HistoryRepo
from store.spatial_project_repo import SpatialProjectRepo

MAX_PAGE_SIZE = 100


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def _text(value: Any) -> str:
    return str(value or "").strip()


class SpatialProjectService:
    """Own project facts after they have left the map workbench."""

    def __init__(
        self,
        repo: SpatialProjectRepo | None = None,
        history_repo: HistoryRepo | None = None,
        datasets: ScopeDatasetService | None = None,
        query_snapshots: SpatialQuerySnapshotStore | None = None,
    ):
        self.repo = repo or SpatialProjectRepo()
        self.history_repo = history_repo or HistoryRepo()
        self.datasets = datasets or ScopeDatasetService()
        self.query_snapshots = query_snapshots or SpatialQuerySnapshotStore()

    def create_project(self, *, name: str, scope: dict[str, Any] | None = None, brief: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_name = _text(name)
        if not normalized_name:
            raise ValueError("project_name_required")
        return self.repo.create_project(project_id=_id("project"), name=normalized_name, scope=deepcopy(scope or {}), brief=deepcopy(brief or {}))

    def list_projects(self) -> list[dict[str, Any]]:
        projects = self.repo.list_projects()
        for project in projects:
            snapshots = self.repo.list_snapshots(project["project_id"])
            project["snapshots"] = [{key: item[key] for key in ("snapshot_id", "status", "created_at")} for item in snapshots]
        return projects

    def list_history_projects(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Expose analysis histories as the Agent-facing spatial project list."""
        records = self.history_repo.get_list(limit=max(min(int(limit), 500), 1))
        return [self._history_project_summary(record) for record in records]

    def read_history_project(self, history_id: str) -> dict[str, Any]:
        normalized_history_id = _text(history_id)
        history = self.history_repo.get_detail(normalized_history_id, include_pois=False)
        if history is None:
            raise LookupError("history_not_found")
        datasets = self.datasets.list_scope_datasets(normalized_history_id)
        return {
            "history_id": normalized_history_id,
            "project_name": _text(history.get("description")) or normalized_history_id,
            "description": _text(history.get("description")),
            "created_at": history.get("created_at") or "",
            "params": deepcopy(history.get("params") or {}),
            "scope": deepcopy(history.get("polygon") or history.get("result_polygon") or {}),
            "documents": self.list_history_project_documents(normalized_history_id),
            "datasets": deepcopy(datasets.get("datasets") or []),
            "warnings": list(datasets.get("warnings") or []),
            "snapshot": {
                "snapshot_id": normalized_history_id,
                "status": "available",
                "source": "analysis_history",
            },
        }

    def list_history_project_documents(self, history_id: str) -> list[dict[str, Any]]:
        normalized_history_id = _text(history_id)
        self._require_history(normalized_history_id)
        return [
            {
                "document_id": document.id,
                "title": document.title,
                "file_name": document.file_name,
                "document_role": document.document_role.value,
                "status": document.status,
                "history_id": document.history_id,
                "uploaded_at": document.upload_time.isoformat(),
            }
            for document in list_documents(history_id=normalized_history_id)
        ]

    def get_history_project_document_resource(self, *, history_id: str, document_id: str) -> dict[str, Any]:
        """Return safe metadata for an original project-document resource."""
        normalized_history_id = _text(history_id)
        if not normalized_history_id:
            raise ValueError("history_id_required")
        self._require_history(normalized_history_id)
        metadata = get_document_source_metadata(document_id, history_id=normalized_history_id)
        return {"history_id": normalized_history_id, **metadata}

    def list_history_project_datasets(self, history_id: str) -> dict[str, Any]:
        normalized_history_id = _text(history_id)
        self._require_history(normalized_history_id)
        result = self.datasets.list_scope_datasets(normalized_history_id)
        return {
            "history_id": normalized_history_id,
            "snapshot_id": normalized_history_id,
            "datasets": deepcopy(result.get("datasets") or []),
            "warnings": list(result.get("warnings") or []),
        }

    def query_history_project_dataset(
        self,
        *,
        history_id: str,
        source_id: str,
        filters: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        spatial: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
        year: int | None = None,
    ) -> dict[str, Any]:
        normalized_history_id = _text(history_id)
        self._require_history(normalized_history_id)
        result = self.datasets.query_scope_dataset(
            history_id=normalized_history_id,
            source_id=_text(source_id),
            filters=filters,
            sort=sort,
            spatial=spatial,
            limit=limit,
            offset=offset,
            year=year,
        )
        return {"history_id": normalized_history_id, "snapshot_id": normalized_history_id, **result}

    def create_history_project_dataset_query_snapshot(
        self,
        *,
        history_id: str,
        source_id: str,
        filters: dict[str, Any] | None = None,
        spatial: dict[str, Any] | None = None,
        year: int | None = None,
    ) -> dict[str, Any]:
        """Persist a complete immutable geometry selection for later rendering."""
        normalized_history_id = _text(history_id)
        normalized_source_id = _text(source_id)
        self._require_history(normalized_history_id)
        selection = self.datasets.materialize_query_snapshot(
            history_id=normalized_history_id,
            source_id=normalized_source_id,
            filters=filters,
            spatial=spatial,
            year=year,
        )
        if selection.get("status") != "available":
            return {
                "status": "unavailable",
                "history_id": normalized_history_id,
                "source_id": normalized_source_id,
                "record_count": int(selection.get("record_count") or 0),
                "normalized_feature_count": int(selection.get("normalized_feature_count") or 0),
                "warnings": list(selection.get("warnings") or []),
                "failure_reasons": list(selection.get("failure_reasons") or []),
            }
        metadata = self.query_snapshots.create(
            history_id=normalized_history_id,
            source_id=normalized_source_id,
            year=year,
            filters=filters,
            spatial=spatial,
            selection=selection,
        )
        return {"status": "available", **metadata, "failure_reasons": []}

    def aggregate_history_project_dataset(
        self,
        *,
        history_id: str,
        source_id: str,
        group_by: str = "",
        metrics: list[dict[str, Any]] | None = None,
        filters: dict[str, Any] | None = None,
        spatial: dict[str, Any] | None = None,
        top_k: int = 20,
        year: int | None = None,
    ) -> dict[str, Any]:
        normalized_history_id = _text(history_id)
        self._require_history(normalized_history_id)
        result = self.datasets.aggregate_scope_dataset(
            history_id=normalized_history_id,
            source_id=_text(source_id),
            group_by=group_by,
            metrics=metrics,
            filters=filters,
            spatial=spatial,
            top_k=top_k,
            year=year,
        )
        return {"history_id": normalized_history_id, "snapshot_id": normalized_history_id, **result}

    def read_history_project_dataset_record(
        self,
        *,
        history_id: str,
        source_id: str,
        record_id: str,
        year: int | None = None,
    ) -> dict[str, Any]:
        normalized_history_id = _text(history_id)
        self._require_history(normalized_history_id)
        result = self.datasets.read_scope_record(
            history_id=normalized_history_id,
            source_id=_text(source_id),
            record_id=_text(record_id),
            year=year,
        )
        return {"history_id": normalized_history_id, "snapshot_id": normalized_history_id, **result}

    def _require_history(self, history_id: str) -> dict[str, Any]:
        if not history_id:
            raise ValueError("history_id_required")
        history = self.history_repo.get_detail(history_id, include_pois=False)
        if history is None:
            raise LookupError("history_not_found")
        return history

    def _history_project_summary(self, record: dict[str, Any]) -> dict[str, Any]:
        history_id = _text(record.get("id"))
        return {
            "history_id": history_id,
            "project_name": _text(record.get("description")) or history_id,
            "description": _text(record.get("description")),
            "created_at": record.get("created_at") or "",
        }

    def build_snapshot(self, *, project_id: str, history_id: str) -> dict[str, Any]:
        project = self.repo.get_project(project_id)
        if project is None:
            raise LookupError("project_not_found")
        history = self.history_repo.get_detail(_text(history_id), include_pois=False)
        if history is None:
            raise LookupError("history_not_found")
        listing = self.datasets.list_scope_datasets(_text(history_id))
        manifest = deepcopy(listing.get("datasets") or [])
        stored_datasets: dict[str, list[dict[str, Any]]] = {}
        warnings = list(listing.get("warnings") or [])
        for item in manifest:
            source_id = _text(item.get("source_id"))
            if not source_id:
                continue
            page = self.datasets.query_scope_dataset(history_id=_text(history_id), source_id=source_id, limit=MAX_PAGE_SIZE, offset=0)
            records = list(page.get("records") or [])
            while page.get("has_more"):
                page = self.datasets.query_scope_dataset(history_id=_text(history_id), source_id=source_id, limit=MAX_PAGE_SIZE, offset=len(records))
                records.extend(page.get("records") or [])
            stored_datasets[source_id] = deepcopy(records)
            warnings.extend(page.get("warnings") or [])
        scope = deepcopy(history.get("polygon") or history.get("result_polygon") or project.get("scope") or {})
        quality_report = {
            "status": "warning" if warnings else "ready",
            "warnings": sorted(set(_text(item) for item in warnings if _text(item))),
            "dataset_count": len(manifest),
            "locked_at": datetime.now(UTC).isoformat(),
        }
        return self.repo.create_snapshot({
            "id": _id("snapshot"), "project_id": project_id, "status": "locked",
            "source_history_ids": [_text(history_id)], "scope": scope,
            "dataset_manifest": manifest, "datasets": stored_datasets, "quality_report": quality_report,
        })

    def read_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return {key: snapshot[key] for key in ("snapshot_id", "project_id", "status", "source_history_ids", "scope", "dataset_manifest", "quality_report", "created_at")}

    def list_datasets(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        return {"snapshot_id": snapshot_id, "datasets": deepcopy(snapshot["dataset_manifest"]), "warnings": list(snapshot["quality_report"].get("warnings") or [])}

    def query_dataset(self, *, project_id: str, snapshot_id: str, source_id: str, filters: dict[str, Any] | None = None, sort: dict[str, str] | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        records = list(snapshot["datasets"].get(source_id) or [])
        allowed_fields = self._query_fields(snapshot, source_id)
        normalized_filters = self._validate_filters(filters, allowed_fields)
        filtered = [record for record in records if all(self._record_value(record, key) == value for key, value in normalized_filters.items())]
        sort_spec = sort or {}
        sort_field = _text(sort_spec.get("field")) if isinstance(sort_spec, dict) else ""
        direction = _text(sort_spec.get("direction") or "asc").lower() if isinstance(sort_spec, dict) else "asc"
        if sort_field:
            if sort_field not in allowed_fields:
                raise ValueError("unsupported_sort_field")
            if direction not in {"asc", "desc"}:
                raise ValueError("invalid_sort_direction")
            filtered.sort(key=lambda record: self._sort_value(self._record_value(record, sort_field)), reverse=direction == "desc")
        safe_limit = min(max(int(limit), 1), MAX_PAGE_SIZE)
        safe_offset = max(int(offset), 0)
        page = filtered[safe_offset:safe_offset + safe_limit]
        return {"source_id": source_id, "total_count": len(filtered), "limit": safe_limit, "offset": safe_offset, "has_more": safe_offset + safe_limit < len(filtered), "records": deepcopy(page), "warnings": list(snapshot["quality_report"].get("warnings") or [])}

    def aggregate_dataset(self, *, project_id: str, snapshot_id: str, source_id: str, group_by: str = "", metrics: list[dict[str, str]] | None = None, filters: dict[str, Any] | None = None, top_k: int = 20) -> dict[str, Any]:
        snapshot = self._snapshot(project_id, snapshot_id)
        allowed_fields = self._query_fields(snapshot, source_id)
        if group_by and group_by not in allowed_fields:
            raise ValueError("unsupported_group_by_field")
        normalized_filters = self._validate_filters(filters, allowed_fields)
        records = [record for record in snapshot["datasets"].get(source_id) or [] if all(self._record_value(record, key) == value for key, value in normalized_filters.items())]
        metric_specs = metrics or [{"op": "count", "field": "*", "as": "count"}]
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            key = _text(self._record_value(record, group_by)) if group_by else "all"
            groups.setdefault(key or "未标注", []).append(record)
        rows = []
        for key, group_records in groups.items():
            row: dict[str, Any] = {"group": key, "count": len(group_records)}
            for metric in metric_specs:
                if not isinstance(metric, dict):
                    raise ValueError("invalid_metric")
                op = _text(metric.get("op") or "count").lower()
                field = _text(metric.get("field") or "*")
                alias = _text(metric.get("as")) or f"{op}_{field}"
                if op not in {"count", "sum", "avg", "min", "max"}:
                    raise ValueError("unsupported_aggregate_op")
                if field != "*" and field not in allowed_fields:
                    raise ValueError("unsupported_metric_field")
                values = [self._numeric_value(self._record_value(record, field)) for record in group_records] if field != "*" else []
                numbers = [value for value in values if value is not None]
                if op == "count":
                    row[alias] = len(group_records) if field == "*" else len(numbers)
                elif op == "sum":
                    row[alias] = sum(numbers) if numbers else None
                elif op == "avg":
                    row[alias] = sum(numbers) / len(numbers) if numbers else None
                elif op == "min":
                    row[alias] = min(numbers) if numbers else None
                else:
                    row[alias] = max(numbers) if numbers else None
            rows.append(row)
        rows.sort(key=lambda row: (-int(row["count"]), row["group"]))
        return {"source_id": source_id, "group_by": group_by, "total_groups": len(rows), "rows": rows[:min(max(int(top_k), 1), MAX_PAGE_SIZE)], "warnings": list(snapshot["quality_report"].get("warnings") or [])}

    def import_units(self, *, project_id: str, snapshot_id: str, feature_collection: dict[str, Any]) -> dict[str, Any]:
        self._snapshot(project_id, snapshot_id)
        features = feature_collection.get("features") if isinstance(feature_collection, dict) else None
        if not isinstance(features, list):
            raise ValueError("geojson_feature_collection_required")
        rows = []
        diagnostics = []
        seen = set()
        for index, feature in enumerate(features):
            props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
            geometry = feature.get("geometry") if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict) else {}
            unit_id = _text(feature.get("id") if isinstance(feature, dict) else "") or _text(props.get("unit_id")) or f"unit_{index + 1}"
            if unit_id in seen or not geometry.get("type") or not geometry.get("coordinates"):
                diagnostics.append({"feature_index": index, "reason": "duplicate_id_or_invalid_geometry"})
                continue
            seen.add(unit_id)
            rows.append({"id": _id("project_unit"), "unit_id": unit_id, "snapshot_id": snapshot_id, "name": _text(props.get("name")) or unit_id, "unit_type": _text(props.get("unit_type")) or "unit", "geometry": deepcopy(geometry), "parent_id": _text(props.get("parent_id")), "status": _text(props.get("status")) or "eligible", "properties": deepcopy(props)})
        created = self.repo.add_units(rows) if rows else []
        return {"accepted_count": len(created), "diagnostics": diagnostics, "units": created}

    def list_units(self, *, project_id: str, snapshot_id: str, status: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        self._snapshot(project_id, snapshot_id)
        total, units = self.repo.list_units(snapshot_id, status=status, limit=min(max(int(limit), 1), MAX_PAGE_SIZE), offset=max(int(offset), 0))
        return {"total_count": total, "units": units, "warnings": []}

    def read_unit(self, *, project_id: str, snapshot_id: str, unit_id: str) -> dict[str, Any]:
        self._snapshot(project_id, snapshot_id)
        unit = self.repo.get_unit(snapshot_id, unit_id)
        if unit is None:
            raise LookupError("spatial_unit_not_found")
        return unit

    def _snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.repo.get_snapshot(_text(project_id), _text(snapshot_id))
        if snapshot is None:
            raise LookupError("snapshot_not_found")
        if snapshot["status"] != "locked":
            raise ValueError("snapshot_is_not_locked")
        return snapshot

    @staticmethod
    def _record_value(record: dict[str, Any], field: str) -> Any:
        if field in {"record_id", "source_id", "title", "locator", "citation"}:
            return record.get(field)
        properties = record.get("properties") if isinstance(record.get("properties"), dict) else {}
        return properties.get(field)

    @staticmethod
    def _numeric_value(value: Any) -> float | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sort_value(value: Any) -> tuple[int, Any]:
        numeric = SpatialProjectService._numeric_value(value)
        if numeric is not None:
            return 0, numeric
        return 1, _text(value)

    @staticmethod
    def _validate_filters(filters: dict[str, Any] | None, allowed_fields: set[str]) -> dict[str, Any]:
        if filters is None:
            return {}
        if not isinstance(filters, dict):
            raise ValueError("filters_must_be_an_object")
        if any(_text(field) not in allowed_fields for field in filters):
            raise ValueError("unsupported_filter_field")
        return {_text(field): value for field, value in filters.items()}

    @staticmethod
    def _query_fields(snapshot: dict[str, Any], source_id: str) -> set[str]:
        for item in snapshot.get("dataset_manifest") or []:
            if isinstance(item, dict) and item.get("source_id") == source_id:
                capabilities = item.get("query_capabilities") if isinstance(item.get("query_capabilities"), dict) else {}
                fields = capabilities.get("filter_fields") if isinstance(capabilities.get("filter_fields"), list) else []
                return {str(field) for field in fields} | {"record_id", "source_id", "title", "locator", "citation"}
        raise ValueError("dataset_not_found")
