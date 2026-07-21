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


system_router = _load_router_module("test_system_router", "router/domains/system.py").router


def _build_test_app():
    app = FastAPI()
    app.include_router(system_router)
    return app


def test_system_readiness_api_reports_runtime_checks(monkeypatch, tmp_path):
    client = TestClient(_build_test_app())
    population_dir = tmp_path / "population"
    nightlight_dir = tmp_path / "nightlight"
    population_dir.mkdir()
    nightlight_dir.mkdir()

    monkeypatch.setattr("modules.system.readiness.resolve_depthmap_cli_path", lambda: "depthmapXcli")
    monkeypatch.setattr("modules.system.readiness.settings.depthmapx_cli_path", "depthmapXcli")
    monkeypatch.setattr("modules.system.readiness.settings.chart_output_dir", str(tmp_path / "charts"))
    monkeypatch.setattr("modules.system.readiness.settings.population_data_dir", str(population_dir))
    monkeypatch.setattr("modules.system.readiness.settings.nightlight_data_dir", str(nightlight_dir))
    monkeypatch.setattr("modules.system.readiness.settings.arcgis_bridge_enabled", True)
    monkeypatch.setattr("modules.system.readiness.settings.arcgis_bridge_base_url", "http://127.0.0.1:18081")
    monkeypatch.setattr("modules.system.readiness.ArcGISSpatialToolModule.report_status", lambda self: {
        "status": "available", "ready": True, "summary": "ArcGIS 报告视觉服务已就绪。",
        "checks": {"service_connection": {"ready": True, "status": "reachable"}}, "limitations": [],
    })

    resp = client.get("/api/v1/system/readiness")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ready"] is True
    assert payload["checks"]["depthmapx"]["configured_path"] == "depthmapXcli"
    assert payload["checks"]["depthmapx"]["resolved_path"] == "depthmapXcli"
    assert payload["checks"]["chart_output_dir"]["exists"] is False
    assert payload["checks"]["chart_output_dir"]["writable"] is True
    assert payload["checks"]["population_data_dir"]["exists"] is True
    assert payload["checks"]["nightlight_data_dir"]["exists"] is True
    assert payload["checks"]["arcgis_bridge"]["enabled"] is True
    assert payload["checks"]["arcgis_bridge"]["base_url"] == "http://127.0.0.1:18081"
    assert payload["checks"]["arcgis_bridge"]["checks"]["service_connection"]["ready"] is True


def test_system_readiness_api_marks_missing_depthmap_and_disabled_arcgis(monkeypatch, tmp_path):
    client = TestClient(_build_test_app())
    population_dir = tmp_path / "population"
    population_dir.mkdir()

    def _missing_depthmap():
        raise RuntimeError("depthmapXcli 未找到。请安装 depthmapXcli 并配置 DEPTHMAPX_CLI_PATH。")

    monkeypatch.setattr("modules.system.readiness.resolve_depthmap_cli_path", _missing_depthmap)
    monkeypatch.setattr("modules.system.readiness.settings.depthmapx_cli_path", "depthmapXcli")
    monkeypatch.setattr("modules.system.readiness.settings.chart_output_dir", str(tmp_path / "charts"))
    monkeypatch.setattr("modules.system.readiness.settings.population_data_dir", str(population_dir))
    monkeypatch.setattr("modules.system.readiness.settings.nightlight_data_dir", str(tmp_path / "missing-nightlight"))
    monkeypatch.setattr("modules.system.readiness.settings.arcgis_bridge_enabled", False)
    monkeypatch.setattr("modules.system.readiness.settings.arcgis_bridge_base_url", "")

    resp = client.get("/api/v1/system/readiness")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ready"] is False
    assert payload["checks"]["depthmapx"]["ready"] is False
    assert "DEPTHMAPX_CLI_PATH" in payload["checks"]["depthmapx"]["message"]
    assert payload["checks"]["nightlight_data_dir"]["exists"] is False
    assert payload["checks"]["arcgis_bridge"]["ready"] is True
    assert payload["checks"]["arcgis_bridge"]["enabled"] is False
