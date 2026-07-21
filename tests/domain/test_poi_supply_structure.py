from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon, mapping
import pytest

from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.poi_supply_structure import PoiSupplyCandidate, PoiSupplyStructureService
from modules.spatial_action.metric_tools import MetricToolService
from modules.spatial_action.project_context import ProjectSpatialAnalysisService
from modules.spatial_action.road_network_routing import LocalRoadNetworkRouter


def _analysis_polygon() -> dict:
    return mapping(Polygon([
        (120.000, 30.000), (120.000, 30.002), (120.002, 30.002),
        (120.002, 30.000), (120.000, 30.000),
    ]))


def _isochrone_polygon(max_x: float = 120.004) -> dict:
    return mapping(Polygon([
        (119.998, 29.999), (119.998, 30.003), (max_x, 30.003),
        (max_x, 29.999), (119.998, 29.999),
    ]))


def _router() -> LocalRoadNetworkRouter:
    return LocalRoadNetworkRouter([
        LineString([(119.999, 30.001), (120.001, 30.001), (120.002, 30.001), (120.003, 30.001), (120.004, 30.001)]),
    ])


def _candidate(poi_id: str, poi_type: str, location: tuple[float, float] | None) -> PoiSupplyCandidate:
    return PoiSupplyCandidate(poi_id=poi_id, poi_type=poi_type, location=location)


def _groups() -> list[dict]:
    return [
        {"group_id": "food", "title": "餐饮与轻饮", "role": "complementary_anchor", "type_codes": ["050000"], "statement_ref": "section-3:daily-food"},
        {"group_id": "shopping", "title": "文化生活对标", "role": "comparison_supply", "type_codes": ["060000"], "statement_ref": "section-3:culture-benchmark"},
    ]


def test_supply_structure_uses_real_taxonomy_and_isochrone_covers_before_road_counts() -> None:
    result = PoiSupplyStructureService(_router()).analyze(
        analysis_geometry=_analysis_polygon(), isochrone_geometry=_isochrone_polygon(), raw_groups=_groups(),
        pois=[
            _candidate("food-near", "050100", (120.002, 30.001)),
            _candidate("food-boundary", "050200", (120.004, 30.001)),
            _candidate("food-outside", "050300", (120.0041, 30.001)),
            _candidate("food-no-coordinate", "050100", None),
            _candidate("shopping-near", "060100", (120.0028, 30.001)),
        ],
    )

    assert result.status == "available"
    assert result.origin == pytest.approx((120.001, 30.001))
    assert result.audit.isochrone_included_poi_count == 3
    assert result.audit.outside_isochrone_poi_count == 1
    assert result.audit.missing_coordinate_poi_count == 1
    assert result.audit.five_minute_accessibility_status == "available"
    food, shopping = result.groups
    assert food.title == "餐饮与轻饮"  # editorial trace only
    assert food.isochrone_poi_count == 2 and food.nearby_5_min_poi_count == 2
    assert shopping.isochrone_poi_count == 1 and shopping.nearby_5_min_poi_count == 1
    assert {(row.main_category, row.subcategory) for row in result.classified_rows} == {
        ("餐饮", "中餐厅"), ("餐饮", "外国餐厅"), ("购物", "商场"),
    }
    assert all(row.main_category != food.title for row in result.classified_rows)


def test_supply_structure_keeps_isochrone_counts_when_road_is_missing_and_audits_unmapped_codes() -> None:
    result = PoiSupplyStructureService().analyze(
        analysis_geometry=None, isochrone_geometry=_isochrone_polygon(),
        raw_groups=[{"group_id": "unknown", "title": "自定义标题", "role": "comparison_supply", "type_codes": ["990000"], "statement_ref": "section-3:unknown"}],
        pois=[_candidate("unknown", "990001", (120.001, 30.001))],
    )
    assert result.status == "unavailable"
    assert result.audit.unmapped_poi_count == 1
    assert result.audit.unmapped_type_codes == ("990001",)
    assert result.error_reason == "no_mapped_pois_in_isochrone"

    available = PoiSupplyStructureService().analyze(
        analysis_geometry=None, isochrone_geometry=_isochrone_polygon(), raw_groups=[_groups()[0]],
        pois=[_candidate("food", "050100", (120.001, 30.001))],
    )
    assert available.status == "partial"
    assert available.classified_rows[0].isochrone_poi_count == 1
    assert available.classified_rows[0].nearby_5_min_poi_count is None
    assert available.audit.five_minute_accessibility_status == "unavailable"
    assert available.groups[0].omission_reason == "local_road_network_unavailable"


