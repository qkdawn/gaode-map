from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, MultiPolygon, Point, box, mapping

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
    def population_for_year(year, factor):
        rows = []
        for record in population:
            properties = dict(record.properties)
            properties.pop("record_id", None)
            properties.update({
                "year": year,
                "population_total": properties["population_total"] * factor,
                "male_total": properties["male_total"] * factor,
                "female_total": properties["female_total"] * factor,
                "age_total": {key: value * factor for key, value in properties["age_total"].items()},
                "age_male": {key: value * factor for key, value in properties["age_male"].items()},
                "age_female": {key: value * factor for key, value in properties["age_female"].items()},
            })
            rows.append(_record(record.source_id, record.record_id, record.geometry, **properties))
        return rows

    population_by_year = {
        2024: population_for_year(2024, 0.8),
        2025: population_for_year(2025, 0.9),
        2026: population_for_year(2026, 1.0),
    }
    nightlight_by_year = {
        year: [
            _record(
                record.source_id,
                record.record_id,
                record.geometry,
                radiance=float(record.properties["radiance"]) * factor,
                year=year,
            )
            for record in nightlight
        ]
        for year, factor in ((2023, 0.7), (2024, 0.85), (2025, 1.0))
    }
    projects = _Projects(
        {
            "current:dataset:population": population,
            "current:dataset:nightlight": nightlight,
            "current:dataset:poi": poi,
            "current:dataset:road_edges": roads,
        },
        records_by_year={
            "current:dataset:population": population_by_year,
            "current:dataset:nightlight": nightlight_by_year,
        },
    )

    def contours(_center, times, _mode):
        bounds = {5.0: box(0.02, 0.02, 0.03, 0.03), 10.0: box(0.01, 0.01, 0.04, 0.04), 15.0: box(0, 0, 0.05, 0.05)}
        return {float(value): bounds[float(value)] for value in times}

    def nightlight_layer(_polygon, _coord_type, *, year, view):
        assert year == 2025
        assert view == "radiance"
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
                "brightness_context_level": "high",
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
    with pytest.raises(ValueError, match="population_sex_requires_exactly_1_value"):
        SpatialEvidenceSelector(dimension="population.sex", values=["male", "female"])
    with pytest.raises(ValueError, match="population_age_band_unsupported"):
        SpatialEvidenceSelector(dimension="population.age_band", values=["18"])
    with pytest.raises(ValueError, match="population_age_band_requires_exactly_1_value"):
        SpatialEvidenceSelector(dimension="population.age_band", values=["65", "70"])
    with pytest.raises(ValueError, match="population_sex_requires_exactly_1_value"):
        SpatialDomainComputationRequest(
            analysis="direction",
            fact_domains=["population"],
            selectors=[
                {"dimension": "population.sex", "values": ["male"]},
                {"dimension": "population.sex", "values": ["female"]},
            ],
        )
    with pytest.raises(ValueError, match="population_age_band_requires_exactly_1_value"):
        SpatialEvidenceRequest(
            analysis="direction",
            metric_ids=["population.total"],
            selectors=[
                {"dimension": "population.age_band", "values": ["65"]},
                {"dimension": "population.age_band", "values": ["70"]},
            ],
        )
    with pytest.raises(ValueError, match="population_measure_unsupported"):
        SpatialEvidenceSelector(dimension="population.measure", values=["median"])
    with pytest.raises(ValueError, match="population_share_requires_selected_subgroup"):
        SpatialDomainComputationRequest(
            analysis="rank",
            fact_domains=["population"],
            selectors=[{"dimension": "population.measure", "values": ["share"]}],
        )
    with pytest.raises(ValueError, match="road_radius_requires_exactly_1_value"):
        SpatialEvidenceSelector(dimension="road.radius", values=["600", "800"])
    with pytest.raises(ValueError, match="poi_category_requires_one_or_two_values"):
        SpatialEvidenceSelector(dimension="poi.category", values=["餐饮", "购物", "住宿"])
    with pytest.raises(ValueError, match="poi_categories_must_be_distinct"):
        SpatialEvidenceSelector(dimension="poi.category", values=["餐饮", "餐饮服务"])
    with pytest.raises(ValueError, match="poi_category_unsupported"):
        SpatialEvidenceSelector(dimension="poi.category", values=["不存在的业态"])
    with pytest.raises(ValueError, match="two_poi_categories_only_supported_for_poi_relationship"):
        SpatialDomainComputationRequest(
            analysis="direction",
            fact_domains=["poi"],
            selectors=[{"dimension": "poi.category", "values": ["餐饮", "购物"]}],
        )


