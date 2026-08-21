from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point, box

from modules.isochrone.adapter import ValhallaIsochroneUnavailable
from modules.population.registry import age_band_keys
from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.spatial_evidence import (
    CATALOG_SCOPE_BINDINGS,
    FACT_DOMAIN_CAPABILITIES,
    METRIC_BINDINGS,
    POPULATION_AGE_BANDS,
    SpatialDomainComputationRequest,
    SpatialEvidenceRequest,
    SpatialEvidenceService,
    SpatialEvidenceSelector,
    _bounded_model_response,
)


def _record(source_id: str, record_id: str, geometry, **properties) -> ScopeRecord:
    return ScopeRecord(
        source_id=source_id,
        record_id=record_id,
        title=str(properties.get("name") or properties.get("road_name") or record_id),
        content="",
        properties={"record_id": record_id, **properties},
        raw={},
        time_scope={"year": properties.get("year")},
        locator=f"{source_id}/{record_id}",
        citation="test",
        geometry=geometry,
    )


class _Datasets:
    def __init__(self, records, records_by_year=None):
        self.records = records
        self.records_by_year = records_by_year or {}
        self.load_calls = []

    def load_scope_records(self, *, history_id, source_id, year=None, require_geometry_metadata=False):
        self.load_calls.append(source_id)
        yearly = self.records_by_year.get(source_id, {})
        available_years = sorted(yearly) or [2026]
        selected_year = int(year) if year is not None else available_years[-1]
        values = yearly.get(selected_year, self.records.get(source_id, []))
        return list(values), available_years, selected_year


class _Projects:
    def __init__(self, records, dataset_summaries=None, records_by_year=None):
        self.datasets = _Datasets(records, records_by_year=records_by_year)
        self.dataset_summaries = dataset_summaries or {}

    def read_history_project(self, history_id):
        return {
            "history_id": history_id,
            "project_name": "测试项目",
            "params": {"center": [0.025, 0.025], "coord_type": "wgs84", "mode": "walking", "time_min": 15},
            "scope": {"type": "Polygon", "coordinates": [[[0, 0], [0.05, 0], [0.05, 0.05], [0, 0.05], [0, 0]]]},
            "snapshot": {"snapshot_id": history_id},
            "datasets": [
                {
                    "source_id": source_id,
                    "status": "ready",
                    "selected_year": 2026,
                    "available_years": sorted(self.datasets.records_by_year.get(source_id, {})) or [2026],
                    "record_count": len(values),
                    "summary": self.dataset_summaries.get(source_id, {}),
                }
                for source_id, values in self.datasets.records.items()
            ],
        }


class _Catalog:
    def catalog(self):
        return [SimpleNamespace(tool_id=metric_id, name=metric_id) for metric_id in (
            "population.total", "nightlight.mean_radiance", "poi.grid_density", "road.nain",
        )]


def _population_properties(index: int) -> dict:
    age_male = {band: float(index + position + 1) for position, band in enumerate(age_band_keys())}
    age_female = {band: float(index + position + 2) for position, band in enumerate(age_band_keys())}
    return {
        "population_total": 100.0 + index,
        "male_total": 48.0 + index,
        "female_total": 52.0,
        "age_male": age_male,
        "age_female": age_female,
        "age_total": {band: age_male[band] + age_female[band] for band in age_band_keys()},
        "year": 2026,
    }


