from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from modules.agent.analysis_runs import AnalysisRun


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "spatial-business-analyst"
CATALOG_PATH = SKILL_ROOT / "references" / "metric-catalog.yaml"
INDEX_PATH = SKILL_ROOT / "references" / "metric-catalog-index.yaml"
CATALOG_SCRIPT = SKILL_ROOT / "scripts" / "metric_catalog.py"
METRIC_SCRIPT = SKILL_ROOT / "scripts" / "normalized_spatial_metrics.py"
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
    "answers_questions",
    "spatial_granularities",
    "use_when",
    "actionability",
    "followup_metrics",
    "valid_comparisons",
    "quality_requirements",
    "comparison_baseline",
    "source",
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def test_metric_catalog_has_one_complete_metric_list_and_valid_sources():
    payload = _catalog()
    assert "available_derived_metrics" not in payload
    assert "planned_metrics" not in payload
    metrics = payload["metrics"]
    ids = [item["id"] for item in metrics]
    assert len(ids) == len(set(ids))
    assert not {
        "nightlight.spatial_continuity",
        "nightlight.overlap_with_poi",
        "road.intersection_density",
        "grid.activity_index",
    }.intersection(ids)
    assert {item["implementation_status"] for item in metrics} <= {"implemented", "not_implemented"}
    for metric in metrics:
        assert REQUIRED_FIELDS <= metric.keys()
        if metric["implementation_status"] == "not_implemented":
            assert metric.get("implementation_gap")
        else:
            assert metric["outputs"]
            assert metric["source"]
            for source in metric["source"]:
                assert (ROOT / source).exists(), f"{metric['id']} source does not exist: {source}"
        assert "combine_with" not in metric
        assert "spatial_unit" not in metric
        assert metric["answers_questions"]
        assert metric["spatial_granularities"]
        assert metric["actionability"]["action_targets"]
        assert metric["actionability"]["possible_actions"]
        baseline = metric["comparison_baseline"]
        assert set(baseline) == {"required", "preferred", "if_missing"}
        assert isinstance(baseline["required"], bool)
        assert baseline["preferred"]
        assert baseline["if_missing"]
        assert {item["metric_id"] for item in metric["followup_metrics"]} <= set(ids)



def test_global_moran_is_global_diagnostic_and_advances_to_local_metrics():
    moran = next(item for item in _catalog()["metrics"] if item["id"] == "spatial.global_moran_i_density")

    assert moran["spatial_granularities"] == [
        {"unit": "scope", "neighborhood": "none", "runtime_parameters": []}
    ]
    assert moran["actionability"]["action_targets"] == ["analysis_method"]
    followups = {(item["metric_id"], item["purpose"]) for item in moran["followup_metrics"]}
    assert ("spatial.gi_star", "locate") in followups
    assert ("spatial.lisa", "disconfirm") in followups
    unsupported = " ".join(moran["does_not_support"])
    assert "局部热点" in unsupported
    assert "入口" in unsupported
    assert "功能" in unsupported

def test_metric_catalog_cli_lists_describes_and_rejects_unknown_ids():
    listed = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "list", "--family", "poi_grid", "--implementation-status", "implemented"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    list_payload = json.loads(listed.stdout)
    assert list_payload["count"] > 0
    assert all(item["family"] == "poi_grid" and item["implementation_status"] == "implemented" for item in list_payload["metrics"])

    described = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "describe", "poi.grid_density", "poi.lq"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert [item["id"] for item in json.loads(described.stdout)["metrics"]] == ["poi.grid_density", "poi.lq"]

    missing = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "describe", "missing.metric"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "missing.metric" in missing.stderr


def test_skill_delegates_metric_selection_and_recipe_ids_are_canonical():
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    selection_text = (SKILL_ROOT / "references" / "metric-selection.md").read_text(encoding="utf-8")
    for required in (
        "references/metric-selection.md",
        "scripts/metric_catalog.py",
        "references/analysis-recipes.md",
    ):
        assert required in skill_text
    assert "metric-catalog-index.yaml" in skill_text
    for required in (
        "references/metric-catalog.yaml",
        "metric_id",
        "does_not_support",
        "valid_comparisons",
        "quality_requirements",
        "comparison_baseline",
    ):
        assert required in selection_text

    metric_ids = {item["id"] for item in _catalog()["metrics"]}
    recipe_text = (SKILL_ROOT / "references" / "analysis-recipes.md").read_text(encoding="utf-8")
    recipe_ids = set(re.findall(r"`([a-z]+(?:\.[a-z0-9_]+)+)`", recipe_text))
    assert recipe_ids
    assert recipe_ids <= metric_ids


