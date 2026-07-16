#!/usr/bin/env python3
"""Query, validate, and index the spatial business metric catalog."""

from __future__ import annotations

import argparse
import hashlib
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
    "entrance",
    "road_segment",
    "route",
    "origin_destination_pair",
}
ALLOWED_NEIGHBORHOODS = {"none", "h3_k_ring", "distance", "network_radius", "origin_destination"}
ALLOWED_ACTION_TARGETS = {
    "site_direction",
    "program_location",
    "entrance",
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
    "route_or_entrance_alternative",
    "scenario_or_design_alternative",
    "documented_project_requirement",
}
LEGACY_FIELDS = {"combine_with", "spatial_unit"}
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
    "does_not_support",
    "use_when",
    "actionability",
    "followup_metrics",
    "comparison_baseline",
    "valid_comparisons",
    "quality_requirements",
    "source",
}
DATA_DOMAINS = (
    {
        "id": "poi",
        "source_ids": ["current:dataset:poi"],
        "families": ["poi"],
    },
    {
        "id": "h3_grid",
        "source_ids": ["current:dataset:h3"],
        "families": ["poi_grid", "spatial_statistics"],
    },
    {
        "id": "population",
        "source_ids": ["current:dataset:population"],
        "families": ["population"],
    },
    {
        "id": "nightlight",
        "source_ids": ["current:dataset:nightlight"],
        "families": ["nightlight"],
    },
    {
        "id": "road",
        "source_ids": ["current:dataset:road"],
        "families": ["road_syntax"],
    },
    {
        "id": "cross_domain",
        "source_ids": [
            "current:dataset:poi",
            "current:dataset:h3",
            "current:dataset:population",
            "current:dataset:nightlight",
            "current:dataset:road",
        ],
        "families": [
            "cross_domain",
            "grid_derived",
            "gwr",
            "isochrone",
            "timeseries",
        ],
    },
    {
        "id": "project_evidence_gates",
        "source_ids": [
            "project:boundary",
            "project:competitor-operations",
            "project:operator-plan",
            "project:financial-model",
        ],
        "families": ["project_evidence_gate"],
    },
)


def catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "metric-catalog.yaml"


def index_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "metric-catalog-index.yaml"