def _service():
    population = []
    nightlight = []
    poi = []
    for index in range(25):
        x = (index % 5) * 0.01
        y = (index // 5) * 0.01
        cell = box(x, y, x + 0.009, y + 0.009)
        population.append(_record("current:dataset:population", f"cell-{index}", cell, **_population_properties(index)))
        nightlight.append(_record("current:dataset:nightlight", f"light-{index}", cell, radiance=float(index + 1), year=2026))
        poi.append(_record("current:dataset:poi", f"poi-{index}", Point(x + 0.004, y + 0.004), category="餐饮服务", subcategory="中餐馆", year=2026))
    roads = [
        _record(
            "current:dataset:road_edges",
            "edge-0",
            LineString([(0.0, 0.0), (0.05, 0.05)]),
            road_name="测试道路",
            road_class="secondary",
            length_m=1000,
            metrics={"integration": 0.6, "choice": 0.4, "connectivity": 2, "depth": 1.2, "control": 0.3},
            integration_global=0.9,
            choice_global=0.7,
            nain_global=0.09,
            nach_global=0.07,
            integration_r600=0.6,
            choice_r600=0.4,
            nain_r600=0.06,
            nach_r600=0.04,
            integration_r800=0.8,
            choice_r800=0.5,
            nain_r800=0.08,
            nach_r800=0.05,
        )
    ]
    projects = _Projects({
        "current:dataset:population": population,
        "current:dataset:nightlight": nightlight,
        "current:dataset:poi": poi,
        "current:dataset:road_edges": roads,
    })

    def contours(_center, times, _mode):
        bounds = {5.0: box(0.02, 0.02, 0.03, 0.03), 10.0: box(0.01, 0.01, 0.04, 0.04), 15.0: box(0, 0, 0.05, 0.05)}
        return {float(value): bounds[float(value)] for value in times}

    def population_timeseries(_polygon, _coord_type, _period, _view):
        def age_distribution(total):
            per_band = total / len(age_band_keys())
            return [
                {
                    "age_band": band,
                    "age_band_label": band,
                    "total": per_band,
                    "male": per_band * 0.49,
                    "female": per_band * 0.51,
                    "ratio": 1 / len(age_band_keys()),
                }
                for band in age_band_keys()
            ]

        return {
            "series": [
                {
                    "year": "2024", "total_population": 1000, "male_total": 490, "female_total": 510,
                    "male_ratio": 0.49, "female_ratio": 0.51, "average_density": 100,
                    "age_distribution": age_distribution(1000),
                    "age_group_totals": {"child_0_14": 150, "working_15_64": 700, "senior_65_plus": 150},
                    "age_group_ratios": {"child_0_14": 0.15, "working_15_64": 0.7, "senior_65_plus": 0.15},
                    "top_age_band": "35", "top_age_band_label": "35-39岁",
                },
                {
                    "year": "2025", "total_population": 1050, "male_total": 515, "female_total": 535,
                    "male_ratio": 0.490476, "female_ratio": 0.509524, "average_density": 105,
                    "age_distribution": age_distribution(1050),
                    "age_group_totals": {"child_0_14": 150, "working_15_64": 730, "senior_65_plus": 170},
                    "age_group_ratios": {"child_0_14": 0.142857, "working_15_64": 0.695238, "senior_65_plus": 0.161905},
                    "top_age_band": "35", "top_age_band_label": "35-39岁",
                },
                {
                    "year": "2026", "total_population": 1100, "male_total": 540, "female_total": 560,
                    "male_ratio": 0.490909, "female_ratio": 0.509091, "average_density": 110,
                    "age_distribution": age_distribution(1100),
                    "age_group_totals": {"child_0_14": 150, "working_15_64": 750, "senior_65_plus": 200},
                    "age_group_ratios": {"child_0_14": 0.136364, "working_15_64": 0.681818, "senior_65_plus": 0.181818},
                    "top_age_band": "35", "top_age_band_label": "35-39岁",
                },
            ],
            "layer": {"summary": {"cell_count": 25, "class_counts": {"increase": 20, "stable": 5}}},
        }

    def nightlight_layer(_polygon, _coord_type, *, view):
        assert view == "hotspot"
        return {
            "year": 2025,
            "summary": {
                "total_radiance": 2500, "mean_radiance": 10, "max_radiance": 30,
                "p90_radiance": 18, "lit_pixel_ratio": 0.9, "valid_pixel_count": 250,
            },
            "analysis": {
                "core_hotspot_count": 10, "secondary_hotspot_count": 7,
                "emerging_hotspot_count": 3, "low_light_count": 4,
                "hotspot_cell_ratio": 0.4, "peak_radiance": 30,
                "peak_cell_id": "light-24", "peak_to_edge_ratio": 2.5,
                "economic_activity_intensity_level": "high",
                "sector_direction_analysis": {
                    "dominant_direction": "北", "secondary_direction": "东",
                    "dominant_share": 0.3, "secondary_share": 0.2,
                },
            },
        }

    def nightlight_timeseries(_polygon, _coord_type, _period, _view):
        return {
            "series": [
                {"year": 2023, "total_radiance": 2000, "mean_radiance": 8, "max_radiance": 25, "p90_radiance": 15, "lit_pixel_ratio": 0.8},
                {"year": 2024, "total_radiance": 2250, "mean_radiance": 9, "max_radiance": 27, "p90_radiance": 16, "lit_pixel_ratio": 0.85},
                {"year": 2025, "total_radiance": 2500, "mean_radiance": 10, "max_radiance": 30, "p90_radiance": 18, "lit_pixel_ratio": 0.9},
            ],
            "layer": {"summary": {"cell_count": 25, "class_counts": {"increase": 18, "stable": 7}}},
        }

    return SpatialEvidenceService(
        projects=projects,
        metric_catalog=_Catalog(),
        isochrone_contours=contours,
        population_timeseries=population_timeseries,
        nightlight_layer=nightlight_layer,
        nightlight_timeseries=nightlight_timeseries,
    )


def _assert_no_geometry(value):
    if isinstance(value, dict):
        assert not {str(key).lower() for key in value} & {"geometry", "coordinates", "features"}
        for item in value.values():
            _assert_no_geometry(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_geometry(item)


def test_request_contract_rejects_invalid_shapes():
    with pytest.raises(ValueError, match="rank_requires_exactly_1_metric"):
        SpatialEvidenceRequest(analysis="rank", metric_ids=["population.total", "nightlight.mean_radiance"])
    with pytest.raises(ValueError, match="relationship_requires_2_to_4_fact_domains"):
        SpatialDomainComputationRequest(analysis="relationship", fact_domains=["population"])
    with pytest.raises(ValueError, match="fact_domains_must_be_unique"):
        SpatialDomainComputationRequest(
            analysis="relationship",
            fact_domains=["population", "population"],
            evidence_dimensions=["population.scale", "population.scale"],
        )
    with pytest.raises(ValueError, match="relationship_requires_one_dimension_per_fact_domain"):
        SpatialDomainComputationRequest(
            analysis="relationship",
            fact_domains=["road", "poi"],
            evidence_dimensions=["road.to_movement", "road.through_movement"],
        )
    with pytest.raises(ValueError, match="population_sex_must_be"):
        SpatialEvidenceSelector(dimension="population.sex", values=["unknown"])
    with pytest.raises(ValueError, match="population_age_band_unsupported"):
        SpatialEvidenceSelector(dimension="population.age_band", values=["18"])
    with pytest.raises(ValueError, match="road_radius_requires_exactly_1_value"):
        SpatialEvidenceSelector(dimension="road.radius", values=["600", "800"])
    with pytest.raises(ValueError, match="poi_category_requires_exactly_one_value"):
        SpatialEvidenceSelector(dimension="poi.category", values=["餐饮", "购物"])
    with pytest.raises(ValueError, match="poi_category_unsupported"):
        SpatialEvidenceSelector(dimension="poi.category", values=["不存在的业态"])


def test_scope_discovers_four_fact_domains_without_metric_menu():
    result = _service().compute_domains(history_id="history-1", request={"analysis": "scope"})

    assert result["status"] == "available"
    assert {item["domain"] for item in result["fact_domains"]} == set(FACT_DOMAIN_CAPABILITIES)
    assert result["summary"]["domain_count"] == 4
    assert "metrics" not in result
    assert "evidence_dimensions" not in result


def test_population_default_uses_total_population_only():
    service = _service()
    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "direction", "fact_domains": ["population"]},
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["population.total"]
    assert set(result["domain_results"][0]["summary"]) == {"population.total"}
    assert service._datasets.load_calls == ["current:dataset:population"]


def test_population_scope_profile_uses_one_saved_snapshot_for_all_age_and_sex_values():
    result = _service().compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["population"]},
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["population.profile", "population.temporal_profile"]
    profile = result["domain_results"][0]["summary"]["population.profile"]
    assert len(profile["age_distribution"]) == 20
    assert {row["age_band"] for row in profile["age_distribution"]} == set(age_band_keys())
    assert profile["sex_totals"]["total"] == pytest.approx(2800.0)
    assert profile["sex_totals"]["male"] + profile["sex_totals"]["female"] == pytest.approx(2800.0)

    temporal = result["domain_results"][1]
    assert temporal["status"] == "available"
    assert [row["year"] for row in temporal["summary"]["series"]] == ["2024", "2025", "2026"]
    assert all(len(row["age_distribution"]) == 20 for row in temporal["summary"]["series"])
    assert temporal["coverage"]["age_band_count_by_year"] == {"2024": 20, "2025": 20, "2026": 20}
    assert temporal["coverage"]["complete"] is True
    assert temporal["summary"]["change_2024_2026"]["total_population"] == {
        "from": 1000.0,
        "to": 1100.0,
        "delta": 100.0,
        "rate": 0.1,
    }
    assert temporal["summary"]["change_2024_2026"]["age_group_ratio"]["senior_65_plus"]["percentage_point_delta"] == pytest.approx(3.1818)
    assert temporal["summary"]["spatial_change"] == {"cell_count": 25, "class_counts": {"increase": 20, "stable": 5}}
    assert temporal["method"]["spatial_aggregation"] == "intersecting_full_cells"


