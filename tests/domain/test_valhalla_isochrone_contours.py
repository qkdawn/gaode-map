from __future__ import annotations

import requests
from shapely.geometry import mapping, box

from modules.isochrone.adapter import (
    ValhallaIsochroneUnavailable,
    fetch_valhalla_isochrone_contours,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetches_all_nested_valhalla_contours_in_one_request(monkeypatch):
    captured = {}

    def post(url, *, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return _Response({
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"contour": value}, "geometry": mapping(box(-value, -value, value, value))}
                for value in (5, 10, 15)
            ],
        })

    monkeypatch.setattr("modules.isochrone.adapter.requests.post", post)

    result = fetch_valhalla_isochrone_contours((112.9, 28.2), [5, 10, 15], "walking")

    assert list(result) == [5.0, 10.0, 15.0]
    assert captured["json"]["costing"] == "pedestrian"
    assert captured["json"]["contours"] == [{"time": 5.0}, {"time": 10.0}, {"time": 15.0}]
    assert captured["json"]["polygons"] is True


def test_valhalla_failure_never_returns_geometric_fallback(monkeypatch):
    def fail(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("modules.isochrone.adapter.requests.post", fail)

    try:
        fetch_valhalla_isochrone_contours((112.9, 28.2), [5, 10, 15], "walking")
    except ValhallaIsochroneUnavailable as exc:
        assert str(exc) == "valhalla_isochrone_request_failed"
    else:
        raise AssertionError("strict contour retrieval must not fall back to a buffer")
