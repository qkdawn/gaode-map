#!/usr/bin/env python3
"""Query, validate, and index the spatial business metric catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ALLOWED_IMPLEMENTATION_STATUSES = {"implemented", "not_implemented"}
ALLOWED_SPATIAL_UNITS = {
    "scope",
    "sector",
    "distance_band",
    "catchment",
    "grid_cell",
    "hotspot_zone",
    "road_segment",
    "route",
    "origin_destination_pair",
    "shared_grid_direction_distance_band",
}
ALLOWED_NEIGHBORHOODS = {"none", "h3_k_ring", "distance", "network_radius", "origin_destination", "eight_direction_distance_band"}
ALLOWED_ACTION_TARGETS = {
    "site_direction",
    "program_location",
    "boundary_interface",
    "street_segment",
    "route",
    "public_space",
    "operations",
    "data_collection",
    "analysis_method",
}
ALLOWED_FOLLOWUP_PURPOSES = {"explain", "validate", "locate", "disconfirm"}
ALLOWED_BASELINE_TYPES = {
    "same_scope_previous_period",
    "same_source_peer_scope",
    "same_scope_category_share",
    "normalized_spatial_unit",
    "statistical_null_expectation",
    "route_or_spatial_alternative",
    "scenario_or_design_alternative",
    "documented_project_requirement",
    "all_shared_cells",
    "same_distance_band_other_sectors",
}
LEGACY_FIELDS = {"combine_with", "spatial_unit"}
# The discovery layer must describe observed spatial conditions, not promise an
# unmeasured commercial outcome. Detailed cards retain the appropriate boundary
# and validation guidance separately.
OVERPROMISING_DISCOVERY_TERMS = {
    "夜间经济活动": "夜间亮度空间分布或分级",
    "消费人口": "服务范围内人口分布",
    "商业机会": "空间条件或候选筛选",
}
REQUIRED_FIELDS = {
    "id",
    "name",
    "family",
    "implementation_status",
    "outputs",
    "required_inputs",
    "definition",
    "unit",
    "answers_questions",
    "spatial_granularities",
    "supports",
    "use_when",
    "actionability",
    "followup_metrics",
    "comparison_baseline",
    "valid_comparisons",
    "quality_requirements",
    "source",
}
def catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "metric-catalog.yaml"


def index_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "metric-catalog-index.yaml"



def load_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or catalog_path()
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    validate_catalog(payload, repository_root=target.resolve().parents[3])
    return payload


def _validate_discovery_language(metric: dict[str, Any]) -> None:
    """Keep catalog labels factual while allowing detailed boundary notes."""

    discovery_text = "\n".join(
        str(value).strip()
        for value in [metric.get("name"), *(metric.get("supports") or [])]
        if str(value).strip()
    )
    for term, replacement in OVERPROMISING_DISCOVERY_TERMS.items():
        if term in discovery_text:
            raise ValueError(
                f"{metric.get('id')} uses overpromising discovery language {term!r}; "
                f"use {replacement!r} instead"
            )


def validate_catalog(payload: dict[str, Any], *, repository_root: Path | None = None) -> None:
    if str(payload.get("catalog_version") or "") != "2.0.0":
        raise ValueError("catalog_version must be 2.0.0")
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("catalog.metrics must be a list")
    unknown_sections = {"available_derived_metrics", "planned_metrics"}.intersection(payload)
    if unknown_sections:
        raise ValueError(f"parallel metric sections are not allowed: {sorted(unknown_sections)}")
    seen: set[str] = set()
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise ValueError(f"metrics[{index}] must be an object")
        legacy = sorted(LEGACY_FIELDS.intersection(metric))
        if legacy:
            raise ValueError(f"metrics[{index}] uses legacy fields: {legacy}")
        missing = sorted(REQUIRED_FIELDS.difference(metric))
        if missing:
            raise ValueError(f"metrics[{index}] missing fields: {missing}")
        metric_id = str(metric.get("id") or "").strip()
        if not metric_id:
            raise ValueError(f"metrics[{index}].id is required")
        if metric_id in seen:
            raise ValueError(f"duplicate metric id: {metric_id}")
        seen.add(metric_id)
        status = str(metric.get("implementation_status") or "")
        if status not in ALLOWED_IMPLEMENTATION_STATUSES:
            raise ValueError(f"{metric_id} has unsupported implementation_status: {status}")
        for field in ("name", "family", "definition", "unit"):
            if not str(metric.get(field) or "").strip():
                raise ValueError(f"{metric_id}.{field} is required")
        _validate_discovery_language(metric)
        list_fields = (
            "outputs",
            "required_inputs",
            "answers_questions",
            "spatial_granularities",
            "supports",
            "use_when",
            "followup_metrics",
            "valid_comparisons",
            "quality_requirements",
            "source",
        )
        for field in list_fields:
            if not isinstance(metric.get(field), list):
                raise ValueError(f"{metric_id}.{field} must be a list")
        for field in (
            "required_inputs",
            "answers_questions",
            "spatial_granularities",
            "supports",
            "use_when",
            "valid_comparisons",
            "quality_requirements",
        ):
            if not metric.get(field):
                raise ValueError(f"{metric_id}.{field} must not be empty")
        if status == "implemented" and not metric.get("outputs"):
            raise ValueError(f"{metric_id}.outputs must not be empty when implemented")
        if status == "implemented" and not metric.get("source"):
            raise ValueError(f"{metric_id}.source must not be empty when implemented")
        if repository_root is not None and status == "implemented":
            for source in metric.get("source") or []:
                source_path = repository_root / str(source)
                if not source_path.exists():
                    raise ValueError(f"{metric_id} references missing source: {source}")

        for granularity in metric["spatial_granularities"]:
            if not isinstance(granularity, dict):
                raise ValueError(f"{metric_id}.spatial_granularities entries must be objects")
            if set(granularity) != {"unit", "neighborhood", "runtime_parameters"}:
                raise ValueError(f"{metric_id}.spatial_granularities has invalid fields")
            if granularity["unit"] not in ALLOWED_SPATIAL_UNITS:
                raise ValueError(f"{metric_id} has unsupported spatial unit: {granularity['unit']}")
            if granularity["neighborhood"] not in ALLOWED_NEIGHBORHOODS:
                raise ValueError(f"{metric_id} has unsupported neighborhood: {granularity['neighborhood']}")
            if not isinstance(granularity["runtime_parameters"], list):
                raise ValueError(f"{metric_id}.runtime_parameters must be a list")

        actionability = metric.get("actionability")
        if not isinstance(actionability, dict) or set(actionability) != {"action_targets", "possible_actions"}:
            raise ValueError(f"{metric_id}.actionability must contain action_targets and possible_actions")
        if not isinstance(actionability["action_targets"], list) or not actionability["action_targets"]:
            raise ValueError(f"{metric_id}.actionability.action_targets must be a non-empty list")
        unknown_targets = sorted(set(actionability["action_targets"]) - ALLOWED_ACTION_TARGETS)
        if unknown_targets:
            raise ValueError(f"{metric_id} has unsupported action targets: {unknown_targets}")
        if not isinstance(actionability["possible_actions"], list) or not actionability["possible_actions"]:
            raise ValueError(f"{metric_id}.actionability.possible_actions must be a non-empty list")

        for followup in metric["followup_metrics"]:
            if not isinstance(followup, dict) or set(followup) != {"metric_id", "purpose", "trigger"}:
                raise ValueError(f"{metric_id}.followup_metrics entries must contain metric_id, purpose, trigger")
            if followup["purpose"] not in ALLOWED_FOLLOWUP_PURPOSES:
                raise ValueError(f"{metric_id} has unsupported followup purpose: {followup['purpose']}")
            if not str(followup["trigger"] or "").strip():
                raise ValueError(f"{metric_id}.followup_metrics.trigger is required")

        baseline = metric.get("comparison_baseline")
        if not isinstance(baseline, dict) or set(baseline) != {"required", "preferred"}:
            raise ValueError(
                f"{metric_id}.comparison_baseline must contain required, preferred"
            )
        if not isinstance(baseline["required"], bool):
            raise ValueError(f"{metric_id}.comparison_baseline.required must be boolean")
        if not isinstance(baseline["preferred"], list) or not baseline["preferred"]:
            raise ValueError(f"{metric_id}.comparison_baseline.preferred must be a non-empty list")
        unknown_baselines = sorted(set(baseline["preferred"]) - ALLOWED_BASELINE_TYPES)
        if unknown_baselines:
            raise ValueError(f"{metric_id} has unsupported comparison baselines: {unknown_baselines}")

    for metric in metrics:
        unknown_followups = sorted(
            {str(item.get("metric_id") or "") for item in metric["followup_metrics"]} - seen
        )
        if unknown_followups:
            raise ValueError(f"{metric['id']} references unknown followup metrics: {unknown_followups}")


def _catalog_item(metric: dict[str, Any]) -> dict[str, Any]:
    """Project one detailed metric into the V4.1 discovery contract."""

    spatial_granularities = metric.get("spatial_granularities") or []
    first_granularity = spatial_granularities[0] if spatial_granularities else {}
    actionability = metric.get("actionability") or {}
    purpose_candidates = metric.get("supports") or metric.get("answers_questions") or [metric.get("definition")]
    purpose = next((str(value).strip() for value in purpose_candidates if str(value).strip()), "空间项目判断")
    return {
        "tool_id": str(metric["id"]),
        "name": str(metric["name"]),
        "purpose": purpose,
        "question_tags": sorted({str(tag) for tag in metric.get("use_when") or [] if str(tag).strip()}),
        "primary_spatial_unit": str(first_granularity.get("unit") or "scope"),
        "action_targets": sorted({str(target) for target in actionability.get("action_targets") or [] if str(target).strip()}),
        "implementation_status": str(metric["implementation_status"]),
    }


def build_index_payload(payload: dict[str, Any], *, catalog_file: Path) -> dict[str, Any]:
    """Build the catalog authors see before selecting a tool.

    Deliberately omit source coverage, runtime rules, input schemas, and detailed
    semantics. Those belong to the tool module and ``detail(tool_id)``.
    """

    del catalog_file  # The V4.1 discovery artifact intentionally has no provenance internals.
    metrics = [_catalog_item(metric) for metric in payload.get("metrics") or []]
    return {"metrics": sorted(metrics, key=lambda item: item["tool_id"])}

def write_index(payload: dict[str, Any], *, target: Path) -> None:
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120))


def validate_index(payload: dict[str, Any], *, catalog: dict[str, Any], catalog_file: Path) -> None:
    expected = build_index_payload(catalog, catalog_file=catalog_file)
    if payload != expected:
        raise ValueError("metric catalog index is stale; run build-index")


def detail_metric(payload: dict[str, Any], metric_id: str) -> dict[str, Any]:
    by_id = {str(item.get("id")): item for item in payload.get("metrics") or []}
    try:
        return by_id[metric_id]
    except KeyError as exc:
        raise KeyError(metric_id) from exc

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=catalog_path())
    parser.add_argument("--index", type=Path, default=index_path())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog", help="Read the lightweight V4.1 metric catalog")
    detail_parser = subparsers.add_parser("detail", help="Read details for a selected metric")
    detail_parser.add_argument("tool_id")
    subparsers.add_parser("validate", help="Validate the detailed tool definitions")
    subparsers.add_parser("build-index", help="Generate the lightweight V4.1 metric catalog")
    subparsers.add_parser("validate-index", help="Validate that the V4.1 catalog matches tool definitions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "catalog":
            index = yaml.safe_load(args.index.read_text(encoding="utf-8")) or {}
            metrics = index.get("metrics")
            if not isinstance(metrics, list):
                raise ValueError("metric catalog index must contain metrics")
            output = {"count": len(metrics), "metrics": metrics}
        else:
            payload = load_catalog(args.catalog)
            if args.command == "detail":
                output = {"metric": detail_metric(payload, args.tool_id)}
            elif args.command == "build-index":
                index = build_index_payload(payload, catalog_file=args.catalog)
                write_index(index, target=args.index)
                output = {"written": str(args.index), "metric_count": len(index["metrics"])}
            elif args.command == "validate-index":
                index = yaml.safe_load(args.index.read_text(encoding="utf-8")) or {}
                validate_index(index, catalog=payload, catalog_file=args.catalog)
                output = {"valid": True, "metric_count": len(index["metrics"])}
            else:
                output = {
                    "valid": True,
                    "catalog_version": payload.get("catalog_version"),
                    "metric_count": len(payload.get("metrics") or []),
                }
    except (OSError, ValueError, yaml.YAMLError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
