import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[2]))

from core.config import settings
from modules.population.registry import age_band_keys
from modules.population.service import (
    get_population_grid,
    get_population_layer,
    get_population_overview,
)
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02


def _write_population_test_rasters(root: Path):
    import rasterio
    from rasterio.transform import from_origin

    root.mkdir(parents=True, exist_ok=True)
    transform = from_origin(121.46, 31.25, 0.01, 0.01)
    crs = "EPSG:4326"

    male_ages = {}
    female_ages = {}
    male_total = np.zeros((4, 4), dtype=np.float32)
    female_total = np.zeros((4, 4), dtype=np.float32)

    for idx, age_band in enumerate(age_band_keys(), start=1):
        male_arr = np.array(
            [
                [idx, idx + 1, idx + 2, idx + 3],
                [idx + 1, idx + 2, idx + 3, idx + 4],
                [idx + 2, idx + 3, idx + 4, idx + 5],
                [idx + 3, idx + 4, idx + 5, idx + 6],
            ],
            dtype=np.float32,
        )
        female_arr = male_arr * 0.8
        male_ages[age_band] = male_arr
        female_ages[age_band] = female_arr
        male_total += male_arr
        female_total += female_arr

    datasets = {
        "chn_T_M_2026_CN_100m_R2025A_v1.tif": male_total,
        "chn_T_F_2026_CN_100m_R2025A_v1.tif": female_total,
    }
    for age_band in age_band_keys():
        datasets[f"chn_m_{age_band}_2026_CN_100m_R2025A_v1.tif"] = male_ages[age_band]
        datasets[f"chn_f_{age_band}_2026_CN_100m_R2025A_v1.tif"] = female_ages[age_band]
        datasets[f"chn_t_{age_band}_2026_CN_100m_R2025A_v1.tif"] = male_ages[age_band] + female_ages[age_band]

    for filename, data in datasets.items():
        path = root / filename
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=data.shape[1],
            height=data.shape[0],
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform,
            nodata=0,
        ) as dst:
            dst.write(data, 1)


def _sample_gcj02_polygon():
    ring_wgs84 = [
        [121.462, 31.248],
        [121.498, 31.248],
        [121.498, 31.214],
        [121.462, 31.214],
        [121.462, 31.248],
    ]
    return [list(wgs84_to_gcj02(lng, lat)) for lng, lat in ring_wgs84]


def _configure_population_dirs(tmp_path: Path):
    data_dir = tmp_path / "population_data"
    _write_population_test_rasters(data_dir / "2026")
    settings.population_data_dir = str(data_dir)
    settings.population_data_year = "2026"
    settings.population_preview_max_size = 512


def test_population_grid_and_layer_alignment(tmp_path):
    _configure_population_dirs(tmp_path)
    polygon = _sample_gcj02_polygon()
    grid = get_population_grid(polygon, "gcj02")
    layer = get_population_layer(polygon, "gcj02", scope_id=grid["scope_id"], view="density")

    assert grid["cell_count"] == len(grid["features"])
    assert len(layer["cells"]) == grid["cell_count"]
    grid_ids = {str((feature.get("properties") or {}).get("cell_id") or "") for feature in grid["features"]}
    layer_ids = {str((cell or {}).get("cell_id") or "") for cell in layer["cells"]}
    assert "" not in grid_ids
    assert grid_ids == layer_ids
    assert grid["year"] == "2026"
    assert grid["source"] == "WorldPop"
    first_feature = grid["features"][0]
    assert first_feature["geometry_wgs84"]["type"] == "Polygon"
    properties = first_feature["properties"]
    assert properties["population_total"] > 0
    assert properties["age_5_19"] > 0
    assert properties["age_30_39"] > 0
    assert properties["age_50_64"] > 0
    assert properties["source"] == "WorldPop"


def test_population_grid_includes_cells_touching_scope_boundary(tmp_path):
    _configure_population_dirs(tmp_path)
    polygon_wgs84 = [
        [121.4601, 31.2499],
        [121.4602, 31.2499],
        [121.4602, 31.2498],
        [121.4601, 31.2498],
        [121.4601, 31.2499],
    ]

    grid = get_population_grid(polygon_wgs84, "wgs84")

    assert grid["cell_count"] == 1
    assert grid["features"][0]["properties"]["cell_id"] == "r0_c0"


def test_population_density_conversion_matches_counts(tmp_path):
    _configure_population_dirs(tmp_path)
    polygon = _sample_gcj02_polygon()
    overview = get_population_overview(polygon, "gcj02")
    density_layer = get_population_layer(polygon, "gcj02", scope_id=overview["scope_id"], view="density")
    overview_layer = get_population_layer(polygon, "gcj02", scope_id=overview["scope_id"], view="overview")

    overview_values = {str(cell["cell_id"]): float(cell["value"]) for cell in overview_layer["cells"]}
    density_values = {str(cell["cell_id"]): float(cell["value"]) for cell in density_layer["cells"]}
    assert overview_values
    for cell_id, count_value in overview_values.items():
        assert abs(density_values[cell_id] - (count_value * 100.0)) < 1e-6
    summary = overview["summary"]
    assert abs((summary["male_total"] + summary["female_total"]) - summary["total_population"]) < 1e-6


def test_population_age_dominant_layer_summary_and_legend(tmp_path):
    _configure_population_dirs(tmp_path)
    polygon = _sample_gcj02_polygon()
    overview = get_population_overview(polygon, "gcj02")
    layer = get_population_layer(
        polygon,
        "gcj02",
        scope_id=overview["scope_id"],
        view="age",
        age_mode="dominant",
        age_band="all",
    )

    assert layer["selected"]["view"] == "age"
    assert layer["selected"]["age_mode"] == "dominant"
    assert layer["legend"]["kind"] == "categorical"
    assert len(layer["cells"]) > 0
    summary = layer["summary"]
    assert summary["dominant_cell_count"] > 0
    assert 0.0 <= float(summary["dominant_cell_ratio"]) <= 1.0
