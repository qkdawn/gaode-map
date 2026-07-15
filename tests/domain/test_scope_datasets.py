from types import SimpleNamespace

import modules.scope_datasets.service as scope_service
from modules.scope_datasets import ScopeDatasetService


class FakeScopeDatasetRepository:
    def list_poi_results(self, history_id):
        assert history_id == "history-1"
        return [
            {
                "id": 1,
                "source": "local",
                "year": 2024,
                "summary": {"total": 2},
            }
        ]

    def get_poi_data(self, poi_result_id):
        assert poi_result_id == 1
        return [
            {"id": "poi-1", "name": "咖啡 A", "type": "咖啡厅", "address": "A 路"},
            {"id": "poi-2", "name": "便利 B", "type": "便利店", "address": "B 路"},
        ]

    def list_analysis_artifacts(self, history_id):
        assert history_id == "history-1"
        return [
            {
                "id": 9,
                "artifact_type": "poi_h3_grid",
                "params": {"year": 2024, "view": "density"},
                "payload": {
                    "geometry_coord_type": "gcj02",
                    "year": 2024,
                    "grid": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"h3_id": "h3-cell-1", "poi_count": 4}},
                        ],
                    },
                },
                "summary": {"grid_count": 1},
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 10,
                "artifact_type": "poi_raster_grid",
                "params": {"year": 2024, "view": "density"},
                "payload": {
                    "geometry_coord_type": "gcj02",
                    "year": 2024,
                    "grid": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"cell_id": "poi-cell-1", "poi_count": 5}},
                        ],
                    },
                },
                "summary": {"grid_count": 1},
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 11,
                "artifact_type": "population",
                "params": {"year": 2024, "view": "density"},
                "payload": {
                    "geometry_coord_type": "gcj02",
                    "year": 2024,
                    "view": "density",
                    "grid": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"cell_id": "cell-1", "population": 120}},
                            {"type": "Feature", "properties": {"cell_id": "cell-2", "population": 80}},
                        ],
                    },
                    "layer": {
                        "view": "density",
                        "cells": [
                            {"cell_id": "cell-1", "value": 12.5},
                            {"cell_id": "cell-2", "value": 8.0},
                        ],
                    },
                },
                "summary": {},
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 12,
                "artifact_type": "road_syntax",
                "params": {"metric": "choice"},
                "payload": {
                    "geometry_coord_type": "gcj02",
                    "metric": "choice",
                    "road_edges": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"edge_id": "r1", "choice_score": 0.7}},
                            {"type": "Feature", "properties": {"edge_id": "r2", "choice_score": 0.2}},
                        ],
                    },
                    "road_grid": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"cell_id": "cell-1", "road_length_km": 0.4, "road_choice": 0.5}},
                        ],
                    },
                },
                "summary": {},
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
        ]


def test_scope_dataset_service_lists_normalized_sources():
    payload = ScopeDatasetService(repository=FakeScopeDatasetRepository()).list_scope_datasets("history-1")

    sources = {item["source_id"]: item for item in payload["datasets"]}
    assert sources["current:dataset:poi"]["record_count"] == 2
    assert sources["current:dataset:population"]["record_count"] == 2
    assert sources["current:dataset:h3"]["record_count"] == 1
    assert sources["current:dataset:poi_grid"]["record_count"] == 1
    assert sources["current:dataset:road_edges"]["record_count"] == 2
    assert sources["current:dataset:road_grid"]["record_count"] == 1
    assert sources["current:dataset:population"]["time_scope"]["years"] == [2024]
    assert sources["current:dataset:h3"]["grid_type"] == "h3"
    assert sources["current:dataset:poi_grid"]["grid_type"] == "regular_raster"
    assert "at_point" in sources["current:dataset:population"]["query_capabilities"]["spatial_relations"]
    assert sources["current:dataset:population"]["query_capabilities"]["spatial_ready"] is True
    assert sources["current:dataset:population"]["query_capabilities"]["spatial_aggregations"][0]["op"] == "area_weighted_sum"


