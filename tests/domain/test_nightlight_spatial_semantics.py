from __future__ import annotations

import json

import pytest
from shapely.geometry import MultiPolygon, box, mapping

from modules.spatial_action.nightlight_evidence import build_nightlight_direction_profile
from tests.domain.test_spatial_evidence import _record, _service


NIGHTLIGHT_REF = "current:dataset:nightlight/light-12"


def _compute(analysis: str, **payload):
    return _service().compute_domains(
        history_id="history-1",
        request={"analysis": analysis, **payload},
    )


def _nightlight_result(result):
    assert result["status"] == "available"
    domain_result = result["domain_results"][0]
    assert "significance" not in json.dumps(domain_result, ensure_ascii=False).lower()
    return domain_result


def test_nightlight_scope_is_saved_isochrone_brightness_not_activity_claim():
    result = _nightlight_result(_compute("scope", fact_domains=["nightlight"]))

    assert result["method"]["spatial_universe"] == "saved_isochrone"
    assert result["summary"]["spatial_distribution"]["valid_cell_count"] == 25
    distribution = result["summary"]["spatial_distribution"]["spatial_distribution"]
    assert len(distribution["brightness_weighted_center_wgs84"]) == 2
    assert distribution["standard_deviation_ellipse"]["major_axis_standard_distance_m"] > 0
    assert result["summary"]["spatial_distribution"]["center_edge_gradient"]["inner_mean_radiance"] is not None
    quality = result["summary"]["spatial_distribution"]["quality_diagnostics"]
    assert quality["observation_quality_available"] is False
    assert quality["limitation"]
    assert "brightness_context" not in result["summary"]
    assert "activity_background" not in result["summary"]


def test_nightlight_accessibility_answers_incremental_isochrone_band_question():
    result = _nightlight_result(_compute("accessibility", fact_domains=["nightlight"]))

    assert result["method"]["kind"] == "nightlight_accessibility_bands"
    assert [group["travel_time_band_min"] for group in result["groups"]] == [
        [0.0, 5.0], [5.0, 10.0], [10.0, 15.0],
    ]
    assert all({"incremental", "cumulative"} <= set(group) for group in result["groups"])


def test_nightlight_direction_answers_eight_sector_brightness_question():
    result = _nightlight_result(_compute("direction", fact_domains=["nightlight"]))

    assert result["method"]["kind"] == "nightlight_direction_profile"
    assert len(result["groups"]) == 8
    assert result["summary"]["comparison_basis"] == (
        "area_weighted_mean_radiance_within_saved_isochrone"
    )
    assert result["method"]["boundary_cell_policy"] == "split_by_sector_intersection_area"
    assert result["coverage"]["spatial_unit_count"] == 25
    assert len(result["summary"]["spatial_distribution"]["brightness_weighted_center_wgs84"]) == 2


def test_nightlight_neighborhood_reports_descriptive_local_contrast():
    result = _nightlight_result(_compute(
        "neighborhood",
        fact_domains=["nightlight"],
        record_refs=[NIGHTLIGHT_REF],
    ))

    contrast = result["groups"][0]["contrast"]
    assert "interpretation_basis" not in contrast
    assert contrast["mean_radiance_delta"] is not None


def test_nightlight_rank_returns_brightest_cells_without_significance_gate():
    result = _nightlight_result(_compute(
        "rank",
        fact_domains=["nightlight"],
        evidence_dimensions=["nightlight.intensity"],
        top_k=3,
    ))

    assert result["method"]["kind"] == "nightlight_cell_rank"
    assert [item["radiance"] for item in result["highlights"]] == [25.0, 24.0, 23.0]


def test_nightlight_relationship_remains_cross_domain_colocation_question():
    result = _nightlight_result(_compute(
        "relationship",
        fact_domains=["population", "nightlight"],
        evidence_dimensions=["population.scale", "nightlight.intensity"],
    ))

    assert result["analysis"] == "relationship"
    assert result["relationship"]["unit_values"]
    assert "combined_score_computed" not in result["relationship"]
    assert "kind" not in result["method"]
    assert set(result["relationship"]["distributions"]) == {
        "population.total",
        "nightlight.mean_radiance",
    }
    assert all(
        set(item["values"]) == {"population.total", "nightlight.mean_radiance"}
        for item in result["relationship"]["unit_values"]
    )
    assert "thresholds" not in result["relationship"]
    assert "significance" not in json.dumps(result, ensure_ascii=False).lower()


def test_nightlight_inspect_explains_cell_inside_isochrone_context():
    result = _nightlight_result(_compute(
        "inspect",
        fact_domains=["nightlight"],
        record_refs=[NIGHTLIGHT_REF],
    ))

    inspected = result["highlights"][0]
    assert inspected["record_ref"] == NIGHTLIGHT_REF
    assert inspected["radiance"] == 13.0
    assert inspected["year"] == 2025
    assert inspected["quality"] == {}
    assert inspected["within_scope_percentile"] is not None
    assert inspected["neighbor_mean_radiance"] is not None


def test_nightlight_change_direction_reports_annual_change_and_center_migration():
    result = _nightlight_result(_compute(
        "direction",
        fact_domains=["nightlight"],
        evidence_dimensions=["nightlight.change"],
    ))

    assert result["method"]["kind"] == "nightlight_descriptive_change"
    assert result["summary"]["period"] == "2023-2025"
    assert result["summary"]["matched_cell_count"] == 25
    assert result["summary"]["change_class_counts"]["increase"] == 25
    assert len(result["groups"]) == 8
    migration = result["summary"]["brightness_center_migration"]
    assert migration["from_center_wgs84"]
    assert migration["to_center_wgs84"]
    assert "time_series_semantics" not in result["summary"]


