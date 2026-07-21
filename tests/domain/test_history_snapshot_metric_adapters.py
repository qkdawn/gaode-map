from __future__ import annotations

from dataclasses import dataclass

import pytest
from shapely.geometry import LineString, Point, Polygon

from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.project_context import ProjectSpatialAnalysisService


HISTORY_DETAIL = {
    "history_id": "history-adapter-test",
    "coordinate_system": "wgs84",
    "params": {"time_min": 15, "mode": "walking"},
    "polygon": [[0, 0], [0.04, 0], [0.04, 0.04], [0, 0.04], [0, 0]],
}


def _record(source_id: str, record_id: str, geometry, properties: dict) -> ScopeRecord:
    return ScopeRecord(
        source_id=source_id,
        record_id=record_id,
        title=record_id,
        content="",
        properties=properties,
        raw={},
        time_scope={},
        locator=record_id,
        citation="test",
        geometry=geometry,
    )


def _records() -> dict[str, list[ScopeRecord]]:
    poi = [
        _record("current:dataset:poi", "poi-1", Point(0.01, 0.01), {"category": "food"}),
        _record("current:dataset:poi", "poi-2", Point(0.011, 0.011), {"category": "food"}),
        _record("current:dataset:poi", "poi-3", Point(0.012, 0.012), {"category": "retail"}),
        _record("current:dataset:poi", "poi-4", Point(0.03, 0.03), {"category": "medical"}),
    ]
    grid = []
    for index, (x, count, density, entropy, neighbor_density, neighbor_entropy, categories) in enumerate(
        [
            (0.005, 3, 300.0, 1.0, 100.0, 0.4, {"food": 2, "retail": 1}),
            (0.015, 4, 400.0, 1.2, 200.0, 0.6, {"food": 2, "medical": 2}),
            (0.025, 5, 500.0, 1.4, 300.0, 0.8, {"retail": 3, "medical": 2}),
            (0.035, 6, 600.0, 1.6, 400.0, 1.0, {"food": 3, "retail": 3}),
        ]
    ):
        grid.append(
            _record(
                "current:dataset:poi_grid",
                f"cell-{index}",
                Polygon([(x, 0), (x + 0.004, 0), (x + 0.004, 0.004), (x, 0.004)]),
                {
                    "cell_id": f"cell-{index}",
                    "poi_count": count,
                    "density_poi_per_km2": density,
                    "local_entropy": entropy,
                    "neighbor_mean_density": neighbor_density,
                    "neighbor_mean_entropy": neighbor_entropy,
                    "neighbor_count": 2,
                    "category_counts": categories,
                },
            )
        )
    roads = [
        _record("current:dataset:road_edges", "edge-1", LineString([(0.0, 0.01), (0.01, 0.01)]), {"length_m": 100, "degree_score": 0.2, "control_score": 0.3, "control_global": 0.3, "connectivity_score": 0.2, "integration_global": 0.3, "intelligibility_score": 0.4}),
        _record("current:dataset:road_edges", "edge-2", LineString([(0.01, 0.01), (0.01, 0.02)]), {"length_m": 100, "degree_score": 0.8, "control_score": 0.5, "control_global": 0.5, "connectivity_score": 0.6, "integration_global": 0.7, "intelligibility_score": 0.6}),
        _record("current:dataset:road_edges", "edge-3", LineString([(0.01, 0.02), (0.02, 0.02)]), {"length_m": 100, "degree_score": 0.5, "control_score": 0.4, "control_global": 0.4, "connectivity_score": 0.4, "integration_global": 0.5, "intelligibility_score": 0.5}),
    ]
    return {"current:dataset:poi": poi, "current:dataset:poi_grid": grid, "current:dataset:road_edges": roads}


@dataclass
class _Datasets:
    records: dict[str, list[ScopeRecord]]

    def list_scope_datasets(self, history_id: str):
        del history_id
        summary = {
            "current:dataset:poi": {"poi_count": 4},
            "current:dataset:poi_grid": {"poi_count": 18, "global_moran_i_density": 0.339561},
            "current:dataset:road_edges": {
                "edge_count": 3,
                "node_count": 4,
                "rendered_edge_count": 3,
                "network_length_km": 0.3,
                "edge_merge_ratio": 1.0,
                "avg_degree": 1.5,
                "avg_control": 0.4,
                "control_source_column": "topology_fallback",
                "control_valid_count": 3,
                "avg_intelligibility": 0.8,
                "avg_intelligibility_r2": 0.64,
                "road_orientation_analysis": {"dominant_orientation": "南北向", "orientation_rows": [{"label": "南北向", "length_km": 0.2, "length_share": 0.67, "edge_count": 2}]},
            },
        }
        return {"datasets": [{"source_id": source_id, "status": "ready", "record_count": len(records), "summary": summary.get(source_id, {})} for source_id, records in self.records.items()], "warnings": []}

    def load_scope_records(self, *, history_id: str, source_id: str, year=None, **kwargs):
        del history_id, year, kwargs
        return self.records.get(source_id, []), [2024], 2024


