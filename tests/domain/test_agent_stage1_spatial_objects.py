from modules.agent.schemas import AnalysisSnapshot
from modules.agent.stage1_spatial_objects import (
    assess_spatial_object_registry,
    bind_spatial_matrix_to_objects,
    build_spatial_object_registry,
    spatial_object_catalog,
)


def test_spatial_object_registry_rejects_unstable_or_invalid_geometry():
    snapshot = AnalysisSnapshot(
        spatial_objects=[
            {
                "spatial_object_id": "road:1",
                "object_type": "road_segment",
                "title": "南侧道路",
                "source_ref": "analysis_snapshot.road.features",
                "source_locator": "analysis_snapshot.road.features/1",
                "feature": {
                    "type": "Feature",
                    "properties": {"road_id": "1"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[112.0, 28.0], [112.1, 28.1]],
                    },
                },
            },
            {
                "spatial_object_id": "road:bad",
                "object_type": "road_segment",
                "source_ref": "analysis_snapshot.road.features",
                "source_locator": "analysis_snapshot.road.features/bad",
                "feature": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": []}},
            },
            {
                "spatial_object_id": "road:single-point",
                "object_type": "road_segment",
                "source_ref": "analysis_snapshot.road.features",
                "source_locator": "analysis_snapshot.road.features/single-point",
                "feature": {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[112.0, 28.0]]},
                },
            },
            {
                "spatial_object_id": "building:open-ring",
                "object_type": "building",
                "source_ref": "project_gis.buildings",
                "source_locator": "project_gis.buildings/open-ring",
                "feature": {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.1]]],
                    },
                },
            },
            {
                "spatial_object_id": "",
                "object_type": "building",
                "source_ref": "project_gis.buildings",
                "source_locator": "project_gis.buildings/missing",
                "feature": {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [112.0, 28.0]},
                },
            },
        ]
    )

    registry = build_spatial_object_registry(snapshot)

    assert list(registry) == ["road:1"]
    assert spatial_object_catalog(registry) == [
        {
            "spatial_object_id": "road:1",
            "object_type": "road_segment",
            "title": "南侧道路",
            "source_ref": "analysis_snapshot.road.features",
            "source_locator": "analysis_snapshot.road.features/1",
        }
    ]


def test_spatial_object_assessment_marks_complete_catalog_ready_without_geometry_leak():
    snapshot = AnalysisSnapshot(
        spatial_objects=[
            {
                "spatial_object_id": "road:1",
                "object_type": "road_segment",
                "title": "南侧道路",
                "source_ref": "analysis_snapshot.road.features",
                "source_locator": "analysis_snapshot.road.features/1",
                "feature": {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[112.0, 28.0], [112.1, 28.1]],
                    },
                },
            },
            {
                "spatial_object_id": "building:hall",
                "object_type": "building",
                "title": "原县政府礼堂",
                "source_ref": "project_gis.buildings",
                "source_locator": "project_gis.buildings/hall",
                "feature": {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [112.0, 28.0],
                                [112.1, 28.0],
                                [112.1, 28.1],
                                [112.0, 28.0],
                            ]
                        ],
                    },
                },
            },
        ]
    )

    assessment = assess_spatial_object_registry(snapshot)

    assert assessment["status"] == "ready"
    assert assessment["input_count"] == 2
    assert assessment["accepted_count"] == 2
    assert assessment["rejected_count"] == 0
    assert assessment["object_type_counts"] == {"building": 1, "road_segment": 1}
    assert assessment["geometry_type_counts"] == {"LineString": 1, "Polygon": 1}
    assert assessment["binding_capabilities"] == {
        "space_decisions": True,
        "movement_routes": True,
    }
    assert all("feature" not in item for item in assessment["catalog"])
    assert all("coordinates" not in item for item in assessment["catalog"])


