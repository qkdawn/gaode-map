import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from modules.h3.analysis import analyze_h3_grid


def _sample_wgs84_polygon():
    lat = 31.2304
    lon = 121.4737
    d = 0.01
    return [
        [lon - d, lat - d],
        [lon + d, lat - d],
        [lon + d, lat + d],
        [lon - d, lat + d],
        [lon - d, lat - d],
    ]


def _sample_gcj02_polygon():
    return [list(wgs84_to_gcj02(x, y)) for x, y in _sample_wgs84_polygon()]


def _sample_pois_gcj02():
    points_wgs84 = [
        (121.4737, 31.2304, "050000"),  # dining
        (121.4742, 31.2306, "050000"),  # dining
        (121.4740, 31.2302, "060000"),  # shopping
        (121.4734, 31.2299, "150000"),  # transport
    ]
    pois = []
    for idx, (lng, lat, type_code) in enumerate(points_wgs84):
        glng, glat = wgs84_to_gcj02(lng, lat)
        pois.append(
            {
                "id": str(idx + 1),
                "name": f"poi-{idx + 1}",
                "location": [glng, glat],
                "type": type_code,
            }
        )
    return pois


def test_poi_count_consistency():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=_sample_pois_gcj02(),
        poi_coord_type="gcj02",
    )
    grid = result["grid"]
    assigned = sum((f.get("properties", {}).get("poi_count") or 0) for f in grid["features"])
    assert assigned == result["summary"]["poi_count"]


def test_h3_grid_preserves_subcategory_counts():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=[{**poi, "type": "type-050700"} for poi in _sample_pois_gcj02()],
        poi_coord_type="gcj02",
    )
    non_empty_cells = [f for f in result["grid"]["features"] if (f.get("properties", {}).get("poi_count") or 0) > 0]
    assert non_empty_cells
    assert sum(
        int((feature["properties"].get("subcategory_counts") or {}).get("type-050700") or 0)
        for feature in non_empty_cells
    ) == result["summary"]["poi_count"]


def test_single_category_entropy_zero():
    one_poi = [_sample_pois_gcj02()[0]]
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=one_poi,
        poi_coord_type="gcj02",
    )
    non_empty_cells = [f for f in result["grid"]["features"] if (f.get("properties", {}).get("poi_count") or 0) > 0]
    assert len(non_empty_cells) > 0
    for feature in non_empty_cells:
        assert feature["properties"]["local_entropy"] == 0.0


def test_empty_poi_input():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=[],
        poi_coord_type="gcj02",
    )
    assert result["summary"]["poi_count"] == 0
    assert result["summary"]["avg_density_poi_per_km2"] == 0.0
    assert result["summary"]["avg_local_entropy"] == 0.0


def test_neighbor_metrics_fields_exist():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=_sample_pois_gcj02(),
        poi_coord_type="gcj02",
    )
    for feature in result["grid"]["features"]:
        props = feature["properties"]
        assert "neighbor_mean_density" in props
        assert "neighbor_mean_entropy" in props
        assert "neighbor_count" in props


def test_moran_i_is_none_or_finite():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=_sample_pois_gcj02(),
        poi_coord_type="gcj02",
    )
    moran = result["summary"]["global_moran_i_density"]
    assert moran is None or isinstance(moran, float)


def test_spatial_structure_fields_exist():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=_sample_pois_gcj02(),
        poi_coord_type="gcj02",
    )
    props_list = [f.get("properties", {}) for f in result["grid"]["features"]]
    assert props_list
    assert all("gi_star_z_score" in p for p in props_list)
    assert all("lisa_i" in p for p in props_list)
    assert all("gi_star_p_value" not in p for p in props_list)
    assert all("lisa_p_value" not in p for p in props_list)
    assert all("gi_star_bin" not in p for p in props_list)
    assert all("lisa_cluster" not in p for p in props_list)
    assert all("spatial_structure_type" not in p for p in props_list)
    summary = result["summary"]
    assert summary.get("gi_render_meta", {}).get("mode") == "fixed_z"
    assert summary.get("lisa_render_meta", {}).get("mode") == "stddev"
    assert "gi_z_stats" in summary
    assert "lisa_i_stats" in summary
    for key in ("count", "mean", "std", "min", "max", "p10", "p50", "p90"):
        assert key in (summary.get("gi_z_stats") or {})
        assert key in (summary.get("lisa_i_stats") or {})
    assert "significant_cell_count" not in summary
    assert "structure_core_hotspot_count" not in summary


def test_summary_contains_descriptive_render_meta():
    result = analyze_h3_grid(
        polygon=_sample_gcj02_polygon(),
        resolution=10,
        coord_type="gcj02",
        include_mode="intersects",
        min_overlap_ratio=0.0,
        pois=[],
        poi_coord_type="gcj02",
    )
    summary = result.get("summary", {})
    gi_meta = summary.get("gi_render_meta") or {}
    lisa_meta = summary.get("lisa_render_meta") or {}
    assert gi_meta.get("mode") == "fixed_z"
    assert gi_meta.get("min") == -3.0
    assert gi_meta.get("max") == 3.0
    assert lisa_meta.get("mode") == "stddev"
    assert "degraded" in lisa_meta
    assert "message" in lisa_meta


if __name__ == "__main__":
    test_poi_count_consistency()
    test_single_category_entropy_zero()
    test_empty_poi_input()
    test_neighbor_metrics_fields_exist()
    test_moran_i_is_none_or_finite()
    test_spatial_structure_fields_exist()
    test_summary_contains_descriptive_render_meta()
    print("H3 analysis core tests passed.")
