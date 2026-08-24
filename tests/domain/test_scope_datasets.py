from types import SimpleNamespace

import pytest

import modules.scope_datasets.service as scope_service
from modules.scope_datasets import ScopeDatasetQueryError, ScopeDatasetService


def _complete_poi(
    poi_id,
    name,
    category,
    subcategory,
    typecode,
    location,
    *,
    year=2024,
    source="local",
    address="",
):
    return {
        "poi_id": poi_id,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "typecode": typecode,
        "address": address,
        "location": location,
        "year": year,
        "source": source,
    }


class FakeScopeDatasetRepository:
    def list_poi_results(self, history_id):
        assert history_id == "history-1"
        return [
            {
                "id": 1,
                "source": "local",
                "year": 2024,
                "summary": {"total": 2, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"},
            }
        ]

    def get_poi_data(self, poi_result_id):
        assert poi_result_id == 1
        return [
            _complete_poi("poi-1", "咖啡 A", "餐饮", "咖啡厅", "050500", [120, 30], address="A 路"),
            _complete_poi("poi-2", "便利 B", "购物", "便利店", "060200", [120.01, 30], address="B 路"),
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
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "year": 2024,
                    "records": [
                        {
                            "cell_id": "cell-1", "year": 2024, "population_total": 120,
                            "male_total": 58, "female_total": 62,
                            "age_total": {"05": 20, "30": 30, "50": 25},
                            "age_male": {"05": 9, "30": 14, "50": 12},
                            "age_female": {"05": 11, "30": 16, "50": 13}, "source": "worldpop",
                            "geometry": {"type": "Polygon", "coordinates": [[[120, 30], [120.01, 30], [120.01, 30.01], [120, 30.01], [120, 30]]]},
                        },
                        {
                            "cell_id": "cell-2", "year": 2024, "population_total": 80,
                            "male_total": 39, "female_total": 41,
                            "age_total": {"05": 10, "30": 20, "50": 15},
                            "age_male": {"05": 5, "30": 9, "50": 7},
                            "age_female": {"05": 5, "30": 11, "50": 8}, "source": "worldpop",
                            "geometry": {"type": "Polygon", "coordinates": [[[120.01, 30], [120.02, 30], [120.02, 30.01], [120.01, 30.01], [120.01, 30]]]},
                        },
                    ],
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
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "nodes": {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120, 30]}, "properties": {"node_id": "n1", "degree": 2}},
                            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.01, 30]}, "properties": {"node_id": "n2", "degree": 3}},
                            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.02, 30]}, "properties": {"node_id": "n3", "degree": 1}},
                        ],
                    },
                    "road_edges": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "LineString", "coordinates": [[120, 30], [120.01, 30]]},
                                "properties": {
                                    "edge_id": "r1",
                                    "road_name": "测试路",
                                    "road_class": "residential",
                                    "from_node": "n1", "to_node": "n2", "length_m": 1000,
                                    "connectivity_score": 0.0,
                                    "metrics": {"integration": 0.6, "choice": 0.7, "connectivity": 0.8, "depth": 2, "control": 0.4},
                                    "integration_global": 0.9, "choice_global": 0.8,
                                    "nain_global": 0.9, "nach_global": 0.8,
                                    "node_count_global": 12, "total_depth_global": 24,
                                    "integration_r600": 0.6, "choice_r600": 0.7,
                                    "integration_r800": 0.75, "choice_r800": 0.72,
                                },
                            },
                            {
                                "type": "Feature",
                                "geometry": {"type": "LineString", "coordinates": [[120.01, 30], [120.02, 30]]},
                                "properties": {
                                    "edge_id": "r2", "road_name": "支路", "road_class": "service",
                                    "from_node": "n2", "to_node": "n3", "length_m": 900,
                                    "connectivity_score": 1.0,
                                    "metrics": {"integration": 0.3, "choice": 0.2, "connectivity": 1, "depth": 3},
                                    "nain_global": 0.3, "nach_global": 0.2,
                                    "node_count_global": 8, "total_depth_global": 18,
                                },
                            },
                        ],
                    },
                    "road_corridors": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "MultiLineString", "coordinates": [[[120, 30], [120.01, 30]], [[120.01, 30], [120.02, 30]]]},
                                "properties": {
                                    "corridor_id": "corridor:main",
                                    "metric": "nain",
                                    "metric_field": "nain_global",
                                    "radius": "global",
                                    "threshold": 0.7,
                                    "mean_value": 0.8,
                                    "max_value": 0.9,
                                    "edge_count": 2,
                                    "length_m": 1900,
                                    "road_names": ["测试路", "支路"],
                                    "member_edge_ids": ["r1", "r2"],
                                    "nain_global": 0.8,
                                },
                            }
                        ],
                    },
                    "road_grid": {"type": "FeatureCollection", "features": [], "count": 0},
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
    assert sources["current:dataset:road_nodes"]["record_count"] == 3
    assert sources["current:dataset:road_corridors"]["record_count"] == 1
    assert sources["current:dataset:road_grid"]["record_count"] == 0
    assert sources["current:dataset:population"]["time_scope"]["years"] == [2024]
    assert sources["current:dataset:h3"]["grid_type"] == "h3"
    assert sources["current:dataset:poi_grid"]["grid_type"] == "regular_raster"
    assert "at_point" in sources["current:dataset:population"]["query_capabilities"]["spatial_relations"]
    assert sources["current:dataset:population"]["query_capabilities"]["spatial_ready"] is True
    assert sources["current:dataset:population"]["query_capabilities"]["spatial_aggregations"][0]["op"] == "area_weighted_sum"
    road_fields = sources["current:dataset:road_edges"]["query_capabilities"]["filter_fields"]
    assert road_fields == ["connectivity_score", "edge_id", "from_node", "length_m", "metrics", "record_id", "road_class", "road_name", "to_node"]


