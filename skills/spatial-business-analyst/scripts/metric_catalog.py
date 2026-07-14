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
REQUIRED_FIELDS = {
    "id",
    "name",
    "family",
    "implementation_status",
    "outputs",
    "required_inputs",
    "definition",
    "unit",
    "supports",
    "does_not_support",
    "use_when",
    "combine_with",
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
        list_fields = REQUIRED_FIELDS.intersection(
            {
                "outputs",
                "required_inputs",
                "supports",
                "does_not_support",
                "use_when",
                "combine_with",
                "valid_comparisons",
                "quality_requirements",
                "source",
            }
        )
        for field in list_fields:
            if not isinstance(metric.get(field), list):
                raise ValueError(f"{metric_id}.{field} must be a list")
        for field in (
            "required_inputs",
            "supports",
            "does_not_support",
            "use_when",
            "combine_with",
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
    known_families = {str(metric.get("family") or "") for metric in metrics}
    indexed_families = {family for domain in DATA_DOMAINS for family in domain["families"]}
    if known_families != indexed_families:
        raise ValueError(
            f"catalog families and index domains differ: missing={sorted(known_families - indexed_families)}, "
            f"unknown={sorted(indexed_families - known_families)}"
        )
    for metric in metrics:
        unknown_companions = sorted(set(metric.get("combine_with") or []).difference(seen))
        if unknown_companions:
            raise ValueError(f"{metric['id']} references unknown combine_with metrics: {unknown_companions}")


def build_index_payload(payload: dict[str, Any], *, catalog_file: Path) -> dict[str, Any]:
    metrics = list(payload.get("metrics") or [])
    domains = []
    for spec in DATA_DOMAINS:
        family_set = set(spec["families"])
        selected = [item for item in metrics if str(item.get("family") or "") in family_set]
        implemented = [
            str(item["id"])
            for item in selected
            if item.get("implementation_status") == "implemented"
        ]
        not_implemented = [
            str(item["id"])
            for item in selected
            if item.get("implementation_status") == "not_implemented"
        ]
        domains.append(
            {
                "id": spec["id"],
                "source_ids": list(spec["source_ids"]),
                "families": list(spec["families"]),
                "metric_ids": [str(item["id"]) for item in selected],
                "implemented_metric_ids": implemented,
                "not_implemented_metric_ids": not_implemented,
                "use_when": sorted(
                    {
                        str(tag)
                        for item in selected
                        for tag in item.get("use_when") or []
                        if str(tag).strip()
                    }
                ),
                "detail_queries": [
                    f"python skills/spatial-business-analyst/scripts/metric_catalog.py list --family {family}"
                    for family in spec["families"]
                ],
            }
        )
    return {
        "index_version": "1.0.0",
        "catalog_version": payload.get("catalog_version"),
        "catalog_sha256": _catalog_sha256(catalog_file),
        "generated_from": "references/metric-catalog.yaml",
        "runtime_rule": "Intersect source_ids with the current AnalysisRun source_versions before selecting metrics.",
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