ALL_METRICS = [
    "poi.count", "poi.grid_count", "poi.local_entropy", "poi.local_entropy_normalized", "poi.neighbor_mean_density", "poi.neighbor_mean_entropy", "poi.lq", "poi.kernel_density",
    "road.network_size", "road.intelligibility", "road.orientation", "road.degree", "road.node_degree", "road.control",
    "spatial.global_moran_i_density", "spatial.neighbor_density_delta", "grid.opportunity_flag",
]


@pytest.mark.parametrize("metric_id", ALL_METRICS)
def test_snapshot_adapter_contract_for_all_17_metrics(metric_id):
    records = _records()
    service = ProjectSpatialAnalysisService(datasets=_Datasets(records))
    execution = service.execute_metric_tool(
        tool_id=metric_id,
        primary_spatial_unit="scope",
        history_id="history-adapter-test",
        history_detail=HISTORY_DETAIL,
        project_documents={"project_name": "test", "documents": []},
    )
    assert execution.status == "available", execution.limitations
    assert execution.input_sources
    assert execution.structured_result[f"evidence:metric:{metric_id}"]


def test_grid_formulas_and_kde_contract():
    records = _records()
    service = ProjectSpatialAnalysisService(datasets=_Datasets(records))
    inventory = service._datasets.list_scope_datasets("history-adapter-test")
    _, blocked = service._snapshot_metric_evidence(
        selected={"poi.local_entropy_normalized", "spatial.neighbor_density_delta", "grid.opportunity_flag", "poi.kernel_density"},
        inventory=inventory,
        loaded=records,
        selected_years={source: 2024 for source in records},
        history_detail=HISTORY_DETAIL,
    )
    assert not blocked
    data, reason = service._poi_grid_metric_data(
        "poi.local_entropy_normalized", records["current:dataset:poi_grid"], inventory["datasets"][1]["summary"], 2024
    )
    assert not reason
    assert data["normalization"] == "local_entropy / ln(7)"
    assert 0 < data["displayed_entropy"][0]["displayed_entropy"] < 1
    heatmap = service._poi_heatmap_surface(records["current:dataset:poi"], 2024)["heatmap_surface"]
    assert heatmap["radius"] == 28
    assert heatmap["max"] == 6

    count_data, reason = service._poi_grid_metric_data(
        "poi.grid_count", records["current:dataset:poi_grid"], inventory["datasets"][1]["summary"], 2024, scope_poi_count=20
    )
    assert not reason
    assert count_data["assigned_poi_count"] == 18
    assert count_data["source_scope_poi_count"] == 20
    assert count_data["grid_assignment_ratio"] == 0.9


def test_node_degree_is_distinct_from_edge_degree():
    service = ProjectSpatialAnalysisService(datasets=_Datasets(_records()))
    data, reason = service._road_metric_data("road.node_degree", _records()["current:dataset:road_edges"], {})
    assert not reason
    assert data["node_count"] == 4
    assert {row["degree"] for row in data["degree"]} == {1, 2}


def test_missing_inputs_do_not_create_fallback_values():
    service = ProjectSpatialAnalysisService(datasets=_Datasets(_records()))
    data, reason = service._poi_grid_metric_data("spatial.global_moran_i_density", _records()["current:dataset:poi_grid"], {}, 2024)
    assert data == {}
    assert "Moran I" in reason

    entropy_records = _records()["current:dataset:poi_grid"]
    for record in entropy_records:
        record.properties["poi_count"] = 1
    data, reason = service._poi_grid_metric_data("poi.local_entropy_normalized", entropy_records, {}, 2024)
    assert data == {}
    assert "最小样本" in reason


def test_moran_without_z_score_preserves_limitation():
    service = ProjectSpatialAnalysisService(datasets=_Datasets(_records()))
    data, reason = service._poi_grid_metric_data("spatial.global_moran_i_density", _records()["current:dataset:poi_grid"], {"global_moran_i_density": 0.2}, 2024)
    assert not reason
    assert data["global_moran_z_score"] is None
    assert data["significance_status"] == "not_available"
    assert data["limitations"]
