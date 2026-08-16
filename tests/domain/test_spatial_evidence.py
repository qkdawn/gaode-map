from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import Point, box

from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.spatial_evidence import (
    CATALOG_SCOPE_BINDINGS,
    METRIC_BINDINGS,
    SpatialEvidenceRequest,
    SpatialEvidenceService,
)
from modules.spatial_action.metric_tools import MetricToolService


def _record(source_id: str, record_id: str, geometry, **properties) -> ScopeRecord:
    return ScopeRecord(
        source_id=source_id,
        record_id=record_id,
        title=record_id,
        content="",
        properties={"record_id": record_id, **properties},
        raw={},
        time_scope={"year": properties.get("year")},
        locator=f"{source_id}/{record_id}",
        citation="test",
        geometry=geometry,
    )


class _Datasets:
    def __init__(self, records):
        self.records = records

    def load_scope_records(self, *, history_id, source_id, require_geometry_metadata=False):
        return list(self.records.get(source_id, [])), [2026], 2026


class _Projects:
    def __init__(self, records):
        self.datasets = _Datasets(records)

    def read_history_project(self, history_id):
        return {
            "history_id": history_id,
            "project_name": "测试项目",
            "params": {"center": [0.025, 0.025], "coord_type": "wgs84"},
            "scope": {"type": "Polygon", "coordinates": [[[0, 0], [0.05, 0], [0.05, 0.05], [0, 0.05], [0, 0]]]},
            "snapshot": {"snapshot_id": history_id},
            "datasets": [
                {"source_id": source_id, "status": "ready", "selected_year": 2026, "record_count": len(values)}
                for source_id, values in self.datasets.records.items()
            ],
        }


class _Catalog:
    def catalog(self):
        return [SimpleNamespace(tool_id=metric_id, name=metric_id) for metric_id in (
            "population.total", "nightlight.mean_radiance", "poi.grid_density", "road.integration",
        )]


class _CatalogExecutor:
    def catalog(self):
        return [SimpleNamespace(tool_id="grid.type", name="网格四象限分型", implementation_status="implemented")]

    def execute(self, **_kwargs):
        return SimpleNamespace(
            status="available",
            result_id="result:grid.type:test",
            tool_id="grid.type",
            tool_version="catalog-test",
            summary="网格分型已生成",
            structured_result={"geometry": {"type": "Polygon"}, "grid_type": [{"key": "high-high"}]},
            input_sources=["current:dataset:h3"],
            spatial_scope={"scope_id": "scope-1"},
            time_scope={"year": 2026},
            limitations=[],
        )


