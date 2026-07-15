import asyncio
import math
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, box

import modules.scope_datasets.spatial as spatial_module
from modules.scope_datasets import ScopeDatasetQueryError, ScopeDatasetService
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


def test_within_distance_does_not_drop_east_west_candidate_at_changsha_latitude():
    latitude = 28.2
    longitude = 112.98
    longitude_delta = math.degrees(95 / (6_378_137 * math.cos(math.radians(latitude))))
    records = [
        SimpleNamespace(
            geometry=Point(longitude + longitude_delta, latitude),
            record_id="east-95m",
        )
    ]

    result = query_spatial_records(
        records,
        {
            "relation": "within_distance",
            "point": [longitude, latitude],
            "coord_type": "wgs84",
            "max_distance_m": 100,
        },
    )

    assert list(result.matches) == [0]
    assert 94.9 < result.matches[0].distance_m < 95.1


def test_spatial_cache_key_changes_when_geometry_changes():
    common = {
        "record_id": "same-record",
        "locator": "current:dataset:poi/same-record",
        "time_scope": {"data_version": "v1", "scope_fingerprint": "scope-a"},
    }
    first = SimpleNamespace(**common, geometry=Point(112.98, 28.2))
    moved = SimpleNamespace(**common, geometry=Point(112.99, 28.2))

    first_key = ScopeDatasetService._spatial_cache_key("history-1", "current:dataset:poi", 2024, [first])
    moved_key = ScopeDatasetService._spatial_cache_key("history-1", "current:dataset:poi", 2024, [moved])

    assert first_key != moved_key


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


def test_spatial_query_wraps_unexpected_metric_failures(monkeypatch):
    monkeypatch.setattr(spatial_module, "_candidate_positions", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(SpatialQueryError) as error:
        query_spatial_records(
            [SimpleNamespace(geometry=Point(0, 0), record_id="p")],
            {"relation": "nearest", "point": [0, 0], "coord_type": "wgs84"},
        )
    assert error.value.code == "spatial_metric_calculation_failed"


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
    assert result["spatial_diagnostics"] == {
        "matched_record_count": 1,
        "skipped_record_count": 0,
        "result_complete": True,
    }


def test_scope_service_uses_existing_record_as_spatial_target_and_excludes_itself():
    result = ScopeDatasetService(repository=_SpatialRepository()).query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        spatial={
            "relation": "nearest",
            "record": {"source_id": "current:dataset:poi", "record_id": "poi-near", "year": 2024},
        },
        limit=5,
    )

    assert result["total_count"] == 1
    assert result["records"][0]["record_id"] == "poi-far"
    assert result["records"][0]["spatial_match"]["distance_m"] > 1_000
    assert result["spatial_query"]["record"]["record_id"] == "poi-near"


def test_scope_service_rejects_unadvertised_filter_and_sort_fields():
    service = ScopeDatasetService(repository=_SpatialRepository())

    with pytest.raises(ScopeDatasetQueryError) as filter_error:
        service.query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:poi",
            filters={"not_a_real_field": "x"},
        )
    assert filter_error.value.code == "scope_dataset_field_unsupported"

    with pytest.raises(ScopeDatasetQueryError) as sort_error:
        service.query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:poi",
            sort={"field": "not_a_real_field", "direction": "desc"},
        )
    assert sort_error.value.code == "scope_dataset_field_unsupported"


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
                        "geometry_coord_type": "wgs84",
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


def test_scope_service_rejects_spatial_query_when_artifact_coord_type_is_missing():
    class MissingCoordTypeRepository:
        def list_poi_results(self, history_id):
            return []

        def list_analysis_artifacts(self, history_id):
            return [
                {
                    "id": 43,
                    "artifact_type": "population",
                    "params": {"year": 2024},
                    "payload": {
                        "grid": {
                            "features": [
                                {
                                    "type": "Feature",
                                    "properties": {"cell_id": "population-cell-1"},
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
                                    },
                                }
                            ]
                        }
                    },
                    "data_version": "v1",
                    "scope_fingerprint": "scope-a",
                }
            ]

    service = ScopeDatasetService(repository=MissingCoordTypeRepository())
    manifest = service.list_scope_datasets("history-1")["datasets"][0]
    assert manifest["query_capabilities"]["spatial_ready"] is False
    assert "空间查询不可用" in manifest["warnings"][0]
    assert service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:population",
    )["total_count"] == 1

    with pytest.raises(SpatialQueryError) as error:
        service.query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:population",
            spatial={"relation": "at_point", "point": [0.005, 0.005], "coord_type": "wgs84"},
        )
    assert error.value.code == "spatial_coord_type_unknown"


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