def test_scope_dataset_service_reads_persisted_road_corridor_records():
    result = ScopeDatasetService(repository=FakeScopeDatasetRepository()).query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_corridors",
        limit=10,
    )

    assert result["total_count"] == 1
    corridor = result["records"][0]
    assert corridor["record_id"] == "corridor:main"
    assert corridor["properties"]["member_edge_ids"] == ["r1", "r2"]
    assert corridor["properties"]["nain_global"] == 0.8


def test_scope_dataset_service_queries_road_name_and_classification():
    service = ScopeDatasetService(repository=FakeScopeDatasetRepository())

    queried = service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_edges",
        filters={"road_name": {"eq": "测试路"}, "road_class": {"eq": "residential"}},
        limit=10,
    )

    assert queried["total_count"] == 1
    assert queried["records"][0]["properties"]["road_name"] == "测试路"
    assert queried["records"][0]["properties"]["road_class"] == "residential"
    properties = queried["records"][0]["properties"]
    assert properties["integration_global"] == 0.9
    assert properties["choice_global"] == 0.8
    assert properties["integration_r600"] == 0.6
    assert properties["choice_r800"] == 0.72


def test_scope_dataset_aggregates_by_road_class_and_name():
    result = ScopeDatasetService(repository=FakeScopeDatasetRepository()).aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_edges",
        group_by=["road_class", "road_name"],
        metrics=[
            {"op": "count", "field": "*", "as": "road_count"},
            {"op": "sum", "field": "length_m", "as": "length_m"},
        ],
        top_k=None,
    )

    assert result["group_by"] == ["road_class", "road_name"]
    assert result["rows"] == [
        {
            "group": {"road_class": "residential", "road_name": "测试路"},
            "count": 1,
            "road_count": 1,
            "length_m": 1000.0,
        },
        {
            "group": {"road_class": "service", "road_name": "支路"},
            "count": 1,
            "road_count": 1,
            "length_m": 900.0,
        },
    ]


