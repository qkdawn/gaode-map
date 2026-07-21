from __future__ import annotations

from dataclasses import dataclass

import pytest

from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from modules.providers.amap.walking import AMapWalkingRouteAdapter, AMapWalkingRouteBlocked


@dataclass
class _Response:
    payload: object
    error: Exception | None = None

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self) -> object:
        return self.payload


def test_routes_wgs84_points_after_gcj02_normalization_without_exposing_key() -> None:
    calls: list[dict] = []

    def get(_url, **kwargs):
        calls.append(kwargs)
        return _Response({"status": "1", "route": {"paths": [{"distance": "825", "duration": "620"}]}})

    adapter = AMapWalkingRouteAdapter(api_key="secret-key", get=get, timeout_s=7, min_interval_s=0)
    route = adapter.route((116.397, 39.908), (116.401, 39.909))

    assert route.distance_m == 825
    assert route.duration_s == 620
    assert calls[0]["timeout"] == 7
    assert calls[0]["params"]["origin"] == f"{wgs84_to_gcj02(116.397, 39.908)[0]:.6f},{wgs84_to_gcj02(116.397, 39.908)[1]:.6f}"
    assert calls[0]["params"]["destination"] == f"{wgs84_to_gcj02(116.401, 39.909)[0]:.6f},{wgs84_to_gcj02(116.401, 39.909)[1]:.6f}"


@pytest.mark.parametrize("payload", [
    {"status": "0", "info": "DENIED"},
    {"status": "1", "route": {"paths": []}},
    {"status": "1", "route": {"paths": [{"distance": "0", "duration": "100"}]}},
])
def test_translates_provider_rejections_to_safe_domain_error(payload) -> None:
    adapter = AMapWalkingRouteAdapter(api_key="secret-key", get=lambda *_args, **_kwargs: _Response(payload), min_interval_s=0)
    with pytest.raises(AMapWalkingRouteBlocked) as exc:
        adapter.route((116.397, 39.908), (116.401, 39.909))
    assert "secret-key" not in str(exc.value)


def test_missing_key_http_failure_and_throttle_are_blocked_or_controlled() -> None:
    with pytest.raises(AMapWalkingRouteBlocked):
        AMapWalkingRouteAdapter(api_key="", min_interval_s=0).route((116.397, 39.908), (116.401, 39.909))

    clock_values = iter([0.0, 0.25, 0.25])
    sleeps: list[float] = []
    adapter = AMapWalkingRouteAdapter(
        api_key="key",
        get=lambda *_args, **_kwargs: _Response({"status": "1", "route": {"paths": [{"distance": "50", "duration": "30"}]}}),
        min_interval_s=0.5,
        clock=lambda: next(clock_values),
        sleeper=sleeps.append,
    )
    adapter.route((116.397, 39.908), (116.401, 39.909))
    adapter.route((116.397, 39.908), (116.401, 39.909))
    assert sleeps == [pytest.approx(0.25)]

    broken = AMapWalkingRouteAdapter(api_key="key", get=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network")), min_interval_s=0)
    with pytest.raises(AMapWalkingRouteBlocked):
        broken.route((116.397, 39.908), (116.401, 39.909))
