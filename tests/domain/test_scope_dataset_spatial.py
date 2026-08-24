import asyncio
import math
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, box

import modules.scope_datasets.spatial as spatial_module
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
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

    boundary = query_spatial_records(
        records,
        {"relation": "at_point", "point": [0.0, 0.005], "coord_type": "wgs84"},
    )
    assert list(boundary.matches) == [0]


def test_gcj02_query_is_normalized_against_wgs84_record_geometry():
    gcj_point = [112.98, 28.2]
    wgs_point = gcj02_to_wgs84(*gcj_point)

    result = query_spatial_records(
        [SimpleNamespace(geometry=Point(*wgs_point), record_id="aligned")],
        {"relation": "nearest", "point": gcj_point, "coord_type": "gcj02"},
    )

    assert result.matches[0].distance_m < 0.01
    assert result.matches[0].coord_type == "gcj02"


def test_intersects_supports_multi_polygon_and_multi_line_string():
    records = [
        SimpleNamespace(
            geometry=MultiPolygon([box(0, 0, 0.01, 0.01), box(0.02, 0, 0.03, 0.01)]),
            record_id="multi-polygon",
        ),
        SimpleNamespace(
            geometry=MultiLineString([
                [(0, 0.005), (0.03, 0.005)],
                [(0, 0.02), (0.03, 0.02)],
            ]),
            record_id="multi-line",
        ),
    ]
    query = {
        "relation": "intersects",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0.005, 0], [0.025, 0], [0.025, 0.01], [0.005, 0.01], [0.005, 0]]],
        },
        "coord_type": "wgs84",
    }

    result = query_spatial_records(records, query)

    assert set(result.matches) == {0, 1}
    assert result.matches[0].overlap_area_m2 > 0
    assert result.matches[1].intersection_length_m > 2_000


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


def _complete_poi(poi_id, name, category, typecode, location, subcategory="测试小类"):
    return {
        "poi_id": poi_id,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "typecode": typecode,
        "address": "",
        "location": location,
        "year": 2024,
        "source": "local",
    }


