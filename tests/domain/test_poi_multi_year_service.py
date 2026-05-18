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
    async def fake_fetch(*, polygon, source, year, keywords="", types="", max_count=0, progress_callback=None):
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

    async def fake_fetch_with_diagnostics(**kwargs):
        return await fake_fetch(**kwargs), {}

    monkeypatch.setattr(poi_service, "fetch_pois_for_source_with_diagnostics", fake_fetch_with_diagnostics)

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


def test_stream_fetch_multi_year_emits_category_progress(monkeypatch):
    calls = []

    async def fake_fetch_with_diagnostics(**kwargs):
        calls.append(kwargs)
        return [
            {
                "id": f"{kwargs.get('year')}-food",
                "name": "Food POI",
                "location": [112.9, 28.2],
                "type": "050100",
                "year": kwargs.get("year"),
            },
            {
                "id": f"{kwargs.get('year')}-shop",
                "name": "Shop POI",
                "location": [112.91, 28.21],
                "type": "060100",
                "year": kwargs.get("year"),
            },
        ], {
            "mode": "gaode_tiled_polygon",
            "api_call_count": 12,
            "request_count": 6,
        }

    monkeypatch.setattr(poi_service, "fetch_pois_for_source_with_diagnostics", fake_fetch_with_diagnostics)
    payload = PoiMultiYearRequest(
        polygon=[[112.0, 28.0], [112.1, 28.0], [112.0, 28.1], [112.0, 28.0]],
        years=[2026],
        categories=[
            PoiCategoryRequest(id="food", name="Food", types="050000"),
            PoiCategoryRequest(id="shop", name="Shop", types="060000"),
        ],
    )

    async def collect_events():
        return [event async for event in poi_service.stream_fetch_multi_year_pois(payload)]

    events = asyncio.run(collect_events())
    event_types = [event["type"] for event in events]

    assert event_types == ["start", "category_start", "category_complete", "year_complete", "final"]
    assert len(calls) == 1
    assert calls[0]["types"] == "050000|060000"
    assert calls[0]["fetch_strategy"] == "year_combined_types"
    assert calls[0]["selected_category_count"] == 2
    assert events[1]["category"] == "all selected categories"
    assert events[2]["count"] == 2
    assert events[-1]["result"]["selected_year"] == 2026
    assert events[-1]["result"]["summary_by_year"][0]["category_counts"] == {"food": 1, "shop": 1}
    assert events[-1]["result"]["category_summary"] == [
        {"id": "food", "name": "Food", "count": 1},
        {"id": "shop", "name": "Shop", "count": 1},
    ]


def test_gaode_combined_year_budget_error_is_visible(monkeypatch):
    async def fake_fetch_with_diagnostics(**kwargs):
        return [
            {
                "id": "food",
                "name": "Food POI",
                "location": [112.9, 28.2],
                "type": "050100",
                "year": kwargs.get("year"),
            }
        ], {
            "mode": "gaode_tiled_polygon",
            "api_call_count": 600,
            "request_count": 160,
            "api_budget_exceeded": True,
            "request_budget_exceeded": True,
        }

    monkeypatch.setattr(poi_service, "fetch_pois_for_source_with_diagnostics", fake_fetch_with_diagnostics)
    payload = PoiMultiYearRequest(
        polygon=[[112.0, 28.0], [112.1, 28.0], [112.0, 28.1], [112.0, 28.0]],
        years=[2026],
        categories=[PoiCategoryRequest(id="food", name="Food", types="050000")],
    )

    result = asyncio.run(poi_service.fetch_multi_year_pois(payload))

    assert result["years"] == [2026]
    assert result["errors"][0]["error"] == "gaode_tiled_year_api_budget_exceeded"
    assert result["errors"][0]["detail"]["api_call_count"] == 600