def test_scope_sum_includes_full_value_of_boundary_intersecting_cell():
    population = [
        _record(
            "current:dataset:population",
            "boundary-cell",
            box(0.04, 0.04, 0.06, 0.06),
            population_total=100,
            year=2026,
        )
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:population": population}),
        metric_catalog=_Catalog(),
    ).analyze(
        history_id="history-1",
        request={"analysis": "scope", "metric_ids": ["population.total"]},
    )

    assert result["summary"]["population.total"] == 100
    assert result["method"]["spatial_aggregation"] == "intersecting_full_cells"
    assert result["method"]["boundary_cell_policy"] == "include_full_cell_value"


def test_nightlight_scope_runs_one_layer_and_one_timeseries_call():
    calls = {"layer": 0, "timeseries": 0}

    def layer(*_args, **_kwargs):
        calls["layer"] += 1
        return {
            "year": 2025,
            "summary": {"total_radiance": 100, "mean_radiance": 4, "max_radiance": 12, "p90_radiance": 8, "lit_pixel_ratio": 0.75, "valid_pixel_count": 25},
            "analysis": {
                "economic_activity_intensity_level": "medium",
                "hotspot_cell_ratio": 0.2,
                "sector_direction_analysis": {"dominant_direction": "北", "dominant_share": 0.4},
            },
        }

    def timeseries(*_args, **_kwargs):
        calls["timeseries"] += 1
        return {
            "series": [
                {"year": 2023, "total_radiance": 80, "mean_radiance": 3, "max_radiance": 10, "p90_radiance": 7, "lit_pixel_ratio": 0.7},
                {"year": 2025, "total_radiance": 100, "mean_radiance": 4, "max_radiance": 12, "p90_radiance": 8, "lit_pixel_ratio": 0.75},
            ],
            "layer": {"summary": {"cell_count": 25, "class_counts": {"increase": 20, "stable": 5}}},
        }

    service = _service()
    service._nightlight_layer = layer
    service._nightlight_timeseries = timeseries
    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["nightlight"]},
    )

    assert calls == {"layer": 1, "timeseries": 1}
    assert result["coverage"]["computation_count"] == 1
    assert result["used_metric_ids"][-2:] == ["nightlight.activity_level", "nightlight.temporal_profile"]
    summary = result["domain_results"][0]["summary"]
    assert summary["activity_background"]["level"] == "medium"
    assert summary["temporal"]["change_2023_2025"]["total_radiance"]["delta"] == 20
    assert result["domain_results"][0]["method"]["current_layer_calls"] == 1


def test_population_sex_and_age_selectors_resolve_hidden_internal_metric():
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "direction",
            "fact_domains": ["population"],
            "selectors": [
                {"dimension": "population.sex", "values": ["female"]},
                {"dimension": "population.age_band", "values": ["65"]},
            ],
        },
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["population.age.65.female"]
    assert [item["dimension"] for item in result["evidence_dimensions"]] == ["population.scale"]
    assert result["domain_results"][0]["summary"]["population.age.65.female"] > 0


def test_all_population_age_and_sex_bindings_are_registered_internally():
    assert tuple(age_band_keys()) == POPULATION_AGE_BANDS
    for band in age_band_keys():
        for sex in ("total", "male", "female"):
            binding = METRIC_BINDINGS[f"population.age.{band}.{sex}"]
            assert binding.fields == (f"age_{sex}.{band}",)
    assert METRIC_BINDINGS["population.male"].fields == ("male_total",)
    assert METRIC_BINDINGS["population.female"].fields == ("female_total",)


def test_semantic_road_metrics_expose_only_normalized_movement_measures():
    assert {
        "road.integration",
        "road.choice",
        "road.integration.selected_radius",
        "road.choice.selected_radius",
    }.isdisjoint(METRIC_BINDINGS)
    assert {
        "road.nain",
        "road.nach",
        "road.nain.selected_radius",
        "road.nach.selected_radius",
    } <= set(METRIC_BINDINGS)


@pytest.mark.parametrize(
    ("radius", "expected_nain", "expected_nach"),
    [("global", 0.09, 0.07), ("600", 0.06, 0.04), ("800", 0.08, 0.05)],
)
def test_road_radius_selector_returns_saved_values(radius, expected_nain, expected_nach):
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "direction",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.to_movement", "road.through_movement"],
            "selectors": [{"dimension": "road.radius", "values": [radius]}],
        },
    )

    assert result["status"] == "available"
    computation = result["domain_results"][0]
    assert computation["summary"]["road.nain.selected_radius"] == pytest.approx(expected_nain)
    assert computation["summary"]["road.nach.selected_radius"] == pytest.approx(expected_nach)