def _service():
    population = []
    nightlight = []
    poi = []
    for index in range(25):
        x = (index % 5) * 0.01
        y = (index // 5) * 0.01
        cell = box(x, y, x + 0.009, y + 0.009)
        population.append(_record("current:dataset:population", f"cell-{index}", cell, population_total=100 + index, age_5_19=10, age_30_39=20, age_50_64=30, year=2026))
        nightlight.append(_record("current:dataset:nightlight", f"cell-{index}", cell, radiance=float(index + 1), year=2026))
        poi.append(_record("current:dataset:poi", f"poi-{index}", Point(x + 0.004, y + 0.004), category="餐饮服务", subcategory="中餐馆", year=2026))
    projects = _Projects({
        "current:dataset:population": population,
        "current:dataset:nightlight": nightlight,
        "current:dataset:poi": poi,
    })
    return SpatialEvidenceService(projects=projects, metric_catalog=_Catalog())


def _assert_no_geometry(value):
    if isinstance(value, dict):
        assert not {str(key).lower() for key in value} & {"geometry", "coordinates", "features"}
        for item in value.values():
            _assert_no_geometry(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_geometry(item)


def test_request_contract_rejects_mode_specific_invalid_shapes():
    with pytest.raises(ValueError, match="rank_requires_exactly_1_metric"):
        SpatialEvidenceRequest(analysis="rank", metric_ids=["population.total", "nightlight.mean_radiance"])
    with pytest.raises(ValueError, match="neighborhood_requires_metrics_and_record_refs"):
        SpatialEvidenceRequest(analysis="neighborhood", metric_ids=["population.total"])
    with pytest.raises(ValueError, match="distance_bands_must_be_sorted"):
        SpatialEvidenceRequest(analysis="distance", metric_ids=["population.total"], distance_bands_m=[[500, 1000], [0, 500]])
    with pytest.raises(ValueError, match="Input should be 'poi.category'"):
        SpatialEvidenceRequest(analysis="scope", selectors=[{"dimension": "database.field", "values": ["x"]}])
    with pytest.raises(ValueError, match="less than or equal to 20"):
        SpatialEvidenceRequest(analysis="rank", metric_ids=["population.total"], top_k=21)
    with pytest.raises(ValueError, match="less than or equal to 3"):
        SpatialEvidenceRequest(
            analysis="neighborhood",
            metric_ids=["population.total"],
            record_refs=["cell-1"],
            neighbor_steps=4,
        )
    with pytest.raises(ValueError, match="List should have at most 6 items"):
        SpatialEvidenceRequest(
            analysis="distance",
            metric_ids=["population.total"],
            distance_bands_m=[[index * 100, (index + 1) * 100] for index in range(7)],
        )


def test_scope_empty_metrics_discovers_only_available_semantic_metrics():
    result = _service().analyze(history_id="history-1", request={"analysis": "scope"})

    assert result["status"] == "available"
    assert result["summary"]["available_metric_count"] >= 3
    assert all("source_id" not in item for item in result["metrics"])
    assert all("data_status" in item and "supported_analyses" in item for item in result["metrics"])
    _assert_no_geometry(result)


def test_every_catalog_metric_has_an_explicit_spatial_evidence_strategy():
    catalog_ids = {item.tool_id for item in MetricToolService().catalog()}

    assert catalog_ids == set(METRIC_BINDINGS) | set(CATALOG_SCOPE_BINDINGS)


def test_missing_requested_dataset_is_unavailable():
    population = [_record("current:dataset:population", "cell-0", box(0, 0, 0.01, 0.01), population_total=10)]
    service = SpatialEvidenceService(
        projects=_Projects({"current:dataset:population": population}),
        metric_catalog=_Catalog(),
    )

    result = service.analyze(
        history_id="history-1",
        request={"analysis": "scope", "metric_ids": ["nightlight.mean_radiance"]},
    )

    assert result["status"] == "unavailable"
    assert "nightlight.mean_radiance" in result["limitations"][0]
    _assert_no_geometry(result)


def test_registered_catalog_scope_strategy_uses_internal_executor_without_exposing_geometry():
    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:population": []}),
        metric_catalog=_CatalogExecutor(),
    ).analyze(history_id="history-1", request={"analysis": "scope", "metric_ids": ["grid.type"]})

    assert result["status"] == "available"
    assert result["summary"]["grid.type"]["grid_type"] == [{"key": "high-high"}]
    _assert_no_geometry(result)


def test_catalog_result_preserves_audit_metadata_and_data_versions():
    class IsochroneCatalog:
        def catalog(self):
            return [SimpleNamespace(tool_id="isochrone.reachable_area", name="等时圈可达范围", implementation_status="implemented")]

        def execute(self, **_kwargs):
            return SimpleNamespace(
                status="available",
                result_id="result:isochrone.reachable_area:test",
                tool_id="isochrone.reachable_area",
                tool_version="catalog-4.1",
                summary="已计算保存网络等时圈",
                structured_result={
                    "thresholds": [{"time_min": 15, "mode": "walking", "area_km2": 1.2}],
                    "scope_policy": "saved_network_isochrone_only",
                },
                input_sources=["history:isochrone"],
                spatial_scope={"snapshot_id": "snapshot-1"},
                time_scope={"time_min": 15},
                limitations=["只使用保存的网络等时圈"],
            )

    result = SpatialEvidenceService(
        projects=_Projects({"current:dataset:road_edges": []}),
        metric_catalog=IsochroneCatalog(),
    ).analyze(history_id="history-1", request={"analysis": "scope", "metric_ids": ["isochrone.reachable_area"]})

    assert result["status"] == "available"
    payload = result["summary"]["isochrone.reachable_area"]
    assert payload["result_id"] == "result:isochrone.reachable_area:test"
    assert payload["thresholds"][0]["mode"] == "walking"
    assert result["provenance"]["results"][0]["tool_version"] == "catalog-4.1"
    assert result["provenance"]["source_ids"] == ["history:isochrone"]
    assert result["method"]["isochrone_mode"].startswith("scope +")


def test_record_refs_require_stable_source_scoped_reference():
    result = _service().analyze(
        history_id="history-1",
        request={"analysis": "inspect", "metric_ids": ["population.total"], "record_refs": ["cell-0"]},
    )

    assert result["status"] == "unavailable"
    assert "指定的空间记录" in result["limitations"][0]


def test_direction_returns_bounded_groups_and_safe_centroids():
    result = _service().analyze(
        history_id="history-1",
        request={"analysis": "direction", "metric_ids": ["population.total", "nightlight.mean_radiance"]},
    )

    assert result["status"] == "available"
    assert len(result["groups"]) == 8
    assert result["method"]["direction_sectors"] == 8
    _assert_no_geometry(result)


def test_distance_returns_default_bands_and_excludes_geometry():
    result = _service().analyze(
        history_id="history-1",
        request={"analysis": "distance", "metric_ids": ["population.total"]},
    )

    assert result["status"] == "available"
    assert [group["key"] for group in result["groups"]] == ["0-500m", "500-1000m", "1000-1600m"]
    assert result["method"]["missing_values"] == "excluded_not_zero_filled"
    _assert_no_geometry(result)


def test_rank_returns_bounded_highlights_without_combined_score():
    result = _service().analyze(
        history_id="history-1",
        request={"analysis": "rank", "metric_ids": ["population.total"], "top_k": 3},
    )

    assert result["status"] == "available"
    assert len(result["highlights"]) <= 3
    assert result["method"]["combined_score"] is False
    _assert_no_geometry(result)


def test_neighborhood_uses_stable_record_ref_and_neighbor_steps():
    result = _service().analyze(
        history_id="history-1",
        request={
            "analysis": "neighborhood",
            "metric_ids": ["population.total"],
            "record_refs": ["current:dataset:population/cell-0"],
            "neighbor_steps": 1,
        },
    )

    assert result["status"] == "available"
    assert result["summary"]["target_count"] == 1
    assert result["groups"][0]["key"] == "current:dataset:population/cell-0"
    assert result["method"]["neighbor_steps"] == 1
    _assert_no_geometry(result)


def test_relationship_uses_quantile_colocation_without_score_or_correlation():
    result = _service().analyze(
        history_id="history-1",
        request={"analysis": "relationship", "metric_ids": ["population.total", "nightlight.mean_radiance"]},
    )

    assert result["status"] == "available"
    assert result["relationship"]["spatial_unit_count"] == 25
    assert result["relationship"]["correlation_computed"] is False
    assert result["relationship"]["combined_score_computed"] is False
    assert "joint_high" in result["relationship"]["pattern_counts"]
    _assert_no_geometry(result)


def test_inspect_accepts_stable_record_reference_only():
    result = _service().analyze(
        history_id="history-1",
        request={"analysis": "inspect", "record_refs": ["current:dataset:poi/poi-0"]},
    )

    assert result["status"] == "available"
    assert result["highlights"][0]["record_ref"] == "current:dataset:poi/poi-0"
    assert "centroid_wgs84" in result["highlights"][0]
    _assert_no_geometry(result)
