from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping
from shapely.ops import unary_union

from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.focused_poi_accessibility import (
    DEFAULT_WALKING_SPEED_M_PER_S,
    FocusedPoiAccessibilityService,
    FocusedPoiCandidate,
    FocusedPoiTypeGroup,
)
from modules.spatial_action.project_context import ProjectSpatialAnalysisService
from modules.spatial_action.road_network_routing import LocalRoadNetworkRouter, RoadNetworkRoutingUnavailable, build_route_map_context


@dataclass
class RecordingLocalRouter:
    """Observe origins without replacing the real saved-road routing algorithm."""

    delegate: LocalRoadNetworkRouter

    def __post_init__(self) -> None:
        self.calls: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def route(self, origin: tuple[float, float], destination: tuple[float, float]):
        self.calls.append((origin, destination))
        return self.delegate.route(origin, destination)


def _analysis_polygon() -> dict:
    return mapping(Polygon([
        (120.000, 30.000), (120.000, 30.002), (120.002, 30.002),
        (120.002, 30.000), (120.000, 30.000),
    ]))


def _road_lines(*, include_far: bool = False) -> list[LineString]:
    end = 120.014 if include_far else 120.006
    return [
        LineString([(119.999, 30.001), (120.001, 30.001), (120.002, 30.001), (120.003, 30.001), (120.004, 30.001), (120.005, 30.001), (120.006, 30.001), (end, 30.001)]),
        # This curved branch proves the emitted geometry retains real road bends.
        LineString([(120.003, 30.001), (120.0032, 30.0014), (120.0034, 30.0018), (120.0038, 30.002)]),
    ]


def _router(*, include_far: bool = False) -> RecordingLocalRouter:
    return RecordingLocalRouter(LocalRoadNetworkRouter(_road_lines(include_far=include_far)))


def _group(*, group_id: str = "food", role: str = "complementary_anchor", type_codes: tuple[str, ...] = ("050000",)) -> FocusedPoiTypeGroup:
    return FocusedPoiTypeGroup(
        group_id=group_id,
        title="餐饮配套" if role == "complementary_anchor" else "同类对标",
        role=role,  # type: ignore[arg-type]
        type_codes=type_codes,
        statement_ref=f"section-3:{group_id}",
    )


def _poi(poi_id: str, name: str, poi_type: str, location: tuple[float, float] | list[float]) -> FocusedPoiCandidate:
    return FocusedPoiCandidate(poi_id=poi_id, name=name, poi_type=poi_type, location=location)


def test_uses_polygon_centroid_as_only_route_origin_and_matches_pipe_separated_prefix_codes() -> None:
    destination = (120.0038, 30.002)
    router = _router()
    result = FocusedPoiAccessibilityService(router).analyze(
        analysis_geometry=_analysis_polygon(),
        groups=[_group(type_codes=("050000|060000",))],
        pois=[
            _poi("matching", "社区食堂", "050101|060100", list(destination)),
            _poi("other", "社区医院", "090000", (120.004, 30.001)),
        ],
    )

    assert result.status == "complete"
    assert result.origin == pytest.approx((120.001, 30.001))
    assert router.calls == [(result.origin, destination)]
    poi = result.groups[0].pois[0]
    assert poi.name == "社区食堂"
    assert poi.route_geometry_status == "available"
    assert poi.routing_algorithm == "local_road_network_shortest_path"
    assert result.groups[0].matched_type_codes == ("050000", "060000")


def test_multpolygon_centroid_is_used_as_origin() -> None:
    geometry = mapping(MultiPolygon([
        Polygon([(120.000, 30.000), (120.000, 30.001), (120.001, 30.001), (120.001, 30.000), (120.000, 30.000)]),
        Polygon([(120.003, 30.000), (120.003, 30.001), (120.004, 30.001), (120.004, 30.000), (120.003, 30.000)]),
    ]))
    router = _router()
    result = FocusedPoiAccessibilityService(router).analyze(
        analysis_geometry=geometry,
        groups=[_group()],
        pois=[_poi("p1", "餐厅", "050100", (120.003, 30.001))],
    )

    assert result.origin == pytest.approx((120.002, 30.0005))
    assert router.calls[0][0] == result.origin