def test_road_scope_reads_persisted_results_once_and_reports_all_radii():
    service = _service()
    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["road"]},
    )

    assert result["coverage"]["computation_count"] == 1
    assert service._datasets.load_calls == ["current:dataset:road_edges"]
    computation = result["domain_results"][0]
    assert computation["method"]["road_model_executed"] is False
    assert [item["radius"] for item in computation["summary"]["radius_profiles"]] == ["global", "600", "800"]
    assert computation["summary"]["radius_profiles"][0]["nain"]["valid_count"] == 1
    assert computation["summary"]["core_background"]["core"]["edge_count"] == 1


def test_road_scope_preserves_no_road_grid_metrics_as_null_not_zero():
    roads = [
        _record(
            "current:dataset:road_edges", "edge-1", LineString([(0, 0), (0.04, 0.04)]),
            road_name="测试道路", length_m=1000, nain_global=0.2, nach_global=0.1,
            metrics={"connectivity": 2},
        )
    ]
    grids = [
        _record(
            "current:dataset:road_grid", "covered", box(0, 0, 0.02, 0.02),
            road_has_data=True, road_nain=0.2, road_nach=0.1, road_connectivity=2,
        ),
        _record(
            "current:dataset:road_grid", "empty", box(0.03, 0.03, 0.04, 0.04),
            road_has_data=False, road_nain=None, road_nach=None, road_connectivity=None,
        ),
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_edges": roads, "current:dataset:road_grid": grids}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["road"]},
    )

    coverage = result["domain_results"][0]["summary"]["grid_coverage"]
    assert coverage["cell_count"] == 2
    assert coverage["covered_cell_count"] == 1
    assert coverage["no_road_cell_count"] == 1
    assert coverage["metric_valid_cell_count"] == {
        "road_nain": 1, "road_nach": 1, "road_connectivity": 1,
    }
    assert coverage["no_road_metric_semantics"] == "null_not_zero"


def test_poi_category_count_is_unique_category_count_not_record_count():
    records = [
        _record("current:dataset:poi", "a", Point(0.01, 0.01), category="餐饮服务"),
        _record("current:dataset:poi", "b", Point(0.02, 0.02), category="餐饮服务"),
        _record("current:dataset:poi", "c", Point(0.03, 0.03), category="购物服务"),
    ]
    service = SpatialEvidenceService(projects=_Projects({"current:dataset:poi": records}), metric_catalog=_Catalog())
    result = service.analyze(
        history_id="history-1",
        request={"analysis": "scope", "metric_ids": ["poi.category_count"]},
    )

    assert result["summary"]["poi.category_count"] == 2


def _poi_lq_service():
    cells = [
        _record(
            "current:dataset:h3",
            "h3-a",
            box(0, 0, 0.01, 0.01),
            h3_id="h3-a",
            poi_count=10,
            density_poi_per_km2=10,
            local_entropy=0.7,
            category_counts={"group-7": 5, "group-6": 5},
        ),
        _record(
            "current:dataset:h3",
            "h3-b",
            box(0.01, 0, 0.02, 0.01),
            h3_id="h3-b",
            poi_count=2,
            density_poi_per_km2=2,
            local_entropy=0,
            category_counts={"group-7": 0, "group-6": 2},
        ),
        _record(
            "current:dataset:h3",
            "h3-c",
            box(0.02, 0, 0.03, 0.01),
            h3_id="h3-c",
            poi_count=1,
            density_poi_per_km2=1,
            local_entropy=0,
            category_counts={"group-7": 1, "group-6": 0},
        ),
    ]
    return SpatialEvidenceService(
        projects=_Projects({"current:dataset:h3": cells}),
        metric_catalog=_Catalog(),
    )


def test_poi_domain_does_not_compute_lq_without_one_selected_category():
    result = _poi_lq_service().compute_domains(
        history_id="history-1",
        request={"analysis": "direction", "fact_domains": ["poi"]},
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["poi.grid_density", "poi.local_entropy"]
    assert "poi.category_lq" not in result["domain_results"][0]["summary"]


def test_selected_poi_category_lq_uses_standard_formula_for_every_nonempty_cell():
    result = _poi_lq_service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.category_specialization"],
            "selectors": [{"dimension": "poi.category", "values": ["餐饮服务"]}],
            "top_k": 3,
        },
    )

    computation = result["domain_results"][0]
    values = {
        item["record_ref"]: item["values"]["poi.category_lq"]
        for item in computation["highlights"]
    }
    assert result["used_metric_ids"] == ["poi.category_lq"]
    assert computation["coverage"]["valid_value_count"]["poi.category_lq"] == 3
    assert values["current:dataset:h3/h3-a"] == pytest.approx(1.083333)
    assert values["current:dataset:h3/h3-b"] == 0
    assert values["current:dataset:h3/h3-c"] == pytest.approx(2.166667)
    assert computation["metrics"][0]["selected_category"] == {"key": "group-7", "label": "餐饮"}
    assert computation["method"]["category_lq"]["smoothing_alpha"] == 0
    assert "lq_category" not in str(computation)


