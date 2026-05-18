import asyncio
import math
from unittest.mock import patch

from modules.poi import service as poi_service
from modules.poi.core import (
    AMAP_TILE_MAX_REQUESTS_PER_TYPE,
    AmapPoiFetchError,
    KeyManager,
    _amap_page_retry_count,
    _amap_poi_max_api_calls_per_year,
    _amap_poi_calls_per_second,
    _amap_qps_backoff_base_seconds,
    _amap_qps_backoff_max_seconds,
    _amap_request_timeout_seconds,
    _amap_tile_max_requests_per_type,
    _expand_type_queries_for_tiled_fetch,
    _initial_type_queries_for_tiled_fetch,
    _fetch_amap_page_one,
    _fetch_pois_by_single_polygon_with_stats,
    fetch_pois_by_polygon_tiled,
)
from modules.poi.schemas import PoiCategoryRequest, PoiMultiYearRequest


def _dense_isochrone(vertex_count: int = 160):
    center_lng, center_lat = 116.395, 39.905
    radius = 0.02
    points = []
    for index in range(vertex_count):
        angle = 2 * math.pi * index / vertex_count
        points.append([center_lng + radius * math.cos(angle), center_lat + radius * math.sin(angle)])
    points.append(points[0])
    return points


def _poi(poi_id: str, lng: float, lat: float, type_code: str = "050100"):
    return {
        "id": poi_id,
        "name": poi_id,
        "location": [lng, lat],
        "type": type_code,
    }


def test_tiled_gaode_fetch_uses_tile_polygon_and_filters_to_original_scope(monkeypatch):
    polygon = _dense_isochrone()
    requested_vertices = []

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        requested_vertices.append(len(polygon_arg))
        return 2, [
            _poi("inside", 116.395, 39.905),
            _poi("outside", 116.375, 39.885),
        ], True, ""

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050101"))

    assert requested_vertices == [5]
    assert [item["id"] for item in results] == ["inside"]
    assert diagnostics["filtered_outside_scope"] == 1
    assert diagnostics["request_count"] == 1


def test_tiled_gaode_fetch_subdivides_saturated_tiles(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.41, 39.90],
        [116.41, 39.92],
        [116.39, 39.92],
        [116.39, 39.90],
    ]
    call_count = 0

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 900, [], False, "page cap"
        lng = sum(point[0] for point in polygon_arg[:-1]) / 4.0
        lat = sum(point[1] for point in polygon_arg[:-1]) / 4.0
        return 1, [_poi(f"child-{call_count}", lng, lat)], True, ""

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050101"))

    assert len(results) == 4
    assert diagnostics["saturated_queries"] == 1
    assert diagnostics["request_count"] == 5
    assert diagnostics["incomplete_tiles"] == []


def test_tiled_gaode_fetch_marks_incomplete_when_min_tile_still_saturated(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.3905, 39.90],
        [116.3905, 39.9005],
        [116.39, 39.9005],
        [116.39, 39.90],
    ]

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        return 900, [_poi("only", 116.39025, 39.90025)], False, "page cap"

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050101"))

    assert len(results) == 1
    assert diagnostics["saturated_queries"] == 1
    assert len(diagnostics["incomplete_tiles"]) == 1


def test_tiled_type_expansion_prefers_subtype_queries(monkeypatch):
    monkeypatch.setattr(
        "modules.poi.core._load_type_children_by_parent",
        lambda: {
            "050000": ["050100", "050101", "050102", "050200"],
            "050100": ["050101", "050102"],
            "060000": ["060100"],
        },
    )

    assert _expand_type_queries_for_tiled_fetch("050000|060000|999999") == ["050101", "050102", "050200", "060100", "999999"]
    assert _expand_type_queries_for_tiled_fetch("050100") == ["050101", "050102"]
    assert _initial_type_queries_for_tiled_fetch("050000|060000") == ["050000|060000"]
    assert _initial_type_queries_for_tiled_fetch(
        "050000|060000",
        sample_key="dummy",
        sample_polygon=[[116.39, 39.90], [116.40, 39.90], [116.40, 39.91], [116.39, 39.91], [116.39, 39.90]],
    ) == ["050000|060000"]


