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
                "id": 11,
                "artifact_type": "population",
                "params": {"year": 2024, "view": "density"},
                "payload": {
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
                    "metric": "choice",
                    "roads": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"road_id": "r1", "choice": 0.7}},
                            {"type": "Feature", "properties": {"road_id": "r2", "choice": 0.2}},
                        ],
                    },
                    "nodes": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "properties": {"node_id": "n1", "connectivity": 3}},
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
    assert sources["current:dataset:road"]["record_count"] == 3
    assert sources["current:dataset:population"]["time_scope"]["years"] == [2024]


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
    assert queried["evidence_nodes"][0]["source_id"] == "current:dataset:population"
    assert queried["evidence_nodes"][0]["metadata"]["time_scope"]["year"] == 2024

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
        source_id="current:dataset:road",
        filters={"feature_kind": "road"},
        sort={"field": "choice", "direction": "desc"},
    )
    assert [item["record_id"] for item in road["records"]] == ["road:r1", "road:r2"]


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
