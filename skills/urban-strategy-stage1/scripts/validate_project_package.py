#!/usr/bin/env python3
"""Validate an UrbanProjectAnalysisPackage and optionally write readiness JSON."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"file_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json:{path}:{exc.lineno}:{exc.colno}") from exc


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve(base: Path, value: Any) -> Path | None:
    raw = _text(value)
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else (base / path).resolve()


def _source_id(item: dict[str, Any]) -> str:
    source = _dict(item.get("source"))
    full_source = _dict(item.get("full_source"))
    return _text(source.get("id") or full_source.get("id") or item.get("id"))


def _source_status(item: dict[str, Any]) -> str:
    source = _dict(item.get("source"))
    full_source = _dict(item.get("full_source"))
    return _text(source.get("status") or full_source.get("status") or item.get("status"))


def _has_evidence_payload(item: dict[str, Any]) -> bool:
    if _list(item.get("evidence_nodes")):
        return True
    payload = _dict(item.get("ai_payload"))
    return bool(payload and any(value not in (None, "", [], {}) for value in payload.values()))


def validate(package_path: Path) -> dict[str, Any]:
    package_path = package_path.resolve()
    base = package_path.parent
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []

    try:
        package = _dict(_load_json(package_path))
    except ValueError as exc:
        return {
            "status": "blocked",
            "package_path": str(package_path),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "errors": [str(exc)],
            "warnings": [],
            "checks": [],
        }

    def require(condition: bool, code: str, detail: str) -> None:
        checks.append({"code": code, "passed": bool(condition), "detail": detail})
        if not condition:
            errors.append(f"{code}:{detail}")

    require(package.get("package_type") == "urban_project_analysis_package", "package_type", "must equal urban_project_analysis_package")
    require(package.get("version") == "v1", "package_version", "must equal v1")

    project = _dict(package.get("project"))
    require(bool(_text(project.get("project_id"))), "project_id", "project.project_id is required")
    require(bool(_text(project.get("name"))), "project_name", "project.name is required")
    require(bool(_text(project.get("analysis_date"))), "analysis_date", "project.analysis_date is required")
    require(bool(_text(project.get("source_cutoff_date"))), "source_cutoff_date", "project.source_cutoff_date is required")

    brief = _dict(package.get("brief"))
    require(bool(_list(brief.get("decision_questions"))), "decision_questions", "at least one decision question is required")
    require(bool(_list(brief.get("goals"))), "project_goals", "at least one goal is required")

    scope = _dict(package.get("scope"))
    require(bool(_dict(scope.get("project_boundary"))), "project_boundary", "scope.project_boundary is required")
    require(bool(_list(scope.get("analysis_areas"))), "analysis_areas", "at least one analysis area is required")
    require(bool(_text(scope.get("coordinate_system"))), "coordinate_system", "scope.coordinate_system is required")

    requested = {_text(item) for item in _list(package.get("requested_deliverables"))}
    require("stage1_report" in requested, "stage1_deliverable", "stage1_report must be requested")
    require("design_handoff" in requested, "handoff_deliverable", "design_handoff must be requested")

    inputs = _dict(package.get("inputs"))
    paths: dict[str, str] = {}
    for key in ("sources_export", "project_brief", "boundary_geojson"):
        path = _resolve(base, inputs.get(key))
        if path is None:
            if key != "boundary_geojson":
                errors.append(f"input_path:{key} is required")
            continue
        paths[key] = str(path)
        require(path.is_file(), f"input_{key}", f"file must exist: {path}")

    for collection_key in ("visual_snapshots", "additional_files"):
        for index, raw in enumerate(_list(inputs.get(collection_key))):
            path = _resolve(base, raw)
            if path is None or not path.is_file():
                warnings.append(f"missing_optional_file:{collection_key}[{index}]:{path or raw}")

    source_summary: dict[str, Any] = {
        "total": 0,
        "ready": 0,
        "with_evidence_payload": 0,
        "core_source_ids": _list(brief.get("core_source_ids")),
        "missing_core_source_ids": [],
        "unreadable_core_source_ids": [],
    }
    source_path = Path(paths["sources_export"]) if paths.get("sources_export") else None
    if source_path and source_path.is_file():
        try:
            source_export = _dict(_load_json(source_path))
            require(source_export.get("export_type") == "ppt_all_sources_full_export", "sources_export_type", "must equal ppt_all_sources_full_export")
            sources = [_dict(item) for item in _list(source_export.get("sources"))]
            source_summary["total"] = len(sources)
            source_summary["ready"] = sum(_source_status(item) == "ready" for item in sources)
            source_summary["with_evidence_payload"] = sum(_has_evidence_payload(item) for item in sources)
            require(bool(sources), "sources_present", "sources export must contain sources")
            require(source_summary["ready"] > 0, "ready_sources", "at least one source must be ready")
            by_id = {_source_id(item): item for item in sources if _source_id(item)}
            core_ids = [_text(item) for item in _list(brief.get("core_source_ids")) if _text(item)]
            if not core_ids:
                warnings.append("core_sources_not_declared:brief.core_source_ids is empty")
            for source_id in core_ids:
                source = by_id.get(source_id)
                if source is None:
                    source_summary["missing_core_source_ids"].append(source_id)
                elif _source_status(source) != "ready" or not _has_evidence_payload(source):
                    source_summary["unreadable_core_source_ids"].append(source_id)
            require(not source_summary["missing_core_source_ids"], "core_sources_present", "all declared core sources must exist")
            require(not source_summary["unreadable_core_source_ids"], "core_sources_readable", "all declared core sources must be ready and carry evidence payload")
        except ValueError as exc:
            errors.append(str(exc))

    quality = _dict(package.get("quality"))
    known_missing = [_text(item) for item in _list(quality.get("known_missing_items")) if _text(item)]
    known_conflicts = [_text(item) for item in _list(quality.get("known_conflicts")) if _text(item)]
    if known_missing:
        warnings.append(f"declared_missing_items:{len(known_missing)}")
    if known_conflicts:
        warnings.append(f"declared_conflicts:{len(known_conflicts)}")

    return {
        "status": "blocked" if errors else ("needs_review" if warnings else "ready"),
        "package_path": str(package_path),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "project_id": _text(project.get("project_id")),
        "project_name": _text(project.get("name")),
        "resolved_inputs": paths,
        "source_summary": source_summary,
        "declared_quality": {
            "known_missing_items": known_missing,
            "known_conflicts": known_conflicts,
        },
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--write-readiness", type=Path)
    args = parser.parse_args()

    result = validate(args.package)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.write_readiness:
        target = args.write_readiness.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
