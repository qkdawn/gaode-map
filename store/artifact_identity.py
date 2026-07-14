from __future__ import annotations

import hashlib
import json
from typing import Any

from core.years import normalize_year


YEAR_SCOPED_ARTIFACT_TYPES = {"population", "nightlight", "poi_raster_grid", "poi_h3_grid"}
CURRENT_ARTIFACT_TYPES = {"road_syntax", "scope"}


def artifact_year(params: Any, payload: Any = None) -> int | None:
    canonical_params = params if isinstance(params, dict) else {}
    canonical_payload = payload if isinstance(payload, dict) else {}
    return normalize_year(canonical_params.get("year") or canonical_payload.get("year"))


def build_artifact_slot_key(artifact_type: Any, params: Any, payload: Any = None) -> str:
    normalized_type = str(artifact_type or "").strip()
    if normalized_type in YEAR_SCOPED_ARTIFACT_TYPES:
        year = artifact_year(params, payload)
        if year is None:
            raise ValueError(f"artifact_year_required:{normalized_type}")
        return f"year:{year}"
    if normalized_type in CURRENT_ARTIFACT_TYPES:
        return "current"
    canonical_params = params if isinstance(params, dict) else {}
    raw = json.dumps(canonical_params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"identity:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