def test_scope_dataset_service_queries_and_reads_evidence_nodes():
    service = ScopeDatasetService(repository=FakeScopeDatasetRepository())

    queried = service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:population",
        filters={"value": {"gte": 10}},
        sort={"field": "value", "direction": "desc"},
        limit=10,
    )
    assert queried["total_count"] == 1
    assert queried["records"][0]["record_id"] == "cell-1"
    assert queried["evidence_nodes"][0]["source_ids"] == ["current:dataset:population"]
    assert queried["evidence_nodes"][0]["time_scope"]["year"] == 2024
    assert "confidence" not in queried["evidence_nodes"][0]["time_scope"]
    assert "confidence_basis" not in queried["evidence_nodes"][0]["time_scope"]

    read = service.read_scope_record(history_id="history-1", source_id="current:dataset:population", record_id="cell-1")
    assert read["evidence_node"]["id"] == "current:dataset:population:record:cell-1"
    assert "当前范围人口网格" in read["evidence_node"]["citation"]


def test_scope_dataset_service_aggregates_poi_and_sorts_road_records():
    service = ScopeDatasetService(repository=FakeScopeDatasetRepository())

    aggregate = service.aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        group_by="category",
        metrics=[{"op": "count", "field": "*", "as": "count"}],
    )
    assert {row["group"]: row["count"] for row in aggregate["rows"]} == {"咖啡厅": 1, "便利店": 1}

    road = service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_edges",
        filters={"feature_kind": "road_edge"},
        sort={"field": "choice_score", "direction": "desc"},
    )
    assert [item["record_id"] for item in road["records"]] == ["road_edge:r1", "road_edge:r2"]
    assert road["selected_year"] is None
    assert road["records"][0]["time_scope"]["kind"] == "static_snapshot"
    assert road["warnings"] == []


def test_scope_dataset_defaults_to_max_year_and_exactly_matches_requested_year():
    class MultiYearRepository:
        def list_poi_results(self, history_id):
            return [
                {"id": 20, "source": "local", "year": 2020, "summary": {"total": 1}},
                {"id": 24, "source": "local", "year": 2024, "summary": {"total": 2}},
            ]

        def get_poi_data(self, poi_result_id):
            return [{"id": f"poi-{poi_result_id}-{index}"} for index in range(2 if poi_result_id == 24 else 1)]

        def list_analysis_artifacts(self, history_id):
            def artifact(artifact_id, artifact_type, year, updated_at, count, summary=None):
                return {
                    "id": artifact_id,
                    "artifact_type": artifact_type,
                    "slot_key": f"year:{year}",
                    "params": {"year": year, "view": "density"},
                    "payload": {
                        "year": year,
                        "grid": {
                            "features": [
                                {"type": "Feature", "properties": {"cell_id": f"{artifact_type}-{year}-{index}", "value": index}}
                                for index in range(count)
                            ]
                        },
                    },
                    "summary": summary or {},
                    "data_version": "v1",
                    "scope_fingerprint": "scope-a",
                    "updated_at": updated_at,
                }

            return [
                artifact(1, "poi_h3_grid", 2020, "2026-07-14T12:00:00", 1),
                artifact(2, "poi_h3_grid", 2024, "2024-01-01T00:00:00", 2),
                artifact(3, "population", 2024, "2026-07-14T12:00:00", 1, {"total_population": 100}),
                artifact(4, "population", 2026, "2024-01-01T00:00:00", 2, {"total_population": 58200.628}),
            ]

    service = ScopeDatasetService(repository=MultiYearRepository())
    default_h3 = service.query_scope_dataset(history_id="history-1", source_id="current:dataset:h3", limit=10)
    old_h3 = service.query_scope_dataset(history_id="history-1", source_id="current:dataset:h3", year="2020", limit=10)
    datasets = {item["source_id"]: item for item in service.list_scope_datasets("history-1")["datasets"]}

    assert default_h3["selected_year"] == 2024
    assert default_h3["available_years"] == [2020, 2024]
    assert default_h3["total_count"] == 2
    assert old_h3["selected_year"] == 2020
    assert old_h3["total_count"] == 1
    assert datasets["current:dataset:h3"]["record_count"] == 2
    assert datasets["current:dataset:population"]["selected_year"] == 2026
    assert datasets["current:dataset:population"]["record_count"] == 2
    assert datasets["current:dataset:population"]["summary"]["total_population"] == 58200.628