def test_poi_neighborhood_uses_all_persisted_local_statistics_without_recomputing():
    cells = [
        _record(
            "current:dataset:h3",
            "cell-a",
            box(0, 0, 0.01, 0.01),
            h3_id="cell-a",
            poi_count=10,
            density_poi_per_km2=100,
            local_entropy=0.8,
            neighbor_mean_density=70,
            neighbor_mean_entropy=0.6,
            gi_star_z_score=2.4,
            lisa_i=0.7,
            lisa_z_score=1.9,
        ),
        _record(
            "current:dataset:h3",
            "cell-b",
            box(0.01, 0, 0.02, 0.01),
            h3_id="cell-b",
            poi_count=5,
            density_poi_per_km2=50,
            local_entropy=0.4,
            neighbor_mean_density=80,
            neighbor_mean_entropy=0.7,
            gi_star_z_score=-1.2,
            lisa_i=-0.3,
            lisa_z_score=-1.1,
        ),
    ]
    projects = _Projects(
        {
            "current:dataset:h3": cells,
            "current:dataset:poi_grid": [
                _record(
                    "current:dataset:poi_grid",
                    "overlap",
                    box(0, 0, 0.02, 0.01),
                    density_poi_per_km2=999,
                    local_entropy=9,
                )
            ],
        },
        dataset_summaries={
            "current:dataset:h3": {
                "grid_count": 2,
                "poi_count": 15,
                "global_moran_i_density": 0.42,
                "global_moran_z_score": 3.1,
            }
        },
    )

    result = SpatialEvidenceService(
        projects=projects,
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply", "poi.mix"],
            "record_refs": ["current:dataset:h3/cell-a"],
        },
    )

    computation = result["domain_results"][0]
    assert result["used_metric_ids"] == [
        "poi.grid_density",
        "poi.neighbor_mean_density",
        "spatial.neighbor_density_delta",
        "spatial.gi_star",
        "spatial.lisa",
        "spatial.lisa_z",
        "poi.local_entropy",
        "poi.neighbor_mean_entropy",
    ]
    assert computation["groups"][0]["target_values"] == {
        "poi.grid_density": 100.0,
        "poi.neighbor_mean_density": 70.0,
        "spatial.neighbor_density_delta": 30.0,
        "spatial.gi_star": 2.4,
        "spatial.lisa": 0.7,
        "spatial.lisa_z": 1.9,
        "poi.local_entropy": 0.8,
        "poi.neighbor_mean_entropy": 0.6,
    }
    assert computation["summary"]["density_spatial_autocorrelation"] == {
        "global_moran_i": 0.42,
        "global_moran_z_score": 3.1,
        "significance_status": "available",
        "statistic_scope": "all_persisted_h3_cells",
        "spatial_unit_count": 2,
        "poi_count_in_spatial_units": 15,
    }
    assert computation["method"]["local_statistics"] == "persisted_h3_spatial_statistics"
    assert computation["method"]["spatial_statistics_recomputed"] is False
    assert projects.datasets.load_calls == ["current:dataset:h3"]


def test_zero_density_h3_keeps_zero_neighbor_delta_instead_of_missing():
    cells = [
        _record(
            "current:dataset:h3",
            "zero-cell",
            box(0, 0, 0.01, 0.01),
            h3_id="zero-cell",
            poi_count=0,
            density_poi_per_km2=0,
            local_entropy=0,
            neighbor_mean_density=25,
            neighbor_mean_entropy=0.2,
            gi_star_z_score=-1,
            lisa_i=0.1,
            lisa_z_score=0.2,
        )
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:h3": cells}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["poi"],
            "record_refs": ["current:dataset:h3/zero-cell"],
        },
    )

    values = result["domain_results"][0]["highlights"][0]["values"]
    assert values["poi.grid_density"] == 0
    assert values["spatial.neighbor_density_delta"] == -25
    assert not any("spatial.neighbor_density_delta" in item for item in result["domain_results"][0]["limitations"])


def test_poi_scope_remains_compact_and_does_not_add_local_statistics():
    result = _service().compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["poi"]},
    )

    assert result["used_metric_ids"] == [
        "poi.count", "poi.category_count", "poi.grid_density", "poi.local_entropy",
    ]
    assert "spatial.gi_star" not in str(result)
    assert "spatial.lisa" not in str(result)


def test_poi_scope_adds_persisted_snapshot_counts_without_claiming_open_close_change():
    def poi(year, count):
        return [
            _record(
                "current:dataset:poi",
                f"{year}-{index}",
                Point(0.01 + index * 0.001, 0.01),
                name=f"POI {index}",
                category="餐饮服务" if index % 2 == 0 else "购物服务",
                year=year,
            )
            for index in range(count)
        ]

    by_year = {2020: poi(2020, 2), 2022: poi(2022, 3), 2024: poi(2024, 4)}
    projects = _Projects(
        {"current:dataset:poi": by_year[2024]},
        records_by_year={"current:dataset:poi": by_year},
    )

    result = SpatialEvidenceService(
        projects=projects,
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["poi"], "evidence_dimensions": ["poi.supply"]},
    )

    temporal = next(item for item in result["domain_results"] if item["method"]["kind"] == "persisted_poi_snapshot_comparison")
    assert temporal["summary"]["snapshots"] == [
        {"year": 2020, "poi_count": 2, "category_count": 2},
        {"year": 2022, "poi_count": 3, "category_count": 2},
        {"year": 2024, "poi_count": 4, "category_count": 2},
    ]
    assert temporal["method"]["entity_change_computed"] is False
    assert temporal["method"]["snapshot_counts_only"] is True
    assert "poi.multi_year_count" in result["used_metric_ids"]
    assert any("不能直接解释为开闭店" in item for item in temporal["limitations"])


def test_internal_category_lq_rejects_missing_category_selector():
    with pytest.raises(ValueError, match="poi_category_lq_requires_exactly_one_poi_category"):
        _poi_lq_service().analyze(
            history_id="history-1",
            request={"analysis": "rank", "metric_ids": ["poi.category_lq"]},
        )


def _focused_accessibility_service(*, disconnected: bool = False):
    origin = (0.025, 0.025)
    roads = [
        _record(
            "current:dataset:road_edges",
            "origin-network",
            LineString([(0.02, 0.025), (0.025, 0.025), (0.03, 0.025)]),
            road_name="中心道路",
        )
    ]
    destination = (0.034, 0.025) if disconnected else (0.027, 0.025)
    if disconnected:
        roads.append(_record(
            "current:dataset:road_edges",
            "disconnected-network",
            LineString([(0.033, 0.025), (0.036, 0.025)]),
            road_name="孤立道路",
        ))
    pois = [
        _record(
            "current:dataset:poi",
            "food-1",
            Point(destination),
            name="路网餐厅",
            category="餐饮服务",
            subcategory="中餐馆",
            typecode="050101",
            address="测试路 1 号",
            year=2026,
        ),
        _record(
            "current:dataset:poi",
            "shop-1",
            Point(0.026, 0.025),
            name="路网商店",
            category="购物服务",
            subcategory="商场",
            typecode="060101",
            year=2026,
        ),
    ]
    projects = _Projects({
        "current:dataset:poi": pois,
        "current:dataset:road_edges": roads,
    })
    isochrone_calls = []

    def contours(_center, times, _mode):
        isochrone_calls.append(tuple(times))
        return {float(value): box(0.02, 0.02, 0.03, 0.03) for value in times}

    return SpatialEvidenceService(
        projects=projects,
        metric_catalog=_Catalog(),
        isochrone_contours=contours,
    ), projects, isochrone_calls, origin