def test_scope_discovers_four_fact_domains_without_metric_menu():
    result = _service().compute_domains(history_id="history-1", request={"analysis": "scope"})

    assert result["status"] == "available"
    assert {item["domain"] for item in result["fact_domains"]} == set(FACT_DOMAIN_CAPABILITIES)
    assert result["summary"]["domain_count"] == 4
    assert "metrics" not in result
    assert "evidence_dimensions" not in result


def test_population_direction_returns_target_population_and_structure_by_sector():
    service = _service()
    result = service.compute_domains(
        history_id="history-1",
        request={"analysis": "direction", "fact_domains": ["population"]},
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["population.total", "population.profile"]
    computation = result["domain_results"][0]
    assert computation["method"]["kind"] == "population_distribution_direction"
    assert "semantics" not in computation["method"]
    assert "dominant_distribution_direction" in computation["summary"]
    assert "dominant_direction" not in computation["summary"]
    assert len(computation["groups"]) == 8
    assert sum(group["target_population_share"] for group in computation["groups"]) == pytest.approx(1.0, abs=2e-6)
    assert all(len(group["age_distribution"]) == 20 for group in computation["groups"])
    distribution = computation["summary"]["distribution"]
    assert len(distribution["weighted_center_wgs84"]) == 2
    assert distribution["standard_deviation_ellipse"]["major_axis_standard_distance_m"] > 0
    assert distribution["standard_deviation_ellipse"]["minor_axis_standard_distance_m"] > 0
    assert service._datasets.load_calls == ["current:dataset:population"]


def test_population_scope_profile_uses_one_saved_snapshot_for_all_age_and_sex_values():
    result = _service().compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["population"]},
    )

    assert result["status"] == "available"
    assert result["used_metric_ids"] == ["population.profile"]
    profile = result["domain_results"][0]["summary"]["population"]
    assert len(profile["age_distribution"]) == 20
    assert {row["age_band"] for row in profile["age_distribution"]} == set(age_band_keys())
    assert profile["sex_totals"]["total"] == pytest.approx(2800.0)
    assert profile["sex_totals"]["male"] + profile["sex_totals"]["female"] == pytest.approx(2800.0)
    assert profile["density_person_per_km2"] > 0
    assert sum(row["share"] for row in profile["age_distribution"]) == pytest.approx(
        sum(row["total"] for row in profile["age_distribution"]) / profile["total_population"]
    )
    assert "limitations" not in result["domain_results"][0]

    change_result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "scope",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.change"],
        },
    )
    temporal = change_result["domain_results"][0]
    assert temporal["status"] == "available"
    assert [row["year"] for row in temporal["summary"]["series"]] == ["2024", "2025", "2026"]
    assert all(len(row["age_distribution"]) == 20 for row in temporal["summary"]["series"])
    assert temporal["coverage"]["age_band_count_by_year"] == {"2024": 20, "2025": 20, "2026": 20}
    assert temporal["coverage"]["complete"] is True
    assert temporal["summary"]["change_2024_2026"]["total_population"] == {
        "from": 2240.0,
        "to": 2800.0,
        "delta": 560.0,
        "rate": 0.25,
    }
    assert temporal["summary"]["change_2024_2026"]["age_group_ratio"]["senior_65_plus"]["percentage_point_delta"] == pytest.approx(0)
    assert temporal["summary"]["spatial_change"] == {
        "cell_count": 25,
        "class_counts": {"increase": 25},
        "cell_matching": "stable_record_id_intersection",
    }
    assert temporal["method"]["spatial_aggregation"] == "geometry_intersection_aggregation"
    assert temporal["method"]["boundary_cell_policy"] == "allocate_extensive_values_by_intersection_fraction"


def test_scope_sum_allocates_boundary_cell_by_intersection_area():
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

    assert result["summary"]["population.total"] == pytest.approx(25)
    assert result["method"]["spatial_aggregation"] == "geometry_intersection_aggregation"
    assert result["method"]["boundary_cell_policy"] == "allocate_extensive_values_by_intersection_fraction"


