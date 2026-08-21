from __future__ import annotations

import pytest
from shapely.geometry import Point, box

from modules.road.projection import LocalMetricProjection


def test_local_metric_projection_round_trips_coordinates():
    projection = LocalMetricProjection.for_geometry(box(112.98, 28.19, 112.99, 28.20))

    x, y = projection.forward_xy(112.986, 28.196)
    lon, lat = projection.inverse_xy(x, y)

    assert lon == pytest.approx(112.986, abs=1e-10)
    assert lat == pytest.approx(28.196, abs=1e-10)


def test_context_buffer_uses_metric_distance():
    scope = box(112.98, 28.19, 112.99, 28.20)
    projection = LocalMetricProjection.for_geometry(scope)

    context = projection.buffer_wgs84(scope, 800)
    west_boundary = projection.forward_geometry(Point(scope.bounds[0], scope.centroid.y))
    context_west = projection.forward_geometry(Point(context.bounds[0], scope.centroid.y))

    assert context.contains(scope)
    assert west_boundary.distance(context_west) == pytest.approx(800, abs=2)
