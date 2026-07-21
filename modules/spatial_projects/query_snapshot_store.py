from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from shapely.geometry import shape


_SAFE_ID = re.compile(r"^[A-Za-z0-9:._-]+$")
SNAPSHOT_SCHEMA_VERSION = "1.0"
MAX_SNAPSHOT_FEATURES = 10_000


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SpatialQuerySnapshotStore:
    """Content-addressed private storage for immutable spatial query results."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parents[2] / "runtime" / "spatial-query-snapshots"

    def create(
        self,
        *,
        history_id: str,
        source_id: str,
        year: int | None,
        filters: Mapping[str, Any] | None,
        spatial: Mapping[str, Any] | None,
        selection: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._validate_id(history_id, "history_id")
        features = selection.get("features")
        if not isinstance(features, list):
            raise ValueError("query_snapshot_features_invalid")
        if len(features) > MAX_SNAPSHOT_FEATURES:
            raise ValueError("query_snapshot_feature_limit_exceeded")
        query = {
            "source_id": source_id,
            "requested_year": year,
            "selected_year": selection.get("selected_year"),
            "filters": deepcopy(dict(filters or {})),
            "spatial": deepcopy(dict(spatial or {})) if spatial else None,
        }
        digest_payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "history_id": history_id,
            "query": query,
            "features": features,
        }
        digest = hashlib.sha256(_canonical(digest_payload).encode("utf-8")).hexdigest()
        snapshot_id = f"snapshot:{digest[:24]}"
        geometry_types = sorted({
            str(feature.get("geometry", {}).get("type") or "")
            for feature in features
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
        } - {""})
        bbox = self._bbox(features)
        payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "history_id": history_id,
            "source_id": source_id,
            "query": query,
            "record_count": int(selection.get("record_count") or 0),
            "normalized_feature_count": len(features),
            "geometry_types": geometry_types,
            "bbox": bbox,
            "crs": "EPSG:4326",
            "digest": f"sha256:{digest}",
            "warnings": [str(item) for item in selection.get("warnings") or []],
            "features": deepcopy(features),
        }
        target = self._path(history_id, snapshot_id)
        if target.is_file():
            existing = self.read(history_id=history_id, snapshot_id=snapshot_id)
            if existing.get("digest") != payload["digest"]:
                raise ValueError("query_snapshot_digest_collision")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(_canonical(payload), encoding="utf-8", newline="\n")
            os.replace(temporary, target)
        return self.public_metadata(payload)

    def read(self, *, history_id: str, snapshot_id: str) -> dict[str, Any]:
        target = self._path(history_id, snapshot_id)
        if not target.is_file():
            raise LookupError("spatial_query_snapshot_not_found")
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("history_id") != history_id or payload.get("snapshot_id") != snapshot_id:
            raise ValueError("spatial_query_snapshot_identity_mismatch")
        return payload

    @staticmethod
    def public_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(payload.get(key))
            for key in (
                "schema_version", "snapshot_id", "history_id", "source_id", "query",
                "record_count", "normalized_feature_count", "geometry_types", "bbox",
                "crs", "digest", "warnings",
            )
        }

    def _path(self, history_id: str, snapshot_id: str) -> Path:
        self._validate_id(history_id, "history_id")
        self._validate_id(snapshot_id, "snapshot_id")
        return self._root / history_id / f"{snapshot_id.replace(':', '-')}.json"

    @staticmethod
    def _bbox(features: list[dict[str, Any]]) -> list[float]:
        bounds = []
        for feature in features:
            try:
                geometry = shape(feature["geometry"])
            except (KeyError, TypeError, ValueError):
                continue
            if not geometry.is_empty:
                bounds.append(geometry.bounds)
        if not bounds:
            return []
        return [
            min(item[0] for item in bounds), min(item[1] for item in bounds),
            max(item[2] for item in bounds), max(item[3] for item in bounds),
        ]

    @staticmethod
    def _validate_id(value: str, field: str) -> None:
        if not isinstance(value, str) or not value or not _SAFE_ID.fullmatch(value):
            raise ValueError(f"invalid_{field}")


__all__ = ["MAX_SNAPSHOT_FEATURES", "SNAPSHOT_SCHEMA_VERSION", "SpatialQuerySnapshotStore"]