def test_population_change_allocates_boundary_cells_across_complete_multipolygon():
    scope_geometry = MultiPolygon([
        box(0.0, 0.0, 0.01, 0.01),
        box(0.04, 0.04, 0.05, 0.05),
    ])

    def yearly_records(year, factor):
        return [
            _record(
                "current:dataset:population", "west", box(-0.01, -0.01, 0.01, 0.01),
                **{**_population_properties(0), "year": year, "population_total": 100 * factor},
            ),
            _record(
                "current:dataset:population", "east", box(0.04, 0.04, 0.06, 0.06),
                **{**_population_properties(0), "year": year, "population_total": 200 * factor},
            ),
        ]

    records_by_year = {2024: yearly_records(2024, 1.0), 2026: yearly_records(2026, 2.0)}
    projects = _Projects(
        {"current:dataset:population": records_by_year[2026]},
        records_by_year={"current:dataset:population": records_by_year},
    )
    base_read = projects.read_history_project

    def read_history_project(history_id):
        project = base_read(history_id)
        project["scope"] = mapping(scope_geometry)
        return project

    projects.read_history_project = read_history_project
    temporal = SpatialEvidenceService(
        projects=projects,
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "scope",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.change"],
        },
    )["domain_results"][0]

    assert [row["total_population"] for row in temporal["summary"]["series"]] == pytest.approx([75, 150])
    assert temporal["summary"]["change_2024_2026"]["total_population"]["delta"] == pytest.approx(75)
    assert temporal["method"]["scope_geometry"] == "complete_polygon_or_multipolygon"


def test_nightlight_intensity_scope_runs_current_layer_without_timeseries():
    calls = {"layer": 0, "timeseries": 0}

    def layer(*_args, **_kwargs):
        calls["layer"] += 1
        return {
            "year": 2025,
            "summary": {"total_radiance": 100, "mean_radiance": 4, "max_radiance": 12, "p90_radiance": 8, "lit_pixel_ratio": 0.75, "valid_pixel_count": 25},
            "analysis": {
                "brightness_context_level": "medium",
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

    assert calls == {"layer": 1, "timeseries": 0}
    assert result["coverage"]["computation_count"] == 1
    assert result["used_metric_ids"][-2:] == ["nightlight.spatial_profile", "nightlight.sector_profile"]
    summary = result["domain_results"][0]["summary"]
    assert summary["brightness_profile"]["dominant_direction"] == "北"
    assert "brightness_context" not in summary
    assert "temporal" not in summary
    assert result["domain_results"][0]["method"]["current_layer_calls"] == 1


def test_population_selector_is_preserved_in_public_result_context():
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "direction",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.scale"],
            "selectors": [
                {"dimension": "population.sex", "values": ["female"]},
                {"dimension": "population.age_band", "values": ["65"]},
            ],
        },
    )

    expected = [
        {"dimension": "population.sex", "values": ["female"]},
        {"dimension": "population.age_band", "values": ["65"]},
    ]
    assert result["selectors"] == expected
    assert result["domain_results"][0]["selectors"] == expected


def test_unavailable_result_preserves_factual_reason_without_limitations():
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["population"],
            "record_refs": ["current:dataset:population/missing"],
        },
    )

    assert result["status"] == "unavailable"
    assert result["unavailable_reasons"]
    assert result["domain_results"][0]["unavailable_reason"]
    assert "limitations" not in result["domain_results"][0]


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
    assert result["used_metric_ids"] == ["population.age.65.female", "population.profile"]
    assert [item["dimension"] for item in result["evidence_dimensions"]] == [
        "population.scale", "population.structure",
    ]
    computation = result["domain_results"][0]
    assert computation["summary"]["target_metric_id"] == "population.age.65.female"
    assert sum(group["target_population"] for group in computation["groups"]) > 0


def test_all_population_age_and_sex_bindings_are_registered_internally():
    assert tuple(age_band_keys()) == POPULATION_AGE_BANDS
    for band in age_band_keys():
        for sex in ("total", "male", "female"):
            binding = METRIC_BINDINGS[f"population.age.{band}.{sex}"]
            assert binding.fields == (f"age_{sex}.{band}",)
    assert METRIC_BINDINGS["population.male"].fields == ("male_total",)
    assert METRIC_BINDINGS["population.female"].fields == ("female_total",)


def test_population_accessibility_returns_incremental_cumulative_and_structure():
    result = _service().compute_domains(
        history_id="history-1",
        request={"analysis": "accessibility", "fact_domains": ["population"]},
    )

    computation = result["domain_results"][0]
    assert computation["method"]["kind"] == "population_accessibility"
    assert [group["time_band_min"] for group in computation["groups"]] == [
        [0.0, 5.0], [5.0, 10.0], [10.0, 15.0],
    ]
    incremental = [group["incremental_population"] for group in computation["groups"]]
    cumulative = [item["population"] for item in computation["summary"]["cumulative"]]
    assert cumulative[-1] == pytest.approx(sum(incremental))
    assert cumulative == sorted(cumulative)
    assert all(len(group["structure"]["age_distribution"]) == 20 for group in computation["groups"])
    assert all(set(group["structure"]["age_groups"]) == {
        "child_0_14", "working_15_64", "senior_65_plus",
    } for group in computation["groups"])


