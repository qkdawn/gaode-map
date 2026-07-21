from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point, Polygon

from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action import project_context
from modules.spatial_action.project_context import ProjectSpatialAnalysisService


HISTORY_DETAIL = {
    "coordinate_system": "wgs84",
    "polygon": [
        [111.99, 27.99],
        [112.03, 27.99],
        [112.03, 28.01],
        [111.99, 28.01],
        [111.99, 27.99],
    ],
}


def _record(
    record_id: str,
    *,
    source_id: str = "current:dataset:poi",
    geometry: Any = None,
    properties: dict[str, Any] | None = None,
) -> ScopeRecord:
    return ScopeRecord(
        source_id=source_id,
        record_id=record_id,
        title=record_id,
        content="",
        properties=properties or {},
        raw={},
        time_scope={},
        locator="",
        citation="test",
        geometry=geometry,
    )


@dataclass
class _FakeDatasets:
    records: dict[str, list[ScopeRecord]]
    years: dict[str, int | None]

    def list_scope_datasets(self, history_id: str) -> dict[str, Any]:
        del history_id
        return {
            "datasets": [
                {"source_id": source_id, "status": "ready"}
                for source_id in self.records
            ],
            "warnings": [],
        }

    def load_scope_records(self, *, history_id: str, source_id: str):
        del history_id
        return self.records[source_id], {}, self.years.get(source_id)


def _population_grid(*, cell_count: int = 2) -> dict[str, Any]:
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[111.999, 27.999], [112.001, 27.999], [112.001, 28.001], [111.999, 28.001], [111.999, 27.999]]]},
            "properties": {"cell_id": "cell-a", "centroid_gcj02": [112.0, 28.0]},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[112.019, 27.999], [112.021, 27.999], [112.021, 28.001], [112.019, 28.001], [112.019, 27.999]]]},
            "properties": {"cell_id": "cell-b", "centroid_gcj02": [112.02, 28.0]},
        },
    ]
    return {"cell_count": cell_count, "features": features[:cell_count]}


def _service(*, records: dict[str, list[ScopeRecord]] | None = None) -> ProjectSpatialAnalysisService:
    records = records or {}
    return ProjectSpatialAnalysisService(datasets=_FakeDatasets(records, {source_id: 2024 for source_id in records}))


def test_record_data_health_distinguishes_unavailable_limited_and_ready():
    unavailable = ProjectSpatialAnalysisService._record_health("current:dataset:poi", [], ["poi.count"])
    assert unavailable.status == "unavailable"

    no_geometry = ProjectSpatialAnalysisService._record_health(
        "current:dataset:poi",
        [_record("missing", geometry=None)],
        ["poi.count"],
    )
    assert no_geometry.status == "unavailable"
    assert no_geometry.checks["valid_geometry_count"] == 0

    limited = ProjectSpatialAnalysisService._record_health(
        "current:dataset:poi",
        [_record("valid", geometry=Point(112.0, 28.0), properties={}), _record("invalid", geometry=None)],
        ["poi.count"],
    )
    assert limited.status == "limited"
    assert limited.limitations

    ready = ProjectSpatialAnalysisService._record_health(
        "current:dataset:poi",
        [_record("a", geometry=Point(112.0, 28.0), properties={"type": "050000"})],
        ["poi.count"],
    )
    assert ready.status == "ready"


def test_vector_health_checks_scope_grid_attributes_and_road_topology():
    scope = ProjectSpatialAnalysisService._project_scope_geometry(HISTORY_DETAIL)
    assert scope is not None

    aligned_grid = ProjectSpatialAnalysisService._record_health(
        "current:dataset:poi_grid",
        [
            _record(
                "grid-a",
                source_id="current:dataset:poi_grid",
                geometry=Polygon([(112.0, 28.0), (112.01, 28.0), (112.01, 28.01), (112.0, 28.01)]),
                properties={"density": 8},
            )
        ],
        ["poi.grid_density"],
        scope_geometry=scope,
        data_year=2024,
    )
    assert aligned_grid.status == "ready"
    assert aligned_grid.checks["scope_intersection_count"] == 1
    assert aligned_grid.checks["coordinate_system"] == "wgs84"
    assert aligned_grid.checks["year"] == 2024

    outside_grid = ProjectSpatialAnalysisService._record_health(
        "current:dataset:poi_grid",
        [
            _record(
                "grid-outside",
                source_id="current:dataset:poi_grid",
                geometry=Polygon([(113.0, 29.0), (113.01, 29.0), (113.01, 29.01), (113.0, 29.01)]),
                properties={"density": 8},
            )
        ],
        ["poi.grid_density"],
        scope_geometry=scope,
    )
    assert outside_grid.status == "unavailable"
    assert "不相交" in outside_grid.limitations[0]

    disconnected_roads = ProjectSpatialAnalysisService._record_health(
        "current:dataset:road_edges",
        [
            _record(
                "road-a",
                source_id="current:dataset:road_edges",
                geometry=LineString([(112.0, 28.0), (112.005, 28.0)]),
                properties={"connectivity_score": 4},
            ),
            _record(
                "road-b",
                source_id="current:dataset:road_edges",
                geometry=LineString([(112.02, 28.0), (112.025, 28.0)]),
                properties={"connectivity_score": 5},
            ),
        ],
        ["road.connectivity"],
        scope_geometry=scope,
    )
    assert disconnected_roads.status == "limited"
    assert disconnected_roads.checks["road_connected_ratio"] == 0.0
    assert "连通性不足" in disconnected_roads.limitations[0]