def test_selected_poi_category_accessibility_routes_over_persisted_road_results():
    service, projects, isochrone_calls, origin = _focused_accessibility_service()

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "accessibility",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
            "selectors": [{"dimension": "poi.category", "values": ["餐饮服务"]}],
        },
    )

    computation = result["domain_results"][0]
    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["poi.focused_accessibility"]
    assert computation["summary"]["selected_category"] == {"key": "group-7", "label": "餐饮"}
    assert computation["summary"]["origin_wgs84"] == pytest.approx(origin)
    assert computation["summary"]["route_verified_poi_count"] == 1
    assert computation["named_spatial_objects"] == [{
        "record_ref": "current:dataset:poi/food-1",
        "object_type": "poi",
        "name": "路网餐厅",
        "category": "餐饮",
        "poi_typecode": "050101",
        "address": "测试路 1 号",
        "walking_distance_m": pytest.approx(222.4, abs=2),
        "walking_time_min": pytest.approx(2.97, abs=0.05),
        "road_path_distance_m": pytest.approx(222.4, abs=2),
        "origin_access_distance_m": pytest.approx(0, abs=0.1),
        "destination_access_distance_m": pytest.approx(0, abs=0.1),
        "route_status": "available",
        "road_source_id": "current:dataset:road_edges",
    }]
    assert computation["method"]["routing_algorithm"] == "local_road_network_shortest_path"
    assert computation["method"]["road_model_executed"] is False
    assert computation["method"]["depthmapx_executed"] is False
    assert computation["method"]["local_route_graph_built"] is True
    assert projects.datasets.load_calls == ["current:dataset:poi", "current:dataset:road_edges"]
    assert isochrone_calls == []
    _assert_no_geometry(result)


def test_poi_accessibility_without_category_keeps_standard_isochrone_supply_analysis():
    service, projects, isochrone_calls, _ = _focused_accessibility_service()

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "accessibility",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
        },
    )

    computation = result["domain_results"][0]
    assert result["used_metric_ids"] == ["poi.grid_density"]
    assert computation["method"]["kind"] == "accessibility_intersection_aggregation"
    assert isochrone_calls == [(5.0, 10.0, 15.0)]
    assert projects.datasets.load_calls == ["current:dataset:poi"]


def test_selected_poi_category_accessibility_omits_disconnected_paths_without_fallback():
    service, _, isochrone_calls, _ = _focused_accessibility_service(disconnected=True)

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "accessibility",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
            "selectors": [{"dimension": "poi.category", "values": ["餐饮"]}],
        },
    )

    computation = result["domain_results"][0]
    assert result["status"] == "unavailable"
    assert computation["summary"]["route_verified_poi_count"] == 0
    assert computation["summary"]["route_status"] == "unavailable"
    assert computation["summary"]["omission_reason"] == "no_local_road_path"
    assert computation["named_spatial_objects"] == []
    assert isochrone_calls == []
    assert "直线距离或模拟路径" in computation["limitations"][0]


def test_rank_and_inspect_reproduce_same_population_value():
    service = _service()
    ranked = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.scale"],
            "top_k": 1,
        },
    )
    highlight = ranked["domain_results"][0]["highlights"][0]
    inspected = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.scale"],
            "record_refs": [highlight["record_ref"]],
        },
    )

    inspected_highlight = inspected["domain_results"][0]["highlights"][0]
    assert inspected_highlight["record_ref"] == highlight["record_ref"]
    assert inspected_highlight["values"]["population.total"] == highlight["values"]["population.total"]
    assert inspected["domain_results"][0]["named_spatial_objects"][0]["record_ref"] == highlight["record_ref"]


def test_road_rank_requires_explicit_semantic_dimension():
    with pytest.raises(ValueError, match="rank_requires_one_dimension_per_fact_domain"):
        SpatialDomainComputationRequest(analysis="rank", fact_domains=["road"])


def test_road_object_is_a_rank_unit_not_an_inspect_or_neighborhood_filter():
    with pytest.raises(ValueError, match="road_object_only_supported_for_rank"):
        SpatialDomainComputationRequest(
            analysis="inspect",
            fact_domains=["road"],
            record_refs=["current:dataset:road_nodes/node-1"],
            selectors=[{"dimension": "road.object", "values": ["segment"]}],
        )
    with pytest.raises(ValueError, match="road_object_unsupported"):
        SpatialEvidenceSelector(dimension="road.object", values=["node"])


def test_road_rank_object_rejects_incompatible_domain_and_dimension():
    with pytest.raises(ValueError, match="road_object_requires_road_fact_domain"):
        SpatialDomainComputationRequest(
            analysis="rank",
            fact_domains=["poi"],
            evidence_dimensions=["poi.supply"],
            selectors=[{"dimension": "road.object", "values": ["segment"]}],
        )
    with pytest.raises(ValueError, match="road_segment_rank_dimension_unsupported"):
        SpatialDomainComputationRequest(
            analysis="rank",
            fact_domains=["road"],
            evidence_dimensions=["road.network_density"],
            selectors=[{"dimension": "road.object", "values": ["segment"]}],
        )


