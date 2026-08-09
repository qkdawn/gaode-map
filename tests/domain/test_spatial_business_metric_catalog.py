from __future__ import annotations

import importlib.util
from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


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


def test_metric_details_are_complete_and_reference_implemented_sources():
    payload = _catalog()
    metrics = payload["metrics"]
    ids = [item["id"] for item in metrics]
    assert len(ids) == len(set(ids))
    assert {item["implementation_status"] for item in metrics} <= {"implemented", "not_implemented"}
    for metric in metrics:
        assert REQUIRED_FIELDS <= metric.keys()
        assert "does_not_support" not in metric
        assert "implementation_gap" not in metric
        assert "if_missing" not in metric["comparison_baseline"]
        if metric["implementation_status"] == "implemented":
            for source in metric["source"]:
                assert (ROOT / source).exists(), f"{metric['id']} source does not exist: {source}"


def test_catalog_cli_exposes_only_lightweight_v4_fields_and_detail_is_explicit():
    catalog = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "catalog"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    catalog_payload = json.loads(catalog.stdout)
    expected_keys = {
        "tool_id",
        "name",
        "purpose",
        "question_tags",
        "primary_spatial_unit",
        "action_targets",
        "implementation_status",
    }
    assert catalog_payload["count"] == 57
    assert all(set(metric) == expected_keys for metric in catalog_payload["metrics"])
    assert all("definition" not in metric and "required_inputs" not in metric for metric in catalog_payload["metrics"])

    detailed = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "detail", "poi.grid_density"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    detail = json.loads(detailed.stdout)["metric"]
    assert detail["id"] == "poi.grid_density"
    assert detail["required_inputs"]
    assert detail["outputs"]
    assert detail["definition"]

    missing = subprocess.run(
        [sys.executable, str(CATALOG_SCRIPT), "detail", "missing.metric"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "missing.metric" in missing.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "夜间经济活动强度"),
        ("supports", ["消费人口覆盖和商业机会排序"]),
    ],
)
def test_catalog_rejects_overpromising_discovery_names_and_purposes(field, value):
    module = _load_module("metric_catalog_discovery_language", CATALOG_SCRIPT)
    payload = deepcopy(_catalog())
    payload["metrics"][0][field] = value

    with pytest.raises(ValueError, match="overpromising discovery language"):
        module.validate_catalog(payload, repository_root=ROOT)


def test_metric_tool_service_uses_light_catalog_and_loads_real_details_on_request():
    from modules.spatial_action.project_context import ProjectSpatialAnalysisService
    from modules.spatial_action.metric_tools import MetricToolService

    tools = MetricToolService()
    catalog = tools.catalog()
    assert len(catalog) == 57
    item = next(value for value in catalog if value.tool_id == "poi.grid_density")
    assert set(item.model_dump()) == {
        "tool_id",
        "name",
        "purpose",
        "question_tags",
        "primary_spatial_unit",
        "action_targets",
        "implementation_status",
    }
    detail = tools.detail(item.tool_id)
    assert detail.measures.definition
    assert detail.measures.outputs
    assert detail.measures.calculation
    assert detail.use_for.decision_questions
    assert detail.use_for.action_targets
    assert detail.compare_by.candidate_targets
    assert detail.compare_by.area_units
    assert detail.interpret_with.combinations
    assert detail.watch_out.field_checks
    assert detail.unavailable_semantics

    directional = tools.detail("regional.directional_evidence_matrix")
    assert directional.measures.outputs == [
        "direction_distance_rows",
        "shared_grid_baseline",
        "observation_universe",
        "source_versions",
    ]

    focused_poi = tools.detail("poi.focused_accessibility")
    assert focused_poi.measures.outputs == [
        "route_verified_poi_groups",
        "route_verified_poi_rows",
        "route_verification_diagnostics",
    ]
    assert "连续道路" in focused_poi.measures.definition

    supply_poi = tools.detail("poi.supply_structure")
    assert supply_poi.measures.outputs == [
        "isochrone_verified_real_taxonomy_counts",
        "nearby_5_min_road_accessible_counts",
        "isochrone_and_taxonomy_audit",
    ]
    assert "5 分钟" in supply_poi.measures.definition
    assert "poi.supply_structure" in ProjectSpatialAnalysisService.executable_metric_ids()


def test_all_metric_details_expose_the_analysis_knowledge_card():
    from modules.spatial_action.metric_tools import MetricToolService

    tools = MetricToolService()
    for item in tools.catalog():
        detail = tools.detail(item.tool_id)
        assert set(detail.model_dump()) == {
            "tool_id", "name", "measures", "use_for", "compare_by",
            "interpret_with", "watch_out", "unavailable_semantics", "asset_types",
        }
        assert detail.measures.definition and detail.measures.unit
        assert detail.use_for.decision_questions and detail.use_for.action_targets
        assert detail.compare_by.candidate_targets and detail.compare_by.area_units
        assert detail.interpret_with.combinations and detail.watch_out.field_checks


def test_v4_skill_documents_catalog_detail_execute_result_flow():
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    selection_text = (SKILL_ROOT / "references" / "metric-selection.md").read_text(encoding="utf-8")
    for marker in (
        "spatial_metric_catalog",
        "spatial_metric_detail",
        "execute_spatial_metric",
        "list_spatial_metric_results",
        "read_spatial_metric_result",
    ):
        assert marker in skill_text
    assert "MetricToolService" in selection_text
    assert "decision_metric_bundles" in selection_text
    assert "不要把指标组合复制成新的报告流程" in selection_text


def test_metric_catalog_index_is_deterministic_and_contains_no_legacy_domain_contract():
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
    assert payload == {"valid": True, "metric_count": 57}
    index = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))
    assert set(index) == {"metrics"}

def test_normalized_spatial_metrics_emits_catalog_metric_ids():
    module = _load_module("normalized_spatial_metrics_for_test", METRIC_SCRIPT)
    result = module.compute(
        {
            "history_id": "history-test",
            "source_id": "current:dataset:poi",
            "year": 2024,
            "center": [112.985, 28.195],
            "center_crs": "wgs84",
            "analysis_scope": [
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
    assert result["status"] == "available"
    assert result["tool_ids"] == ["poi.count", "poi.grid_density", "poi.lq"]
    assert set(result["tool_ids"]) <= catalog_ids
    assert result["result_id"].startswith("result:poi.normalized_spatial:")
    assert result["structured_result"]["accepted_record_count"] == 2
    assert result["input_sources"] == ["current:dataset:poi@sha256:" + result["structured_result"]["dataset_content_sha256"].removeprefix("sha256:")]
    assert set(result) == {
        "result_id",
        "tool_ids",
        "status",
        "summary",
        "input_sources",
        "time_scope",
        "spatial_scope",
        "structured_result",
        "limitations",
    }


def _metric_payload(center, center_crs="wgs84"):
    payload = {
        "history_id": "history-test",
        "source_id": "current:dataset:poi",
        "year": 2024,
        "center": center,
        "center_crs": center_crs,
        "analysis_scope": [
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

    first_data = first["structured_result"]
    second_data = second["structured_result"]
    assert first_data["dataset_content_sha256"] == second_data["dataset_content_sha256"]
    assert first_data["analysis_spec_sha256"] != second_data["analysis_spec_sha256"]
    assert first["result_id"] != second["result_id"]


def test_normalized_metric_rejects_non_wgs84_input():
    module = _load_module("normalized_spatial_metrics_crs_guard_test", METRIC_SCRIPT)

    with pytest.raises(ValueError, match="center_crs must be wgs84"):
        module.compute(_metric_payload([112.9863, 28.2208], center_crs="gcj02"))
