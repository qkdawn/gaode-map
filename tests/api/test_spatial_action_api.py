from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.spatial_action import SpatialActionService, ValhallaRouteBlocked
from modules.spatial_action.valhalla import ValhallaRoute
from router.domains import spatial_action as spatial_action_router_module


def _app():
    app = FastAPI()
    app.include_router(spatial_action_router_module.router)
    return app


def _polygon(x0: float, y0: float, size: float = 0.001):
    return {
        "type": "Polygon",
        "coordinates": [[
            [x0, y0],
            [x0 + size, y0],
            [x0 + size, y0 + size],
            [x0, y0 + size],
            [x0, y0],
        ]],
    }


def test_local_pattern_api_returns_addressable_measured_zone(monkeypatch):
    monkeypatch.setattr(spatial_action_router_module, "_service", SpatialActionService())
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-actions/local-patterns",
            json={
                "alpha": 0.05,
                "cells": [
                    {
                        "cell_id": "cell:north:1",
                        "metric_id": "spatial.gi_star",
                        "value": 12,
                        "z_score": 3.1,
                        "p_value": 0.01,
                        "cluster_type": "hotspot",
                        "geometry": _polygon(112.9, 28.2),
                        "neighbor_ids": ["cell:north:2"],
                    },
                    {
                        "cell_id": "cell:north:2",
                        "metric_id": "spatial.gi_star",
                        "value": 11,
                        "z_score": 2.9,
                        "p_value": 0.01,
                        "cluster_type": "hotspot",
                        "geometry": _polygon(112.901, 28.2),
                        "neighbor_ids": ["cell:north:1"],
                    },
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_state"] == "measured"
    assert payload["zones"][0]["pattern_type"] == "hotspot"
    assert payload["zones"][0]["cell_ids"] == ["cell:north:1", "cell:north:2"]


def test_entrance_api_infers_boundary_road_candidates_as_experimental(monkeypatch):
    monkeypatch.setattr(spatial_action_router_module, "_service", SpatialActionService())
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-actions/entrances",
            json={
                "entrances": [],
                "project_boundary": _polygon(112.9, 28.2, 0.002),
                "road_segments": [
                    {
                        "segment_id": "road:north-south",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[112.901, 28.199], [112.901, 28.203]],
                        },
                        "integration": 0.8,
                        "choice": 0.7,
                    }
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert {item["source_type"] for item in payload} == {"inferred_candidate"}
    assert {item["evidence_state"] for item in payload} == {"experimental_assumption"}
    assert {item["snapped_road_segment_id"] for item in payload} == {"road:north-south"}


def test_path_api_returns_blocked_without_fabricating_route(monkeypatch):
    class BlockedAdapter:
        def route(self, origin, destination):
            raise ValhallaRouteBlocked("valhalla_unavailable:test")

    monkeypatch.setattr(
        spatial_action_router_module,
        "_service",
        SpatialActionService(route_adapter=BlockedAdapter()),
    )
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-actions/paths",
            json={
                "entrances": [
                    {
                        "entrance_id": "entrance:north",
                        "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
                        "source_type": "project_planned",
                    }
                ],
                "destinations": [
                    {
                        "destination_id": "destination:transit",
                        "geometry": {"type": "Point", "coordinates": [112.91, 28.2]},
                        "destination_type": "transit",
                    }
                ],
                "pairs": [
                    {"entrance_id": "entrance:north", "destination_id": "destination:transit"}
                ],
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "status": "blocked",
        "reason": "valhalla_unavailable:test",
    }


def test_path_api_preserves_real_route_when_depthmapx_is_absent(monkeypatch):
    class RouteAdapter:
        def route(self, origin, destination):
            return ValhallaRoute(
                geometry={
                    "type": "LineString",
                    "coordinates": [[112.9, 28.2], [112.905, 28.201], [112.91, 28.2]],
                },
                distance_m=1200.0,
                duration_s=900.0,
            )

    monkeypatch.setattr(
        spatial_action_router_module,
        "_service",
        SpatialActionService(route_adapter=RouteAdapter()),
    )
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-actions/paths",
            json={
                "entrances": [
                    {
                        "entrance_id": "entrance:north",
                        "geometry": {"type": "Point", "coordinates": [112.9, 28.2]},
                        "source_type": "project_planned",
                    }
                ],
                "destinations": [
                    {
                        "destination_id": "destination:transit",
                        "geometry": {"type": "Point", "coordinates": [112.91, 28.2]},
                        "destination_type": "transit",
                    }
                ],
                "pairs": [
                    {"entrance_id": "entrance:north", "destination_id": "destination:transit"}
                ],
                "road_segments": None,
            },
        )

    assert response.status_code == 200
    route = response.json()[0]
    assert route["network_distance_m"] == 1200.0
    assert route["detour_ratio"] > 1
    assert route["diagnostics"] == ["depthmapx_syntax_unavailable"]