def test_population_rank_neighborhood_and_inspect_use_population_semantics():
    service = _service()
    ranked = service.compute_domains(
        history_id="history-1",
        request={"analysis": "rank", "fact_domains": ["population"], "top_k": 2},
    )["domain_results"][0]
    target_ref = ranked["highlights"][0]["record_ref"]

    assert ranked["method"]["kind"] == "population_grid_rank"
    assert ranked["highlights"][0]["target_population"] >= ranked["highlights"][1]["target_population"]

    neighborhood = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "fact_domains": ["population"],
            "record_refs": [target_ref],
        },
    )["domain_results"][0]
    assert neighborhood["method"]["kind"] == "population_grid_neighborhood_comparison"
    assert neighborhood["method"]["comparison"] == "descriptive_target_vs_neighbors"
    assert "target" in neighborhood["groups"][0]
    assert "neighbors" in neighborhood["groups"][0]
    assert "comparison" in neighborhood["groups"][0]

    inspected = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["population"],
            "record_refs": [target_ref],
        },
    )["domain_results"][0]
    assert inspected["method"]["kind"] == "population_grid_inspect"
    assert inspected["highlights"][0]["population"]["age_distribution"]
    assert inspected["highlights"][0]["year"] == 2026
    assert inspected["highlights"][0]["population"]["density_person_per_km2"] > 0
    assert "neighborhood" in inspected["highlights"][0]


@pytest.mark.parametrize(
    ("measure", "selectors", "expected_unit"),
    [
        ("count", [], "person"),
        ("density", [], "person_per_km2"),
        (
            "share",
            [
                {"dimension": "population.sex", "values": ["female"]},
                {"dimension": "population.age_band", "values": ["65"]},
            ],
            "ratio",
        ),
    ],
)
def test_population_rank_explicitly_distinguishes_count_density_and_share(
    measure,
    selectors,
    expected_unit,
):
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "rank",
            "fact_domains": ["population"],
            "selectors": [
                *selectors,
                {"dimension": "population.measure", "values": [measure]},
            ],
            "top_k": 3,
        },
    )["domain_results"][0]

    assert result["summary"]["rank_measure"] == measure
    assert result["summary"]["rank_unit"] == expected_unit
    assert [row["rank_value"] for row in result["highlights"]] == sorted(
        (row["rank_value"] for row in result["highlights"]),
        reverse=True,
    )
    assert all(row["rank_measure"] == measure for row in result["highlights"])


def test_population_neighborhood_compares_target_with_adjacent_grid_mean():
    population = [
        _record(
            "current:dataset:population",
            "target",
            box(0.0, 0.0, 0.01, 0.01),
            **{**_population_properties(0), "population_total": 100.0},
        ),
        _record(
            "current:dataset:population",
            "neighbor",
            box(0.01, 0.0, 0.02, 0.01),
            **{**_population_properties(0), "population_total": 40.0},
        ),
        _record(
            "current:dataset:population",
            "outside",
            box(0.03, 0.03, 0.04, 0.04),
            **{**_population_properties(0), "population_total": 500.0},
        ),
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:population": population}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "fact_domains": ["population"],
            "record_refs": ["current:dataset:population/target"],
        },
    )["domain_results"][0]

    group = result["groups"][0]
    assert group["neighbor_count"] == 1
    assert group["target"]["target_population"] == pytest.approx(100.0)
    assert group["neighbors"]["target_population_mean_per_grid"] == pytest.approx(40.0)
    assert group["comparison"]["target_population_delta_from_neighbor_mean"] == pytest.approx(60.0)
    assert group["comparison"]["target_to_neighbor_mean_ratio"] == pytest.approx(2.5)
    assert group["focus_continuity"]["target_is_focus_grid"] is False
    assert group["focus_continuity"]["continuous_focus_area"] is False