def test_population_raster_health_uses_valid_cells_not_record_count(monkeypatch):
    service = _service()
    monkeypatch.setattr(project_context, "get_population_overview", lambda *args, **kwargs: {"summary": {"total_population": 42}})
    monkeypatch.setattr(project_context, "get_population_grid", lambda *args, **kwargs: _population_grid())

    ready = service._raster_health(
        source_id="current:dataset:population",
        history_detail=HISTORY_DETAIL,
        metric_ids=["population.total"],
    )
    assert ready.status == "ready"
    assert ready.checks["record_count"] is None
    assert ready.checks["valid_cell_count"] == 2
    assert ready.eligible_metric_ids == ["population.total"]

    monkeypatch.setattr(project_context, "get_population_grid", lambda *args, **kwargs: _population_grid(cell_count=0))
    unavailable = service._raster_health(
        source_id="current:dataset:population",
        history_detail=HISTORY_DETAIL,
        metric_ids=["population.total"],
    )
    assert unavailable.status == "unavailable"
    assert unavailable.blocked_metric_ids == ["population.total"]


def test_nightlight_raster_health_covers_limited_and_unavailable(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        project_context,
        "get_nightlight_layer",
        lambda *args, **kwargs: {
            "year": 2024,
            "summary": {"valid_pixel_count": 1},
            "cells": [
                {"cell_id": "cell-a", "valid_pixel_count": 1},
                {"cell_id": "cell-b", "valid_pixel_count": 0},
            ],
        },
    )
    limited = service._raster_health(
        source_id="current:dataset:nightlight",
        history_detail=HISTORY_DETAIL,
        metric_ids=["nightlight.mean_radiance"],
    )
    assert limited.status == "limited"
    assert limited.checks["record_count"] is None

    monkeypatch.setattr(project_context, "get_nightlight_layer", lambda *args, **kwargs: {"year": 2024, "summary": {"valid_pixel_count": 0}, "cells": []})
    unavailable = service._raster_health(
        source_id="current:dataset:nightlight",
        history_detail=HISTORY_DETAIL,
        metric_ids=["nightlight.mean_radiance"],
    )
    assert unavailable.status == "unavailable"


def test_nightlight_raster_health_uses_interpolated_cell_coverage(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        project_context,
        "get_nightlight_layer",
        lambda *args, **kwargs: {
            "year": 2024,
            "summary": {"valid_pixel_count": 1},
            "cells": [
                {"cell_id": "cell-a", "has_data": True, "valid_pixel_count": 1},
                {"cell_id": "cell-b", "has_data": True, "valid_pixel_count": 1},
            ],
        },
    )

    health = service._raster_health(
        source_id="current:dataset:nightlight",
        history_detail=HISTORY_DETAIL,
        metric_ids=["nightlight.mean_radiance"],
    )

    assert health.status == "ready"
    assert health.checks["valid_cell_count"] == 2
    assert health.checks["total_cell_count"] == 2