def test_scope_dataset_service_queries_and_reads_evidence_nodes():
    service = ScopeDatasetService(repository=FakeScopeDatasetRepository())

    queried = service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:population",
        filters={"population_total": {"gte": 100}},
        sort={"field": "population_total", "direction": "desc"},
        limit=10,
    )
    assert queried["total_count"] == 1
    assert queried["records"][0]["record_id"] == "cell-1"
    assert queried["records"][0]["geometry"]["type"] == "Polygon"
    assert queried["records"][0]["geometry_coord_type"] == "wgs84"
    assert queried["evidence_nodes"][0]["source_ids"] == ["current:dataset:population"]
    assert queried["evidence_nodes"][0]["time_scope"]["year"] == 2024
    assert "confidence" not in queried["evidence_nodes"][0]["time_scope"]
    assert "confidence_basis" not in queried["evidence_nodes"][0]["time_scope"]

    read = service.read_scope_record(history_id="history-1", source_id="current:dataset:population", record_id="cell-1")
    assert read["evidence_node"]["id"] == "current:dataset:population:record:cell-1"
    assert "当前范围人口网格" in read["evidence_node"]["citation"]

    poi = service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        filters={"poi_id": "poi-1"},
    )["records"][0]
    assert set(poi["properties"]) == {
        "record_id", "poi_id", "name", "category", "subcategory", "typecode",
        "address", "location", "year", "source",
    }
    assert poi["geometry"]["type"] == "Point"


def test_scope_dataset_normalizes_nightlight_record_contract():
    class NightlightRepository:
        def list_poi_results(self, history_id):
            return []

        def get_poi_data(self, poi_result_id):
            return []

        def list_analysis_artifacts(self, history_id):
            return [{
                "id": 1,
                "artifact_type": "nightlight",
                "slot_key": "year:2024",
                "params": {"year": 2024},
                "payload": {
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                    "year": 2024,
                    "records": [{
                        "cell_id": "night-1", "year": 2024, "radiance": 6.2,
                        "unit": "nW/cm2/sr", "has_data": True, "source": "viirs",
                        "geometry": {"type": "Polygon", "coordinates": [[[120, 30], [120.01, 30], [120.01, 30.01], [120, 30.01], [120, 30]]]},
                        "producer_detail": "retained in raw",
                    }],
                },
                "summary": {},
                "data_version": "v1",
                "scope_fingerprint": "scope-a",
            }]

    service = ScopeDatasetService(repository=NightlightRepository())
    records, _, _ = service.load_scope_records(
        history_id="history-1",
        source_id="current:dataset:nightlight",
    )

    assert records[0].properties == {
        "record_id": "night-1", "cell_id": "night-1", "year": 2024,
        "radiance": 6.2, "unit": "nW/cm2/sr", "has_data": True, "source": "viirs",
    }
    assert records[0].raw["producer_detail"] == "retained in raw"


def test_scope_dataset_service_aggregates_poi_and_sorts_road_records():
    service = ScopeDatasetService(repository=FakeScopeDatasetRepository())

    aggregate = service.aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        group_by="category",
        metrics=[{"op": "count", "field": "*", "as": "count"}],
    )
    assert {row["group"]["category"]: row["count"] for row in aggregate["rows"]} == {"餐饮": 1, "购物": 1}

    road = service.query_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:road_edges",
        sort={"field": "length_m", "direction": "desc"},
    )
    assert [item["record_id"] for item in road["records"]] == ["road_edge:r1", "road_edge:r2"]
    assert road["selected_year"] is None
    assert road["records"][0]["time_scope"]["kind"] == "static_snapshot"
    assert road["warnings"] == []


def test_scope_dataset_normalizes_complete_road_nodes_and_serializes_checksum():
    service = ScopeDatasetService(repository=FakeScopeDatasetRepository())

    records, years, selected_year = service.load_scope_records(
        history_id="history-1",
        source_id="current:dataset:road_nodes",
    )
    serialized = service.serialize_scope_records(reversed(records))

    assert years == []
    assert selected_year is None
    assert [record.properties for record in records] == [
        {"record_id": "road_node:n1", "node_id": "n1", "location": [120.0, 30.0], "degree": 2},
        {"record_id": "road_node:n2", "node_id": "n2", "location": [120.01, 30.0], "degree": 3},
        {"record_id": "road_node:n3", "node_id": "n3", "location": [120.02, 30.0], "degree": 1},
    ]
    assert serialized["record_count"] == 3
    assert serialized["checksum"].startswith("sha256:")
    assert serialized == service.serialize_scope_records(records)
    assert serialized["records"][0]["geometry"]["type"] == "Point"


