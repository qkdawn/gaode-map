import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from core.config import Settings, settings
from modules.gwr import arcgis_bridge as gwr_bridge
from modules.h3 import arcgis_bridge as h3_bridge
from modules.road import arcgis_bridge as road_bridge


class _DummyResponse:
    def __init__(self, body, status_code=200, headers=None, content=b""):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.text = ""

    def json(self):
        return self._body


class _DummyClient:
    def __init__(self, recorder):
        self._recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, headers=None, json=None):
        self._recorder.append({"url": url, "headers": headers or {}, "json": json or {}})
        if url.endswith("/v1/arcgis/h3/export"):
            return _DummyResponse(
                {},
                headers={
                    "content-type": "application/geopackage+sqlite3",
                    "content-disposition": 'attachment; filename="h3.gpkg"',
                },
                content=b"gpkg",
            )
        return _DummyResponse(
            {
                "ok": True,
                "status": "ok",
                "cells": [],
                "global_moran": {},
                "summary": {},
                "roads": {"type": "FeatureCollection", "features": [], "count": 0},
            }
        )


def test_settings_reads_arcgis_runtime_env(monkeypatch):
    monkeypatch.setenv("ARCGIS_PYTHON_PATH", r"C:\ArcGIS\python.exe")
    monkeypatch.setenv("ARCGIS_SCRIPT_PATH", r"D:\arcgis\h3.py")
    monkeypatch.setenv("ARCGIS_ROAD_SYNTAX_SDNA_SCRIPT_PATH", r"D:\arcgis\road.py")
    monkeypatch.setenv("ARCGIS_BRIDGE_PORT", "19081")

    runtime_settings = Settings()

    assert runtime_settings.arcgis_python_path == r"C:\ArcGIS\python.exe"
    assert runtime_settings.arcgis_script_path == r"D:\arcgis\h3.py"
    assert runtime_settings.arcgis_road_syntax_sdna_script_path == r"D:\arcgis\road.py"
    assert runtime_settings.arcgis_bridge_port == 19081


def test_h3_bridge_uses_arcgis_python_path_from_settings(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "arcgis_bridge_enabled", True)
    monkeypatch.setattr(settings, "arcgis_bridge_token", "token")
    monkeypatch.setattr(settings, "arcgis_bridge_base_url", "http://bridge.test")
    monkeypatch.setattr(settings, "arcgis_python_path", r"C:\ArcGIS\python.exe")
    monkeypatch.setattr(h3_bridge.httpx, "Client", lambda timeout, trust_env: _DummyClient(calls))

    h3_bridge.run_arcgis_h3_analysis(
        features=[
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[121.47, 31.23], [121.48, 31.23], [121.48, 31.24], [121.47, 31.24], [121.47, 31.23]]],
                },
                "properties": {"h3_id": "8928308280fffff"},
            }
        ],
        stats_by_cell={"8928308280fffff": {"density_poi_per_km2": 1.2}},
    )

    assert calls
    assert calls[0]["json"]["arcgis_python_path"] == r"C:\ArcGIS\python.exe"


def test_h3_export_omits_arcgis_python_path_when_not_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "arcgis_bridge_enabled", True)
    monkeypatch.setattr(settings, "arcgis_bridge_token", "token")
    monkeypatch.setattr(settings, "arcgis_bridge_base_url", "http://bridge.test")
    monkeypatch.setattr(settings, "arcgis_python_path", "")
    monkeypatch.setattr(h3_bridge.httpx, "Client", lambda timeout, trust_env: _DummyClient(calls))

    h3_bridge.run_arcgis_h3_export(
        export_format="gpkg",
        include_poi=False,
        style_mode="density",
        grid_features=[
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[121.47, 31.23], [121.48, 31.23], [121.48, 31.24], [121.47, 31.24], [121.47, 31.23]]],
                },
                "properties": {"h3_id": "8928308280fffff"},
            }
        ],
    )

    assert calls
    assert "arcgis_python_path" not in calls[0]["json"]


def test_gwr_bridge_uses_arcgis_python_path_from_settings(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "arcgis_bridge_enabled", True)
    monkeypatch.setattr(settings, "arcgis_bridge_token", "token")
    monkeypatch.setattr(settings, "arcgis_bridge_base_url", "http://bridge.test")
    monkeypatch.setattr(settings, "arcgis_python_path", r"C:\ArcGIS\python.exe")
    monkeypatch.setattr(gwr_bridge.httpx, "Client", lambda timeout, trust_env: _DummyClient(calls))

    gwr_bridge.run_arcgis_gwr_analysis(
        rows=[{"cell_id": "c1", "nightlight_radiance": 1.0, "predictors": {"poi_density_per_km2": 1.0}}],
        variables=[{"key": "poi_density_per_km2", "label": "POI"}],
    )

    assert calls
    assert calls[0]["json"]["arcgis_python_path"] == r"C:\ArcGIS\python.exe"


def test_road_bridge_uses_arcgis_python_path_from_settings(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "arcgis_bridge_enabled", True)
    monkeypatch.setattr(settings, "arcgis_bridge_token", "token")
    monkeypatch.setattr(settings, "arcgis_bridge_base_url", "http://bridge.test")
    monkeypatch.setattr(settings, "arcgis_python_path", r"C:\ArcGIS\python.exe")
    client_options = []

    def make_client(**kwargs):
        client_options.append(kwargs)
        return _DummyClient(calls)

    monkeypatch.setattr(road_bridge.httpx, "Client", make_client)

    road_bridge.run_arcgis_road_syntax_webgl(
        road_features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[121.47, 31.23], [121.48, 31.24]]},
                "properties": {"accessibility_score": 0.8},
            }
        ]
    )

    assert calls
    assert calls[0]["json"]["arcgis_python_path"] == r"C:\ArcGIS\python.exe"
    assert client_options == [{"timeout": 300.0, "trust_env": False}]
