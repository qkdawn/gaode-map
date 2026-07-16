"""Immutable on-disk storage for AnalysisRun artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.config import settings


_V3_ROOT_ARTIFACT_FILENAMES = {
    "analysis_blueprint": "analysis-blueprint.json",
    "evidence_snapshot": "evidence-snapshot.json",
    "chapter_assignments": "chapter-assignments.json",
    "analyst_chapters": "analyst-chapters.json",
    "editorial_review": "editorial-review.json",
    "report_assembly": "report-assembly.json",
}
_SUCCESS_STATUSES = {"completed", "completed_with_warnings"}


class AnalysisRunStorageError(ValueError):
    """A persisted run cannot be safely read or reused."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_part(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"analysis_run_{field}_invalid")
    return value


def _filename(value: str, fallback: str, *, markdown: bool = False, svg: bool = False) -> str:
    candidate = Path(str(value or "").strip() or fallback)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.name:
        raise ValueError("analysis_run_filename_invalid")
    name = candidate.name
    if markdown and not name.lower().endswith(".md"):
        name = f"{name}.md"
    if svg and not name.lower().endswith(".svg"):
        name = f"{name}.svg"
    if not markdown and not svg and not Path(name).suffix:
        name = f"{name}.json"
    return name


class AnalysisRunStorage:
    """Own the run layout, integrity checks, and atomic publication protocol."""

    def __init__(self, root: str | Path | None = None) -> None:
        path = Path(root if root is not None else settings.analysis_run_storage_dir)
        self.root = (path if path.is_absolute() else Path.cwd() / path).resolve()

    def create(self, *, history_id: str, manifest: dict[str, Any], artifact_payloads: dict[str, Any], execution_request: dict[str, Any]) -> dict[str, Any]:
        capability_id = _safe_part(manifest.get("capability_id", ""), "capability_id")
        run_id = _safe_part(manifest.get("run_id", ""), "id")
        final = self.root / capability_id / run_id
        if final.exists():
            self.validate(capability_id, run_id)
            existing = self.read(capability_id, run_id)
            if not self._same(existing, history_id, manifest, artifact_payloads, execution_request):
                raise ValueError("analysis_run_immutable")
            return existing
        staging = self.root / capability_id / f".{run_id}.{uuid4().hex}.staging"
        try:
            staging.mkdir(parents=True, exist_ok=False)
            (staging / "inputs" / "upstream").mkdir(parents=True)
            if str(manifest.get("schema_version") or "") != "3.0":
                for folder in ("artifacts", "evidence", "chapters", "report", "diagnostics"):
                    (staging / folder).mkdir()
            self._write_json(staging / "analysis-run.json", {"history_id": history_id, "manifest": manifest})
            self._write_json(staging / "inputs" / "execution-request.json", execution_request)
            self._write_json(staging / "artifact-index.json", self._write_artifacts(staging, manifest, artifact_payloads))
            index_sha256 = _sha256((staging / "artifact-index.json").read_bytes())
            if self._is_publishable(manifest):
                (staging / ".complete").write_text(index_sha256, encoding="utf-8")
            else:
                self._write_json(
                    staging / ".run-state.json",
                    {"status": str(manifest.get("status") or ""), "artifact_index_sha256": index_sha256},
                )
            self._validate_directory(staging)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final)
            return self.read(capability_id, run_id)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

    def delete(self, capability_id: str, run_id: str) -> None:
        path = self._path(capability_id, run_id)
        if path.exists():
            shutil.rmtree(path)

    def read(self, capability_id: str, run_id: str) -> dict[str, Any]:
        path = self._path(capability_id, run_id)
        self.validate(capability_id, run_id)
        run_payload = self._read_json(path / "analysis-run.json")
        index = self._read_json(path / "artifact-index.json")
        artifacts = []
        for item in index.get("artifacts", []):
            payload = self._read_payload(path / item["path"], item["format"]) if item["direction"] == "output" else None
            artifacts.append({"direction": item["direction"], "artifact": deepcopy(item["artifact"]), "payload": payload})
        return {"history_id": str(run_payload["history_id"]), "run": deepcopy(run_payload["manifest"]), "artifacts": artifacts, "execution_request": self._read_json(path / "inputs" / "execution-request.json")}

    def validate(self, capability_id: str, run_id: str) -> None:
        path = self._path(capability_id, run_id)
        if not path.is_dir() or not (
            (path / ".complete").is_file() or (path / ".run-state.json").is_file()
        ):
            raise AnalysisRunStorageError("analysis_run_storage_missing")
        self._validate_directory(path)

    def _path(self, capability_id: str, run_id: str) -> Path:
        return self.root / _safe_part(capability_id, "capability_id") / _safe_part(run_id, "id")

    def _write_artifacts(self, base: Path, manifest: dict[str, Any], payloads: dict[str, Any]) -> dict[str, Any]:
        entries = []
        for direction, key in (("input", "input_artifact_refs"), ("output", "output_artifact_refs")):
            for artifact in manifest.get(key) or []:
                if not isinstance(artifact, dict) or not str(artifact.get("artifact_id") or "").strip():
                    continue
                artifact_id = str(artifact["artifact_id"])
                if direction == "input" and str(artifact.get("source_run_id") or "").strip():
                    relative, fmt = self._copy_upstream(base, artifact)
                else:
                    relative, fmt = self._write_artifact(base, direction, artifact, payloads.get(artifact_id) if direction == "output" else None)
                entries.append({"direction": direction, "artifact_id": artifact_id, "artifact_type": str(artifact.get("artifact_type") or "structured_data"), "path": relative.as_posix(), "format": fmt, "content_digest": str(artifact.get("content_digest") or ""), "sha256": _sha256((base / relative).read_bytes()), "artifact": deepcopy(artifact)})
        return {"version": 1, "artifacts": entries}

    def _write_artifact(self, base: Path, direction: str, artifact: dict[str, Any], payload: Any) -> tuple[Path, str]:
        artifact_type = str(artifact.get("artifact_type") or "structured_data")
        root_filename = _V3_ROOT_ARTIFACT_FILENAMES.get(artifact_type) if direction == "output" else None
        folder = "inputs" if direction == "input" else {"evidence_nodes": "evidence", "evidence_gates": "evidence", "report": "report", "report_visual": "report/assets", "report_chapter": "chapters", "diagnostic_report": "diagnostics"}.get(artifact_type, "artifacts")
        svg = artifact_type == "report_visual"
        if svg and not isinstance(payload, str):
            raise ValueError("analysis_run_report_visual_svg_required")
        markdown = not svg and isinstance(payload, str) and (artifact_type in {"report", "evidence_nodes"} or str(artifact.get("filename") or "").lower().endswith(".md"))
        relative = (
            Path(root_filename)
            if root_filename
            else Path(folder) / _filename(artifact.get("filename", ""), artifact["artifact_id"], markdown=markdown, svg=svg)
        )
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError("analysis_run_artifact_path_conflict")
        if svg:
            target.write_text(payload, encoding="utf-8", newline="\n")
            return relative, "svg"
        if markdown:
            target.write_text(payload or "", encoding="utf-8", newline="\n")
            return relative, "markdown"
        self._write_json(target, payload)
        return relative, "json"

    def _copy_upstream(self, base: Path, artifact: dict[str, Any]) -> tuple[Path, str]:
        source_run_id = _safe_part(artifact.get("source_run_id", ""), "id")
        matches = list(self.root.glob(f"*/{source_run_id}/artifact-index.json"))
        if len(matches) != 1:
            raise AnalysisRunStorageError("analysis_run_storage_missing")
        source = matches[0].parent
        self._validate_directory(source)
        entry = next((item for item in self._read_json(source / "artifact-index.json").get("artifacts", []) if item.get("direction") == "output" and item.get("artifact_id") == artifact["artifact_id"]), None)
        if entry is None:
            raise AnalysisRunStorageError("analysis_run_storage_missing")
        relative = Path("inputs") / "upstream" / source_run_id / Path(entry["path"]).name
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / entry["path"], target)
        return relative, str(entry["format"])

    def _validate_directory(self, path: Path) -> None:
        try:
            index_raw = (path / "artifact-index.json").read_bytes()
            run_payload = self._read_json(path / "analysis-run.json")
            manifest = run_payload.get("manifest") if isinstance(run_payload, dict) else None
            if not isinstance(manifest, dict):
                raise ValueError
            expected_index_sha256 = _sha256(index_raw)
            if self._is_publishable(manifest):
                if not (path / ".complete").is_file() or (path / ".run-state.json").exists():
                    raise ValueError
                if (path / ".complete").read_text(encoding="utf-8").strip() != expected_index_sha256:
                    raise ValueError
            elif str(manifest.get("schema_version") or "") == "3.0":
                if (path / ".complete").exists() or not (path / ".run-state.json").is_file():
                    raise ValueError
                state = self._read_json(path / ".run-state.json")
                if state != {
                    "status": str(manifest.get("status") or ""),
                    "artifact_index_sha256": expected_index_sha256,
                }:
                    raise ValueError
            index = json.loads(index_raw)
            self._read_json(path / "inputs" / "execution-request.json")
            if str(manifest.get("schema_version") or "") == "3.0" and not self._is_publishable(manifest):
                forbidden = {"report", "report_visual"}
                if any(
                    item.get("direction") == "output" and item.get("artifact_type") in forbidden
                    for item in index.get("artifacts", [])
                ):
                    raise ValueError
            for item in index.get("artifacts", []):
                relative = Path(str(item["path"]))
                if relative.is_absolute() or ".." in relative.parts or not (path / relative).is_file() or _sha256((path / relative).read_bytes()) != item["sha256"]:
                    raise ValueError
                fmt = str(item["format"])
                if item.get("direction") == "output" and item.get("artifact_type") == "report_visual":
                    if fmt != "svg" or relative.suffix.lower() != ".svg" or relative.parent.as_posix() != "report/assets":
                        raise ValueError
                if item.get("direction") == "output" and item.get("artifact_type") == "report_chapter":
                    if fmt != "json" or relative.suffix.lower() != ".json" or relative.parent.as_posix() != "chapters":
                        raise ValueError
                self._read_payload(path / relative, fmt)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AnalysisRunStorageError("analysis_run_storage_corrupt") from exc

    @staticmethod
    def _same(existing: dict[str, Any], history_id: str, manifest: dict[str, Any], payloads: dict[str, Any], request: dict[str, Any]) -> bool:
        outputs = {item["artifact"]["artifact_id"]: item["payload"] for item in existing["artifacts"] if item["direction"] == "output"}
        return existing["history_id"] == history_id and existing["run"] == manifest and existing["execution_request"] == request and outputs == payloads

    @staticmethod
    def _is_publishable(manifest: dict[str, Any]) -> bool:
        if str(manifest.get("schema_version") or "") != "3.0":
            return True
        return str(manifest.get("status") or "") in _SUCCESS_STATUSES

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_json_bytes(value))

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_payload(path: Path, fmt: str) -> Any:
        if fmt in {"markdown", "svg"}:
            return path.read_text(encoding="utf-8")
        if fmt == "json":
            return AnalysisRunStorage._read_json(path)
        raise ValueError("analysis_run_artifact_format_invalid")


analysis_run_storage = AnalysisRunStorage()
