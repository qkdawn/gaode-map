from __future__ import annotations

from types import SimpleNamespace
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from modules.spatial_action.project_context import ProjectSpatialAnalysisService
from modules.spatial_cells.service import build_directional_evidence_matrix


def _feature(cell_id: str, lon: float, lat: float, **properties: object) -> dict:
    gcj_lon, gcj_lat = wgs84_to_gcj02(lon, lat)
    return {
        "properties": {
            "cell_id": cell_id,
            "centroid_gcj02": [gcj_lon, gcj_lat],
            "area_km2": 0.01,
            "poi_count": 10,
            "category_counts": {"050000": 6, "060000": 4},
            "population_density": 10000,
            "nightlight_radiance": 50,
            "road_has_data": True,
            "road_length_km_per_km2": 20,
            "road_integration": 0.6,
            "road_connectivity": 0.5,
            **properties,
        }
    }


def _shared_grid(features: list[dict]) -> dict:
    return {
        "join_key": "cell_id",
        "grid": {"features": features},
        "summary": {"assigned_poi_count": 20},
        "source_readiness": {"poi": {"record_count": 21}},
        "source_versions": {
            "poi": {"year": 2024},
            "population": {"year": "2026"},
            "nightlight": {"year": 2025},
            "road": {"year": None},
        },
    }


def test_directional_matrix_aligns_shared_cells_and_keeps_road_coverage_distinct():
    matrix = build_directional_evidence_matrix(
        _shared_grid([
            _feature("north", 112.98077, 28.22867, road_integration=0.9),
            _feature("east", 112.98586, 28.22417, road_has_data=False, road_length_km_per_km2=0, road_integration=None, road_connectivity=None),
        ]),
        center_wgs84=[112.98077, 28.22417],
        distance_bands_m=[[0, 1000]],
    )

    north = next(row for row in matrix["rows"] if row["sector"] == "N")
    east = next(row for row in matrix["rows"] if row["sector"] == "E")
    assert north["cell_count"] == 1
    assert north["road_coverage_ratio"] == 1.0
    assert north["road_integration_covered_mean"] == 0.9
    assert east["cell_count"] == 1
    assert east["road_coverage_ratio"] == 0.0
    assert east["road_integration_covered_mean"] is None
    assert matrix["observation_universe"]["unassigned_record_count"] == 1


def test_directional_matrix_rejects_missing_center_and_non_contiguous_bands():
    shared = _shared_grid([_feature("north", 112.98077, 28.22867)])

    try:
        build_directional_evidence_matrix(shared, center_wgs84=[])
    except ValueError as exc:
        assert str(exc) == "directional_matrix_center_required"
    else:
        raise AssertionError("expected missing center to fail")

    try:
        build_directional_evidence_matrix(shared, center_wgs84=[112.98077, 28.22417], distance_bands_m=[[500, 1000], [0, 500]])
    except ValueError as exc:
        assert str(exc) == "directional_matrix_invalid_distance_bands"
    else:
        raise AssertionError("expected unordered bands to fail")


def test_metric_service_executes_the_composite_directional_matrix(monkeypatch):
    shared = _shared_grid([_feature("north", 112.98077, 28.22867)])
    service = ProjectSpatialAnalysisService()
    monkeypatch.setattr(
        "modules.spatial_action.project_context.build_shared_grid_analysis",
        lambda **_kwargs: shared,
    )
    monkeypatch.setattr(
        "modules.spatial_action.project_context.build_nightlight_meta_payload",
        lambda: {"default_year": 2025},
    )
    monkeypatch.setattr(
        service,
        "_load_snapshot",
        lambda _history_id: (
            {"datasets": []},
            {
                "current:dataset:poi": [SimpleNamespace(raw={})],
                "current:dataset:road_edges": [SimpleNamespace(raw={})],
            },
            {"current:dataset:poi": 2024},
        ),
    )
    monkeypatch.setattr(service, "data_health", lambda **_kwargs: [])

    result = service.execute_metric_tool(
        tool_id="regional.directional_evidence_matrix",
        primary_spatial_unit="shared_grid_direction_distance_band",
        history_id="test",
        history_detail={"polygon": [[112.97, 28.21], [112.99, 28.21], [112.99, 28.23], [112.97, 28.21]], "params": {"coord_type": "wgs84"}},
        project_documents={},
        parameters={"center": [112.98077, 28.22417]},
    )

    assert result.status == "available"
    assert result.structured_result["directional_evidence_matrix"]["rows"]
