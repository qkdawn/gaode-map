import os
import sys
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

def _load_router_module(module_name: str, relative_path: str):
    path = Path(__file__).resolve().parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


road_module = _load_router_module("test_road_router", "router/domains/road.py")
road_router = road_module.router


def _build_test_app():
    app = FastAPI()
    app.include_router(road_router)
    return app


def _sample_polygon():
    return [
        [112.9800, 28.1900],
        [112.9900, 28.1900],
        [112.9900, 28.2000],
        [112.9800, 28.2000],
        [112.9800, 28.1900],
    ]


def test_road_syntax_api_rejects_context_polygon_extra_field():
    client = TestClient(_build_test_app())
    payload = {
        "polygon": _sample_polygon(),
        "context_polygon": _sample_polygon(),
        "coord_type": "gcj02",
        "mode": "walking",
        "graph_model": "segment",
        "highway_filter": "all",
    }
    resp = client.post("/api/v1/analysis/road-syntax", json=payload)
    assert resp.status_code == 422


def test_road_syntax_api_rejects_legacy_depthmap_cli_override_field():
    client = TestClient(_build_test_app())
    payload = {
        "polygon": _sample_polygon(),
        "coord_type": "gcj02",
        "mode": "walking",
        "graph_model": "segment",
        "highway_filter": "all",
        "depthmap_cli_path": "/usr/local/bin/depthmapXcli",
    }

    resp = client.post("/api/v1/analysis/road-syntax", json=payload)

    assert resp.status_code == 422


def test_road_syntax_api_local_segment_defaults_radii(monkeypatch):
    client = TestClient(_build_test_app())

    def _fake_analyze_road_syntax(**kwargs):
        assert kwargs.get("graph_model") == "segment"
        assert kwargs.get("radii_m") == [600, 800]
        return {
            "summary": {
                "analysis_engine": "depthmapxcli",
            }
        }

    monkeypatch.setattr(road_module, "analyze_road_syntax", _fake_analyze_road_syntax)

    payload = {
        "polygon": _sample_polygon(),
        "coord_type": "gcj02",
        "mode": "walking",
        "graph_model": "segment",
        "highway_filter": "all",
    }
    resp = client.post("/api/v1/analysis/road-syntax", json=payload)
    assert resp.status_code == 200
    assert resp.json().get("summary", {}).get("analysis_engine") == "depthmapxcli"


def test_road_syntax_api_local_axial_pass_through(monkeypatch):
    client = TestClient(_build_test_app())

    def _fake_analyze_road_syntax(**kwargs):
        assert kwargs.get("graph_model") == "axial"
        assert kwargs.get("radii_m") == [600, 800]
        return {
            "summary": {
                "analysis_engine": "depthmapxcli-axial",
            }
        }

    monkeypatch.setattr(road_module, "analyze_road_syntax", _fake_analyze_road_syntax)

    payload = {
        "polygon": _sample_polygon(),
        "coord_type": "gcj02",
        "mode": "walking",
        "graph_model": "axial",
        "highway_filter": "all",
        "radii_m": [600, 800],
    }
    resp = client.post("/api/v1/analysis/road-syntax", json=payload)
    assert resp.status_code == 200
    assert resp.json().get("summary", {}).get("analysis_engine") == "depthmapxcli-axial"
