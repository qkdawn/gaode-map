from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from core.config import settings
from modules.road.depthmap import resolve_depthmap_cli_path
from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule


def _directory_writable(path: Path) -> bool:
    target = path if path.exists() else path.parent
    return target.exists() and os.access(target, os.W_OK)


def _check_depthmapx() -> Dict[str, Any]:
    configured_path = str(settings.depthmapx_cli_path or "").strip()
    try:
        resolved_path = resolve_depthmap_cli_path()
    except RuntimeError as exc:
        return {
            "ready": False,
            "message": str(exc),
            "configured_path": configured_path,
            "resolved_path": "",
        }
    return {
        "ready": True,
        "message": "depthmapXcli 已解析",
        "configured_path": configured_path,
        "resolved_path": resolved_path,
    }


def _check_chart_output_dir() -> Dict[str, Any]:
    path = Path(str(settings.chart_output_dir or "").strip())
    exists = path.exists()
    writable = _directory_writable(path)
    if exists and writable:
        message = "图表输出目录已就绪"
        ready = True
    elif not exists and writable:
        message = "图表输出目录不存在，但父目录可写，运行时可创建"
        ready = True
    elif exists:
        message = "图表输出目录存在，但当前进程不可写"
        ready = False
    else:
        message = "图表输出目录不存在，且父目录不可写"
        ready = False
    return {
        "ready": ready,
        "message": message,
        "path": str(path),
        "exists": exists,
        "writable": writable,
    }


def _check_existing_dir(path_value: str, *, label: str) -> Dict[str, Any]:
    path = Path(str(path_value or "").strip())
    exists = path.exists()
    return {
        "ready": exists,
        "message": f"{label}已就绪" if exists else f"{label}不存在",
        "path": str(path),
        "exists": exists,
    }


def _check_arcgis_bridge() -> Dict[str, Any]:
    enabled = bool(settings.arcgis_bridge_enabled)
    base_url = str(settings.arcgis_bridge_base_url or "").strip()
    if not enabled:
        return {
            "ready": True,
            "status": "disabled",
            "message": "ArcGIS bridge 已禁用，报告视觉不会调用 ArcGIS。",
            "enabled": False,
            "base_url": base_url,
        }
    try:
        status = ArcGISSpatialToolModule().report_status()
    except Exception as exc:  # readiness must remain diagnostic if optional ArcGIS deps fail
        return {
            "ready": False,
            "status": "failed",
            "message": f"ArcGIS 状态检查失败：{exc}",
            "enabled": True,
            "base_url": base_url,
        }
    return {
        **status,
        "message": status.get("summary", "ArcGIS 报告视觉状态已检查"),
        "enabled": True,
        "base_url": base_url,
    }


def build_system_readiness() -> Dict[str, Any]:
    checks = {
        "depthmapx": _check_depthmapx(),
        "chart_output_dir": _check_chart_output_dir(),
        "population_data_dir": _check_existing_dir(settings.population_data_dir, label="人口数据目录"),
        "nightlight_data_dir": _check_existing_dir(settings.nightlight_data_dir, label="夜光数据目录"),
        "arcgis_bridge": _check_arcgis_bridge(),
    }
    return {
        "ready": all(bool(item.get("ready")) for item in checks.values()),
        "checks": checks,
    }