def test_population_candidate_comparison_uses_same_buffer_and_raster_values(monkeypatch):
    service = _service()
    monkeypatch.setattr(project_context, "get_population_grid", lambda *args, **kwargs: _population_grid())
    monkeypatch.setattr(
        project_context,
        "get_population_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "cell-a", "value": 12.0}, {"cell_id": "cell-b", "value": 30.0}]},
    )
    monkeypatch.setattr(project_context, "gcj02_to_wgs84", lambda longitude, latitude: (longitude, latitude))

    comparison = service._project_internal_comparison(
        tool_id="population.total",
        history_id="history-test",
        history_detail=HISTORY_DETAIL,
        project_anchors={
            "comparison_design": "两个候选点均使用 800 米范围",
            "candidate_targets": [
                {"target_id": "a", "label": "A 点", "coordinates": [112.0, 28.0]},
                {"target_id": "b", "label": "B 点", "coordinates": [112.02, 28.0]},
            ],
        },
        parameters={"radius_m": 800},
    )

    assert comparison["mode"] == "candidate_uniform_buffer"
    assert comparison["parameters"]["spatial_range_type"] == "uniform_buffer_approximation"
    assert [row["normalized_value"] for row in comparison["comparison_table"]] == [12.0, 30.0]
    assert "项目对照组" in comparison["main_differences"][0]


def test_nightlight_and_single_area_vector_comparisons_use_internal_units(monkeypatch):
    service = _service(
        records={
            "current:dataset:poi": [_record("raw", geometry=Point(112.0, 28.0))],
            "current:dataset:poi_grid": [
                _record("grid-a", source_id="current:dataset:poi_grid", geometry=Point(112.0, 28.0), properties={"density": 4}),
                _record("grid-b", source_id="current:dataset:poi_grid", geometry=Point(112.02, 28.0), properties={"density": 11}),
            ],
        }
    )
    monkeypatch.setattr(project_context, "get_population_grid", lambda *args, **kwargs: _population_grid())
    monkeypatch.setattr(
        project_context,
        "get_nightlight_layer",
        lambda *args, **kwargs: {
            "year": 2024,
            "cells": [
                {"cell_id": "cell-a", "value": 5.0, "has_data": True, "valid_pixel_count": 1},
                {"cell_id": "cell-b", "value": 9.0, "has_data": True, "valid_pixel_count": 1},
            ],
        },
    )
    monkeypatch.setattr(project_context, "gcj02_to_wgs84", lambda longitude, latitude: (longitude, latitude))

    nightlight = service._project_internal_comparison(
        tool_id="nightlight.mean_radiance",
        history_id="history-test",
        history_detail=HISTORY_DETAIL,
        project_anchors={},
        parameters={},
    )
    assert nightlight["mode"] == "project_internal_cells"
    assert nightlight["parameters"]["unit"] == "夜间亮度栅格单元"
    assert [row["value"] for row in nightlight["comparison_table"]] == [5.0, 9.0]

    poi = service._project_internal_comparison(
        tool_id="poi.count",
        history_id="history-test",
        history_detail=HISTORY_DETAIL,
        project_anchors={},
        parameters={},
    )
    assert poi["mode"] == "project_internal_cells"
    assert poi["parameters"]["comparison_source_id"] == "current:dataset:poi_grid"
    assert poi["parameters"]["unit"] == "project_grid_cell"
    assert [row["value"] for row in poi["comparison_table"]] == [4.0, 11.0]


def test_nightlight_evidence_keeps_only_brightness_pattern_semantics(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        project_context,
        "get_nightlight_layer",
        lambda *args, **kwargs: {
            "year": 2024,
            "summary": {"mean_radiance": 7.5, "valid_pixel_count": 2},
            "analysis": {
                "core_hotspot_count": 2,
                "economic_activity_intensity_level": "high",
                "economic_activity_summary_text": "夜间经济活动很强。",
                "sector_direction_analysis": {"dominant_direction": "东"},
            },
            "cells": [],
        },
    )

    analysis = service.analyze_history_snapshot(
        history_id="history-test",
        history_detail=HISTORY_DETAIL,
        project_documents={},
        decision_questions=[],
        metric_plan_entries=[
            {
                "plan_entry_id": "nightlight",
                "metric_id": "nightlight.mean_radiance",
                "role": "primary",
                "planned_spatial_target": {"unit": "grid", "source": "test"},
            }
        ],
    )

    evidence = next(item for item in analysis.evidence_nodes if item["id"] == "evidence:nightlight:scope-profile")
    nightlight_analysis = evidence["data"]["analysis"]
    assert nightlight_analysis["core_hotspot_count"] == 2
    assert nightlight_analysis["night_brightness_spatial_level"] == "high"
    assert nightlight_analysis["night_brightness_distribution_note"] == "夜间亮度高值相对集中于东方向。"
    assert not any("economic_activity" in key for key in nightlight_analysis)
    assert "经济活动" not in str(nightlight_analysis)