class _SpatialRepository:
    def list_poi_results(self, history_id):
        return [{"id": 1, "source": "local", "year": 2024, "summary": {"total": 2, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"}}]

    def get_poi_data(self, poi_result_id):
        return [
            _complete_poi("poi-near", "近点", "餐饮", "050100", [0.005, 0.0002], "中餐厅"),
            _complete_poi("poi-far", "远点", "餐饮", "050100", [0.005, 0.01], "中餐厅"),
        ]

    def list_analysis_artifacts(self, history_id):
        return []


class _SpatialCombinationRepository:
    def list_poi_results(self, history_id):
        return [{"id": 2, "source": "local", "year": 2024, "summary": {"total": 3, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"}}]

    def get_poi_data(self, poi_result_id):
        return [
            _complete_poi("food-near", "餐饮近点", "餐饮", "050100", [0.001, 0], "中餐厅"),
            _complete_poi("shop", "商店", "购物", "060200", [0.002, 0], "便利店"),
            _complete_poi("food-far", "餐饮远点", "餐饮", "050100", [0.003, 0], "中餐厅"),
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


def test_scope_service_combines_spatial_filter_attributes_and_pagination():
    result = ScopeDatasetService(repository=_SpatialCombinationRepository()).query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        spatial={
            "relation": "within_distance",
            "point": [0, 0],
            "coord_type": "wgs84",
            "max_distance_m": 500,
        },
        filters={"category": {"contains": "餐饮"}},
        limit=1,
        offset=1,
    )

    assert result["total_count"] == 2
    assert result["records"][0]["record_id"] == "food-far"
    assert result["has_more"] is False
    assert result["spatial_diagnostics"] == {
        "matched_record_count": 3,
        "skipped_record_count": 0,
        "result_complete": True,
    }
    assert result["warnings"] == []


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
                        "schema_version": "spatial_records/v1",
                        "geometry_coord_type": "wgs84",
                        "nodes": {"type": "FeatureCollection", "features": []},
                        "road_edges": {"type": "FeatureCollection", "features": []},
                        "road_corridors": {"type": "FeatureCollection", "features": []},
                        "road_grid": {
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "properties": {
                                        "cell_id": "road-cell-1", "road_has_data": True,
                                        "road_length_km": 1.0, "road_length_km_per_km2": 4.0,
                                        "road_nain": 0.7, "road_nach": 0.8, "road_connectivity": 2.0,
                                        "road_connectivity_score": 0.6,
                                        "road_choice": 0.8,
                                    },
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


def test_scope_service_rejects_legacy_artifact_without_new_contract():
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
                                        "coordinates": [[
                                            [112.9813, 28.2158],
                                            [112.9913, 28.2158],
                                            [112.9913, 28.2258],
                                            [112.9813, 28.2258],
                                            [112.9813, 28.2158],
                                        ]],
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
    with pytest.raises(ScopeDatasetQueryError) as error:
        service.list_scope_datasets("history-1")
    assert error.value.code == "schema_version_unsupported"


def test_scope_service_rejects_versioned_artifact_with_missing_required_fields():
    class IncompletePopulationRepository:
        def list_poi_results(self, history_id):
            return []

        def list_analysis_artifacts(self, history_id):
            return [{
                "id": 44,
                "artifact_type": "population",
                "params": {"year": 2024},
                "payload": {
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "records": [{
                        "cell_id": "population-cell-1",
                        "year": 2024,
                        "population_total": 100,
                        "male_total": 48,
                        "female_total": 52,
                        "source": "test",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                        },
                    }],
                },
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            }]

    with pytest.raises(ScopeDatasetQueryError) as error:
        ScopeDatasetService(repository=IncompletePopulationRepository()).list_scope_datasets("history-1")

    assert error.value.code == "schema_version_unsupported"


def test_scope_service_still_rejects_unknown_artifact_coord_type():
    with pytest.raises(SpatialQueryError) as error:
        ScopeDatasetService._artifact_coord_type(
            "current:dataset:population",
            {"artifact_type": "unknown_grid", "payload": {}},
            required=True,
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
        def record(cell_id, west, east, **properties):
            return {
                "cell_id": cell_id,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[west, 0], [east, 0], [east, 0.01], [west, 0.01], [west, 0]]],
                },
                "year": 2024,
                "source": "test",
                **properties,
            }

        return [
            {
                "id": 51,
                "artifact_type": "population",
                "params": {"year": 2024},
                "payload": {
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "year": 2024,
                    "records": [
                        record(
                            "population-a", 0, 0.01, population_total=100,
                            male_total=48, female_total=52, age_total={"05": 10},
                            age_male={"05": 4}, age_female={"05": 6},
                        ),
                        record(
                            "population-b", 0.01, 0.02, population_total=200,
                            male_total=96, female_total=104, age_total={"05": 20},
                            age_male={"05": 8}, age_female={"05": 12},
                        ),
                    ],
                },
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 52,
                "artifact_type": "nightlight",
                "params": {"year": 2024},
                "payload": {
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "year": 2024,
                    "records": [
                        record("nightlight-a", 0, 0.01, radiance=10, unit="nW/(cm2 sr)", has_data=True),
                        record("nightlight-b", 0.01, 0.02, radiance=30, unit="nW/(cm2 sr)", has_data=True),
                    ],
                },
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            },
            {
                "id": 53,
                "artifact_type": "road_syntax",
                "params": {"metric": "choice"},
                "payload": {
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "nodes": {"type": "FeatureCollection", "features": [
                        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0.005]}, "properties": {"node_id": "node:1", "degree": 1}},
                        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.02, 0.005]}, "properties": {"node_id": "node:2", "degree": 1}},
                    ]},
                    "road_edges": {
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {
                                    "edge_id": "road-1", "from_node": "node:1", "to_node": "node:2",
                                    "road_name": "测试路", "road_class": "residential", "length_m": 2220,
                                    "connectivity_score": 0.0,
                                    "metrics": {"integration": 0.7, "choice": 0.8, "connectivity": 1, "depth": 2, "control": 0.5},
                                    "nain_global": 0.7, "nach_global": 0.8,
                                    "node_count_global": 2, "total_depth_global": 2,
                                },
                                "geometry": {"type": "LineString", "coordinates": [[0, 0.005], [0.02, 0.005]]},
                            }
                        ]
                    },
                    "road_corridors": {"type": "FeatureCollection", "features": []},
                    "road_grid": {"type": "FeatureCollection", "features": []},
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
        metrics=[{"op": "area_weighted_sum", "field": "population_total", "as": "estimated_population"}],
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
    assert population["spatial_summary"]["input_record_ids"] == ["population-a", "population-b"]
    assert population["spatial_summary"]["coverage_ratio"] == 1.0
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
            metrics=[{"op": "area_weighted_sum", "field": "population_total"}],
        )
    assert error.value.code == "spatial_aggregate_invalid"

    with pytest.raises(ScopeDatasetQueryError) as unsafe_error:
        ScopeDatasetService(repository=_SpatialAggregateRepository()).aggregate_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:population",
            metrics=[{"op": "sum", "field": "population_total"}],
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
                "metrics": [{"op": "area_weighted_sum", "field": "population_total", "as": "estimated_population"}],
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
