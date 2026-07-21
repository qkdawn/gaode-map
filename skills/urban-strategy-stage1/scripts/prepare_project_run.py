#!/usr/bin/env python3
"""Create a non-destructive Stage 1 run workspace from a full sources export."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"file_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json:{path}:{exc.lineno}:{exc.colno}") from exc


def _safe_id(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in cleaned.split("-") if part) or "urban-project"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-export", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--analysis-scope", type=Path)
    parser.add_argument("--coordinate-system", default="GCJ-02")
    parser.add_argument("--source-cutoff-date", default=str(date.today()))
    args = parser.parse_args()

    source_path = args.sources_export.resolve()
    try:
        source_export = _load_json(source_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not isinstance(source_export, dict) or source_export.get("export_type") != "ppt_all_sources_full_export":
        print("invalid_sources_export:export_type must equal ppt_all_sources_full_export", file=sys.stderr)
        return 1

    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        print(f"target_not_empty:{out}", file=sys.stderr)
        return 1

    input_dir = out / "input"
    work_dir = out / "work" / "expert_workpacks"
    output_dir = out / "output"
    for directory in (input_dir, work_dir, output_dir):
        directory.mkdir(parents=True, exist_ok=True)

    source_target = input_dir / "ppt_sources_full_export.json"
    shutil.copy2(source_path, source_target)

    skill_root = Path(__file__).resolve().parent.parent
    brief_target = input_dir / "project_brief.md"
    shutil.copy2(skill_root / "assets" / "project_brief.template.md", brief_target)

    scope_ref = ""
    analysis_scope: dict[str, Any] = {"type": "unresolved", "status": "pending_verification"}
    analysis_areas = [{"id": "analysis-scope", "label": "分析范围", "kind": "analysis_scope", "status": "pending_verification"}]
    if args.analysis_scope:
        scope_path = args.analysis_scope.resolve()
        if not scope_path.is_file():
            print(f"analysis_scope_not_found:{scope_path}", file=sys.stderr)
            return 1
        scope_target = input_dir / "analysis_scope.geojson"
        shutil.copy2(scope_path, scope_target)
        scope_ref = scope_target.name
        analysis_scope = {"type": "Feature", "geometry_ref": scope_ref, "status": "provided"}
        analysis_areas[0]["status"] = "provided"

    sources = source_export.get("sources") if isinstance(source_export.get("sources"), list) else []
    document_ids: list[str] = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        source_id = str(source.get("id") or "").strip()
        source_kind = str(source.get("source_kind") or "").strip()
        if source_id and source_kind == "document" and source.get("status") == "ready":
            document_ids.append(source_id)

    today = str(date.today())
    package = {
        "package_type": "urban_project_analysis_package",
        "version": "v1",
        "project": {
            "project_id": args.project_id.strip() or _safe_id(args.project_name),
            "name": args.project_name.strip(),
            "location": args.location.strip(),
            "analysis_date": today,
            "source_cutoff_date": args.source_cutoff_date,
        },
        "brief": {
            "decision_questions": ["该地区在现有约束下最适合承载什么功能，为什么？"],
            "goals": ["形成第一阶段项目定位、功能策略与设计前置任务书"],
            "non_goals": ["本阶段不确定建筑造型、结构、材料和施工做法"],
            "known_constraints": [],
            "stakeholders": [],
            "core_source_ids": document_ids[:5],
            "preferred_report_language": "zh-CN",
        },
        "scope": {
            "analysis_scope": analysis_scope,
            "analysis_areas": analysis_areas,
            "coordinate_system": args.coordinate_system,
            "scope_ids": ["analysis-scope"],
        },
        "inputs": {
            "sources_export": source_target.name,
            "project_brief": brief_target.name,
            "visual_snapshots": [],
            "additional_files": [],
        },
        "quality": {
            "known_missing_items": [] if scope_ref else ["分析范围 GeoJSON 尚未提供"],
            "known_conflicts": [],
            "notes": ["请编辑 project_brief.md，并确认 core_source_ids。"],
        },
        "requested_deliverables": ["stage1_report", "evidence_appendix", "design_handoff"],
    }
    if scope_ref:
        package["inputs"]["analysis_scope_geojson"] = scope_ref

    package_path = input_dir / "urban_project_analysis_package.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "created",
        "run_dir": str(out),
        "package": str(package_path),
        "document_core_source_candidates": document_ids,
        "next_actions": [
            f"Edit {brief_target}",
            f"Review {package_path}",
            "Run validate_project_package.py before analysis",
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
