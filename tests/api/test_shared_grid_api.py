import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import router.domains.shared_grid as shared_grid_router_module
from main import app


def _request_payload():
    return {
        "polygon": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        "coord_type": "gcj02",
        "population_year": "2026",
        "nightlight_year": 2025,
        "pois": [{"id": "poi-1", "location": [0.5, 0.5], "type": "050100"}],
        "poi_ready": True,
        "road_features": [],
        "road_ready": True,
    }


def test_shared_grid_api_returns_joined_grid_and_source_metadata(monkeypatch):
    client = TestClient(app)

    def fake_build_shared_grid_analysis(**kwargs):
        assert kwargs["population_year"] == "2026"
        assert kwargs["nightlight_year"] == 2025
        assert kwargs["poi_ready"] is True
        assert kwargs["road_ready"] is True
        return {
            "evidence_version": "shared_grid_v1",
            "join_key": "cell_id",
            "grid": {"type": "FeatureCollection", "features": []},
            "summary": {"grid_count": 0, "assigned_poi_count": 0},
            "source_versions": {"population": {"ready": True, "year": "2026", "record_count": 0}},
            "source_readiness": {"population": {"ready": True, "year": "2026", "record_count": 0}},
            "limitations": ["仅作空间条件与代理线索"],
        }

    monkeypatch.setattr(shared_grid_router_module, "build_shared_grid_analysis", fake_build_shared_grid_analysis)
    response = client.post("/api/v1/analysis/shared-grid", json=_request_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["join_key"] == "cell_id"
    assert data["grid"]["type"] == "FeatureCollection"
    assert data["source_versions"]["population"]["year"] == "2026"
    assert data["source_readiness"]["population"]["ready"] is True


def test_shared_grid_api_returns_domain_readiness_error(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(
        shared_grid_router_module,
        "build_shared_grid_analysis",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("shared_grid_sources_not_ready:路网")),
    )

    response = client.post("/api/v1/analysis/shared-grid", json=_request_payload())

    assert response.status_code == 422
    assert "shared_grid_sources_not_ready" in response.json()["detail"]


def test_shared_grid_api_requires_population_and_nightlight_years():
    client = TestClient(app)
    payload = _request_payload()
    payload.pop("population_year")
    payload.pop("nightlight_year")

    response = client.post("/api/v1/analysis/shared-grid", json=payload)

    assert response.status_code == 422
