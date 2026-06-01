from modules.poi.schemas import PoiCategoryRequest
from modules.spatial_cells import service as spatial_cell_service


def _cell_feature(row, col):
    west = float(col)
    east = west + 1.0
    south = float(row)
    north = south + 1.0
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
        },
        "properties": {
            "cell_id": f"r{row}_c{col}",
            "h3_id": f"r{row}_c{col}",
            "row": row,
            "col": col,
            "centroid_gcj02": [(west + east) / 2, (south + north) / 2],
        },
    }


def _grid(size):
    features = []
    for row in range(size):
        for col in range(size):
            features.append(_cell_feature(row, col))
    return {"scope_id": f"scope-{size}", "cell_count": len(features), "features": features}


def test_shared_grid_neighbor_rings_follow_rectangular_moore_rule(monkeypatch):
    monkeypatch.setattr(spatial_cell_service, "get_population_grid", lambda *args, **kwargs: _grid(7))

    result_ring_1 = spatial_cell_service.analyze_shared_grid(polygon=[], pois=[], neighbor_ring=1)
    result_ring_2 = spatial_cell_service.analyze_shared_grid(polygon=[], pois=[], neighbor_ring=2)
    result_ring_3 = spatial_cell_service.analyze_shared_grid(polygon=[], pois=[], neighbor_ring=3)

    def _props(result):
        rows = {
            item["properties"]["cell_id"]: item["properties"]
            for item in result["grid"]["features"]
        }
        return rows["r3_c3"]

    assert _props(result_ring_1)["neighbor_count"] == 8
    assert _props(result_ring_2)["neighbor_count"] == 24
    assert _props(result_ring_3)["neighbor_count"] == 48


def test_shared_grid_metrics_align_with_h3_shape_and_arcgis_writeback(monkeypatch):
    monkeypatch.setattr(spatial_cell_service, "get_population_grid", lambda *args, **kwargs: _grid(3))

    def _fake_arcgis(**kwargs):
        assert kwargs["knn_neighbors"] == 8
        return {
            "status": "ArcGIS shared grid test double completed",
            "global_moran": {"i": 0.42, "z_score": 2.7},
            "cells": [
                {"h3_id": "r0_c0", "gi_z_score": 1.5, "lisa_i": 0.11, "lisa_z_score": 0.51},
                {"h3_id": "r1_c1", "gi_z_score": -0.8, "lisa_i": -0.09, "lisa_z_score": -0.41},
            ],
            "image_url": "https://example.test/shared.png",
            "image_url_gi": "https://example.test/shared-gi.png",
            "image_url_lisa": "https://example.test/shared-lisa.png",
        }

    monkeypatch.setattr(spatial_cell_service, "run_h3_arcgis_analysis", _fake_arcgis)

    result = spatial_cell_service.analyze_shared_grid(
        polygon=[],
        coord_type="gcj02",
        pois=[
            {"id": "a", "location": [0.2, 0.2], "type": "050100"},
            {"id": "b", "location": [0.8, 0.2], "type": "060100"},
            {"id": "c", "location": [1.2, 1.2], "type": "050200"},
        ],
        poi_coord_type="gcj02",
        categories=[
            PoiCategoryRequest(id="food", name="餐饮", types="050000"),
            PoiCategoryRequest(id="retail", name="购物", types="060000"),
        ],
        neighbor_ring=1,
        arcgis_neighbor_ring=1,
    )

    assert set(result.keys()) == {"grid", "summary", "charts"}
    assert result["grid"]["grid_type"] == "shared_raster"
    assert result["grid"]["cell_id_source"] == "population_nightlight_shared_cell_id"
    assert result["grid"]["scope_id"] == "scope-3"
    assert result["summary"]["grid_count"] == 9
    assert result["summary"]["poi_count"] == 3
    assert result["summary"]["analysis_engine"] == "arcgis"
    assert result["summary"]["arcgis_status"] == "ArcGIS shared grid test double completed"
    assert result["summary"]["arcgis_image_url"] == "https://example.test/shared.png"
    assert result["summary"]["arcgis_image_url_gi"] == "https://example.test/shared-gi.png"
    assert result["summary"]["arcgis_image_url_lisa"] == "https://example.test/shared-lisa.png"
    assert result["summary"]["global_moran_i_density"] == 0.42
    assert result["summary"]["global_moran_z_score"] == 2.7
    assert result["summary"]["gi_render_meta"]["mode"] == "fixed_z"
    assert result["summary"]["lisa_render_meta"]["mode"] == "stddev"
    assert "category_distribution" in result["charts"]
    assert "density_histogram" in result["charts"]

    props = {item["properties"]["cell_id"]: item["properties"] for item in result["grid"]["features"]}
    assert props["r0_c0"]["poi_count"] == 2
    assert props["r0_c0"]["density_poi_per_km2"] > 0
    assert props["r0_c0"]["local_entropy"] > 0
    assert props["r0_c0"]["neighbor_mean_density"] >= 0
    assert props["r0_c0"]["gi_star_z_score"] == 1.5
    assert props["r0_c0"]["gi_star_value"] == 1.5
    assert props["r0_c0"]["lisa_i"] == 0.11
    assert props["r1_c1"]["lisa_z_score"] == -0.41
