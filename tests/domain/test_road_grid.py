import pytest

from modules.road.grid import build_road_grid


def _cell(cell_id, coordinates):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "properties": {"cell_id": cell_id, "h3_id": cell_id},
    }


def _edge(coordinates, **properties):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": properties,
    }


def test_build_road_grid_uses_clipped_length_and_weighted_metrics():
    grid = {"features": [
        _cell("a", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]),
        _cell("b", [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]),
        _cell("empty", [[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]),
    ]}
    edges = [
        _edge([[0, 0.5], [2, 0.5]], choice_score=0.2, integration_score=0.4, connectivity_score=0.6),
        _edge([[0, 0.25], [1, 0.25]], choice_score=0.8, integration_score=0.6, connectivity_score=0.4),
    ]

    result, summary = build_road_grid(edges, grid)
    props = {feature["properties"]["cell_id"]: feature["properties"] for feature in result["features"]}

    assert result["count"] == 3
    assert summary["covered_cell_count"] == 2
    assert props["a"]["road_has_data"] is True
    assert props["a"]["road_segment_count"] == 2
    assert props["a"]["road_choice"] == pytest.approx(0.5, abs=1e-5)
    assert props["b"]["road_segment_count"] == 1
    assert props["b"]["road_choice"] == pytest.approx(0.2, abs=1e-5)
    assert props["empty"]["road_has_data"] is False
    assert props["empty"]["road_choice"] is None
