import asyncio

from modules.poi import service as poi_service
from modules.poi.aggregation import build_category_summary, build_summary_by_year
from modules.poi.fetcher import resolve_source_for_year
from modules.poi.schemas import PoiCategoryRequest, PoiMultiYearRequest


def test_resolve_source_for_year_defaults():
    assert resolve_source_for_year(2020) == "local"
    assert resolve_source_for_year(2022) == "local"
    assert resolve_source_for_year(2024) == "local"
    assert resolve_source_for_year(2026) == "gaode"


def test_build_summaries_count_categories():
    categories = [PoiCategoryRequest(id="food", name="Food", types="050000")]
    results = [
        {
            "year": 2024,
            "source": "local",
            "pois": [
                {"id": "a", "type": "050100", "location": [112.9, 28.2]},
                {"id": "b", "type": "060000", "location": [112.9, 28.2]},
            ],
            "count": 2,
        }
    ]

    assert build_summary_by_year(results, categories)[0]["category_counts"] == {"food": 1}
    assert build_category_summary(results[0]["pois"], categories) == [
        {"id": "food", "name": "Food", "count": 1}
    ]


def test_fetch_multi_year_keeps_partial_success_and_selects_latest(monkeypatch):
    async def fake_fetch(*, polygon, source, year, keywords="", types="", max_count=0):
        if year == 2022 and types == "060000":
            raise RuntimeError("category failed")
        return [
            {
                "id": f"{year}-{types}",
                "name": f"{year}-{types}",
                "location": [112.9, 28.2],
                "type": types,
                "year": year,
            }
        ]

    monkeypatch.setattr(poi_service, "fetch_pois_for_source", fake_fetch)

    payload = PoiMultiYearRequest(
        polygon=[[112.0, 28.0], [112.1, 28.0], [112.0, 28.1], [112.0, 28.0]],
        years=[2020, 2022, 2024],
        categories=[
            PoiCategoryRequest(id="food", name="Food", types="050000"),
            PoiCategoryRequest(id="shop", name="Shop", types="060000"),
        ],
    )

    result = asyncio.run(poi_service.fetch_multi_year_pois(payload))

    assert result["years"] == [2020, 2022, 2024]
    assert result["selected_year"] == 2024
    assert len(result["errors"]) == 1
    assert result["errors"][0]["year"] == 2022
    assert result["summary_by_year"][1]["count"] == 1
    assert result["category_summary"] == [
        {"id": "food", "name": "Food", "count": 1},
        {"id": "shop", "name": "Shop", "count": 1},
    ]