@pytest.mark.parametrize(
    ("dimension", "metric_id", "expected"),
    [
        ("road.to_movement", "road.nain.selected_radius", 0.06),
        ("road.through_movement", "road.nach.selected_radius", 0.04),
    ],
)
def test_road_rank_uses_requested_movement_dimension(dimension, metric_id, expected):
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["road"],
            "evidence_dimensions": [dimension],
            "selectors": [{"dimension": "road.radius", "values": ["600"]}],
            "top_k": 1,
        },
    )

    assert result["used_metric_ids"] == [metric_id]
    assert result["domain_results"][0]["highlights"][0]["values"][metric_id] == pytest.approx(expected)


def test_road_orientation_cannot_be_used_for_rank():
    with pytest.raises(ValueError, match="dimension_not_supported_for_rank:road.orientation"):
        SpatialDomainComputationRequest(
            analysis="rank",
            fact_domains=["road"],
            evidence_dimensions=["road.orientation"],
        )


def test_road_rank_can_select_persisted_continuous_corridors():
    corridors = [
        _record(
            "current:dataset:road_corridors",
            "corridor-a",
            LineString([(0.0, 0.01), (0.03, 0.01)]),
            corridor_id="corridor-a",
            metric="nain",
            radius="global",
            road_names=["主廊道"],
            edge_count=3,
            length_m=3000,
            nain_global=0.8,
        ),
        _record(
            "current:dataset:road_corridors",
            "corridor-b",
            LineString([(0.0, 0.02), (0.02, 0.02)]),
            corridor_id="corridor-b",
            metric="nain",
            radius="global",
            road_names=["次廊道"],
            edge_count=2,
            length_m=2000,
            nain_global=0.5,
        ),
    ]
    service = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_corridors": corridors}),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.to_movement"],
            "selectors": [{"dimension": "road.object", "values": ["corridor"]}],
            "top_k": 1,
        },
    )

    highlight = result["domain_results"][0]["highlights"][0]
    assert highlight["record_ref"] == "current:dataset:road_corridors/corridor-a"
    assert highlight["identity"]["road_names"] == ["主廊道"]


def test_road_network_density_rank_uses_shared_grid_not_segments():
    roads = [
        _record(
            "current:dataset:road_edges",
            "edge-a",
            LineString([(0.0, 0.01), (0.03, 0.01)]),
            road_name="不应作为密度排名单元",
            length_m=3000,
        )
    ]
    grid = [
        _record(
            "current:dataset:road_grid",
            "grid-low",
            box(0.0, 0.0, 0.01, 0.01),
            cell_id="grid-low",
            road_length_km=0.5,
            road_length_km_per_km2=2.0,
        ),
        _record(
            "current:dataset:road_grid",
            "grid-high",
            box(0.01, 0.0, 0.02, 0.01),
            cell_id="grid-high",
            road_length_km=0.8,
            road_length_km_per_km2=5.0,
        ),
    ]
    service = SpatialEvidenceService(
        projects=_Projects({
            "current:dataset:road_edges": roads,
            "current:dataset:road_grid": grid,
        }),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.network_density"],
            "top_k": 1,
        },
    )

    highlight = result["domain_results"][0]["highlights"][0]
    assert highlight["record_ref"] == "current:dataset:road_grid/grid-high"
    assert highlight["values"]["road.network_density"] == 5.0


def test_explicit_corridor_rank_does_not_fall_back_to_segments():
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.to_movement"],
            "selectors": [{"dimension": "road.object", "values": ["corridor"]}],
        },
    )

    assert result["status"] == "unavailable"
    assert result["domain_results"][0]["highlights"] == []


def test_road_neighborhood_uses_persisted_node_topology_not_line_intersection():
    roads = [
        _record(
            "current:dataset:road_edges",
            "edge-a",
            LineString([(0.0, 0.01), (0.02, 0.01)]),
            road_name="A路",
            from_node="n1",
            to_node="n2",
            metrics={"connectivity": 2},
        ),
        _record(
            "current:dataset:road_edges",
            "edge-b",
            LineString([(0.02, 0.01), (0.04, 0.01)]),
            road_name="B路",
            from_node="n2",
            to_node="n3",
            metrics={"connectivity": 3},
        ),
        _record(
            "current:dataset:road_edges",
            "edge-crossing",
            LineString([(0.01, 0.0), (0.01, 0.02)]),
            road_name="跨越路",
            from_node="n4",
            to_node="n5",
            metrics={"connectivity": 1},
        ),
    ]
    service = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_edges": roads}),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.connectivity"],
            "record_refs": ["current:dataset:road_edges/edge-a"],
            "neighbor_steps": 1,
        },
    )

    computation = result["domain_results"][0]
    assert computation["groups"][0]["neighbor_count"] == 1
    assert computation["method"]["kind"] == "road_edge_topology"


def test_road_grid_neighborhood_uses_grid_adjacency():
    grid = [
        _record(
            "current:dataset:road_grid", "grid-a", box(0.0, 0.0, 0.01, 0.01),
            cell_id="grid-a", road_connectivity=2.0,
        ),
        _record(
            "current:dataset:road_grid", "grid-b", box(0.01, 0.0, 0.02, 0.01),
            cell_id="grid-b", road_connectivity=3.0,
        ),
        _record(
            "current:dataset:road_grid", "grid-far", box(0.03, 0.0, 0.04, 0.01),
            cell_id="grid-far", road_connectivity=1.0,
        ),
    ]
    service = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_grid": grid}),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.connectivity"],
            "record_refs": ["current:dataset:road_grid/grid-a"],
            "neighbor_steps": 1,
        },
    )

    computation = result["domain_results"][0]
    assert computation["groups"][0]["neighbor_count"] == 1
    assert computation["method"]["kind"] == "geometry_adjacency"


