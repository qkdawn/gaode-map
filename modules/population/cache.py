from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict

PREVIEW_STYLE_VERSION = "v3"
GRID_STYLE_VERSION = "v7"
IN_MEMORY_JSON_CACHE_MAX_ENTRIES = 512

_IN_MEMORY_CACHE_LOCK = threading.Lock()
_IN_MEMORY_JSON_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_dir(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = project_root() / path
    return path.resolve()


def cache_path(filename: str) -> Path:
    return project_root() / "runtime" / "generated_population" / str(filename)


def overview_cache_path(scope_id: str) -> Path:
    return cache_path(f"{scope_id}_overview.json")


def grid_cache_path(scope_id: str) -> Path:
    return cache_path(f"{scope_id}_grid_{GRID_STYLE_VERSION}.json")


def raster_cache_json_path(scope_id: str, sex: str, age_band: str) -> Path:
    return cache_path(f"{scope_id}_{sex}_{age_band}_{PREVIEW_STYLE_VERSION}.json")


def layer_cache_json_path(scope_id: str, view: str, sex_mode: str, age_mode: str, age_band: str) -> Path:
    safe_view = str(view or "density").strip().lower()
    safe_sex_mode = str(sex_mode or "male").strip().lower()
    safe_age_mode = str(age_mode or "ratio").strip().lower()
    safe_age_band = str(age_band or "25").strip().lower()
    return cache_path(
        f"{scope_id}_{safe_view}_{safe_sex_mode}_{safe_age_mode}_{safe_age_band}_{GRID_STYLE_VERSION}.json"
    )


def cache_key(path: Path) -> str:
    return f"{str(path.parent)}::{path.name}"


def read_json(path: Path) -> Dict[str, Any] | None:
    key = cache_key(path)
    with _IN_MEMORY_CACHE_LOCK:
        payload = _IN_MEMORY_JSON_CACHE.get(key)
        if payload is None:
            return None
        _IN_MEMORY_JSON_CACHE.move_to_end(key)
        return copy.deepcopy(payload)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    key = cache_key(path)
    with _IN_MEMORY_CACHE_LOCK:
        _IN_MEMORY_JSON_CACHE[key] = copy.deepcopy(payload)
        _IN_MEMORY_JSON_CACHE.move_to_end(key)
        while len(_IN_MEMORY_JSON_CACHE) > IN_MEMORY_JSON_CACHE_MAX_ENTRIES:
            _IN_MEMORY_JSON_CACHE.popitem(last=False)