def test_spatial_object_assessment_reports_rejections_and_missing_route_capability():
    snapshot = AnalysisSnapshot(
        spatial_objects=[
            {
                "spatial_object_id": "building:hall",
                "object_type": "building",
                "source_ref": "project_gis.buildings",
                "source_locator": "project_gis.buildings/hall",
                "feature": {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [112.0, 28.0]},
                },
            },
            {
                "spatial_object_id": "building:hall",
                "object_type": "building",
                "source_ref": "project_gis.buildings",
                "source_locator": "project_gis.buildings/hall-duplicate",
                "feature": {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [112.1, 28.1]},
                },
            },
            {
                "spatial_object_id": "courtyard:1",
                "object_type": "courtyard",
                "source_ref": "",
                "source_locator": "project_gis.courtyards/1",
                "feature": {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [112.2, 28.2]},
                },
            },
            {
                "spatial_object_id": "open-space:1",
                "object_type": "open_space",
                "source_ref": "project_gis.open_spaces",
                "source_locator": "project_gis.open_spaces/1",
                "feature": {"type": "Feature", "geometry": {"type": "Point", "coordinates": []}},
            },
        ]
    )

    assessment = assess_spatial_object_registry(snapshot)

    assert assessment["status"] == "partial"
    assert assessment["accepted_count"] == 1
    assert assessment["rejected_count"] == 3
    assert assessment["binding_capabilities"] == {
        "space_decisions": True,
        "movement_routes": False,
    }
    assert [item["index"] for item in assessment["diagnostics"]] == [1, 2, 3]
    messages = [item["message"] for item in assessment["diagnostics"]]
    assert any("重复" in item for item in messages)
    assert any("缺少来源或来源定位" in item for item in messages)
    assert any("有效 GeoJSON 几何" in item for item in messages)
    assert "尚无可用于动线绑定的线要素" in assessment["availability_message"]


def test_spatial_matrix_binding_uses_authoritative_geometry_not_model_geometry():
    snapshot = AnalysisSnapshot(
        spatial_objects=[
            {
                "spatial_object_id": "road:1",
                "object_type": "road_segment",
                "title": "南侧道路",
                "source_ref": "analysis_snapshot.road.features",
                "source_locator": "analysis_snapshot.road.features/1",
                "feature": {
                    "type": "Feature",
                    "properties": {"road_id": "1"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[112.0, 28.0], [112.1, 28.1]],
                    },
                },
            }
        ]
    )
    registry = build_spatial_object_registry(snapshot)
    matrix = {
        "space_decisions": [
            {
                "space_id": "path-1",
                "map_binding": {
                    "status": "bound",
                    "spatial_object_id": "road:1",
                    "feature": {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                    },
                },
            }
        ]
    }

    result = bind_spatial_matrix_to_objects(matrix, registry)

    binding = result["space_decisions"][0]["map_binding"]
    assert binding["status"] == "bound"
    assert binding["feature"]["geometry"]["type"] == "LineString"
    assert binding["feature"]["geometry"]["coordinates"][0] == [112.0, 28.0]
    assert result["map_binding_summary"] == {
        "registry_count": 1,
        "decision_count": 1,
        "bound_count": 1,
        "unavailable_count": 0,
        "status": "complete",
    }
    assert matrix["space_decisions"][0]["map_binding"]["feature"]["geometry"]["type"] == "Point"


def test_spatial_matrix_binding_rejects_model_invented_object_id():
    result = bind_spatial_matrix_to_objects(
        {
            "space_decisions": [
                {
                    "space_id": "building-1",
                    "map_binding": {
                        "status": "bound",
                        "spatial_object_id": "building:invented",
                    },
                }
            ]
        },
        {},
    )

    binding = result["space_decisions"][0]["map_binding"]
    assert binding["status"] == "unavailable"
    assert binding["spatial_object_id"] == ""
    assert "权威对象清单" in binding["reason"]


def test_spatial_matrix_binding_requires_explicit_bound_status():
    snapshot = AnalysisSnapshot(
        spatial_objects=[
            {
                "spatial_object_id": "road:1",
                "object_type": "road_segment",
                "source_ref": "analysis_snapshot.road.features",
                "source_locator": "analysis_snapshot.road.features/1",
                "feature": {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[112.0, 28.0], [112.1, 28.1]],
                    },
                },
            }
        ]
    )
    registry = build_spatial_object_registry(snapshot)

    result = bind_spatial_matrix_to_objects(
        {
            "space_decisions": [
                {
                    "space_id": "road-space",
                    "map_binding": {
                        "status": "unavailable",
                        "spatial_object_id": "road:1",
                        "reason": "无法确认是同一空间",
                    },
                }
            ]
        },
        registry,
    )

    assert result["space_decisions"][0]["map_binding"] == {
        "status": "unavailable",
        "spatial_object_id": "",
        "reason": "无法确认是同一空间",
        "object_type": "",
        "title": "",
        "source_ref": "",
        "source_locator": "",
        "feature": None,
    }
