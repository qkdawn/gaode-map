from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Sequence

import numpy as np
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from .registry import DEFAULT_POPULATION_YEAR, age_band_keys, resolve_population_file_paths

logger = logging.getLogger(__name__)


def require_rasterio():
    try:
        import rasterio  # type: ignore
        from rasterio.mask import mask  # type: ignore
        from rasterio.transform import array_bounds  # type: ignore

        return rasterio, mask, array_bounds
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"population analysis rasterio import failed: {exc.__class__.__name__}: {exc}"
        ) from exc


def ensure_data_files(paths: Sequence[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError(f"population raster files missing: {', '.join(missing)}")


def mask_dataset(dataset_path: Path, geom_wgs84: BaseGeometry):
    rasterio, mask, _ = require_rasterio()

    with rasterio.open(dataset_path) as src:
        try:
            masked, masked_transform = mask(
                src,
                [mapping(geom_wgs84)],
                crop=True,
                filled=False,
                all_touched=True,
            )
        except ValueError:
            return None
        band = np.ma.asarray(masked[0], dtype=np.float64)
        return {
            "array": band,
            "transform": masked_transform,
            "crs": src.crs,
            "shape": band.shape,
        }


def combine_masked_layers(paths: Sequence[Path], geom_wgs84: BaseGeometry):
    base = None
    for path in paths:
        current = mask_dataset(path, geom_wgs84)
        if current is None:
            continue
        if base is None:
            base = current
            continue
        if base["shape"] != current["shape"] or base["transform"] != current["transform"]:
            raise RuntimeError("population raster alignment mismatch")
        base["array"] = np.ma.asarray(base["array"], dtype=np.float64) + np.ma.asarray(
            current["array"], dtype=np.float64
        )
    return base


def fallback_age_sum_paths(
    data_dir: Path,
    sex: str,
    age_band: str,
    year: str = DEFAULT_POPULATION_YEAR,
) -> list[Path]:
    if age_band != "all":
        return []
    if sex == "male":
        return [path for key in age_band_keys() for path in resolve_population_file_paths(data_dir, "male", key, year)]
    if sex == "female":
        return [path for key in age_band_keys() for path in resolve_population_file_paths(data_dir, "female", key, year)]
    if sex == "total":
        return (
            [path for key in age_band_keys() for path in resolve_population_file_paths(data_dir, "male", key, year)]
            + [path for key in age_band_keys() for path in resolve_population_file_paths(data_dir, "female", key, year)]
        )
    return []


def combine_population_layers(
    data_dir: Path,
    sex: str,
    age_band: str,
    geom_wgs84: BaseGeometry,
    year: str = DEFAULT_POPULATION_YEAR,
):
    primary_paths = resolve_population_file_paths(data_dir, sex, age_band, year)
    ensure_data_files(primary_paths)
    try:
        return combine_masked_layers(primary_paths, geom_wgs84)
    except Exception as exc:
        fallback_paths = fallback_age_sum_paths(data_dir, sex, age_band, year)
        if not fallback_paths:
            raise
        logger.warning(
            "population primary all-age rasters failed; fallback to age-band sum",
            extra={
                "sex": sex,
                "age_band": age_band,
                "primary_paths": [str(path) for path in primary_paths],
                "fallback_count": len(fallback_paths),
                "error": f"{exc.__class__.__name__}: {exc}",
            },
        )
        ensure_data_files(fallback_paths)
        return combine_masked_layers(fallback_paths, geom_wgs84)


def masked_stats(masked_array: np.ma.MaskedArray, round_float) -> Dict[str, float | int]:
    if masked_array is None:
        return {
            "sum": 0.0,
            "nonzero_pixel_count": 0,
            "max_pixel_value": 0.0,
        }
    valid = np.ma.filled(masked_array, 0.0).astype(np.float64)
    positive = valid[valid > 0]
    return {
        "sum": round_float(valid.sum(), 3),
        "nonzero_pixel_count": int(np.count_nonzero(valid > 0)),
        "max_pixel_value": round_float(float(np.max(positive)) if positive.size else 0.0, 3),
    }
