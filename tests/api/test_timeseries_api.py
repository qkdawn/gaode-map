import asyncio
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import httpx

from core.config import settings
from main import app
from modules.nightlight.dataset import clear_clip_cache
from modules.population import service as population_service
from modules.population.registry import age_band_keys
from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02


def _sample_gcj02_polygon():
    ring_wgs84 = [
        [121.462, 31.248],
        [121.498, 31.248],
        [121.498, 31.214],
        [121.462, 31.214],
        [121.462, 31.248],
    ]
    return [list(wgs84_to_gcj02(lng, lat)) for lng, lat in ring_wgs84]


def _write_population_year(root: Path, year: str, scale: float = 1.0):
    import rasterio
    from rasterio.transform import from_origin

    year_dir = root / year
    year_dir.mkdir(parents=True, exist_ok=True)
    transform = from_origin(121.46, 31.25, 0.01, 0.01)
    male_total = np.zeros((4, 4), dtype=np.float32)
    female_total = np.zeros((4, 4), dtype=np.float32)
    male_ages = {}
    female_ages = {}
    for idx, age_band in enumerate(age_band_keys(), start=1):
        base = np.array(
            [
                [idx, idx + 1, idx + 2, idx + 3],
                [idx + 1, idx + 2, idx + 3, idx + 4],
                [idx + 2, idx + 3, idx + 4, idx + 5],
                [idx + 3, idx + 4, idx + 5, idx + 6],
            ],
            dtype=np.float32,
        ) * np.float32(scale)
        male_ages[age_band] = base
        female_ages[age_band] = base * np.float32(0.8)
        male_total += male_ages[age_band]
        female_total += female_ages[age_band]

    datasets = {
        f"chn_T_M_{year}_CN_100m_R2025A_v1.tif": male_total,
        f"chn_T_F_{year}_CN_100m_R2025A_v1.tif": female_total,
    }
    for age_band in age_band_keys():
        datasets[f"chn_m_{age_band}_{year}_CN_100m_R2025A_v1.tif"] = male_ages[age_band]
        datasets[f"chn_f_{age_band}_{year}_CN_100m_R2025A_v1.tif"] = female_ages[age_band]
        datasets[f"chn_t_{age_band}_{year}_CN_100m_R2025A_v1.tif"] = male_ages[age_band] + female_ages[age_band]

    for filename, data in datasets.items():
        with rasterio.open(
            year_dir / filename,
            "w",
            driver="GTiff",
            width=data.shape[1],
            height=data.shape[0],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            nodata=0,
        ) as dst:
            dst.write(data, 1)


def _write_nightlight_year(root: Path, year: int, scale: float = 1.0):
    import rasterio
    from rasterio.transform import from_origin

    annual_dir = root / "annual"
    annual_dir.mkdir(parents=True, exist_ok=True)
    data = np.array(
        [
            [1, 2, 3, 4],
            [5, 6, 7, 8],
            [9, 10, 11, 12],
            [13, 14, 15, 16],
        ],
        dtype=np.float32,
    ) * np.float32(scale)
    transform = from_origin(121.46, 31.25, 0.01, 0.01)
    tif_path = annual_dir / f"black_marble_{year}_china.tif"
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(data, 1)


def _configure_timeseries_data(tmp_path: Path):
    population_root = tmp_path / "population_data"
    _write_population_year(population_root, "2024", 1.0)
    _write_population_year(population_root, "2025", 1.1)
    _write_population_year(population_root, "2026", 1.25)

    nightlight_root = tmp_path / "nightlight_data"
    for year, scale in [(2023, 1.0), (2024, 1.2), (2025, 0.9)]:
        _write_nightlight_year(nightlight_root, year, scale)
    manifest = {
        "default_year": 2025,
        "datasets": [
            {
                "year": year,
                "label": f"{year} 年",
                "file": f"annual/black_marble_{year}_china.tif",
                "unit": "nWatts/(cm^2 sr)",
                "variable": "NearNadir_Composite_Snow_Free",
            }
            for year in [2023, 2024, 2025]
        ],
    }
    (nightlight_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    settings.population_data_dir = str(population_root)
    settings.population_data_year = "2026"
    settings.nightlight_data_dir = str(nightlight_root)
    settings.population_preview_max_size = 512
    settings.nightlight_preview_max_size = 512
    clear_clip_cache()
    population_service._IN_MEMORY_JSON_CACHE.clear()


async def _request(method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


def test_timeseries_meta_api():
    resp = asyncio.run(_request("GET", "/api/v1/analysis/timeseries/meta"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["population_years"] == ["2024", "2025", "2026"]
    assert data["nightlight_years"] == [2023, 2024, 2025]
    assert data["common_years"] == [2024, 2025]
    assert data["default_joint_period"] == "2024-2025"


def test_population_timeseries_api_returns_series_and_layer(tmp_path):
    _configure_timeseries_data(tmp_path)
    resp = asyncio.run(_request(
        "POST",
        "/api/v1/analysis/timeseries/population",
        json={
            "polygon": _sample_gcj02_polygon(),
            "coord_type": "gcj02",
            "period": "2024-2026",
            "layer_view": "population_rate",
        },
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 3
    assert len(data["series"][-1]["age_distribution"]) == 20
    assert data["series"][-1]["male_ratio"] > 0
    assert data["series"][-1]["female_ratio"] > 0
    assert data["series"][-1]["age_group_ratios"]["working_15_64"] > 0
    assert data["series"][-1]["top_age_band_label"]
    assert data["layer"]["view"] == "population_rate"
    assert data["layer"]["cells"]
    assert data["layer"]["summary"]["increase_count"] > 0
    assert data["insights"]


def test_nightlight_timeseries_api_returns_hotspot_layer(tmp_path):
    _configure_timeseries_data(tmp_path)
    resp = asyncio.run(_request(
        "POST",
        "/api/v1/analysis/timeseries/nightlight",
        json={
            "polygon": _sample_gcj02_polygon(),
            "coord_type": "gcj02",
            "period": "2023-2025",
            "layer_view": "hotspot_shift",
        },
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 3
    assert data["layer"]["view"] == "hotspot_shift"
    assert data["layer"]["legend"]["kind"] == "categorical"
    assert data["layer"]["cells"]


def test_joint_timeseries_api_returns_quadrant_cells(tmp_path):
    _configure_timeseries_data(tmp_path)
    resp = asyncio.run(_request(
        "POST",
        "/api/v1/analysis/timeseries/joint",
        json={
            "polygon": _sample_gcj02_polygon(),
            "coord_type": "gcj02",
            "period": "2024-2025",
        },
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 2
    assert data["layer"]["view"] == "joint_quadrant"
    assert data["layer"]["legend"]["kind"] == "categorical"
    assert data["layer"]["cells"]
    assert "class_counts" in data["layer"]["summary"]


def test_timeseries_invalid_year_returns_400(tmp_path):
    _configure_timeseries_data(tmp_path)
    resp = asyncio.run(_request(
        "POST",
        "/api/v1/analysis/timeseries/population",
        json={
            "polygon": _sample_gcj02_polygon(),
            "coord_type": "gcj02",
            "period": "2023-2026",
            "layer_view": "population_delta",
        },
    ))
    assert resp.status_code == 400
