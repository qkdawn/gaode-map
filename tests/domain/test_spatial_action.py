from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Point, Polygon, mapping

from modules.spatial_action import (
    DestinationAnchor,
    EntranceAnchor,
    LocalizedPatternInputCell,
    RoadSegmentRef,
    SpatialActionService,
    ValhallaRouteAdapter,
    ValhallaRouteBlocked,
)


def _square(x, y, size=0.001):
    return mapping(Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)]))


def test_local_patterns_group_significant_neighbors_and_keep_singleton_outlier():
    cells = [
        LocalizedPatternInputCell(cell_id="a", metric_id="spatial.gi_star", value=10, geometry=_square(0, 0), p_value=0.001, z_score=3, cluster_type="hotspot", neighbor_ids=["b"]),
        LocalizedPatternInputCell(cell_id="b", metric_id="spatial.gi_star", value=11, geometry=_square(0.001, 0), p_value=0.002, z_score=3.2, cluster_type="hotspot", neighbor_ids=["a"]),
        LocalizedPatternInputCell(cell_id="c", metric_id="spatial.gi_star", value=1, geometry=_square(0.01, 0), p_value=0.003, z_score=-3, cluster_type="coldspot"),
        LocalizedPatternInputCell(cell_id="d", metric_id="spatial.gi_star", value=4, geometry=_square(0.02, 0), p_value=0.8, z_score=0.1),
    ]
    result = SpatialActionService().analyze_local_patterns(cells)
    assert result.evidence_state == "measured"
    assert {zone.pattern_type for zone in result.zones} == {"hotspot", "local_outlier"}
    hotspot = next(zone for zone in result.zones if zone.pattern_type == "hotspot")
    assert hotspot.cell_ids == ["a", "b"]
    assert all(cell.adjusted_p_value is not None for cell in result.cells)


def test_local_patterns_without_p_values_are_proxy_not_hotspot():
    result = SpatialActionService().analyze_local_patterns([
        LocalizedPatternInputCell(cell_id=str(index), metric_id="poi.grid_density", value=value, geometry=_square(index * 0.002, 0))
        for index, value in enumerate([1, 2, 3, 10])
    ])
    assert result.evidence_state == "proxy"
    assert result.pattern_label == "高值集中区"
    assert "p_values_missing_not_statistical_hotspot" in result.diagnostics
    assert all(zone.pattern_type != "hotspot" for zone in result.zones)


def _roads():
    return [
        RoadSegmentRef(segment_id="s1", geometry=mapping(LineString([(-0.01, 0), (0.0, 0)])), integration=0.2, choice=0.2),
        RoadSegmentRef(segment_id="s2", geometry=mapping(LineString([(0.0, 0), (0.01, 0)])), integration=0.9, choice=0.9),
    ]


def test_inferred_entrance_is_candidate_and_uses_projected_snap_and_network_distance():
    boundary = mapping(Polygon([(-0.001, -0.001), (0.001, -0.001), (0.001, 0.001), (-0.001, 0.001), (-0.001, -0.001)]))
    result = SpatialActionService().analyze_entrance_relations(
        entrances=[],
        road_segments=_roads(),
        project_boundary=boundary,
        target_road_segment_ids=["s2"],
    )
    assert result
    assert all(item.source_type == "inferred_candidate" for item in result)
    assert all(item.evidence_state == "experimental_assumption" for item in result)
    assert all(item.snap_distance_m is not None for item in result)
    assert any("s2" in item.target_road_distances_m for item in result)


def _encode_polyline6(coords):
    output = []
    previous_lat = previous_lon = 0
    for lon, lat in coords:
        lat_i = round(lat * 1_000_000)
        lon_i = round(lon * 1_000_000)
        for delta in (lat_i - previous_lat, lon_i - previous_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                output.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            output.append(chr(value + 63))
        previous_lat, previous_lon = lat_i, lon_i
    return "".join(output)


class _Response:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


def test_valhalla_route_drives_distance_detour_and_syntax_overlap():
    coords = [(0.0, 0.0), (0.005, 0.0), (0.01, 0.0)]
    adapter = ValhallaRouteAdapter(
        base_url="http://fixture",
        post=lambda *args, **kwargs: _Response({"trip": {"summary": {"length": 1.2, "time": 900}, "legs": [{"shape": _encode_polyline6(coords)}]}}),
    )
    service = SpatialActionService(route_adapter=adapter)
    entrances = [EntranceAnchor(entrance_id="e1", geometry=mapping(Point(0, 0)), source_type="existing_observed")]
    destinations = [DestinationAnchor(destination_id="d1", geometry=mapping(Point(0.01, 0)), destination_type="transit")]
    result = service.analyze_path_relations(entrances=entrances, destinations=destinations, pairs=[("e1", "d1")], road_segments=_roads())[0]
    assert result.network_distance_m == 1200
    assert result.duration_s == 900
    assert result.detour_ratio > 1
    assert result.road_segment_ids == ["s1", "s2"]
    assert result.high_choice_overlap_ratio is not None
    assert result.high_integration_overlap_ratio is not None


def test_route_failure_is_blocked_and_never_fabricated():
    adapter = ValhallaRouteAdapter(base_url="http://fixture", post=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    service = SpatialActionService(route_adapter=adapter)
    with pytest.raises(ValhallaRouteBlocked):
        service.analyze_path_relations(
            entrances=[EntranceAnchor(entrance_id="e1", geometry=mapping(Point(0, 0)), source_type="existing_observed")],
            destinations=[DestinationAnchor(destination_id="d1", geometry=mapping(Point(0.01, 0)), destination_type="transit")],
            pairs=[("e1", "d1")],
        )


def test_real_route_survives_when_depthmapx_is_unavailable():
    coords = [(0.0, 0.0), (0.01, 0.0)]
    adapter = ValhallaRouteAdapter(post=lambda *args, **kwargs: _Response({"trip": {"summary": {"length": 1.2, "time": 900}, "legs": [{"shape": _encode_polyline6(coords)}]}}))
    result = SpatialActionService(route_adapter=adapter).analyze_path_relations(
        entrances=[EntranceAnchor(entrance_id="e1", geometry=mapping(Point(0, 0)), source_type="project_planned")],
        destinations=[DestinationAnchor(destination_id="d1", geometry=mapping(Point(0.01, 0)), destination_type="internal_program")],
        pairs=[("e1", "d1")],
        road_segments=None,
    )[0]
    assert result.network_distance_m == 1200
    assert result.high_choice_overlap_ratio is None
    assert "depthmapx_syntax_unavailable" in result.diagnostics
