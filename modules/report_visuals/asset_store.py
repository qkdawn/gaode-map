"""Private storage for MCP-created constrained Vega report visual bundles."""
from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from core.svg_safety import validate_safe_svg
from .schemas import VisualManifest

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_ASSET_PATH = re.compile(r"^assets/[A-Za-z0-9._-]+\.svg$")


class ReportVegaVisualAssetStore:
    """Own controlled report bundle paths and validated SVG asset reads.

    MCP callers identify a report by ``history_id`` and ``report_id`` only.  They
    never supply a filesystem path, asset filename, SVG, or Vega specification.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parents[2] / "runtime" / "report-vega-visuals"

    @staticmethod
    def asset_resource_uri(history_id: str, report_id: str, asset_id: str) -> str:
        for value, field in ((history_id, "history_id"), (report_id, "report_id"), (asset_id, "asset_id")):
            ReportVegaVisualAssetStore._validate_id(value, field)
        return f"report-vega-visual://{history_id}/{report_id}/{asset_id}"

    @staticmethod
    def report_resource_uri(history_id: str, report_id: str) -> str:
        ReportVegaVisualAssetStore._validate_id(history_id, "history_id")
        ReportVegaVisualAssetStore._validate_id(report_id, "report_id")
        return f"report-vega-report://{history_id}/{report_id}"

    @staticmethod
    def plan_resource_uri(history_id: str, report_id: str) -> str:
        ReportVegaVisualAssetStore._validate_id(history_id, "history_id")
        ReportVegaVisualAssetStore._validate_id(report_id, "report_id")
        return f"report-vega-visual-plan://{history_id}/{report_id}"

    @staticmethod
    def manifest_resource_uri(history_id: str, report_id: str) -> str:
        ReportVegaVisualAssetStore._validate_id(history_id, "history_id")
        ReportVegaVisualAssetStore._validate_id(report_id, "report_id")
        return f"report-vega-visual-manifest://{history_id}/{report_id}"

    def prepare_report(self, *, history_id: str, report_id: str, report_markdown: str) -> Path:
        directory = self._directory(history_id, report_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "report.md"
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text(str(report_markdown).replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, target)
        return target

    def report_path(self, *, history_id: str, report_id: str) -> Path:
        return self._required_file(self._directory(history_id, report_id) / "report.md", "report_vega_report_not_found")

    def read_report(self, *, history_id: str, report_id: str) -> str:
        return self.report_path(history_id=history_id, report_id=report_id).read_text(encoding="utf-8")

    def read_plan(self, *, history_id: str, report_id: str) -> str:
        return self._required_file(self._directory(history_id, report_id) / "visual-plan.json", "report_vega_visual_plan_not_found").read_text(encoding="utf-8")

    def asset_metadata(self, *, history_id: str, report_id: str, asset_id: str) -> dict[str, str]:
        item = self._manifest_asset_item(history_id=history_id, report_id=report_id, asset_id=asset_id)
        target = self._asset_path_from_item(history_id=history_id, report_id=report_id, item=item)
        return {
            "asset_id": asset_id,
            "filename": target.name,
            "resource_uri": self.asset_resource_uri(history_id, report_id, asset_id),
            "media_type": "image/svg+xml",
            "template_id": str(item.get("template_id") or ""),
        }

    def read_asset(self, *, history_id: str, report_id: str, asset_id: str) -> str:
        item = self._manifest_asset_item(history_id=history_id, report_id=report_id, asset_id=asset_id)
        target = self._asset_path_from_item(history_id=history_id, report_id=report_id, item=item)
        if item.get("asset_sha256") != sha256(target.read_bytes()).hexdigest():
            raise LookupError("report_vega_visual_asset_checksum_mismatch")
        svg = target.read_text(encoding="utf-8")
        validate_safe_svg(svg)
        return svg

    def write_manifest(self, *, history_id: str, report_id: str, manifest: dict[str, Any]) -> None:
        directory = self._directory(history_id, report_id)
        directory.mkdir(parents=True, exist_ok=True)
        validated = VisualManifest.model_validate(manifest)
        target = directory / "visual-manifest.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(validated.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, target)

    def read_manifest(self, *, history_id: str, report_id: str) -> dict[str, Any]:
        target = self._required_file(self._directory(history_id, report_id) / "visual-manifest.json", "report_vega_visual_manifest_not_found")
        try:
            value = VisualManifest.model_validate_json(target.read_text(encoding="utf-8"))
        except Exception as exc:
            raise LookupError("report_vega_visual_manifest_not_found") from exc
        if value.history_id != history_id or value.report_id != report_id:
            raise LookupError("report_vega_visual_manifest_not_found")
        return value.model_dump(mode="json")

    @staticmethod
    def validate_asset_path(value: str) -> None:
        if not isinstance(value, str) or not _ASSET_PATH.fullmatch(value):
            raise ValueError("report_vega_visual_asset_path_invalid")

    def _manifest_asset_item(self, *, history_id: str, report_id: str, asset_id: str) -> dict[str, Any]:
        self._validate_id(asset_id, "asset_id")
        manifest = self.read_manifest(history_id=history_id, report_id=report_id)
        item = next((value for value in manifest.get("items", []) if isinstance(value, Mapping) and value.get("asset_id") == asset_id), None)
        if not isinstance(item, Mapping) or item.get("status") != "generated":
            raise LookupError("report_vega_visual_asset_not_found")
        return deepcopy(dict(item))

    def _asset_path_from_item(self, *, history_id: str, report_id: str, item: Mapping[str, Any]) -> Path:
        asset_path = item.get("asset_path")
        self.validate_asset_path(asset_path)
        target = (self._directory(history_id, report_id) / str(asset_path)).resolve()
        assets_directory = (self._directory(history_id, report_id) / "assets").resolve()
        if assets_directory not in target.parents or not target.is_file():
            raise LookupError("report_vega_visual_asset_not_found")
        return target

    def _directory(self, history_id: str, report_id: str) -> Path:
        self._validate_id(history_id, "history_id")
        self._validate_id(report_id, "report_id")
        return self._root / history_id / report_id

    @staticmethod
    def _required_file(target: Path, error: str) -> Path:
        if not target.is_file():
            raise LookupError(error)
        return target

    @staticmethod
    def _validate_id(value: str, field: str) -> None:
        if not isinstance(value, str) or not value or not _SAFE_ID.fullmatch(value):
            raise ValueError(f"invalid_{field}")


__all__ = ["ReportVegaVisualAssetStore"]