def test_nightlight_change_rank_and_inspect_use_stable_cell_ids():
    ranked = _nightlight_result(_compute(
        "rank",
        fact_domains=["nightlight"],
        evidence_dimensions=["nightlight.change"],
        top_k=3,
    ))

    assert [item["delta_radiance"] for item in ranked["highlights"]] == [7.5, 7.2, 6.9]
    target_ref = ranked["highlights"][0]["record_ref"]
    inspected = _nightlight_result(_compute(
        "inspect",
        fact_domains=["nightlight"],
        evidence_dimensions=["nightlight.change"],
        record_refs=[target_ref],
    ))
    assert inspected["highlights"][0]["record_ref"] == target_ref
    assert inspected["highlights"][0]["from_year"] == 2023
    assert inspected["highlights"][0]["to_year"] == 2025
    assert [item["year"] for item in inspected["highlights"][0]["yearly_radiance"]] == [2023, 2024, 2025]
    assert inspected["provenance"]["selected_years"] == {
        "current:dataset:nightlight": [2023, 2024, 2025],
    }


def test_nightlight_intensity_and_change_return_independent_results():
    result = _compute(
        "direction",
        fact_domains=["nightlight"],
        evidence_dimensions=["nightlight.intensity", "nightlight.change"],
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["nightlight.semantic_profile", "nightlight.change_profile"]
    assert [item["method"]["kind"] for item in result["domain_results"]] == [
        "nightlight_direction_profile",
        "nightlight_descriptive_change",
    ]
    assert [item["evidence_dimensions"] for item in result["domain_results"]] == [
        ["nightlight.intensity"],
        ["nightlight.change"],
    ]
    assert result["domain_results"][1]["summary"]["period"] == "2023-2025"


def test_nightlight_scope_intensity_and_change_return_independent_results():
    result = _compute(
        "scope",
        fact_domains=["nightlight"],
        evidence_dimensions=["nightlight.intensity", "nightlight.change"],
    )

    assert result["status"] == "available"
    assert [item["method"]["kind"] for item in result["domain_results"]] == [
        "nightlight_scope_profile",
        "nightlight_descriptive_change",
    ]
    assert [item["evidence_dimensions"] for item in result["domain_results"]] == [
        ["nightlight.intensity"],
        ["nightlight.change"],
    ]


@pytest.mark.parametrize("analysis", ["neighborhood", "inspect"])
@pytest.mark.parametrize("dimension", ["nightlight.intensity", "nightlight.change"])
def test_nightlight_missing_record_ref_is_unavailable(analysis, dimension):
    result = _compute(
        analysis,
        fact_domains=["nightlight"],
        evidence_dimensions=[dimension],
        record_refs=["current:dataset:nightlight/missing"],
    )

    assert result["status"] == "unavailable"
    assert result["domain_results"][0]["status"] == "unavailable"
    assert "limitations" not in result["domain_results"][0]


def test_nightlight_scope_uses_complete_multipolygon_and_saved_year():
    service = _service()
    original_project_reader = service._projects.read_history_project
    original_layer = service._nightlight_layer
    original_timeseries = service._nightlight_timeseries
    scope_geometry = MultiPolygon([
        box(0, 0, 0.02, 0.02),
        box(0.03, 0.03, 0.05, 0.05),
    ])
    calls = {}

    def read_history_project(history_id):
        project = original_project_reader(history_id)
        project["scope"] = mapping(scope_geometry)
        return project

    def layer(polygon, coord_type, *, year, view):
        calls["layer_polygon"] = polygon
        calls["layer_year"] = year
        calls["layer_view"] = view
        return original_layer(polygon, coord_type, year=year, view=view)

    def timeseries(polygon, coord_type, period, view):
        calls["timeseries_polygon"] = polygon
        calls["period"] = period
        return original_timeseries(polygon, coord_type, period, view)

    service._projects.read_history_project = read_history_project
    service._nightlight_layer = layer
    service._nightlight_timeseries = timeseries
    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["nightlight"]},
    )

    assert result["status"] == "available"
    assert len(calls["layer_polygon"]) == 2
    assert calls["layer_year"] == 2025
    assert calls["layer_view"] == "radiance"
    assert "timeseries_polygon" not in calls
    assert "period" not in calls


def test_nightlight_scope_rejects_runtime_layer_year_mismatch():
    service = _service()
    original_layer = service._nightlight_layer

    def mismatched_layer(polygon, coord_type, *, year, view):
        result = original_layer(polygon, coord_type, year=year, view=view)
        return {**result, "year": 2024}

    service._nightlight_layer = mismatched_layer
    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["nightlight"]},
    )

    assert result["status"] == "unavailable"
    assert "limitations" not in result


def test_nightlight_direction_splits_boundary_cell_by_intersection_area():
    scope = box(-1, -1, 1, 1)
    crossing_cell = _record(
        "current:dataset:nightlight",
        "crossing",
        box(-0.2, 0.1, 0.4, 0.6),
        radiance=10,
        year=2025,
    )

    profile = build_nightlight_direction_profile([crossing_cell], scope, (0.0, 0.0))
    contributing = [group for group in profile["groups"] if group["valid_cell_count"]]

    assert len(contributing) > 1
    assert sum(group["radiance_index_share"] for group in profile["groups"]) == pytest.approx(1.0)