def test_amap_poi_fetch_timing_settings_are_configurable(monkeypatch):
    class FakeSettings:
        amap_poi_calls_per_second = "9"
        amap_tile_max_requests_per_type = "88"
        amap_poi_page_retry_count = "2"
        amap_poi_request_timeout_s = "3.5"
        amap_poi_qps_backoff_base_s = "1.5"
        amap_poi_qps_backoff_max_s = "12"
        amap_poi_max_pages_per_tile = "3"
        amap_poi_max_api_calls_per_year = "77"

    monkeypatch.setattr("modules.poi.core.settings", FakeSettings())

    assert _amap_poi_calls_per_second() == 9
    assert _amap_tile_max_requests_per_type() == 88
    assert _amap_page_retry_count() == 2
    assert _amap_request_timeout_seconds() == 3.5
    assert _amap_qps_backoff_base_seconds() == 1.5
    assert _amap_qps_backoff_max_seconds() == 12
    from modules.poi.core import _amap_poi_max_pages_per_tile
    assert _amap_poi_max_pages_per_tile() == 3
    assert _amap_poi_max_api_calls_per_year() == 77


def test_saturated_tile_fetch_skips_remaining_parent_pages(monkeypatch):
    async def fake_page_one(*args, **kwargs):
        return 900, [_poi("first-page", 116.39, 39.90)]

    async def fail_remaining_pages(*args, **kwargs):
        raise AssertionError("saturated parent tile should not fetch remaining pages")

    monkeypatch.setattr("modules.poi.core._fetch_amap_page_one", fake_page_one)
    monkeypatch.setattr("modules.poi.core._fetch_remaining_pages", fail_remaining_pages)

    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        count, pois, complete, error = asyncio.run(
            _fetch_pois_by_single_polygon_with_stats(
                [[116.39, 39.90], [116.40, 39.90], [116.40, 39.91], [116.39, 39.91], [116.39, 39.90]],
                "",
                "050000",
                key_manager=__import__("modules.poi.core", fromlist=["KeyManager"]).KeyManager("dummy_key"),
                session=None,
            )
        )

    assert count == 900
    assert len(pois) == 1
    assert complete is False
    assert "saturated" in error


def test_tile_fetch_skips_remaining_pages_when_page_budget_exceeded(monkeypatch):
    async def fake_page_one(*args, **kwargs):
        return 126, [_poi("first-page", 116.39, 39.90)]

    async def fail_remaining_pages(*args, **kwargs):
        raise AssertionError("tile page budget should skip remaining pages")

    monkeypatch.setattr("modules.poi.core._fetch_amap_page_one", fake_page_one)
    monkeypatch.setattr("modules.poi.core._fetch_remaining_pages", fail_remaining_pages)

    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        count, pois, complete, error = asyncio.run(
            _fetch_pois_by_single_polygon_with_stats(
                [[116.39, 39.90], [116.40, 39.90], [116.40, 39.91], [116.39, 39.91], [116.39, 39.90]],
                "",
                "050000",
                key_manager=__import__("modules.poi.core", fromlist=["KeyManager"]).KeyManager("dummy_key"),
                session=None,
                max_pages=4,
            )
        )

    assert count == 126
    assert len(pois) == 1
    assert complete is False
    assert "page budget" in error


def test_tiled_gaode_fetch_uses_coarse_type_until_saturated(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.40, 39.90],
        [116.40, 39.91],
        [116.39, 39.91],
        [116.39, 39.90],
    ]
    requested_types = []

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        requested_types.append(types)
        return 1, [_poi("coarse", 116.395, 39.905, types)], True, ""

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    monkeypatch.setattr(
        "modules.poi.core._load_type_children_by_parent",
        lambda: {"050000": ["050101", "050102"]},
    )
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050000"))

    assert requested_types == ["050000"]
    assert results[0]["type"] == "050000"
    assert diagnostics["expanded_type_queries"] == 0


