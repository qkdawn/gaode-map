import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from core.config import DEFAULT_CHART_OUTPUT_DIR, PROJECT_ROOT, Settings
from modules.road import depthmap


def test_settings_chart_output_dir_defaults_to_runtime_directory(monkeypatch):
    monkeypatch.delenv("CHART_OUTPUT_DIR", raising=False)

    runtime_settings = Settings(_env_file=None)

    assert runtime_settings.chart_output_dir == str(DEFAULT_CHART_OUTPUT_DIR.resolve())


def test_settings_chart_output_dir_resolves_relative_path_from_project_root(monkeypatch):
    monkeypatch.setenv("CHART_OUTPUT_DIR", "runtime/custom_charts")

    runtime_settings = Settings(_env_file=None)

    assert runtime_settings.chart_output_dir == str((PROJECT_ROOT / "runtime" / "custom_charts").resolve())


def test_depthmap_cli_path_uses_settings_value(monkeypatch):
    monkeypatch.setattr(depthmap.settings, "depthmapx_cli_path", "depthmap-custom")
    monkeypatch.setattr(depthmap.shutil, "which", lambda item: "/opt/depthmap-custom" if item == "depthmap-custom" else None)

    resolved = depthmap.resolve_depthmap_cli_path()

    assert resolved == "/opt/depthmap-custom"