def test_route_geometry_follows_saved_bent_roads_without_straight_line_shortcut() -> None:
    router = _router()
    destination = (120.0038, 30.002)
    result = FocusedPoiAccessibilityService(router).analyze(
        analysis_geometry=_analysis_polygon(), groups=[_group()],
        pois=[_poi("bent", "沿街门店", "050100", destination)],
    )

    poi = result.groups[0].pois[0]
    coordinates = poi.route_geometry["coordinates"]
    network = unary_union(_road_lines())
    assert len(coordinates) >= 4
    assert all(network.distance(Point(point)) < 1e-10 for point in coordinates)
    assert (120.0032, 30.0014) in [tuple(point) for point in coordinates]
    assert poi.walking_duration_s == pytest.approx(poi.walking_distance_m / DEFAULT_WALKING_SPEED_M_PER_S)


def test_routes_are_sorted_by_local_network_length_and_limited_to_three() -> None:
    locations = [(120.003, 30.001), (120.004, 30.001), (120.005, 30.001), (120.006, 30.001)]
    result = FocusedPoiAccessibilityService(_router()).analyze(
        analysis_geometry=_analysis_polygon(), groups=[_group()],
        pois=[_poi(f"p{index}", f"POI {index}", "050100", location) for index, location in enumerate(locations)],
    )

    group = result.groups[0]
    assert [poi.poi_id for poi in group.pois] == ["p0", "p1", "p2"]
    assert len(group.pois) == 3
    assert [poi.walking_distance_m for poi in group.pois] == sorted(poi.walking_distance_m for poi in group.pois)
    assert all(poi.walking_duration_s <= 15 * 60 for poi in group.pois)


def test_disconnected_saved_roads_are_omitted_without_a_fabricated_line() -> None:
    roads = [
        LineString([(119.999, 30.001), (120.004, 30.001)]),
        LineString([(120.007, 30.001), (120.009, 30.001)]),
    ]
    result = FocusedPoiAccessibilityService(LocalRoadNetworkRouter(roads)).analyze(
        analysis_geometry=_analysis_polygon(),
        groups=[_group(), _group(group_id="benchmark", role="comparison_supply", type_codes=("080000",))],
        pois=[
            _poi("reachable", "社区食堂", "050100", (120.003, 30.001)),
            _poi("blocked", "同类店", "080100", (120.008, 30.001)),
        ],
    )

    assert result.status == "partial"
    assert result.groups[0].status == "available"
    assert result.groups[1].status == "omitted"
    assert result.groups[1].omission_reason == "no_local_road_path"
    assert not result.groups[1].pois


def test_pre_filters_candidates_and_records_excess_groups_as_omitted() -> None:
    router = _router()
    groups = [_group(group_id=f"g{index}") for index in range(5)]
    result = FocusedPoiAccessibilityService(router, max_candidates_per_group=2).analyze(
        analysis_geometry=_analysis_polygon(),
        groups=groups,
        pois=[_poi(f"p{index}", f"POI {index}", "050100", (120.002 + index * 0.001, 30.001)) for index in range(5)],
    )

    assert len(router.calls) == 8
    assert all(group.candidates_considered == 2 for group in result.groups[:4])
    assert result.groups[4].omission_reason == "max_groups_exceeded"


def test_filters_out_pois_beyond_two_kilometres_and_omits_routes_over_fifteen_minutes() -> None:
    router = _router(include_far=True)
    near = (120.004, 30.001)
    far = (120.030, 30.001)
    result = FocusedPoiAccessibilityService(router).analyze(
        analysis_geometry=_analysis_polygon(), groups=[_group()],
        pois=[_poi("near", "近点", "050100", near), _poi("far", "远点", "050100", far)],
    )
    assert [poi.poi_id for poi in result.groups[0].pois] == ["near"]
    assert [call[1] for call in router.calls] == [near]

    long_route = FocusedPoiAccessibilityService(_router(include_far=True)).analyze(
        analysis_geometry=_analysis_polygon(), groups=[_group()],
        pois=[_poi("late", "超时点", "050100", (120.013, 30.001))],
    )
    assert long_route.status == "omitted"
    assert long_route.groups[0].omission_reason == "no_local_road_path"


def _scope_record(*, source_id: str, record_id: str, title: str, geometry, raw: dict, properties: dict | None = None) -> ScopeRecord:
    return ScopeRecord(
        source_id=source_id, record_id=record_id, title=title, content="", properties=properties or {}, raw=raw,
        time_scope={}, locator=record_id, citation="测试", geometry=geometry,
    )