def test_population_neighborhood_connects_only_adjacent_focus_grids():
    values = [100.0, 100.0, 10.0, 10.0]
    geometries = [
        box(0.0, 0.0, 0.01, 0.01),
        box(0.01, 0.0, 0.02, 0.01),
        box(0.03, 0.0, 0.04, 0.01),
        box(0.03, 0.02, 0.04, 0.03),
    ]
    population = [
        _record(
            "current:dataset:population", f"cell-{index}", geometry,
            **{**_population_properties(0), "population_total": value},
        )
        for index, (geometry, value) in enumerate(zip(geometries, values))
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:population": population}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "fact_domains": ["population"],
            "record_refs": ["current:dataset:population/cell-0"],
        },
    )["domain_results"][0]

    continuity = result["groups"][0]["focus_continuity"]
    assert continuity["target_is_focus_grid"] is True
    assert continuity["connected_focus_grid_count"] == 2
    assert continuity["connected_focus_population"] == pytest.approx(200)
    assert continuity["continuous_focus_area"] is True
    assert result["method"]["focus_rule"] == "descriptive_saved_isochrone_p75"


def test_population_relationship_reports_descriptive_mismatch_without_significance():
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "relationship",
            "fact_domains": ["population", "nightlight"],
            "evidence_dimensions": ["population.scale", "nightlight.intensity"],
        },
    )

    computation = result["domain_results"][0]
    assert "kind" not in computation["method"]
    assert computation["highlights"] == []
    assert computation["evidence"] == []
    assert computation["relationship"]["unit_values"]
    assert "pattern_counts" not in computation["relationship"]
    assert set(computation["relationship"]["distributions"]) == {
        "population.total",
        "nightlight.mean_radiance",
    }
    assert all(
        item["record_ref"] and set(item["values"]) == {"population.total", "nightlight.mean_radiance"}
        for item in computation["relationship"]["unit_values"]
    )


def test_population_relationship_uses_boundary_allocated_population_values():
    geometries = [
        box(0.0, 0.0, 0.01, 0.01),
        box(0.01, 0.0, 0.02, 0.01),
        box(0.02, 0.0, 0.03, 0.01),
        box(0.04, 0.04, 0.06, 0.06),
    ]
    populations = [10.0, 20.0, 30.0, 100.0]
    population_records = [
        _record(
            "current:dataset:population", f"population-{index}", geometry,
            **{**_population_properties(0), "population_total": value},
        )
        for index, (geometry, value) in enumerate(zip(geometries, populations))
    ]
    nightlight_records = [
        _record(
            "current:dataset:nightlight", f"nightlight-{index}", geometry,
            radiance=float(index + 1), year=2026,
        )
        for index, geometry in enumerate(geometries)
    ]
    result = SpatialEvidenceService(
        projects=_Projects({
            "current:dataset:population": population_records,
            "current:dataset:nightlight": nightlight_records,
        }),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "relationship",
            "fact_domains": ["population", "nightlight"],
            "evidence_dimensions": ["population.scale", "nightlight.intensity"],
        },
    )["domain_results"][0]

    boundary = next(
        row for row in result["relationship"]["unit_values"]
        if row["record_ref"] == "current:dataset:population/population-3"
    )
    assert boundary["values"]["population.total"] == pytest.approx(25.0)
    assert result["relationship"]["distributions"]["population.total"]["p75"] <= 30.0


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


def test_road_scope_returns_only_the_selected_semantic_dimension():
    service = _service()
    result = service.compute_domains(
        history_id="history-1",
        request={
            "analysis": "scope",
            "fact_domains": ["road"],
            "evidence_dimensions": ["road.to_movement"],
        },
    )

    computation = result["domain_results"][0]
    assert result["used_metric_ids"] == ["road.nain"]
    assert computation["evidence_dimensions"] == ["road.to_movement"]
    assert set(computation["summary"]) == {
        "radius_profiles", "core_background", "continuous_corridors",
    }
    assert set(computation["summary"]["radius_profiles"][0]) == {"radius", "nain"}
    assert "nach_p75" not in computation["summary"]["core_background"]
    assert service._datasets.load_calls == ["current:dataset:road_edges"]


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
    assert "no_road_metric_semantics" not in coverage


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


def test_poi_direction_returns_eight_sector_supply_and_equal_weight_ellipse():
    result = _service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "direction",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply", "poi.mix"],
        },
    )

    computation = result["domain_results"][0]
    assert computation["method"]["kind"] == "poi_direction_distribution"
    assert computation["method"]["spatial_universe"] == "saved_isochrone"
    assert len(computation["groups"]) == 8
    assert sum(group["poi_count"] for group in computation["groups"]) == 25
    assert sum(group["poi_share"] for group in computation["groups"]) == pytest.approx(1.0)
    distribution = computation["summary"]["distribution"]
    assert len(distribution["weighted_center_wgs84"]) == 2
    assert distribution["standard_deviation_ellipse"]["major_axis_standard_distance_m"] > 0
    assert "weight_semantics" not in distribution