def _catalog_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or catalog_path()
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    validate_catalog(payload, repository_root=target.resolve().parents[3])
    return payload


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
        if status == "not_implemented" and not str(metric.get("implementation_gap") or "").strip():
            raise ValueError(f"{metric_id} must declare implementation_gap")
        for field in ("name", "family", "definition", "unit"):
            if not str(metric.get(field) or "").strip():
                raise ValueError(f"{metric_id}.{field} is required")
        list_fields = (
            "outputs",
            "required_inputs",
            "answers_questions",
            "spatial_granularities",
            "supports",
            "does_not_support",
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
            "does_not_support",
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
        if not isinstance(baseline, dict) or set(baseline) != {"required", "preferred", "if_missing"}:
            raise ValueError(
                f"{metric_id}.comparison_baseline must contain required, preferred, if_missing"
            )
        if not isinstance(baseline["required"], bool):
            raise ValueError(f"{metric_id}.comparison_baseline.required must be boolean")
        if not isinstance(baseline["preferred"], list) or not baseline["preferred"]:
            raise ValueError(f"{metric_id}.comparison_baseline.preferred must be a non-empty list")
        unknown_baselines = sorted(set(baseline["preferred"]) - ALLOWED_BASELINE_TYPES)
        if unknown_baselines:
            raise ValueError(f"{metric_id} has unsupported comparison baselines: {unknown_baselines}")
        if not str(baseline["if_missing"] or "").strip():
            raise ValueError(f"{metric_id}.comparison_baseline.if_missing is required")

    known_families = {str(metric.get("family") or "") for metric in metrics}
    indexed_families = {family for domain in DATA_DOMAINS for family in domain["families"]}
    if known_families != indexed_families:
        raise ValueError(
            f"catalog families and index domains differ: missing={sorted(known_families - indexed_families)}, "
            f"unknown={sorted(indexed_families - known_families)}"
        )
    for metric in metrics:
        unknown_followups = sorted(
            {str(item.get("metric_id") or "") for item in metric["followup_metrics"]} - seen
        )
        if unknown_followups:
            raise ValueError(f"{metric['id']} references unknown followup metrics: {unknown_followups}")


def build_index_payload(payload: dict[str, Any], *, catalog_file: Path) -> dict[str, Any]:
    metrics = list(payload.get("metrics") or [])
    domains = []
    for spec in DATA_DOMAINS:
        family_set = set(spec["families"])
        selected = [item for item in metrics if str(item.get("family") or "") in family_set]
        domains.append(
            {
                "id": spec["id"],
                "source_ids": list(spec["source_ids"]),
                "families": list(spec["families"]),
                "metrics": [
                    {
                        "metric_id": str(item["id"]),
                        "decision_tags": sorted(
                            {str(tag) for tag in item.get("use_when") or [] if str(tag).strip()}
                        ),
                        "primary_spatial_unit": str(item["spatial_granularities"][0]["unit"]),
                        "action_targets": list(item["actionability"]["action_targets"]),
                        "implementation_status": str(item["implementation_status"]),
                    }
                    for item in selected
                ],
                "detail_queries": [
                    f"python skills/spatial-business-analyst/scripts/metric_catalog.py list --family {family}"
                    for family in spec["families"]
                ],
            }
        )
    return {
        "index_version": "2.0.0",
        "catalog_version": payload.get("catalog_version"),
        "catalog_sha256": _catalog_sha256(catalog_file),
        "generated_from": "references/metric-catalog.yaml",
        "runtime_rule": "Use source coverage to predict succeeded versus blocked attempts; keep decision-critical unavailable metrics in MetricPlan and exclude only metrics judged irrelevant.",
        "data_domains": domains,
    }


def write_index(payload: dict[str, Any], *, target: Path) -> None:
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def validate_index(payload: dict[str, Any], *, catalog: dict[str, Any], catalog_file: Path) -> None:
    expected = build_index_payload(catalog, catalog_file=catalog_file)
    if payload != expected:
        raise ValueError("metric catalog index is stale; run build-index")


def _matches(value: str, filters: list[str]) -> bool:
    if not filters:
        return True
    normalized = value.strip().lower()
    return any(normalized == item.strip().lower() for item in filters)


def list_metrics(
    payload: dict[str, Any],
    *,
    families: list[str] | None = None,
    implementation_statuses: list[str] | None = None,
    use_when: list[str] | None = None,
) -> list[dict[str, Any]]:
    family_filters = families or []
    status_filters = implementation_statuses or []
    use_filters = [item.strip().lower() for item in (use_when or []) if item.strip()]
    result = []
    for metric in payload.get("metrics") or []:
        if not _matches(str(metric.get("family") or ""), family_filters):
            continue
        if not _matches(str(metric.get("implementation_status") or ""), status_filters):
            continue
        tags = [str(item).strip().lower() for item in metric.get("use_when") or []]
        if use_filters and not any(any(query in tag for tag in tags) for query in use_filters):
            continue
        result.append(metric)
    return result


def describe_metrics(payload: dict[str, Any], metric_ids: list[str]) -> list[dict[str, Any]]:
    by_id = {str(item.get("id")): item for item in payload.get("metrics") or []}
    missing = [metric_id for metric_id in metric_ids if metric_id not in by_id]
    if missing:
        raise KeyError(", ".join(missing))
    return [by_id[metric_id] for metric_id in metric_ids]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=catalog_path())
    parser.add_argument("--index", type=Path, default=index_path())
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="List metrics with optional filters")
    list_parser.add_argument("--family", action="append", default=[])
    list_parser.add_argument("--implementation-status", action="append", default=[])
    list_parser.add_argument("--use-when", action="append", default=[])
    describe_parser = subparsers.add_parser("describe", help="Describe one or more metric ids")
    describe_parser.add_argument("metric_id", nargs="+")
    subparsers.add_parser("validate", help="Validate the detailed catalog contract")
    subparsers.add_parser("build-index", help="Generate the compact startup index")
    subparsers.add_parser("validate-index", help="Validate that the startup index matches the catalog")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = load_catalog(args.catalog)
        if args.command == "list":
            metrics = list_metrics(
                payload,
                families=args.family,
                implementation_statuses=args.implementation_status,
                use_when=args.use_when,
            )
            output = {"count": len(metrics), "metrics": metrics}
        elif args.command == "describe":
            metrics = describe_metrics(payload, args.metric_id)
            output = {"count": len(metrics), "metrics": metrics}
        elif args.command == "build-index":
            index = build_index_payload(payload, catalog_file=args.catalog)
            write_index(index, target=args.index)
            output = {"written": str(args.index), "data_domain_count": len(index["data_domains"])}
        elif args.command == "validate-index":
            index = yaml.safe_load(args.index.read_text(encoding="utf-8")) or {}
            validate_index(index, catalog=payload, catalog_file=args.catalog)
            output = {
                "valid": True,
                "catalog_sha256": index.get("catalog_sha256"),
                "metric_count": len(payload.get("metrics") or []),
                "data_domain_count": len(index.get("data_domains") or []),
            }
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
