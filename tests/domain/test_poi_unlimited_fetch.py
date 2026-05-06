import asyncio
from unittest.mock import patch

from modules.poi.core import (
    _calculate_amap_page_count,
    fetch_local_pois_by_polygon,
    fetch_pois_by_polygon,
)
from modules.poi.schemas import PoiRequest


POLYGON = [
    [116.39, 39.90],
    [116.40, 39.90],
    [116.40, 39.91],
    [116.39, 39.91],
    [116.39, 39.90],
]


def _poi(index: int):
    return {
        "id": f"poi-{index}",
        "name": f"POI {index}",
        "location": [116.39 + index * 0.000001, 39.90],
    }


def test_poi_request_defaults_to_unlimited_app_side_count():
    payload = PoiRequest(polygon=POLYGON, keywords="餐饮")

    assert payload.max_count == 0


def test_gaode_polygon_fetch_does_not_slice_when_max_count_is_zero():
    pois = [_poi(index) for index in range(1205)]

    async def fake_single_polygon(*args, **kwargs):
        return pois

    with patch("modules.poi.core._fetch_pois_by_single_polygon", side_effect=fake_single_polygon):
        results = asyncio.run(fetch_pois_by_polygon(POLYGON, "餐饮", max_count=0))

    assert len(results) == 1205


def test_gaode_polygon_fetch_keeps_explicit_max_count_limit():
    pois = [_poi(index) for index in range(20)]

    async def fake_single_polygon(*args, **kwargs):
        return pois

    with patch("modules.poi.core._fetch_pois_by_single_polygon", side_effect=fake_single_polygon):
        results = asyncio.run(fetch_pois_by_polygon(POLYGON, "餐饮", max_count=5))

    assert len(results) == 5


def test_local_polygon_fetch_does_not_slice_when_max_count_is_zero():
    pois = [_poi(index) for index in range(1205)]

    async def fake_local_single_polygon(*args, **kwargs):
        return pois

    with patch("modules.poi.core._fetch_local_pois_by_single_polygon", side_effect=fake_local_single_polygon):
        results = asyncio.run(fetch_local_pois_by_polygon(POLYGON, max_count=0))

    assert len(results) == 1205


def test_amap_remaining_page_count_uses_total_count_without_900_cap():
    assert _calculate_amap_page_count(1200, 25) == 48
    assert _calculate_amap_page_count(901, 25) == 37
    assert _calculate_amap_page_count(0, 25) == 1