def test_poi_relationship_uses_directional_clq_for_two_selected_categories():
    records = [
        _record("current:dataset:poi", "food-west", Point(0.001, 0.025), name="西侧餐饮", category="餐饮服务"),
        _record("current:dataset:poi", "shop-1", Point(0.002, 0.025), name="商店一", category="购物服务"),
        _record("current:dataset:poi", "shop-2", Point(0.0021, 0.025), name="商店二", category="购物服务"),
        _record("current:dataset:poi", "shop-3", Point(0.0022, 0.025), name="商店三", category="购物服务"),
        _record("current:dataset:poi", "food-east", Point(0.012, 0.025), name="东侧餐饮", category="餐饮服务"),
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:poi": records}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "relationship",
            "fact_domains": ["poi"],
            "selectors": [{"dimension": "poi.category", "values": ["餐饮", "购物"]}],
        },
    )

    computation = result["domain_results"][0]
    directed = computation["relationship"]["directed_colocation"]
    assert result["used_metric_ids"] == ["poi.category_colocation_quotient"]
    assert computation["method"]["kind"] == "poi_category_colocation_quotient"
    assert computation["method"]["spatial_universe"] == "saved_isochrone"
    assert computation["method"]["significance_test"] is False
    assert directed[0]["source_category"]["label"] == "餐饮"
    assert directed[0]["neighbor_category"]["label"] == "购物"
    assert directed[0]["clq"] == pytest.approx(4 / 3)
    assert directed[1]["source_category"]["label"] == "购物"
    assert directed[1]["clq"] == 0
    assert all("current:dataset:poi/" in item["source_record_ref"] for item in computation["named_spatial_objects"])
    _assert_no_geometry(result)


def test_poi_inspect_expands_inside_and_nearest_named_facilities_within_isochrone():
    cell = _record(
        "current:dataset:h3",
        "inspect-cell",
        box(0, 0, 0.01, 0.01),
        h3_id="inspect-cell",
        poi_count=1,
        density_poi_per_km2=10,
    )
    pois = [
        _record(
            "current:dataset:poi", "inside", Point(0.004, 0.004),
            name="格内餐厅", category="餐饮服务", subcategory="中餐馆",
        ),
        _record(
            "current:dataset:poi", "nearest", Point(0.014, 0.004),
            name="邻近商店", category="购物服务", subcategory="商场",
        ),
        _record(
            "current:dataset:poi", "outside", Point(0.08, 0.08),
            name="圈外设施", category="住宿服务", subcategory="酒店",
        ),
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:h3": [cell], "current:dataset:poi": pois}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "inspect",
            "fact_domains": ["poi"],
            "record_refs": ["current:dataset:h3/inspect-cell"],
        },
    )

    computation = result["domain_results"][0]
    assert computation["method"]["kind"] == "poi_grid_inspect"
    assert computation["groups"][0]["poi_count"] == 1
    assert computation["groups"][0]["category_structure"][0]["label"] == "餐饮"
    assert [item["name"] for item in computation["named_spatial_objects"]] == ["格内餐厅", "邻近商店"]
    assert [item["relation"] for item in computation["named_spatial_objects"]] == [
        "inside_target", "nearest_in_scope",
    ]


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


