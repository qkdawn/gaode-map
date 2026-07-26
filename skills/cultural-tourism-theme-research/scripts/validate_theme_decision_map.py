#!/usr/bin/env python3
"""Validate the machine-readable theme decision map consumed by the parent skill."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


NODE_FIELDS = ("id", "decision_question", "judgment", "action", "counterexample", "validation", "status")
LIST_FIELDS = ("when", "alternatives", "evidence_refs", "limitations")
METRIC_FIELDS = ("result_id", "tool_id", "observation", "comparison_basis", "decision_effect", "does_not_prove")


def validate(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["decision map must be an object"]
    errors: list[str] = []
    if payload.get("schema") != "cultural-tourism-theme-decision-map":
        errors.append("schema must be cultural-tourism-theme-decision-map")
    if payload.get("project_identity") not in {"confirmed", "context_only"}:
        errors.append("project_identity must be confirmed or context_only")
    if payload.get("status") not in {"ready", "source_discovery_only"}:
        errors.append("status must be ready or source_discovery_only")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*errors, "nodes must contain at least one theme judgment"]
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("every node must be an object")
            continue
        for field in NODE_FIELDS:
            if not isinstance(node.get(field), str) or not node[field].strip():
                errors.append(f"node field {field} must be a non-empty string")
        for field in LIST_FIELDS:
            if not isinstance(node.get(field), list):
                errors.append(f"node field {field} must be a list")
        if isinstance(node.get("when"), list) and not node["when"]:
            errors.append("node field when must contain at least one condition")
        if node.get("status") not in {"supported", "conditional", "excluded"}:
            errors.append("node status is invalid")
        metric_refs = node.get("metric_refs", [])
        if not isinstance(metric_refs, list):
            errors.append("metric_refs must be a list when present")
        else:
            for metric in metric_refs:
                if not isinstance(metric, dict) or any(
                    not isinstance(metric.get(field), str) or not metric[field].strip() for field in METRIC_FIELDS
                ):
                    errors.append("metric reference lacks provenance, effect or inference boundary")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_theme_decision_map.py <theme-decision-map.json>")
        return 2
    path = Path(sys.argv[1])
    try:
        errors = validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL cannot read decision map: {exc}")
        return 2
    if errors:
        print("FAIL theme decision map validation")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS theme decision map validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