def test_road_direction_is_relative_to_project_anchor_not_road_orientation():
    grid = [
        _record(
            "current:dataset:road_grid", "west", box(0.0, 0.021, 0.01, 0.029),
            cell_id="west", road_nain=0.2,
        ),
        _record(
            "current:dataset:road_grid", "east", box(0.04, 0.021, 0.05, 0.029),
            cell_id="east", road_nain=0.8,
        ),
    ]
    service = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_grid": grid}),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "direction",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.to_movement"],
        },
    )

    computation = result["domain_results"][0]
    groups = {item["key"]: item for item in computation["groups"]}
    assert set(groups) == {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
    assert groups["E"]["cell_count"] == 1
    assert groups["W"]["cell_count"] == 1
    assert all(groups[key]["cell_count"] == 0 for key in {"N", "NE", "SE", "S", "SW", "NW"})
    assert groups["E"]["values"]["road.nain"] == 0.8
    assert groups["W"]["values"]["road.nain"] == 0.2
    assert computation["method"]["kind"] == "direction_grouping"
    assert "orientation" not in computation["summary"]


def test_road_node_inspect_expands_persisted_record_without_edge_metrics():
    nodes = [
        _record(
            "current:dataset:road_nodes", "node-1", Point(0.025, 0.025),
            node_id="node-1", degree=4,
        )
    ]
    service = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_nodes": nodes}),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["road"],
            "record_refs": ["current:dataset:road_nodes/node-1"],
        },
    )

    computation = result["domain_results"][0]
    assert result["status"] == "available"
    assert result["used_metric_ids"] == []
    assert computation["named_spatial_objects"][0]["record_ref"] == "current:dataset:road_nodes/node-1"
    assert computation["named_spatial_objects"][0]["attributes"]["degree"] == 4


def test_road_node_inspect_reads_only_the_referenced_dataset():
    projects = _Projects({
        "current:dataset:road_nodes": [
            _record(
                "current:dataset:road_nodes", "node-1", Point(0.025, 0.025),
                node_id="node-1", degree=4,
            )
        ],
        "current:dataset:road_edges": [
            _record(
                "current:dataset:road_edges", "edge-1", LineString([(0.02, 0.025), (0.03, 0.025)]),
                road_name="无关道路", metrics={"connectivity": 1},
            )
        ],
        "current:dataset:poi": [
            _record("current:dataset:poi", "poi-1", Point(0.025, 0.025), name="无关设施"),
        ],
    })
    service = SpatialEvidenceService(projects=projects, metric_catalog=_Catalog())

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["road"],
            "record_refs": ["current:dataset:road_nodes/node-1"],
        },
    )

    assert result["status"] == "available"
    assert projects.datasets.load_calls == ["current:dataset:road_nodes"]


def test_road_accessibility_uses_valhalla_bands_and_road_structure_not_nain():
    grid = []
    for index in range(25):
        x = (index % 5) * 0.01
        y = (index // 5) * 0.01
        grid.append(_record(
            "current:dataset:road_grid",
            f"road-{index}",
            box(x, y, x + 0.009, y + 0.009),
            cell_id=f"road-{index}",
            road_length_km=1.0,
            road_length_km_per_km2=4.0,
            road_connectivity=2.0,
            road_nain=0.9,
        ))
    service = _service()
    service._projects = _Projects({"current:dataset:road_grid": grid})
    service._datasets = service._projects.datasets

    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "accessibility", "fact_domains": ["road"]},
    )

    computation = result["domain_results"][0]
    assert result["used_metric_ids"] == [
        "road.network_size", "road.network_density", "road.connectivity",
    ]
    assert len(computation["groups"]) == 3
    assert computation["method"]["travel_time_method"] == "valhalla_nested_isochrone_contours"
    assert "road.nain" not in str(computation["metrics"])


def test_road_poi_relationship_uses_shared_grid_colocation_only():
    poi_grid = []
    road_grid = []
    for index in range(25):
        x = (index % 5) * 0.01
        y = (index // 5) * 0.01
        geometry = box(x, y, x + 0.009, y + 0.009)
        poi_grid.append(_record(
            "current:dataset:poi_grid",
            f"cell-{index}",
            geometry,
            cell_id=f"cell-{index}",
            density_poi_per_km2=float(index),
        ))
        road_grid.append(_record(
            "current:dataset:road_grid",
            f"cell-{index}",
            geometry,
            cell_id=f"cell-{index}",
            road_nain=float(index),
        ))
    service = SpatialEvidenceService(
        projects=_Projects({
            "current:dataset:poi_grid": poi_grid,
            "current:dataset:road_grid": road_grid,
        }),
        metric_catalog=_Catalog(),
    )

    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "relationship",
            "fact_domains": ["road", "poi"],
            "evidence_dimensions": ["road.to_movement", "poi.supply"],
        },
    )

    computation = result["domain_results"][0]
    assert computation["relationship"]["spatial_unit_count"] == 25
    assert computation["relationship"]["pattern_counts"]["joint_high"] > 0
    assert computation["method"]["kind"] == "p25_p75_colocation"
    assert any("不表示因果关系" in value for value in computation["limitations"])


def test_accessibility_does_not_fabricate_when_valhalla_is_unavailable():
    def unavailable(*_args):
        raise ValhallaIsochroneUnavailable("connection failed")

    service = _service()
    service._isochrone_contours = unavailable
    result = service.analyze(
        history_id="history-1",
        request={"analysis": "accessibility", "metric_ids": ["population.total"]},
    )

    assert result["status"] == "unavailable"
    assert result["limitations"]


def test_model_projection_removes_geometry_and_bounds_payload():
    payload = {
        "schema_version": "spatial_evidence/v7",
        "result_id": "spatial:test",
        "status": "available",
        "analysis": "scope",
        "summary": {"geometry": {"type": "Polygon"}, "message": "x" * 9000},
        "highlights": [{"record_ref": f"record:{index}", "coordinates": [0, 0]} for index in range(40)],
        "evidence": [],
        "limitations": [],
        "method": {"kind": "test"},
        "provenance": {},
    }

    projected = _bounded_model_response(payload)

    _assert_no_geometry(projected)
    assert len(str(projected)) < 9000
    assert projected["summary"]


def test_internal_metrics_are_not_second_public_dimension_catalog():
    schema = SpatialDomainComputationRequest.model_json_schema()["properties"]
    assert "evidence_dimensions" in schema
    assert "metric_ids" not in schema
    assert set(CATALOG_SCOPE_BINDINGS).isdisjoint({
        metric_id for metric_id in METRIC_BINDINGS if metric_id.startswith("population.age.")
    })