def test_poi_neighborhood_compares_in_scope_h3_and_expands_named_facilities():
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
            "current:dataset:poi": [
                _record(
                    "current:dataset:poi", "target-food", Point(0.004, 0.004),
                    name="目标餐厅", category="餐饮服务", subcategory="中餐馆",
                ),
                _record(
                    "current:dataset:poi", "target-shop", Point(0.006, 0.006),
                    name="目标商店", category="购物服务", subcategory="商场",
                ),
                _record(
                    "current:dataset:poi", "neighbor-food", Point(0.014, 0.004),
                    name="邻格餐厅", category="餐饮服务", subcategory="中餐馆",
                ),
            ],
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
        "poi.local_entropy",
        "poi.neighbor_mean_entropy",
    ]
    assert computation["groups"][0]["target_values"] == {
        "poi.grid_density": 100.0,
        "poi.neighbor_mean_density": 70.0,
        "spatial.neighbor_density_delta": 30.0,
        "poi.local_entropy": 0.8,
        "poi.neighbor_mean_entropy": 0.6,
    }
    context = computation["groups"][0]["poi_context"]
    assert context["target"]["poi_count"] == 2
    assert context["neighbors"]["poi_count"] == 1
    assert context["comparison"]["poi_count_delta_from_neighbor_mean"] == 1
    assert {item["name"] for item in context["named_facilities"]} == {"目标餐厅", "目标商店", "邻格餐厅"}
    assert "comparison_semantics" not in computation["summary"]
    assert computation["method"]["comparison"] == "descriptive_target_vs_neighbors"
    assert projects.datasets.load_calls == ["current:dataset:poi", "current:dataset:h3"]


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
    assert "limitations" not in result["domain_results"][0]


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
    profile = result["domain_results"][0]
    assert profile["summary"]["supply"]["poi_count"] == 25
    assert profile["summary"]["supply"]["categories"] == [{
        "key": "group-7", "label": "餐饮", "count": 25, "share": 1.0,
    }]
    assert profile["summary"]["mix"]["shannon_entropy"] == 0
    assert profile["method"]["spatial_universe"] == "saved_isochrone"


def test_poi_scope_structure_excludes_points_outside_saved_isochrone():
    records = [
        _record("current:dataset:poi", "food", Point(0.01, 0.01), category="餐饮服务"),
        _record("current:dataset:poi", "shop", Point(0.02, 0.02), category="购物服务"),
        _record("current:dataset:poi", "outside", Point(0.06, 0.02), category="餐饮服务"),
    ]
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:poi": records}),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={"analysis": "scope", "fact_domains": ["poi"]},
    )

    summary = result["domain_results"][0]["summary"]
    assert summary["supply"]["poi_count"] == 2
    assert {row["label"]: row["count"] for row in summary["supply"]["categories"]} == {"餐饮": 1, "购物": 1}
    assert summary["mix"]["shannon_entropy"] == pytest.approx(0.693147)
    assert summary["mix"]["normalized_shannon_entropy"] == 1.0


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
    assert "limitations" not in temporal


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
    assert computation["summary"]["reachable_poi_count"] == 1
    assert computation["summary"]["named_facility_count"] == 1
    assert computation["summary"]["cumulative_reachable_count"][-1] == {"minutes": 15.0, "count": 1}
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


def _equal_weight_accessibility_service():
    road = _record(
        "current:dataset:road_edges",
        "main-road",
        LineString([(0.0, 0.025), (0.05, 0.025)]),
        road_name="供需测试道路",
    )
    facilities = [
        _record(
            "current:dataset:poi",
            "clinic-west",
            Point(0.020, 0.025),
            name="西侧诊所",
            category="医疗保健服务",
            typecode="090100",
        ),
        _record(
            "current:dataset:poi",
            "clinic-east",
            Point(0.022, 0.025),
            name="东侧诊所",
            category="医疗保健服务",
            typecode="090100",
        ),
    ]
    population = [
        _record(
            "current:dataset:population",
            "demand-west",
            box(0.0205, 0.0245, 0.0215, 0.0255),
            population_total=100,
            year=2026,
        ),
        _record(
            "current:dataset:population",
            "demand-east",
            box(0.0395, 0.0245, 0.0405, 0.0255),
            population_total=300,
            year=2026,
        ),
    ]

    def contours(_center, times, _mode):
        return {float(value): box(0, 0, 0.05, 0.05) for value in times}

    return SpatialEvidenceService(
        projects=_Projects({
            "current:dataset:poi": facilities,
            "current:dataset:population": population,
            "current:dataset:road_edges": [road],
        }),
        metric_catalog=_Catalog(),
        isochrone_contours=contours,
    )


def test_poi_population_accessibility_returns_equal_weight_supply_demand_index():
    result = _equal_weight_accessibility_service().compute_domains(
        history_id="history-1",
        request={
            "analysis": "accessibility",
            "fact_domains": ["poi", "population"],
            "evidence_dimensions": ["poi.supply", "population.scale"],
            "selectors": [{"dimension": "poi.category", "values": ["医疗"]}],
        },
    )

    computation = next(
        item
        for item in result["domain_results"]
        if item["method"]["kind"] == "equal_weight_supply_demand_accessibility"
    )
    assert computation["status"] == "available"
    assert "facility_weight_semantics" not in computation["summary"]
    assert computation["summary"]["equal_weight_facility_count"] == 2
    assert computation["summary"]["total_population"] == pytest.approx(400)
    assert computation["summary"]["bands"][-1][
        "population_weighted_mean_facilities_per_1000_residents"
    ] == pytest.approx(5.0)
    assert computation["method"]["output_unit"] == "equal_weight_facilities_per_1000_residents"
    assert computation["coverage"]["within_max_catchment_pair_count"] == 2
    assert [item["population"] for item in computation["highlights"]] == [300, 100]
    assert computation["highlights"][0]["facilities_per_1000_residents"] == 0
    _assert_no_geometry(result)