def test_scope_dataset_uses_all_road_nodes_and_edges_instead_of_top_nodes():
    class CompleteRoadRepository:
        def list_poi_results(self, history_id):
            return []

        def get_poi_data(self, poi_result_id):
            return []

        def list_analysis_artifacts(self, history_id):
            nodes = [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120 + index / 10000, 30]}, "properties": {"node_id": f"n{index}", "degree": index % 5}}
                for index in range(130)
            ]
            edges = [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[120 + index / 10000, 30], [120 + (index + 1) / 10000, 30]]},
                    "properties": {
                        "edge_id": f"e{index}", "road_name": "", "road_class": "local",
                        "from_node": f"n{index}", "to_node": f"n{index + 1}", "length_m": 10,
                        "connectivity_score": 0.0,
                        "metrics": {"integration": 0.0, "choice": 0.0, "connectivity": 2, "depth": 0.0},
                        "nain_global": 0.0, "nach_global": 0.0,
                        "node_count_global": 2, "total_depth_global": 1,
                    },
                }
                for index in range(129)
            ]
            return [{
                "id": 1, "artifact_type": "road_syntax", "params": {},
                "payload": {
                    "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84",
                    "top_nodes": nodes[:10],
                    "nodes": {"type": "FeatureCollection", "features": nodes},
                    "road_edges": {"type": "FeatureCollection", "features": edges},
                    "road_corridors": {"type": "FeatureCollection", "features": []},
                    "road_grid": {"type": "FeatureCollection", "features": []},
                },
                "summary": {}, "data_version": "v1", "scope_fingerprint": "scope-a",
            }]

    service = ScopeDatasetService(repository=CompleteRoadRepository())

    nodes = service.query_scope_dataset(history_id="history-1", source_id="current:dataset:road_nodes", limit=500)
    edges = service.query_scope_dataset(history_id="history-1", source_id="current:dataset:road_edges", limit=500)

    assert nodes["total_count"] == 130
    assert len(nodes["records"]) == 130
    assert edges["total_count"] == 129
    assert len(edges["records"]) == 129


@pytest.mark.parametrize("missing_part", ["nain_global", "road_corridors", "road_grid"])
def test_scope_dataset_rejects_incomplete_new_road_contract(missing_part):
    class IncompleteRoadRepository(FakeScopeDatasetRepository):
        def list_analysis_artifacts(self, history_id):
            artifacts = super().list_analysis_artifacts(history_id)
            road = next(item for item in artifacts if item.get("artifact_type") == "road_syntax")
            if missing_part in {"road_corridors", "road_grid"}:
                road["payload"].pop(missing_part)
            else:
                road["payload"]["road_edges"]["features"][0]["properties"].pop(missing_part)
            return [road]

    with pytest.raises(ScopeDatasetQueryError) as exc_info:
        ScopeDatasetService(repository=IncompleteRoadRepository()).query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:road_edges",
        )

    assert exc_info.value.code == "schema_version_unsupported"


def test_scope_dataset_rejects_legacy_spatial_artifact_schema():
    class LegacyRepository(FakeScopeDatasetRepository):
        def list_analysis_artifacts(self, history_id):
            artifact = super().list_analysis_artifacts(history_id)[2]
            artifact["payload"].pop("schema_version")
            return [artifact]

    with pytest.raises(ScopeDatasetQueryError) as exc_info:
        ScopeDatasetService(repository=LegacyRepository()).query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:population",
        )

    assert exc_info.value.code == "schema_version_unsupported"


def test_scope_dataset_rejects_poi_rows_without_wgs84_schema_marker():
    class LegacyPoiRepository:
        def list_poi_results(self, history_id):
            return [{"id": 1, "source": "local", "year": 2024, "summary": {"total": 1}}]

        def get_poi_data(self, poi_result_id):
            return [{"id": "legacy", "location": "120,30"}]

        def list_analysis_artifacts(self, history_id):
            return []

    with pytest.raises(ScopeDatasetQueryError) as exc_info:
        ScopeDatasetService(repository=LegacyPoiRepository()).query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:poi",
        )

    assert exc_info.value.code == "schema_version_unsupported"


