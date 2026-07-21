from modules.poi.schemas import PoiCategoryRequest
from modules.spatial_cells import service as spatial_cell_service


def _feature(cell_id, west, south, east, north):
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, north], [east, north], [east, south], [west, south], [west, north]]],
        },
        "properties": {
            "cell_id": cell_id,
            "h3_id": cell_id,
            "row": 0,
            "col": 0,
            "centroid_gcj02": [(west + east) / 2, (south + north) / 2],
        },
    }


def test_unified_spatial_cells_aggregates_poi_population_nightlight_and_road(monkeypatch):
    features = [_feature("c0", 0.0, 0.0, 1.0, 1.0), _feature("c1", 1.0, 0.0, 2.0, 1.0)]
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_grid",
        lambda *args, **kwargs: {"scope_id": "scope-1", "cell_count": len(features), "features": features},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "c0", "value": 1200}, {"cell_id": "c1", "value": 800}]},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_nightlight_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "c0", "value": 8.5}, {"cell_id": "c1", "value": 0.0}]},
    )

    payload = spatial_cell_service.build_unified_spatial_cells(
        polygon=[],
        pois=[
            {"id": "food-1", "location": [0.25, 0.25], "type": "050100"},
            {"id": "food-2", "location": [0.75, 0.25], "type": "050200"},
            {"id": "shop-1", "location": [1.25, 0.25], "type": "060100"},
        ],
        road_features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.5], [2.0, 0.5]]},
                "properties": {"integration_score": 0.6, "connectivity_score": 0.4},
            }
        ],
        categories=[
            PoiCategoryRequest(id="food", name="餐饮", types="050000"),
            PoiCategoryRequest(id="retail", name="购物", types="060000"),
        ],
    )

    assert payload["grid_type"] == "shared_raster"
    assert payload["cell_id_source"] == "population_nightlight_shared_cell_id"
    assert payload["summary"]["cell_count"] == 2
    assert payload["summary"]["active_poi_cell_count"] == 2
    assert payload["summary"]["lit_cell_count"] == 1
    assert payload["summary"]["road_covered_cell_count"] == 2

    rows = {item["properties"]["cell_id"]: item["properties"] for item in payload["features"]}
    assert rows["c0"]["poi_count"] == 2
    assert rows["c0"]["dominant_category"] == "food"
    assert rows["c0"]["dominant_category_name"] == "餐饮"
    assert rows["c0"]["population_density"] == 1200
    assert rows["c0"]["nightlight_radiance"] == 8.5
    assert rows["c0"]["road_integration"] == 0.6
    assert rows["c0"]["road_connectivity"] == 0.4
    assert rows["c0"]["road_length_km_per_km2"] > 0
    assert rows["c1"]["poi_count"] == 1



def test_shared_grid_analysis_joins_population_grid_cell_id_with_road_metrics(monkeypatch):
    feature = _feature("r7_c9", 0.0, 0.0, 1.0, 1.0)
    feature["properties"].update({"row": 7, "col": 9})
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_grid",
        lambda *args, **kwargs: {"scope_id": "scope-r7-c9", "cell_count": 1, "features": [feature]},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "r7_c9", "value": 23781}]},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_nightlight_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "r7_c9", "value": 12.25}]},
    )

    payload = spatial_cell_service.build_shared_grid_analysis(
        polygon=[],
        population_year="2026",
        nightlight_year=2025,
        pois=[{"id": "poi-1", "location": [0.5, 0.5], "type": "050100"}],
        poi_ready=True,
        road_ready=True,
        road_features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.5], [1.0, 0.5]]},
                "properties": {"integration_score": 0.808, "connectivity_score": 0.5},
            }
        ],
    )

    props = payload["grid"]["features"][0]["properties"]
    assert props["cell_id"] == "r7_c9"
    assert props["population_density"] == 23781
    assert props["nightlight_radiance"] == 12.25
    assert props["road_integration"] == 0.808
    assert payload["join_key"] == "cell_id"
    assert payload["source_readiness"]["road"]["ready"] is True
    assert payload["source_versions"]["population"]["year"] == "2026"


def test_shared_grid_rejects_unready_sources():
    try:
        spatial_cell_service.build_shared_grid_analysis(
            polygon=[],
            population_year="2026",
            nightlight_year=2025,
            pois=[],
            poi_ready=False,
            road_features=[],
            road_ready=False,
        )
    except ValueError as exc:
        assert "shared_grid_sources_not_ready" in str(exc)
        assert "POI" in str(exc)
        assert "路网" in str(exc)
    else:
        raise AssertionError("expected unready shared-grid sources to be rejected")


def test_unified_grid_distinguishes_missing_road_source_from_real_zero(monkeypatch):
    feature = _feature("r7_c9", 0.0, 0.0, 1.0, 1.0)
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_grid",
        lambda *args, **kwargs: {"scope_id": "scope-r7-c9", "cell_count": 1, "features": [feature]},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "r7_c9", "value": 23781}]},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_nightlight_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "r7_c9", "value": 0.0}]},
    )

    missing_road = spatial_cell_service.build_unified_spatial_cells(
        polygon=[], population_year="2026", nightlight_year=2025, pois=[], road_features=[]
    )
    missing_props = missing_road["features"][0]["properties"]
    assert "road_integration" not in missing_props
    assert "road_connectivity" not in missing_props
    assert "road_length_km_per_km2" not in missing_props

    ready_empty_road = spatial_cell_service.build_unified_spatial_cells(
        polygon=[],
        population_year="2026",
        nightlight_year=2025,
        pois=[],
        road_features=[],
        road_source_ready=True,
    )
    ready_props = ready_empty_road["features"][0]["properties"]
    assert ready_props["road_integration"] == 0.0
    assert ready_props["road_connectivity"] == 0.0
    assert ready_props["road_length_km_per_km2"] == 0.0


def test_poi_raster_grid_does_not_claim_unjoined_cross_layer_metrics(monkeypatch):
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_grid",
        lambda *args, **kwargs: {"scope_id": "scope-poi-only", "cell_count": 1, "features": [_feature("r7_c9", 0.0, 0.0, 1.0, 1.0)]},
    )

    payload = spatial_cell_service.analyze_shared_grid(polygon=[], pois=[])
    props = payload["grid"]["features"][0]["properties"]

    assert "population_density" not in props
    assert "nightlight_radiance" not in props
    assert "road_integration" not in props
    assert "road_connectivity" not in props
    assert "road_length_km_per_km2" not in props
