from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "skills" / "spatial-business-analyst" / "scripts" / "directional_fusion.py"
_spec = importlib.util.spec_from_file_location("directional_fusion", SCRIPT)
assert _spec and _spec.loader
_directional_fusion = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_directional_fusion)


analyze = _directional_fusion.analyze
_svg = _directional_fusion._svg


def _row(cell_id: str, lon: float, lat: float, **values: object) -> dict[str, object]:
    return {
        "cell_id": cell_id,
        "centroid_gcj02": [lon, lat],
        "area_km2": 0.01,
        "poi_count": 10,
        "density_poi_per_km2": 1000,
        "population_density": 10000,
        "nightlight_radiance": 50,
        "road_covered": True,
        "road_length_km_per_km2": 20,
        "road_integration": 0.6,
        "road_connectivity": 0.5,
        "category_counts": {"050000": 5, "060000": 5},
        **values,
    }


def test_analyze_is_stably_ordered_by_direction_and_distance() -> None:
    rows = [
        _row("south", 0.0, -0.0045),
        _row("north", 0.0, 0.0045),
        _row("east", 0.0045, 0.0),
        _row("west", -0.0045, 0.0),
    ]

    result = analyze(rows, (0.0, 0.0), ((0.0, 1000.0),))

    assert [sector["sector"] for sector in result["sectors"]] == ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    assert [row["cell_id"] for row in result["rows"]] == ["north", "east", "south", "west"]
    assert [row["distance_band"] for row in result["distance_bands"]] == [
        "0-1000m",
    ] * 8


def test_summary_uses_shared_grid_baseline_and_keeps_road_coverage_separate() -> None:
    rows = [
        _row("covered-high", 0.0, 0.0045, density_poi_per_km2=2000, population_density=20000, nightlight_radiance=80, road_length_km_per_km2=30, road_integration=0.9),
        _row("not-covered", 0.0045, 0.0, density_poi_per_km2=500, population_density=8000, nightlight_radiance=20, road_covered=False, road_length_km_per_km2=0, road_integration=0, road_connectivity=0),
    ]

    result = analyze(rows, (0.0, 0.0), ((0.0, 1000.0),))
    north = next(item for item in result["sectors"] if item["sector"] == "N")
    east = next(item for item in result["sectors"] if item["sector"] == "E")

    assert north["road_coverage_ratio"] == 1.0
    assert north["road_integration_covered_mean"] == 0.9
    assert east["road_coverage_ratio"] == 0.0
    assert east["road_integration_covered_mean"] is None
    assert east["signals"]["road_coverage_available"] is False
    assert "low_connectivity" not in east["signals"]
    assert "opportunity_score" not in result


def test_empty_grid_and_missing_centroid_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="shared grid is empty"):
        _directional_fusion._unwrap_grid([])

    with pytest.raises(ValueError, match="has no centroid"):
        _directional_fusion._unwrap_grid([{"properties": {"cell_id": "missing"}}])


def test_svg_contains_reader_warning_and_no_external_markup() -> None:
    result = analyze([_row("north", 0.0, 0.0045)], (0.0, 0.0), ((0.0, 1000.0),))
    svg = _svg(result)

    assert svg.startswith("<svg ")
    assert "不是客流、消费或营收预测" in svg
    assert "<script" not in svg.lower()
    assert "http://" not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