def test_tiled_gaode_fetch_expands_type_when_saturated(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.3905, 39.90],
        [116.3905, 39.9005],
        [116.39, 39.9005],
        [116.39, 39.90],
    ]
    requested_types = []

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        requested_types.append(types)
        if types == "050000":
            return 900, [], False, "page cap"
        lng = sum(point[0] for point in polygon_arg[:-1]) / 4.0
        lat = sum(point[1] for point in polygon_arg[:-1]) / 4.0
        return 1, [_poi(types, lng, lat, types)], True, ""

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    monkeypatch.setattr(
        "modules.poi.core._load_type_children_by_parent",
        lambda: {"050000": ["050101", "050102"]},
    )
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050000"))

    assert requested_types == ["050000", "050101", "050102"]
    assert {item["type"] for item in results} == {"050101", "050102"}
    assert diagnostics["expanded_type_queries"] == 2


def test_tiled_gaode_fetch_subdivides_before_expanding_saturated_type(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.41, 39.90],
        [116.41, 39.92],
        [116.39, 39.92],
        [116.39, 39.90],
    ]
    requested_types = []

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        requested_types.append(types)
        if len(requested_types) == 1:
            return 900, [], False, "page cap"
        lng = sum(point[0] for point in polygon_arg[:-1]) / 4.0
        lat = sum(point[1] for point in polygon_arg[:-1]) / 4.0
        return 1, [_poi(f"{types}-{len(requested_types)}", lng, lat, types)], True, ""

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    monkeypatch.setattr(
        "modules.poi.core._load_type_children_by_parent",
        lambda: {"050000": ["050101", "050102"]},
    )
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050000"))

    assert requested_types == ["050000", "050000", "050000", "050000", "050000"]
    assert len(results) == 4
    assert diagnostics["expanded_type_queries"] == 0


def test_tiled_gaode_fetch_stops_when_request_budget_is_exceeded(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.45, 39.90],
        [116.45, 39.96],
        [116.39, 39.96],
        [116.39, 39.90],
    ]

    async def fake_fetch(polygon_arg, keywords, types, *, key_manager, session, **kwargs):
        return 900, [], False, "page cap"

    monkeypatch.setattr("modules.poi.core._fetch_pois_by_single_polygon_with_stats", fake_fetch)
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050101"))

    assert results == []
    assert diagnostics["request_count"] == AMAP_TILE_MAX_REQUESTS_PER_TYPE
    assert diagnostics["request_budget_exceeded"] is True
    assert any(row["reason"] == "tile_request_budget_exceeded" for row in diagnostics["incomplete_tiles"])


def test_tiled_gaode_fetch_stops_when_year_api_budget_is_exceeded(monkeypatch):
    polygon = [
        [116.39, 39.90],
        [116.45, 39.90],
        [116.45, 39.96],
        [116.39, 39.96],
        [116.39, 39.90],
    ]

    async def fake_page_one(*args, **kwargs):
        return 900, []

    monkeypatch.setattr("modules.poi.core._fetch_amap_page_one", fake_page_one)
    with patch("modules.poi.core.settings") as mock_settings:
        mock_settings.amap_web_service_key = "dummy_key"
        mock_settings.amap_poi_max_api_calls_per_year = 3
        results, diagnostics = asyncio.run(fetch_pois_by_polygon_tiled(polygon, "", "050101"))

    assert results == []
    assert diagnostics["api_call_count"] == 3
    assert diagnostics["api_budget_exceeded"] is True
    assert any(row["reason"] == "year_api_budget_exceeded" for row in diagnostics["incomplete_tiles"])


def test_multi_year_gaode_diagnostics_are_preserved(monkeypatch):
    async def fake_fetch(**kwargs):
        return [
            _poi("gaode-1", 116.39, 39.90, kwargs.get("types") or "050100")
        ], {"mode": "gaode_tiled_polygon", "request_count": 3, "dedup_removed": 0}

    monkeypatch.setattr(poi_service, "fetch_pois_for_source_with_diagnostics", fake_fetch)
    payload = PoiMultiYearRequest(
        polygon=[[116.39, 39.90], [116.40, 39.90], [116.39, 39.91], [116.39, 39.90]],
        years=[2026],
        categories=[PoiCategoryRequest(id="food", name="Food", types="050000")],
    )

    result = asyncio.run(poi_service.fetch_multi_year_pois(payload))

    assert result["results_by_year"][0]["diagnostics"][0]["mode"] == "gaode_tiled_polygon"
    assert result["results_by_year"][0]["diagnostics"][0]["request_count"] == 3