def test_route_map_context_keeps_current_project_sized_road_backdrop_by_default() -> None:
    records = [
        SimpleNamespace(
            record_id=f"road-{index}",
            geometry=LineString([(120.001, 30.0005), (120.001, 30.0015)]),
            raw={"edge_id": f"road-{index}"},
            properties={},
        )
        for index in range(1_194)
    ]
    context = build_route_map_context(
        analysis_geometry=_analysis_polygon(),
        origin=(120.001, 30.001),
        route_geometries=[mapping(LineString([(120.001, 30.001), (120.003, 30.001)]))],
        road_records=records,
    )

    assert context["road_edges_clipped_count"] == 1_194
    assert context["road_edges_rendered_count"] == 1_194
    assert len(context["road_edges"]) == 1_194


def test_metric_tool_serializes_only_local_road_routes_and_map_context(monkeypatch) -> None:
    service = ProjectSpatialAnalysisService()
    poi = _scope_record(
        source_id="current:dataset:poi", record_id="poi-1", title="社区食堂", geometry=Point(120.0038, 30.002),
        raw={"name": "社区食堂", "typecode": "050100", "address": "测试路 1 号"},
    )
    roads = [
        _scope_record(source_id="current:dataset:road_edges", record_id=f"road-{index}", title="道路", geometry=line, raw={"edge_id": f"road-{index}"})
        for index, line in enumerate(_road_lines())
    ]
    monkeypatch.setattr(
        service, "_load_snapshot",
        lambda _history_id: ({}, {"current:dataset:poi": [poi], "current:dataset:road_edges": roads}, {"current:dataset:poi": 2026}),
    )

    execution = service.execute_metric_tool(
        tool_id="poi.focused_accessibility", primary_spatial_unit="route", history_id="history-test",
        history_detail={"analysis_geometry": _analysis_polygon(), "coordinate_system": "wgs84"}, project_documents={},
        parameters={"groups": [{"group_id": "food", "title": "餐饮配套", "role": "complementary_anchor", "type_codes": ["050000"], "statement_ref": "section-3:poi-supply"}]},
    )

    assert execution.status == "available"
    payload = execution.structured_result["focused_poi_accessibility"]
    assert payload["year"] == 2026
    assert payload["routing_algorithm"] == "local_road_network_shortest_path"
    row = payload["groups"][0]["pois"][0]
    assert row["route_geometry"]["type"] == "LineString"
    assert row["route_geometry_status"] == "available"
    assert row["location"] == pytest.approx([120.0038, 30.002])
    assert payload["map_context"]["road_source_id"] == "current:dataset:road_edges"
    assert payload["map_context"]["road_edges"]
    assert "高德" not in str(payload)


def test_metric_tool_is_unavailable_when_saved_roads_are_disconnected(monkeypatch) -> None:
    service = ProjectSpatialAnalysisService()
    poi = _scope_record(
        source_id="current:dataset:poi", record_id="poi-1", title="不可达店", geometry=Point(120.008, 30.001),
        raw={"name": "不可达店", "typecode": "050100"},
    )
    roads = [
        _scope_record(source_id="current:dataset:road_edges", record_id="origin-road", title="道路", geometry=LineString([(119.999, 30.001), (120.004, 30.001)]), raw={}),
        _scope_record(source_id="current:dataset:road_edges", record_id="poi-road", title="道路", geometry=LineString([(120.007, 30.001), (120.009, 30.001)]), raw={}),
    ]
    monkeypatch.setattr(
        service, "_load_snapshot",
        lambda _history_id: ({}, {"current:dataset:poi": [poi], "current:dataset:road_edges": roads}, {"current:dataset:poi": 2026}),
    )

    execution = service.execute_metric_tool(
        tool_id="poi.focused_accessibility", primary_spatial_unit="route", history_id="history-test",
        history_detail={"analysis_geometry": _analysis_polygon()}, project_documents={},
        parameters={"groups": [{"group_id": "food", "title": "餐饮配套", "role": "complementary_anchor", "type_codes": ["050000"], "statement_ref": "section-3:poi-supply"}]},
    )

    assert execution.status == "unavailable"
    payload = execution.structured_result["focused_poi_accessibility"]
    assert payload["groups"][0]["omission_reason"] == "no_local_road_path"
    assert not payload["groups"][0]["pois"]