class _SpatialAggregateRepository:
    @staticmethod
    def _cell(cell_id, west, east, value_field, value):
        return {
            "type": "Feature",
            "properties": {"cell_id": cell_id, value_field: value},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[west, 0], [east, 0], [east, 0.01], [west, 0.01], [west, 0]]],
            },
        }

    def list_poi_results(self, history_id):
        return []

    def list_analysis_artifacts(self, history_id):
        return [
            {
                "id": 51,
                "artifact_type": "population",
                "params": {"year": 2024},
                "payload": {
                    "geometry_coord_type": "wgs84",
                    "year": 2024,
                    "grid": {
                        "features": [
                            self._cell("population-a", 0, 0.01, "population", 100),
                            self._cell("population-b", 0.01, 0.02, "population", 200),
                        ]
                    },
                },
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 52,
                "artifact_type": "nightlight",
                "params": {"year": 2024},
                "payload": {
                    "geometry_coord_type": "wgs84",
                    "year": 2024,
                    "grid": {
                        "features": [
                            self._cell("nightlight-a", 0, 0.01, "radiance", 10),
                            self._cell("nightlight-b", 0.01, 0.02, "radiance", 30),
                        ]
                    },
                },
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 53,
                "artifact_type": "road_syntax",
                "params": {"metric": "choice"},
                "payload": {
                    "geometry_coord_type": "wgs84",
                    "road_edges": {
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"edge_id": "road-1", "choice_score": 0.8},
                                "geometry": {"type": "LineString", "coordinates": [[0, 0.005], [0.02, 0.005]]},
                            }
                        ]
                    },
                },
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
        ]


def _aggregate_polygon():
    return {
        "relation": "intersects",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0.005, 0], [0.015, 0], [0.015, 0.01], [0.005, 0.01], [0.005, 0]]],
        },
        "coord_type": "wgs84",
    }


def test_spatial_aggregate_uses_overlap_weights_and_clipped_road_length():
    service = ScopeDatasetService(repository=_SpatialAggregateRepository())

    population = service.aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:population",
        metrics=[{"op": "area_weighted_sum", "field": "population", "as": "estimated_population"}],
        spatial=_aggregate_polygon(),
    )
    nightlight = service.aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:nightlight",
        metrics=[{"op": "area_weighted_avg", "field": "radiance", "as": "mean_radiance"}],
        spatial=_aggregate_polygon(),
    )
    roads = service.aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_edges",
        metrics=[{"op": "intersection_length_sum", "field": "intersection_length_m", "as": "road_length_m"}],
        spatial=_aggregate_polygon(),
    )

    assert 149.9 < population["rows"][0]["estimated_population"] < 150.1
    assert population["metric_methods"][0]["assumptions"] == ["uniform_distribution_within_cell"]
    assert population["spatial_summary"]["matched_record_count"] == 2
    assert population["evidence_node"]["kind"] == "spatial_metric"
    assert population["evidence_node"]["data"]["assumptions"] == ["uniform_distribution_within_cell"]
    assert 19.9 < nightlight["rows"][0]["mean_radiance"] < 20.1
    assert nightlight["metric_methods"][0]["method"] == "overlap_area_weighted_mean"
    assert 1_110 < roads["rows"][0]["road_length_m"] < 1_115
    assert roads["spatial_summary"]["intersection_length_m"] == roads["rows"][0]["road_length_m"]


def test_spatial_aggregate_rejects_unsafe_whole_cell_sum():
    with pytest.raises(ScopeDatasetQueryError) as error:
        ScopeDatasetService(repository=_SpatialAggregateRepository()).aggregate_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:population",
            metrics=[{"op": "area_weighted_sum", "field": "population"}],
        )
    assert error.value.code == "spatial_aggregate_invalid"

    with pytest.raises(ScopeDatasetQueryError) as unsafe_error:
        ScopeDatasetService(repository=_SpatialAggregateRepository()).aggregate_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:population",
            metrics=[{"op": "sum", "field": "population"}],
            spatial=_aggregate_polygon(),
        )
    assert unsafe_error.value.code == "spatial_aggregate_unsafe"


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


def test_scope_dataset_aggregate_tool_publishes_citable_spatial_evidence(monkeypatch):
    monkeypatch.setattr(
        scope_dataset_tools,
        "_service",
        lambda: ScopeDatasetService(repository=_SpatialAggregateRepository()),
    )
    result = asyncio.run(
        scope_dataset_tools.aggregate_scope_dataset(
            arguments={
                "source_id": "current:dataset:population",
                "metrics": [{"op": "area_weighted_sum", "field": "population", "as": "estimated_population"}],
                "spatial": _aggregate_polygon(),
            },
            snapshot=SimpleNamespace(context={"history_id": "history-1"}),
            artifacts={},
            question="这个范围内估算人口是多少",
        )
    )

    assert result.status == "success"
    assert result.result["rows"][0]["estimated_population"] > 0
    nodes = result.artifacts["scope_dataset_evidence_nodes"]
    assert nodes[0]["kind"] == "spatial_metric"
    assert nodes[0]["citation"]
