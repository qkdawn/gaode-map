from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from modules.spatial_projects.service import SpatialProjectService


class Repo:
    def __init__(self):
        self.projects = {}
        self.snapshots = {}
        self.units = {}

    def create_project(self, **payload):
        self.projects[payload["project_id"]] = deepcopy(payload)
        return {"project_id": payload["project_id"], "name": payload["name"], "scope": payload["scope"], "brief": payload["brief"], "created_at": "", "updated_at": ""}

    def list_projects(self):
        return [self.get_project(key) for key in self.projects]

    def get_project(self, project_id):
        row = self.projects.get(project_id)
        return {"project_id": row["project_id"], "name": row["name"], "scope": deepcopy(row["scope"]), "brief": deepcopy(row["brief"]), "created_at": "", "updated_at": ""} if row else None

    def create_snapshot(self, payload):
        self.snapshots[payload["id"]] = deepcopy(payload)
        return self.get_snapshot(payload["project_id"], payload["id"])

    def get_snapshot(self, project_id, snapshot_id):
        row = self.snapshots.get(snapshot_id)
        if not row or row["project_id"] != project_id:
            return None
        return {"snapshot_id": row["id"], "project_id": row["project_id"], "status": row["status"], "source_history_ids": deepcopy(row["source_history_ids"]), "scope": deepcopy(row["scope"]), "dataset_manifest": deepcopy(row["dataset_manifest"]), "datasets": deepcopy(row["datasets"]), "quality_report": deepcopy(row["quality_report"]), "created_at": ""}

    def list_snapshots(self, project_id):
        return [self.get_snapshot(project_id, key) for key, row in self.snapshots.items() if row["project_id"] == project_id]

    def add_units(self, rows):
        for row in rows:
            self.units[(row["snapshot_id"], row["unit_id"])] = deepcopy(row)
        return [self._unit(row) for row in rows]

    def list_units(self, snapshot_id, *, status="", limit=50, offset=0):
        rows = [row for (saved_snapshot, _), row in self.units.items() if saved_snapshot == snapshot_id and (not status or row["status"] == status)]
        return len(rows), [self._unit(row) for row in rows[offset:offset + limit]]

    def get_unit(self, snapshot_id, unit_id):
        row = self.units.get((snapshot_id, unit_id))
        return self._unit(row) if row else None

    @staticmethod
    def _unit(row):
        return {"unit_id": row["unit_id"], "snapshot_id": row["snapshot_id"], "name": row["name"], "unit_type": row["unit_type"], "geometry": deepcopy(row["geometry"]), "parent_id": row["parent_id"], "status": row["status"], "properties": deepcopy(row["properties"]), "created_at": ""}


class History:
    def get_detail(self, history_id, include_pois=False):
        return {
            "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "params": {"center": [0.5, 0.5], "coord_type": "wgs84"},
        } if history_id == "history-1" else None


class Datasets:
    def list_scope_datasets(self, history_id):
        return {"datasets": [{"source_id": "current:dataset:poi", "record_count": 2, "time_scope": {"years": [2025]}, "query_capabilities": {"filter_fields": ["category", "score"]}}], "warnings": []}

    def query_scope_dataset(self, **kwargs):
        return {"records": [{"record_id": "p1", "properties": {"category": "coffee", "score": 2}}, {"record_id": "p2", "properties": {"category": "coffee", "score": 5}}], "has_more": False, "warnings": []}

    def aggregate_scope_dataset(self, **kwargs):
        return {"source_id": kwargs["source_id"], "rows": [], "warnings": []}


def test_history_backed_project_reads_documents_and_uses_history_as_snapshot(monkeypatch):
    service = SpatialProjectService(repo=Repo(), history_repo=History(), datasets=Datasets())
    monkeypatch.setattr(
        "modules.spatial_projects.service.list_documents",
        lambda history_id="": [
            type("Document", (), {"id": "doc-1", "title": "项目任务书", "file_name": "brief.docx", "document_role": type("Role", (), {"value": "project_brief"})(), "status": "parsed", "history_id": history_id, "upload_time": datetime(2026, 7, 10)})()
        ],
    )

    result = service.read_history_project("history-1")

    assert result["history_id"] == "history-1"
    assert result["snapshot"] == {"snapshot_id": "history-1", "status": "available", "source": "analysis_history"}
    assert result["params"] == {"center": [0.5, 0.5], "coord_type": "wgs84"}
    assert result["documents"][0]["document_role"] == "project_brief"
    assert result["datasets"][0]["source_id"] == "current:dataset:poi"


