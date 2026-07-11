from modules.agent.schemas import AnalysisSnapshot
from modules.agent.stage1_spatial_objects import (
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
