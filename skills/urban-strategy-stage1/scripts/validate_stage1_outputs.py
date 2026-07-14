#!/usr/bin/env python3
"""Validate Stage 1 urban strategy run artifacts and evidence references."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ALLOWED_EVIDENCE_CLASSES = {
    "project_fact",
    "policy_or_plan",
    "measured_spatial_result",
    "observed_visual_evidence",
    "external_reference",
    "design_intent",
    "inference",
    "hypothesis",
}
ALLOWED_STATUSES = {"confirmed", "pending_verification", "conflicting", "not_available", "not_applicable"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
WORKPACKS = ("urban_planning", "cultural_tourism", "urban_renewal", "commercial_operations")
REPORT_HEADINGS = (
    "执行摘要",
    "任务与研究边界",
    "资料系统与可信度",
    "区域结构研判",
    "人群、活动与需求线索",
    "地方文化与文旅资产",
    "存量空间与更新条件",
    "机会主题与备选定位",
    "决策矩阵与推荐定位",
    "功能组合",
    "空间策略",
    "内容、运营与治理",
    "分期与验证计划",
    "设计任务书",
    "风险、缺口与下一步",
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"file_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json:{path}:{exc.lineno}:{exc.colno}") from exc


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _refs(value: Any) -> list[str]:
    return [_text(item) for item in _list(value) if _text(item)]


def _walk_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"evidence_refs", "evidence_ref"}:
                if isinstance(item, list):
                    yield from _refs(item)
                elif _text(item):
                    yield _text(item)
            else:
                yield from _walk_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_refs(item)


def _require_file(path: Path, errors: list[str]) -> bool:
    if not path.is_file():
        errors.append(f"missing_file:{path}")
        return False
    return True


def validate(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    work = run_dir / "work"
    output = run_dir / "output"
    errors: list[str] = []
    warnings: list[str] = []

    expected = [
        work / "source_readiness.json",
        work / "evidence_nodes.jsonl",
        work / "conflict_register.json",
        work / "strategy_options.json",
        work / "decision_matrix.json",
        output / "stage1_report.md",
        output / "evidence_appendix.md",
        output / "design_handoff.json",
        output / "run_manifest.json",
    ]
    for path in expected:
        _require_file(path, errors)
    for name in WORKPACKS:
        _require_file(work / "expert_workpacks" / f"{name}.json", errors)

    evidence_ids: set[str] = set()
    ledger_path = work / "evidence_nodes.jsonl"
    if ledger_path.is_file():
        for line_no, raw in enumerate(ledger_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                item = _dict(json.loads(raw))
            except json.JSONDecodeError as exc:
                errors.append(f"invalid_ledger_json:line={line_no}:{exc.msg}")
                continue
            evidence_id = _text(item.get("evidence_id"))
            if not evidence_id:
                errors.append(f"missing_evidence_id:line={line_no}")
            elif evidence_id in evidence_ids:
                errors.append(f"duplicate_evidence_id:{evidence_id}")
            else:
                evidence_ids.add(evidence_id)
            if item.get("evidence_class") not in ALLOWED_EVIDENCE_CLASSES:
                errors.append(f"invalid_evidence_class:{evidence_id or line_no}:{item.get('evidence_class')}")
            if item.get("status") not in ALLOWED_STATUSES:
                errors.append(f"invalid_evidence_status:{evidence_id or line_no}:{item.get('status')}")
            if item.get("confidence") not in ALLOWED_CONFIDENCE:
                errors.append(f"invalid_evidence_confidence:{evidence_id or line_no}:{item.get('confidence')}")
            if item.get("status") == "confirmed" and not _text(item.get("source_id")):
                errors.append(f"confirmed_without_source:{evidence_id or line_no}")
            if item.get("status") == "confirmed" and not _text(item.get("locator")):
                warnings.append(f"confirmed_without_locator:{evidence_id or line_no}")
    if not evidence_ids:
        errors.append("empty_evidence_nodes")

    referenced: set[str] = set()
    json_paths = [
        work / "strategy_options.json",
        work / "decision_matrix.json",
        output / "design_handoff.json",
        output / "run_manifest.json",
    ] + [work / "expert_workpacks" / f"{name}.json" for name in WORKPACKS]
    loaded: dict[Path, Any] = {}
    for path in json_paths:
        if not path.is_file():
            continue
        try:
            payload = _load_json(path)
            loaded[path] = payload
            referenced.update(_walk_refs(payload))
        except ValueError as exc:
            errors.append(str(exc))
    unknown_refs = sorted(referenced - evidence_ids)
    if unknown_refs:
        errors.extend(f"unknown_evidence_ref:{item}" for item in unknown_refs)

    report_path = output / "stage1_report.md"
    report_text = report_path.read_text(encoding="utf-8-sig") if report_path.is_file() else ""
    for heading in REPORT_HEADINGS:
        if heading not in report_text:
            errors.append(f"missing_report_section:{heading}")

    conflicts_path = work / "conflict_register.json"
    if conflicts_path.is_file():
        try:
            conflict_payload = _dict(_load_json(conflicts_path))
            for conflict in [_dict(item) for item in _list(conflict_payload.get("conflicts"))]:
                if conflict.get("severity") == "critical" and conflict.get("resolution") == "unresolved":
                    conflict_id = _text(conflict.get("conflict_id"))
                    topic = _text(conflict.get("topic"))
                    if conflict_id and conflict_id not in report_text and topic and topic not in report_text:
                        errors.append(f"critical_conflict_not_disclosed:{conflict_id}:{topic}")
        except ValueError as exc:
            errors.append(str(exc))

    handoff_path = output / "design_handoff.json"
    handoff = _dict(loaded.get(handoff_path))
    required_handoff = (
        "version",
        "project_identity",
        "preferred_positioning",
        "program",
        "spatial_strategy",
        "renewal_principles",
        "operational_requirements",
        "hard_constraints",
        "open_design_questions",
        "evidence_refs",
        "items_requiring_survey_or_approval",
    )
    for key in required_handoff:
        if key not in handoff:
            errors.append(f"missing_handoff_key:{key}")
    if handoff:
        positioning = _dict(handoff.get("preferred_positioning"))
        program = _dict(handoff.get("program"))
        spatial = _dict(handoff.get("spatial_strategy"))
        if not _text(positioning.get("statement")):
            errors.append("empty_handoff_positioning")
        if not _list(program.get("must_have")):
            errors.append("empty_handoff_must_have_program")
        if not _list(spatial.get("zones")):
            errors.append("empty_handoff_spatial_zones")
        if not _list(handoff.get("open_design_questions")):
            errors.append("empty_handoff_open_design_questions")
        if not _refs(handoff.get("evidence_refs")):
            errors.append("empty_handoff_evidence_refs")

    readiness_path = work / "source_readiness.json"
    if readiness_path.is_file():
        try:
            readiness = _dict(_load_json(readiness_path))
            if readiness.get("status") == "blocked":
                errors.append("source_readiness_blocked")
        except ValueError as exc:
            errors.append(str(exc))

    return {
        "status": "failed" if errors else ("passed_with_warnings" if warnings else "passed"),
        "run_dir": str(run_dir),
        "evidence_count": len(evidence_ids),
        "referenced_evidence_count": len(referenced),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = validate(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