def test_locked_snapshot_copies_dataset_records_and_supports_aggregate():
    service = SpatialProjectService(repo=Repo(), history_repo=History(), datasets=Datasets())
    project = service.create_project(name="测试项目")

    snapshot = service.build_snapshot(project_id=project["project_id"], history_id="history-1")
    result = service.aggregate_dataset(project_id=project["project_id"], snapshot_id=snapshot["snapshot_id"], source_id="current:dataset:poi", group_by="category", metrics=[{"op": "max", "field": "score", "as": "top_score"}])

    assert snapshot["status"] == "locked"
    assert result["rows"] == [{"group": "coffee", "count": 2, "top_score": 5.0}]


def test_dataset_query_applies_manifest_limited_filters_and_sorting():
    service = SpatialProjectService(repo=Repo(), history_repo=History(), datasets=Datasets())
    project = service.create_project(name="测试项目")
    snapshot = service.build_snapshot(project_id=project["project_id"], history_id="history-1")

    result = service.query_dataset(project_id=project["project_id"], snapshot_id=snapshot["snapshot_id"], source_id="current:dataset:poi", filters={"category": "coffee"}, sort={"field": "score", "direction": "desc"})

    assert [record["record_id"] for record in result["records"]] == ["p2", "p1"]


def test_history_dataset_operations_pass_spatial_target_to_dataset_service():
    class CapturingDatasets(Datasets):
        def __init__(self):
            self.query_kwargs = {}
            self.aggregate_kwargs = {}

        def query_scope_dataset(self, **kwargs):
            self.query_kwargs = kwargs
            return super().query_scope_dataset(**kwargs)

        def aggregate_scope_dataset(self, **kwargs):
            self.aggregate_kwargs = kwargs
            return super().aggregate_scope_dataset(**kwargs)

    datasets = CapturingDatasets()
    service = SpatialProjectService(repo=Repo(), history_repo=History(), datasets=datasets)
    spatial = {"relation": "within_distance", "point": [0.5, 0.5], "max_distance_m": 500}
    service.query_history_project_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        spatial=spatial,
    )
    service.aggregate_history_project_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        spatial=spatial,
    )

    assert datasets.query_kwargs["spatial"] == spatial
    assert datasets.aggregate_kwargs["spatial"] == spatial


def test_import_units_records_invalid_features_instead_of_silently_omitting_them():
    service = SpatialProjectService(repo=Repo(), history_repo=History(), datasets=Datasets())
    project = service.create_project(name="测试项目")
    snapshot = service.build_snapshot(project_id=project["project_id"], history_id="history-1")

    result = service.import_units(project_id=project["project_id"], snapshot_id=snapshot["snapshot_id"], feature_collection={"type": "FeatureCollection", "features": [{"id": "u1", "properties": {"name": "地块 A"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}}, {"id": "u1", "properties": {}, "geometry": {}}]})

    assert result["accepted_count"] == 1
    assert result["diagnostics"] == [{"feature_index": 1, "reason": "duplicate_id_or_invalid_geometry"}]


def test_stable_unit_id_can_be_reused_by_a_new_snapshot():
    service = SpatialProjectService(repo=Repo(), history_repo=History(), datasets=Datasets())
    project = service.create_project(name="测试项目")
    first = service.build_snapshot(project_id=project["project_id"], history_id="history-1")
    second = service.build_snapshot(project_id=project["project_id"], history_id="history-1")
    feature_collection = {"type": "FeatureCollection", "features": [{"id": "plot-a", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]}}]}

    service.import_units(project_id=project["project_id"], snapshot_id=first["snapshot_id"], feature_collection=feature_collection)
    service.import_units(project_id=project["project_id"], snapshot_id=second["snapshot_id"], feature_collection=feature_collection)

    assert service.read_unit(project_id=project["project_id"], snapshot_id=second["snapshot_id"], unit_id="plot-a")["unit_id"] == "plot-a"
