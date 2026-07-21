from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def test_local_pattern_api_returns_addressable_measured_zone():
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
    assert response.json()["zones"][0]["pattern_type"] == "hotspot"