def test_metric_selection_steps_are_ordered_without_loading_full_catalog_at_startup():
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    selection_text = (SKILL_ROOT / "references" / "metric-selection.md").read_text(encoding="utf-8")
    ordered_markers = (
        "Resolve the capability against the locked registry version",
        "Discover eligible metric candidates from `metric-catalog-index.yaml`",
        "Use `analysis-recipes.md` only to form candidate combinations",
        "Query detailed semantics only for shortlisted IDs",
        "Resolve parameters, adapters, activation rules, and execution order deterministically",
        "Persist the resolved internal plan and every terminal attempt",
    )
    positions = [selection_text.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
    assert "Never load the detailed `references/metric-catalog.yaml` at startup" in selection_text
    assert "never load the detailed catalog at startup" in skill_text
    assert "evidence engine, not the Agent, selects Metric IDs" in skill_text


def test_cultural_destination_recipe_runs_before_detailed_catalog_lookup():
    recipe_text = (SKILL_ROOT / "references" / "analysis-recipes.md").read_text(encoding="utf-8")
    introduction, cultural_recipe = recipe_text.split("## Cultural destination", 1)
    assert "after discovering candidate domains and metric IDs" in introduction
    assert "before querying detailed entries" in introduction
    assert "only after selecting available metrics" not in introduction
    for metric_id in (
        "poi.category_count",
        "poi.lq",
        "isochrone.reachable_area",
        "road.integration",
    ):
        assert f"`{metric_id}`" in cultural_recipe


def test_metric_catalog_index_is_deterministic_and_synchronized():
    before = INDEX_PATH.read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(CATALOG_SCRIPT), "build-index"], cwd=ROOT, check=True)
    assert INDEX_PATH.read_text(encoding="utf-8") == before
    validated = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "validate-index"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(validated.stdout)
    assert payload["metric_count"] == 60
    assert payload["data_domain_count"] == 7


def test_normalized_spatial_metrics_emits_catalog_metric_ids():
    module = _load_module("normalized_spatial_metrics_for_test", METRIC_SCRIPT)
    result = module.compute(
        {
            "history_id": "history-test",
            "source_id": "current:dataset:poi",
            "year": 2024,
            "center": [112.985, 28.195],
            "center_crs": "wgs84",
            "boundary": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ],
            "records": [
                {"record_id": "poi-1", "properties": {"location": [112.987, 28.195], "type": "050100"}},
                {"record_id": "poi-2", "properties": {"location": [112.983, 28.196], "type": "060100"}},
            ],
        }
    )
    catalog_ids = {item["id"] for item in _catalog()["metrics"]}
    nodes = result["evidence_nodes"]
    assert len(nodes) == 1
    assert nodes[0]["kind"] == "spatial_metric"
    assert nodes[0]["run_id"] == result["run_id"]
    assert nodes[0]["metric_ids"] == ["poi.count", "poi.grid_density", "poi.lq"]
    assert all("confidence" not in node and "confidence_basis" not in node for node in nodes)
    assert set(nodes[0]["metric_ids"]) <= catalog_ids
    assert all(attempt["metric_id"] in catalog_ids for attempt in result["metric_attempts"])
    assert all(attempt["evidence_node_ids"] for attempt in result["metric_attempts"] if attempt["execution_status"] == "succeeded")
    assert all(not attempt["evidence_node_ids"] for attempt in result["metric_attempts"] if attempt["execution_status"] != "succeeded")
    run = AnalysisRun.model_validate(result["analysis_run"])
    assert run.manifest_sha256 == run.canonical_manifest_sha256()
    assert run.project_location == run.scope_origin == run.partition_origin
    assert run.source_versions[0].record_count == 2


def _metric_payload(center, center_crs="wgs84"):
    payload = {
        "history_id": "history-test",
        "source_id": "current:dataset:poi",
        "year": 2024,
        "center": center,
        "center_crs": center_crs,
        "boundary": [
            [112.97, 28.18],
            [113.00, 28.18],
            [113.00, 28.21],
            [112.97, 28.21],
            [112.97, 28.18],
        ],
        "records": [
            {"record_id": "poi-1", "properties": {"location": [112.987, 28.195], "type": "050100"}},
            {"record_id": "poi-2", "properties": {"location": [112.983, 28.196], "type": "060100"}},
        ],
    }
    return payload


def test_normalized_metric_run_hash_includes_analysis_origin():
    module = _load_module("normalized_spatial_metrics_hash_test", METRIC_SCRIPT)
    first = module.compute(_metric_payload([112.985, 28.195]))
    second = module.compute(_metric_payload([112.986, 28.195]))

    assert first["dataset_content_sha256"] == second["dataset_content_sha256"]
    assert first["analysis_spec_sha256"] != second["analysis_spec_sha256"]
    assert first["run_sha256"] != second["run_sha256"]
    assert {node["id"] for node in first["evidence_nodes"]}.isdisjoint(
        node["id"] for node in second["evidence_nodes"]
    )


def test_normalized_metric_rejects_non_wgs84_input():
    module = _load_module("normalized_spatial_metrics_crs_guard_test", METRIC_SCRIPT)

    with pytest.raises(ValueError, match="center_crs must be wgs84"):
        module.compute(_metric_payload([112.9863, 28.2208], center_crs="gcj02"))