def test_multi_year_gaode_diagnostic_errors_are_visible(monkeypatch):
    calls = []

    async def fake_fetch(**kwargs):
        calls.append(kwargs)
        return [
            _poi("same-poi", 116.39, 39.90, kwargs.get("types") or "050100")
        ], {
            "mode": "gaode_tiled_polygon",
            "request_count": 300,
            "type_query_count": 1,
            "failed_queries": [{"reason": "network"}],
            "incomplete_tiles": [{"reason": "tile_request_budget_exceeded"}],
            "request_budget_exceeded": True,
        }

    monkeypatch.setattr(poi_service, "fetch_pois_for_source_with_diagnostics", fake_fetch)
    payload = PoiMultiYearRequest(
        polygon=[[116.39, 39.90], [116.40, 39.90], [116.39, 39.91], [116.39, 39.90]],
        years=[2026],
        categories=[
            PoiCategoryRequest(id="food", name="Food", types="050000"),
            PoiCategoryRequest(id="shop", name="Shop", types="060000"),
        ],
    )

    result = asyncio.run(poi_service.fetch_multi_year_pois(payload))
    error_codes = {row["error"] for row in result["errors"]}

    assert "gaode_tiled_query_failed" in error_codes
    assert "gaode_tiled_fetch_incomplete" in error_codes
    assert "gaode_tiled_request_budget_exceeded" in error_codes
    assert len(calls) == 1
    assert calls[0]["types"] == "050000|060000"
    assert result["results_by_year"][0]["diagnostics"][0]["fetch_strategy"] == "year_combined_types"
    assert result["results_by_year"][0]["diagnostics"][0]["final_count"] == 1


def test_amap_qps_limit_retries_with_backoff(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.status = 200
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse({"status": "0", "infocode": "10003", "info": "QPS_HAS_EXCEEDED_THE_LIMIT"})
            return FakeResponse({"status": "1", "count": "1", "pois": [{"id": "p1", "name": "POI", "location": "116.39,39.90", "typecode": "050101"}]})

    class FakeLimiter:
        def __init__(self):
            self.backoffs = []

        async def acquire(self):
            return None

        async def trigger_backoff(self, seconds):
            self.backoffs.append(seconds)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr("modules.poi.core.asyncio.sleep", fake_sleep)
    from modules.poi.core import KeyManager

    limiter = FakeLimiter()
    session = FakeSession()

    count, pois = asyncio.run(
        _fetch_amap_page_one(
            [[116.39, 39.90], [116.40, 39.90], [116.40, 39.91], [116.39, 39.91], [116.39, 39.90]],
            "",
            "050101",
            KeyManager("dummy_key"),
            limiter,
            session,
        )
    )

    assert count == 1
    assert len(pois) == 1
    assert session.calls == 2
    assert limiter.backoffs


def test_amap_daily_quota_error_keeps_last_infocode(monkeypatch):
    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self):
            return {"status": "0", "infocode": "10044", "info": "USER_DAILY_QUERY_OVER_LIMIT"}

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    class FakeLimiter:
        async def acquire(self):
            return None

    diagnostics = {"api_call_count": 0}
    error = None
    try:
        asyncio.run(
            _fetch_amap_page_one(
                [[116.39, 39.90], [116.40, 39.90], [116.40, 39.91], [116.39, 39.91], [116.39, 39.90]],
                "",
                "050101",
                KeyManager("key_one,key_two"),
                FakeLimiter(),
                FakeSession(),
                diagnostics=diagnostics,
            )
        )
    except AmapPoiFetchError as exc:
        error = str(exc)

    assert error is not None
    assert "USER_DAILY_QUERY_OVER_LIMIT" in error
    assert "infocode=10044" in error
    assert diagnostics["api_call_count"] == 2