def test_scope_dataset_rejects_incomplete_poi_records_with_new_schema_marker():
    class FalselyStampedPoiRepository:
        def list_poi_results(self, history_id):
            return [{
                "id": 1,
                "source": "local",
                "year": 2024,
                "summary": {
                    "total": 1,
                    "schema_version": "spatial_records/v1",
                    "geometry_coord_type": "wgs84",
                },
            }]

        def get_poi_data(self, poi_result_id):
            return [{
                "poi_id": "legacy",
                "name": "旧记录",
                "category": "050100",
                "subcategory": "",
                "typecode": "",
                "address": "",
                "location": [120, 30],
                "year": 2024,
                "source": "local",
            }]

        def list_analysis_artifacts(self, history_id):
            return []

    with pytest.raises(ScopeDatasetQueryError) as exc_info:
        ScopeDatasetService(repository=FalselyStampedPoiRepository()).query_scope_dataset(
            history_id="history-1",
            source_id="current:dataset:poi",
        )

    assert exc_info.value.code == "schema_version_unsupported"


def test_scope_dataset_supports_500_records_and_unlimited_group_output():
    class ManyPoiRepository:
        def list_poi_results(self, history_id):
            return [{"id": 1, "source": "local", "year": 2024, "summary": {"total": 550, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"}}]

        def get_poi_data(self, poi_result_id):
            return [
                _complete_poi(
                    f"poi-{index}", f"POI {index}", f"category-{index}", f"subcategory-{index}",
                    f"{index % 1_000_000:06d}", [120 + index / 100_000, 30],
                )
                for index in range(550)
            ]

        def list_analysis_artifacts(self, history_id):
            return []

    service = ScopeDatasetService(repository=ManyPoiRepository())
    queried = service.query_scope_dataset(history_id="history-1", source_id="current:dataset:poi", limit=999)
    aggregate = service.aggregate_scope_dataset(
        history_id="history-1",
        source_id="current:dataset:poi",
        group_by="category",
        top_k=None,
    )

    assert queried["limit"] == 500
    assert len(queried["records"]) == 500
    assert queried["has_more"] is True
    assert aggregate["total_groups"] == 550
    assert len(aggregate["rows"]) == 550


def test_scope_dataset_defaults_to_max_year_and_exactly_matches_requested_year():
    class MultiYearRepository:
        def list_poi_results(self, history_id):
            return [
                {"id": 20, "source": "local", "year": 2020, "summary": {"total": 1, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"}},
                {"id": 24, "source": "local", "year": 2024, "summary": {"total": 2, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"}},
            ]

        def get_poi_data(self, poi_result_id):
            year = 2024 if poi_result_id == 24 else 2020
            return [
                _complete_poi(
                    f"poi-{poi_result_id}-{index}", f"POI {index}", "餐饮", "中餐厅", "050100",
                    [120 + index / 1000, 30], year=year,
                )
                for index in range(2 if poi_result_id == 24 else 1)
            ]

        def list_analysis_artifacts(self, history_id):
            def artifact(artifact_id, artifact_type, year, updated_at, count, summary=None):
                if artifact_type == "population":
                    payload = {
                        "schema_version": "spatial_records/v1",
                        "geometry_coord_type": "wgs84",
                        "year": year,
                        "records": [
                            {
                                "cell_id": f"{artifact_type}-{year}-{index}",
                                "year": year,
                                "population_total": index,
                                "male_total": 0, "female_total": index,
                                "age_total": {}, "age_male": {}, "age_female": {}, "source": "test",
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": [[
                                            [120 + index / 1000, 30],
                                            [120.0005 + index / 1000, 30],
                                            [120.0005 + index / 1000, 30.0005],
                                            [120 + index / 1000, 30.0005],
                                            [120 + index / 1000, 30],
                                        ]],
                                    },
                            }
                            for index in range(count)
                        ],
                    }
                else:
                    payload = {
                        "year": year,
                        "grid": {
                            "features": [
                                {"type": "Feature", "properties": {"cell_id": f"{artifact_type}-{year}-{index}", "value": index}}
                                for index in range(count)
                            ]
                        },
                    }
                return {
                    "id": artifact_id,
                    "artifact_type": artifact_type,
                    "slot_key": f"year:{year}",
                    "params": {"year": year, "view": "density"},
                    "payload": payload,
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
            return [{"id": 24, "source": "local", "year": 2024, "summary": {"total": 2, "schema_version": "spatial_records/v1", "geometry_coord_type": "wgs84"}}]

        def get_poi_data(self, poi_result_id):
            return [
                _complete_poi("poi-1", "POI 1", "餐饮", "中餐厅", "050100", [120, 30]),
                _complete_poi("poi-2", "POI 2", "购物", "便利店", "060200", [120.01, 30]),
            ]

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
