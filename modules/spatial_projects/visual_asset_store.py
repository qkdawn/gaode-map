from __future__ import annotations

import os
import re
import json
from copy import deepcopy
from pathlib import Path

from core.svg_safety import validate_safe_svg

_SAFE_ID = re.compile(r"^[A-Za-z0-9:._-]+$")


class SpatialReportVisualAssetStore:
    """Persist generated report visuals independently from final publication."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parents[2] / "runtime" / "spatial-report-visuals"

    @staticmethod
    def resource_uri(history_id: str, asset_id: str) -> str:
        SpatialReportVisualAssetStore._validate_id(history_id, "history_id")
        SpatialReportVisualAssetStore._validate_id(asset_id, "asset_id")
        return f"spatial-report-visual://{history_id}/{asset_id}"

    def save(
        self, *, history_id: str, asset_id: str, filename: str, svg: str,
        visual_manifest: dict,
    ) -> dict[str, str]:
        validate_safe_svg(svg)
        self._validate_manifest(visual_manifest)
        target = self._path(history_id, asset_id)
        manifest_target = self._manifest_path(history_id, asset_id)
        expected_filename = self._filename(asset_id)
        if Path(str(filename or "")).name != expected_filename:
            raise ValueError("spatial_report_visual_filename_mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        svg_temporary = target.with_suffix(".svg.tmp")
        manifest_temporary = manifest_target.with_suffix(".json.tmp")
        svg_temporary.write_text(svg, encoding="utf-8", newline="\n")
        manifest_temporary.write_text(
            json.dumps(visual_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8", newline="\n",
        )
        # The SVG is the commit marker. Readers never consider an asset verified
        # unless both files exist and the sidecar passes the quality contract.
        os.replace(manifest_temporary, manifest_target)
        os.replace(svg_temporary, target)
        return {
            "asset_id": asset_id,
            "filename": expected_filename,
            "resource_uri": self.resource_uri(history_id, asset_id),
        }

    def metadata(self, *, history_id: str, asset_id: str) -> dict[str, str]:
        target = self._path(history_id, asset_id)
        if not target.is_file():
            raise LookupError("spatial_report_visual_asset_not_found")
        manifest = self.read_manifest(history_id=history_id, asset_id=asset_id)
        return {
            "asset_id": asset_id,
            "filename": target.name,
            "resource_uri": self.resource_uri(history_id, asset_id),
            "media_type": "image/svg+xml",
            "manifest_status": "verified" if manifest.get("quality_status") == "passed" else "legacy_unverified",
            "quality_status": str(manifest.get("quality_status") or "legacy_unverified"),
        }

    def read(self, *, history_id: str, asset_id: str) -> str:
        target = self._path(history_id, asset_id)
        if not target.is_file():
            raise LookupError("spatial_report_visual_asset_not_found")
        svg = target.read_text(encoding="utf-8")
        validate_safe_svg(svg)
        return svg

    def read_manifest(self, *, history_id: str, asset_id: str) -> dict:
        target = self._path(history_id, asset_id)
        if not target.is_file():
            raise LookupError("spatial_report_visual_asset_not_found")
        manifest_target = self._manifest_path(history_id, asset_id)
        if not manifest_target.is_file():
            return {
                "schema_version": "legacy",
                "asset_id": asset_id,
                "quality_status": "legacy_unverified",
                "warnings": ["legacy_asset_has_no_quality_manifest"],
            }
        manifest = json.loads(manifest_target.read_text(encoding="utf-8"))
        self._validate_manifest(manifest)
        return deepcopy(manifest)

    def _path(self, history_id: str, asset_id: str) -> Path:
        self._validate_id(history_id, "history_id")
        self._validate_id(asset_id, "asset_id")
        return self._root / history_id / self._filename(asset_id)

    def _manifest_path(self, history_id: str, asset_id: str) -> Path:
        return self._path(history_id, asset_id).with_suffix(".manifest.json")

    @staticmethod
    def _validate_manifest(manifest: dict) -> None:
        required = {
            "schema_version", "input_result_ids", "input_layer_manifest", "input_feature_count",
            "rendered_feature_count", "geometry_types", "bbox", "crs", "basemap_status",
            "road_context_status", "legend_items", "warnings", "quality_status", "pixel_quality",
        }
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise ValueError("spatial_report_visual_manifest_invalid")
        if manifest.get("schema_version") != "1.0" or manifest.get("quality_status") != "passed":
            raise ValueError("spatial_report_visual_manifest_not_passed")
        if int(manifest.get("input_feature_count") or -1) != int(manifest.get("rendered_feature_count") or -2):
            raise ValueError("spatial_report_visual_manifest_count_mismatch")
        if manifest.get("crs") != "EPSG:4326" or not isinstance(manifest.get("pixel_quality"), dict) or manifest["pixel_quality"].get("status") != "passed":
            raise ValueError("spatial_report_visual_manifest_quality_mismatch")
        layers = manifest.get("input_layer_manifest")
        if not isinstance(layers, list) or any(not isinstance(layer, dict) for layer in layers) or any(
            bool(layer.get("required", True))
            and int(layer.get("rendered_feature_count") or -1) != int(layer.get("normalized_feature_count") or 0)
            for layer in layers if isinstance(layer, dict)
        ):
            raise ValueError("spatial_report_visual_manifest_layer_mismatch")

    @staticmethod
    def _filename(asset_id: str) -> str:
        return f"{asset_id.replace(':', '-')}.svg"

    @staticmethod
    def _validate_id(value: str, field: str) -> None:
        if not isinstance(value, str) or not value or not _SAFE_ID.fullmatch(value):
            raise ValueError(f"invalid_{field}")


__all__ = ["SpatialReportVisualAssetStore"]