def test_scope_dataset_keeps_poi_raster_separate_from_h3():
    class MissingCurrentGridRepository:
        def list_poi_results(self, history_id):
            return [{"id": 24, "source": "local", "year": 2024, "summary": {"total": 2}}]

        def get_poi_data(self, poi_result_id):
            return []

        def list_analysis_artifacts(self, history_id):
            return [{
                "id": 1,
                "artifact_type": "poi_raster_grid",
                "slot_key": "year:2020",
                "params": {"year": 2020},
                "payload": {"year": 2020, "grid": {"features": [{"properties": {"cell_id": "old"}}]}},
                "summary": {"grid_count": 1},
                "updated_at": "2026-07-14T12:00:00",
            }]

    datasets = {
        item["source_id"]: item
        for item in ScopeDatasetService(repository=MissingCurrentGridRepository()).list_scope_datasets("history-1")["datasets"]
    }

    assert "current:dataset:h3" not in datasets
    assert datasets["current:dataset:poi_grid"]["status"] == "pending"
    assert datasets["current:dataset:poi_grid"]["selected_year"] == 2024
    assert datasets["current:dataset:poi_grid"]["available_years"] == [2020]
    assert datasets["current:dataset:poi_grid"]["record_count"] == 0


def test_scope_dataset_repository_lists_poi_results_without_large_json(monkeypatch):
    queried_entities = []

    class FakeQuery:
        def __init__(self, entities):
            self.entities = entities

        def filter_by(self, **kwargs):
            assert kwargs == {"history_id": "history-1"}
            return self

        def order_by(self, *clauses):
            assert clauses
            return self

        def all(self):
            return [
                SimpleNamespace(
                    id=7,
                    source="local",
                    year=2024,
                    summary={"total": 12},
                    created_at=None,
                )
            ]

    class FakeSession:
        def query(self, *entities):
            queried_entities.extend(entities)
            return FakeQuery(entities)

        def close(self):
            pass

    monkeypatch.setattr(scope_service, "SessionLocal", lambda: FakeSession())

    rows = scope_service.ScopeDatasetRepository().list_poi_results("history-1")

    assert rows == [{"id": 7, "source": "local", "year": 2024, "summary": {"total": 12}}]
    assert all(entity is not scope_service.PoiResult for entity in queried_entities)
    assert all(entity is not scope_service.PoiResult.poi_data for entity in queried_entities)


def test_scope_dataset_repository_orders_artifacts_without_large_json(monkeypatch):
    queried_entities = []
    loaded_ids = []

    class FakeIdQuery:
        def __init__(self, entities):
            self.entities = entities

        def filter_by(self, **kwargs):
            assert kwargs == {"history_id": "history-1"}
            return self

        def order_by(self, *clauses):
            assert clauses
            return self

        def all(self):
            return [(12,), (11,)]

    class FakeSession:
        def query(self, *entities):
            queried_entities.extend(entities)
            assert len(entities) == 1
            assert entities[0] is scope_service.AnalysisArtifact.id
            return FakeIdQuery(entities)

        def get(self, model, record_id):
            assert model is scope_service.AnalysisArtifact
            loaded_ids.append(record_id)
            return SimpleNamespace(
                id=record_id,
                artifact_type="population",
                slot_key="year:2024",
                params={"year": 2024},
                payload={"grid": {"features": []}},
                summary={"grid_count": 0},
                data_version="v1",
                scope_fingerprint="scope-a",
                updated_at=None,
            )

        def close(self):
            pass

    monkeypatch.setattr(scope_service, "SessionLocal", lambda: FakeSession())

    rows = scope_service.ScopeDatasetRepository().list_analysis_artifacts("history-1")

    assert [row["id"] for row in rows] == [12, 11]
    assert loaded_ids == [12, 11]
    assert all(entity is not scope_service.AnalysisArtifact for entity in queried_entities)