def test_selected_poi_accessibility_counts_all_routes_but_limits_named_facilities():
    roads = [
        _record(
            "current:dataset:road_edges",
            "road",
            LineString([(0.02, 0.025), (0.03, 0.025)]),
            road_name="中心道路",
        )
    ]
    pois = [
        _record(
            "current:dataset:poi",
            f"food-{index}",
            Point(0.025 + index * 0.001, 0.025),
            name=f"餐厅 {index}",
            category="餐饮服务",
            typecode="050101",
        )
        for index in range(1, 5)
    ]
    result = SpatialEvidenceService(
        projects=_Projects({
            "current:dataset:poi": pois,
            "current:dataset:road_edges": roads,
        }),
        metric_catalog=_Catalog(),
    ).compute_domains(
        history_id="history-1",
        request={
            "analysis": "accessibility",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
            "selectors": [{"dimension": "poi.category", "values": ["餐饮"]}],
            "top_k": 3,
        },
    )

    computation = result["domain_results"][0]
    assert computation["summary"]["reachable_poi_count"] == 4
    assert computation["summary"]["named_facility_count"] == 3
    assert len(computation["named_spatial_objects"]) == 3
    assert computation["summary"]["cumulative_reachable_count"][-1] == {"minutes": 15.0, "count": 4}
    assert "count_semantics" not in computation["method"]


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
    assert result["used_metric_ids"] == ["poi.count"]
    assert computation["method"]["kind"] == "accessibility_intersection_aggregation"
    assert [group["key"] for group in computation["groups"]] == ["within-5min", "within-10min", "within-15min"]
    assert [group["values"]["poi.count"] for group in computation["groups"]] == [2.0, 2.0, 2.0]
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
    assert computation["summary"]["reachable_poi_count"] == 0
    assert computation["summary"]["route_status"] == "unavailable"
    assert computation["summary"]["omission_reason"] == "no_local_road_path"
    assert computation["named_spatial_objects"] == []
    assert isochrone_calls == []
    assert "limitations" not in computation


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
    assert inspected_highlight["target_population"] == highlight["target_population"]
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
    assert computation["relationship"]["unit_values"]
    assert "pattern_counts" not in computation["relationship"]
    assert "limitations" not in computation


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
    assert "limitations" not in result


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


def test_model_projection_preserves_reproducibility_identity_when_compacted():
    payload = {
        "result_id": "spatial:test-large",
        "status": "available",
        "summary": {f"fact_{index}": "x" * 1200 for index in range(40)},
        "method": {"kind": "test"},
        "provenance": {
            "snapshot_id": "snapshot-1",
            "source_ids": ["current:dataset:nightlight"],
            "selected_years": {"current:dataset:nightlight": 2025},
            "data_versions": {
                "current:dataset:nightlight": {
                    "data_version": "viirs-v2",
                    "selected_year": 2025,
                    "resolution": 500,
                },
            },
            "result_checksum": "sha256:abc",
        },
    }

    projected = _bounded_model_response(payload)

    assert projected["provenance"] == payload["provenance"]


def test_provenance_falls_back_to_dataset_selected_year():
    project = {
        "history_id": "history-1",
        "snapshot": {"snapshot_id": "snapshot-1"},
        "datasets": [{
            "source_id": "current:dataset:population",
            "selected_year": 2025,
            "data_version": "worldpop-v1",
        }],
    }

    provenance = SpatialEvidenceService._provenance(
        project,
        {},
        {"current:dataset:population"},
    )

    assert provenance["selected_years"] == {"current:dataset:population": 2025}
    assert provenance["data_versions"]["current:dataset:population"]["data_version"] == "worldpop-v1"


def test_internal_metrics_are_not_second_public_dimension_catalog():
    schema = SpatialDomainComputationRequest.model_json_schema()["properties"]
    assert "evidence_dimensions" in schema
    assert "metric_ids" not in schema
    assert set(CATALOG_SCOPE_BINDINGS).isdisjoint({
        metric_id for metric_id in METRIC_BINDINGS if metric_id.startswith("population.age.")
    })