def test_supply_structure_rejects_invalid_groups_and_preserves_no_straight_line_fallback() -> None:
    invalid = PoiSupplyStructureService(_router()).analyze(
        analysis_geometry=_analysis_polygon(), isochrone_geometry=_isochrone_polygon(),
        raw_groups=[
            {"group_id": "food", "title": "餐饮", "role": "complementary_anchor", "type_codes": ["050000"], "statement_ref": ""},
            {"group_id": "other", "title": "重复", "role": "comparison_supply", "type_codes": ["050000"], "statement_ref": "section-3:other"},
        ], pois=[_candidate("food", "050100", (120.002, 30.001))],
    )
    assert invalid.status == "unavailable"
    assert "missing_statement_ref" in invalid.diagnostics[0]

    overlap = PoiSupplyStructureService(_router()).analyze(
        analysis_geometry=_analysis_polygon(), isochrone_geometry=_isochrone_polygon(),
        raw_groups=[
            {"group_id": "food", "title": "餐饮", "role": "complementary_anchor", "type_codes": ["050000"], "statement_ref": "section-3:food"},
            {"group_id": "duplicate", "title": "重复", "role": "comparison_supply", "type_codes": ["050100"], "statement_ref": "section-3:duplicate"},
        ], pois=[_candidate("food", "050100", (120.002, 30.001))],
    )
    assert overlap.status == "unavailable"
    assert any("type_codes_overlap_across_groups" in item for item in overlap.diagnostics)

    disconnected = LocalRoadNetworkRouter([
        LineString([(119.999, 30.001), (120.002, 30.001)]),
        LineString([(120.004, 30.001), (120.005, 30.001)]),
    ])
    result = PoiSupplyStructureService(disconnected).analyze(
        analysis_geometry=_analysis_polygon(), isochrone_geometry=_isochrone_polygon(120.006), raw_groups=[_groups()[0]],
        pois=[_candidate("food", "050100", (120.0045, 30.001))],
    )
    assert result.status == "partial"
    assert result.classified_rows[0].nearby_5_min_poi_count is None
    assert result.groups[0].omission_reason == "no_local_road_path"


def _scope_record(*, source_id: str, record_id: str, title: str, geometry, raw: dict) -> ScopeRecord:
    return ScopeRecord(source_id=source_id, record_id=record_id, title=title, content="", properties={}, raw=raw, time_scope={}, locator=record_id, citation="测试", geometry=geometry)


def test_supply_structure_executes_from_the_shared_metric_entrypoint_without_roads(monkeypatch) -> None:
    service = ProjectSpatialAnalysisService()
    poi_records = [
        _scope_record(source_id="current:dataset:poi", record_id="food", title="社区食堂", geometry=Point(120.002, 30.001), raw={"typecode": "050100"}),
        _scope_record(source_id="current:dataset:poi", record_id="shopping", title="商场", geometry=Point(120.0028, 30.001), raw={"typecode": "060100"}),
    ]
    monkeypatch.setattr(service, "_load_snapshot", lambda _history_id: ({}, {"current:dataset:poi": poi_records}, {"current:dataset:poi": 2026}))
    execution = service.execute_metric_tool(
        tool_id="poi.supply_structure", primary_spatial_unit="scope", history_id="history-test",
        history_detail={"analysis_geometry": _analysis_polygon(), "polygon_wgs84": _isochrone_polygon(), "coordinate_system": "wgs84", "params": {"time_min": 15, "mode": "walking"}},
        project_documents={}, parameters={"groups": _groups()},
    )

    assert execution.status == "partial"
    payload = execution.structured_result["poi_supply_structure"]
    assert payload["year"] == 2026
    assert payload["scope"]["kind"] == "verified_walking_isochrone"
    assert payload["scope"]["point_inclusion_method"] == "covers"
    assert payload["groups"][0]["isochrone_poi_count"] == 1
    assert payload["groups"][0]["nearby_5_min_poi_count"] is None
    assert {row["main_category"] for row in payload["classified_rows"]} == {"餐饮", "购物"}
    assert payload["taxonomy_audit"]["source"] == "share/type_map.json"

def test_supply_structure_is_discoverable_through_the_metric_catalog() -> None:
    service = MetricToolService()

    catalog_item = next(item for item in service.catalog() if item.tool_id == "poi.supply_structure")
    detail = service.detail("poi.supply_structure")

    assert catalog_item.implementation_status == "implemented"
    assert catalog_item.primary_spatial_unit == "scope"
    assert "share/type_map.json" in detail.measures.definition
    assert "15 分钟 walking 等时圈" in detail.measures.definition
