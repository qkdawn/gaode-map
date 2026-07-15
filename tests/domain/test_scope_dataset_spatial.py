import asyncio
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, box

from modules.scope_datasets import ScopeDatasetService
from modules.scope_datasets.spatial import SpatialQueryError, query_spatial_records
from modules.agent.tool_adapters import scope_dataset_tools


def test_nearest_uses_real_line_geometry_and_returns_projection_point():
    records = [
        SimpleNamespace(geometry=LineString([(0.0, 0.0), (0.01, 0.0)]), record_id="near"),
        SimpleNamespace(geometry=LineString([(0.0, 0.01), (0.01, 0.01)]), record_id="far"),
    ]

    result = query_spatial_records(
        records,
        {
            "relation": "nearest",
            "point": [0.005, 0.0002],
            "coord_type": "wgs84",
            "max_distance_m": 100,
        },
    )

    assert list(result.matches) == [0]
    match = result.matches[0].as_payload()
    assert match["geometry_type"] == "LineString"
    assert 20 < match["distance_m"] < 25
    assert match["matched_point"] == [0.005, 0.0]


def test_at_point_and_intersects_return_polygon_overlap_evidence():
    records = [
        SimpleNamespace(geometry=box(0.0, 0.0, 0.01, 0.01), record_id="cell-a"),
        SimpleNamespace(geometry=box(0.02, 0.02, 0.03, 0.03), record_id="cell-b"),
    ]

    at_point = query_spatial_records(
        records,
        {"relation": "at_point", "point": [0.005, 0.005], "coord_type": "wgs84"},
    )
    assert list(at_point.matches) == [0]
    assert at_point.matches[0].distance_m is None

    intersects = query_spatial_records(
        records,
        {
            "relation": "intersects",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.005, 0.0], [0.015, 0.0], [0.015, 0.01], [0.005, 0.01], [0.005, 0.0]]],
            },
            "coord_type": "wgs84",
        },
    )
    match = intersects.matches[0].as_payload()
    assert 0.49 < match["record_overlap_ratio"] < 0.51
    assert 0.49 < match["query_overlap_ratio"] < 0.51
    assert match["overlap_area_m2"] > 500_000


def test_spatial_query_rejects_missing_coordinate_type():
    with pytest.raises(SpatialQueryError) as error:
        query_spatial_records(
            [SimpleNamespace(geometry=Point(0, 0), record_id="p")],
            {"relation": "nearest", "point": [0, 0]},
        )
    assert error.value.code == "spatial_coord_type_unknown"


class _SpatialRepository:
    def list_poi_results(self, history_id):
        return [{"id": 1, "source": "local", "year": 2024, "summary": {"total": 2}}]

    def get_poi_data(self, poi_result_id):
        return [
            {"id": "poi-near", "name": "近点", "type": "餐饮", "location": "0.005,0.0002"},
            {"id": "poi-far", "name": "远点", "type": "餐饮", "location": "0.005,0.01"},
        ]

    def list_analysis_artifacts(self, history_id):
        return []


def test_scope_service_attaches_spatial_match_to_record_and_evidence():
    result = ScopeDatasetService(repository=_SpatialRepository()).query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        spatial={
            "relation": "nearest",
            "point": [0.005, 0.0],
            "coord_type": "wgs84",
            "max_distance_m": 100,
        },
        limit=5,
    )

    assert result["total_count"] == 1
    assert result["records"][0]["record_id"] == "poi-near"
    assert result["records"][0]["spatial_match"]["distance_m"] > 0
    assert result["evidence_nodes"][0]["data"]["spatial_match"]["relation"] == "nearest"
    assert result["spatial_query"]["max_distance_m"] == 100


def test_scope_service_queries_road_grid_as_polygon_source():
    class RoadGridRepository:
        def list_poi_results(self, history_id):
            return []

        def list_analysis_artifacts(self, history_id):
            return [
                {
                    "id": 42,
                    "artifact_type": "road_syntax",
                    "params": {"metric": "choice"},
                    "payload": {
                        "road_grid": {
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "properties": {"cell_id": "road-cell-1", "road_choice": 0.8},
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
                                    },
                                }
                            ],
                        }
                    },
                    "summary": {},
                    "data_version": "v1",
                    "scope_fingerprint": "scope-a",
                }
            ]

    result = ScopeDatasetService(repository=RoadGridRepository()).query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_grid",
        spatial={"relation": "at_point", "point": [0.005, 0.005], "coord_type": "wgs84"},
        limit=5,
    )

    assert result["total_count"] == 1
    assert result["records"][0]["record_id"] == "road-cell-1"
    assert result["records"][0]["spatial_match"]["geometry_type"] == "Polygon"


def test_scope_service_rejects_relation_not_declared_by_source():
    with pytest.raises(SpatialQueryError) as error:
        ScopeDatasetService(repository=_SpatialRepository()).query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:population",
            spatial={
                "relation": "within_distance",
                "point": [0, 0],
                "coord_type": "wgs84",
                "max_distance_m": 100,
            },
        )
    assert error.value.code == "spatial_relation_unsupported"


def test_scope_dataset_tool_returns_domain_error_for_invalid_spatial_query(monkeypatch):
    class FailingService:
        def query_scope_dataset(self, **kwargs):
            raise SpatialQueryError("spatial_relation_unsupported", "不支持 nearest")

    monkeypatch.setattr(scope_dataset_tools, "_service", lambda: FailingService())
    result = asyncio.run(
        scope_dataset_tools.query_scope_dataset(
            arguments={"source_id": "current:dataset:population", "spatial": {"relation": "nearest"}},
            snapshot=SimpleNamespace(context={"history_id": "history-1"}),
            artifacts={},
            question="",
        )
    )

    assert result.status == "failed"
    assert result.error == "spatial_relation_unsupported"
