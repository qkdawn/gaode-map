import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

from fastapi.testclient import TestClient

from main import app
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
    features = [_cell_feature(row, col) for row in range(size) for col in range(size)]
    return {"scope_id": f"scope-{size}", "cell_count": len(features), "features": features}


def test_poi_grid_api_returns_shared_grid_semantics(monkeypatch):
    monkeypatch.setattr("modules.poi.aggregation.get_population_grid", lambda *args, **kwargs: _grid(2))
    client = TestClient(app)
    payload = {
        "polygon": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        "coord_type": "gcj02",
        "pois": [{"id": "1", "location": [0.2, 0.2], "type": "050100"}],
        "poi_coord_type": "gcj02",
        "categories": [{"id": "food", "name": "餐饮", "types": "050000"}],
    }
    resp = client.post("/api/v1/analysis/pois/grid", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["grid_type"] == "shared_raster"
    assert data["cell_id_source"] == "population_nightlight_shared_cell_id"
    assert "scope_id" in data
    assert data["features"][0]["properties"]["cell_id"]


def test_poi_grid_metrics_api_shape(monkeypatch):
    monkeypatch.setattr(spatial_cell_service, "get_population_grid", lambda *args, **kwargs: _grid(3))

    def _fake_arcgis(**kwargs):
        return {
            "status": "ArcGIS shared api test double completed",
            "global_moran": {"i": 0.35, "z_score": 2.1},
            "method": {
                "analysis_crs_wkid": 32631,
                "conceptualization": "CONTIGUITY_EDGES_CORNERS",
                "spatial_weights_kind": "QUEEN_CONTIGUITY",
                "neighbor_order": 1,
                "neighbor_count_distribution": {"3": 4, "5": 4, "8": 1},
            },
            "cells": [
                {"h3_id": "r0_c0", "gi_z_score": 1.1, "lisa_i": 0.07, "lisa_z_score": 0.31},
                {"h3_id": "r1_c1", "gi_z_score": -0.6, "lisa_i": -0.03, "lisa_z_score": -0.22},
            ],
            "image_url": None,
            "image_url_gi": "https://example.test/api-gi.png",
            "image_url_lisa": "https://example.test/api-lisa.png",
        }

    monkeypatch.setattr(spatial_cell_service, "run_h3_arcgis_analysis", _fake_arcgis)

    client = TestClient(app)
    payload = {
        "polygon": [[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]],
        "coord_type": "gcj02",
        "pois": [
            {"id": "1", "location": [0.2, 0.2], "type": "050100"},
            {"id": "2", "location": [1.2, 1.2], "type": "060100"},
            {"id": "3", "location": [2.2, 2.2], "type": "050200"},
        ],
        "poi_coord_type": "gcj02",
        "categories": [
            {"id": "food", "name": "餐饮", "types": "050000"},
            {"id": "retail", "name": "购物", "types": "060000"},
        ],
        "arcgis_export_image": True,
        "arcgis_timeout_sec": 240,
    }
    resp = client.post("/api/v1/analysis/pois/grid-metrics", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "grid" in data and "summary" in data and "charts" in data
    assert data["grid"]["grid_type"] == "shared_raster"
    assert data["grid"]["cell_id_source"] == "population_nightlight_shared_cell_id"
    assert data["summary"]["grid_count"] == len(data["grid"]["features"])
    assert data["summary"]["poi_count"] == 3
    assert data["summary"]["arcgis_status"] == "ArcGIS shared api test double completed"
    assert data["summary"]["spatial_statistics_method"] == {
        "analysis_crs_wkid": 32631,
        "conceptualization": "CONTIGUITY_EDGES_CORNERS",
        "spatial_weights_kind": "QUEEN_CONTIGUITY",
        "neighbor_order": 1,
        "neighbor_count_distribution": {"3": 4, "5": 4, "8": 1},
    }
    assert data["summary"]["arcgis_image_url_gi"] == "https://example.test/api-gi.png"
    assert data["summary"]["arcgis_image_url_lisa"] == "https://example.test/api-lisa.png"
    props = [feature["properties"] for feature in data["grid"]["features"]]
    assert props
    assert all("cell_id" in item for item in props)
    assert all("neighbor_mean_density" in item for item in props)
    assert all("local_entropy" in item for item in props)
    assert all("gi_star_z_score" in item for item in props)
    assert all("lisa_i" in item for item in props)


def test_poi_grid_metrics_progress_api(monkeypatch):
    monkeypatch.setattr(spatial_cell_service, "get_population_grid", lambda *args, **kwargs: _grid(2))

    def _fake_arcgis(**kwargs):
        return {
            "status": "ArcGIS shared api test double completed",
            "global_moran": {"i": 0.21, "z_score": 1.4},
            "cells": [
                {"h3_id": "r0_c0", "gi_z_score": 0.9, "lisa_i": 0.05, "lisa_z_score": 0.22},
            ],
            "image_url": None,
            "image_url_gi": None,
            "image_url_lisa": None,
        }

    monkeypatch.setattr(spatial_cell_service, "run_h3_arcgis_analysis", _fake_arcgis)

    client = TestClient(app)
    run_id = "poi-shared-progress-test"
    payload = {
        "polygon": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        "coord_type": "gcj02",
        "pois": [{"id": "1", "location": [0.2, 0.2], "type": "050100"}],
        "poi_coord_type": "gcj02",
        "categories": [{"id": "food", "name": "餐饮", "types": "050000"}],
        "arcgis_export_image": True,
        "arcgis_timeout_sec": 240,
        "run_id": run_id,
    }
    resp = client.post("/api/v1/analysis/pois/grid-metrics", json=payload)
    assert resp.status_code == 200

    progress_resp = client.get(f"/api/v1/analysis/pois/grid-metrics/progress?run_id={run_id}")
    assert progress_resp.status_code == 200
    progress = progress_resp.json()
    assert progress["run_id"] == run_id
    assert progress["stage"] == "completed"
    assert progress["status"] == "success"
    assert progress["step"] == 7
    assert progress["total"] == 7
