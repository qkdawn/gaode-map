from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from core.config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHART_DIR = PROJECT_ROOT / "runtime" / "generated_charts"
LEGACY_CHART_DIR = PROJECT_ROOT / "modules" / "generated_charts"


def _resolve_chart_dir() -> Path:
    configured = str(settings.chart_output_dir or "").strip()
    return Path(configured) if configured else DEFAULT_CHART_DIR


def _migrate_legacy_dir(target_dir: Path) -> None:
    if not LEGACY_CHART_DIR.exists() or LEGACY_CHART_DIR == target_dir:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in LEGACY_CHART_DIR.iterdir():
        destination = target_dir / item.name
        if destination.exists():
            continue
        shutil.move(str(item), str(destination))
    try:
        LEGACY_CHART_DIR.rmdir()
    except OSError:
        # Directory not empty or not removable. Keep runtime path as source of truth.
        pass


CHART_DIR_PATH = _resolve_chart_dir()
_migrate_legacy_dir(CHART_DIR_PATH)
CHART_DIR_PATH.mkdir(parents=True, exist_ok=True)
CHART_DIR = str(CHART_DIR_PATH)


def save_svg(svg_content: str) -> tuple[str, str]:
    chart_id = uuid.uuid4().hex
    filename = f"{chart_id}.svg"
    filepath = CHART_DIR_PATH / filename
    with filepath.open("w", encoding="utf-8") as handle:
        handle.write(svg_content)
    return chart_id, filename


def save_png(png_bytes: bytes) -> tuple[str, str]:
    chart_id = uuid.uuid4().hex
    filename = f"{chart_id}.png"
    filepath = CHART_DIR_PATH / filename
    with filepath.open("wb") as handle:
        handle.write(png_bytes)
    return chart_id, filename


def get_chart_path(filename: str) -> str:
    safe_name = Path(filename).name
    return str(CHART_DIR_PATH / safe_name)
