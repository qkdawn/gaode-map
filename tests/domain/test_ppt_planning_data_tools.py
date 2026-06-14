import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.ppt_planning.data_tools import (
    PptDataIntentLlmUnavailable,
    PptDataInvalidIntentPlan,
    PptDataSourceNotFound,
    create_ppt_data_package,
    list_ppt_sources,
    query_nearby_poi_points,
    query_poi_points,
)
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84, wgs84_to_gcj02
from modules.ppt_planning.schemas import PptDataPackageRequest, PptPoiNearbyRequest, PptPoiQueryRequest
from store.ai_models import AiBase, Document, DocumentIndexNode


def _fake_detail():
    return {
        "id": "history-1",
        "params": {"center": [112.9, 28.2], "time_min": 35},
        "polygon": [[112.9, 28.2], [112.91, 28.2], [112.91, 28.21]],
    }


def _fake_pois():
    return {
        "history_id": "history-1",
        "polygon": [[112.9, 28.2], [112.91, 28.2], [112.91, 28.21]],
        "pois": [
            {
                "id": "poi-1",
                "name": "长沙县政府原址",
                "location": [112.9, 28.2],
                "address": "开福区",
                "category": "政府机构",
                "subcategory": "政府机关",
                "typecode": "130100",
            },
            {
                "id": "poi-2",
                "name": "城市更新展示馆",
                "location": [112.901, 28.201],
                "address": "开福区",
                "category": "科教文化",
                "subcategory": "博物馆",
                "typecode": "140400",
            },
            {
                "id": "poi-3",
                "name": "很远的商场",
                "location": [113.1, 28.4],
                "address": "长沙",
                "category": "购物",
                "subcategory": "购物中心",
                "typecode": "060101",
            },
        ],
        "poi_summary": {"政府机构": 1, "科教文化": 1, "购物": 1},
        "count": 3,
        "available_years": [2024],
        "selected_year": 2024,
    }


def _fake_night_pois():
    payload = _fake_pois()
    payload["pois"] = payload["pois"] + [
        {
            "id": "poi-4",
            "name": "七夕堂7x24酒吧",
            "location": [112.902, 28.202],
            "address": "岳麓区",
            "category": "体育",
            "subcategory": "娱乐场所",
            "typecode": "080302",
        },
        {
            "id": "poi-5",
            "name": "牧羊馆烧烤夜宵",
            "location": [112.903, 28.203],
            "address": "岳麓区",
            "category": "餐饮",
            "subcategory": "中餐厅",
            "typecode": "050100",
        },
        {
            "id": "poi-6",
            "name": "普通生活超市",
            "location": [112.902, 28.202],
            "address": "岳麓区",
            "category": "购物",
            "subcategory": "超级市场",
            "typecode": "060400",
        },
        {
            "id": "poi-7",
            "name": "普通中餐菜馆",
            "location": [112.902, 28.202],
            "address": "岳麓区",
            "category": "餐饮",
            "subcategory": "中餐厅",
            "typecode": "050100",
        },
        {
            "id": "poi-8",
            "name": "24小时便利店",
            "location": [112.902, 28.202],
            "address": "岳麓区",
            "category": "购物",
            "subcategory": "便民商店/便利店",
            "typecode": "060200",
        },
    ]
    payload["count"] = len(payload["pois"])
    return payload


def _fake_near_edge_night_pois():
    payload = _fake_pois()
    payload["pois"] = [
        {
            "id": "poi-edge",
            "name": "边缘烧烤夜宵",
            "location": [112.90091, 28.202],
            "address": "岳麓区",
            "category": "餐饮",
            "subcategory": "中餐厅",
            "typecode": "050100",
        },
    ]
    payload["count"] = len(payload["pois"])
    return payload


def _fake_carrier_pois():
    return {
        "history_id": "history-1",
        "polygon": [[112.9, 28.2], [112.904, 28.2], [112.904, 28.204], [112.9, 28.204], [112.9, 28.2]],
        "pois": [
            {
                "id": "poi-commerce-1",
                "name": "中心购物街",
                "location": [112.902, 28.202],
                "address": "测试区",
                "category": "购物",
                "subcategory": "特色商业街",
                "typecode": "061000",
            },
            {
                "id": "poi-commerce-2",
                "name": "沿街餐饮店",
                "location": [112.901, 28.2004],
                "address": "测试区",
                "category": "餐饮",
                "subcategory": "中餐厅",
                "typecode": "050100",
            },
            {
                "id": "poi-commerce-3",
                "name": "生活便利店",
                "location": [112.9036, 28.202],
                "address": "测试区",
                "category": "购物",
                "subcategory": "便民商店/便利店",
                "typecode": "060200",
            },
            {
                "id": "poi-culture-1",
                "name": "城市展示馆",
                "location": [112.902, 28.2036],
                "address": "测试区",
                "category": "科教文化",
                "subcategory": "博物馆",
                "typecode": "140400",
            },
        ],
        "poi_summary": {"购物": 2, "餐饮": 1, "科教文化": 1},
        "count": 4,
        "available_years": [2024],
        "selected_year": 2024,
    }


def _fake_dense_carrier_pois():
    payload = _fake_carrier_pois()
    payload["pois"] = payload["pois"] + [
        {
            "id": f"poi-restaurant-{index}",
            "name": f"沿街餐饮样本 {index}",
            "location": [112.9004 + index * 0.00012, 28.2005 + index * 0.00008],
            "address": "测试区",
            "category": "餐饮",
            "subcategory": "中餐厅",
            "typecode": "050100",
        }
        for index in range(1, 16)
    ] + [
        {
            "id": f"poi-shop-{index}",
            "name": f"商业零售样本 {index}",
            "location": [112.9006 + index * 0.0001, 28.202 + index * 0.00007],
            "address": "测试区",
            "category": "购物",
            "subcategory": "购物中心",
            "typecode": "060101",
        }
        for index in range(1, 10)
    ]
    payload["count"] = len(payload["pois"])
    payload["poi_summary"] = {"购物": 11, "餐饮": 16, "科教文化": 1}
    return payload


def _road_feature(coords, road_id, *, choice=0.9, integration=0.88, connectivity=0.75, skeleton=True):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": road_id,
            "length_m": 440,
            "choice_score": choice,
            "integration_score": integration,
            "connectivity_score": connectivity,
            "control_score": 0.55,
            "depth_score": 0.2,
            "intelligibility_score": 0.66,
            "is_skeleton_choice_top20": skeleton,
            "is_skeleton_integration_top20": skeleton,
        },
    }


def _fake_carrier_road_payload(mode="block_loop"):
    if mode == "segment":
        edges = [
            _road_feature([[112.9, 28.2], [112.904, 28.2]], "single-main"),
        ]
    elif mode == "corridor":
        edges = [
            _road_feature([[112.9, 28.2], [112.904, 28.2]], "axis-1"),
            _road_feature([[112.904, 28.2], [112.908, 28.202]], "axis-2"),
            _road_feature([[112.908, 28.202], [112.91, 28.204]], "axis-3"),
        ]
    else:
        edges = [
            _road_feature([[112.9, 28.2], [112.904, 28.2]], "bottom"),
            _road_feature([[112.904, 28.2], [112.904, 28.204]], "right"),
            _road_feature([[112.904, 28.204], [112.9, 28.204]], "top"),
            _road_feature([[112.9, 28.204], [112.9, 28.2]], "left"),
        ]
    return {"roads": {"type": "FeatureCollection", "features": edges, "count": len(edges)}}


def _fake_shared_grid_payload():
    return {
        "grid": {
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [112.8995, 28.1995],
                        [112.9045, 28.1995],
                        [112.9045, 28.2045],
                        [112.8995, 28.2045],
                        [112.8995, 28.1995],
                    ]],
                },
                "properties": {"cell_id": "r0_c0", "row": 0, "col": 0},
            }],
        },
    }


def _fake_carrier_artifacts(*, road_mode="block_loop", missing_population=False, missing_nightlight=False, population_view="overview"):
    def fake_artifacts(area_id, artifact_type="", params_hash=""):
        del area_id, params_hash
        if artifact_type == "road_syntax":
            return [{"payload": _fake_carrier_road_payload(mode=road_mode)}]
        if artifact_type == "poi_raster_grid":
            return [{"payload": _fake_shared_grid_payload()}]
        if artifact_type == "population" and not missing_population:
            if population_view == "density":
                return [{
                    "params": {"view": "density"},
                    "payload": {
                        "view": "density",
                        "legend": {"title": "人口密度", "unit": "人/平方公里"},
                        "layer_cells": [{"cell_id": "r0_c0", "value": 8800}],
                    },
                }]
            return [{
                "params": {"view": "overview"},
                "payload": {
                    "view": "overview",
                    "selected": {"view": "overview", "view_label": "总人口", "unit": "人口"},
                    "layer_cells": [{"cell_id": "r0_c0", "value": 1800}],
                },
            }]
        if artifact_type == "nightlight" and not missing_nightlight:
            return [{"payload": {"layer_cells": [{"cell_id": "r0_c0", "value": 24.5, "class_key": "core_hotspot", "class_label": "核心热点"}]}}]
        return []
    return fake_artifacts


def test_query_poi_points_returns_normalized_points(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())

    response = query_poi_points(PptPoiQueryRequest(area_id="history-1", limit=1, offset=0))

    assert response.coordinate_system == "WGS84"
    assert response.total == 3
    assert response.items[0].name == "长沙县政府原址"
    assert response.items[0].location
    assert response.items[0].typecode == "130100"
    assert response.items[0].category == "政府机构"


def test_query_poi_points_filters_by_text_category_and_subcategory(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())

    text_response = query_poi_points(PptPoiQueryRequest(area_id="history-1", filters={"query": "展示馆"}))
    category_response = query_poi_points(PptPoiQueryRequest(area_id="history-1", filters={"category": "科教文化"}))
    subcategory_response = query_poi_points(PptPoiQueryRequest(area_id="history-1", filters={"subcategory": "购物中心"}))

    assert text_response.total == 1
    assert text_response.items[0].id == "poi-2"
    assert category_response.total == 1
    assert category_response.items[0].id == "poi-2"
    assert subcategory_response.total == 1
    assert subcategory_response.items[0].id == "poi-3"


def test_query_nearby_poi_points_filters_by_radius_and_sorts_distance(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())

    response = query_nearby_poi_points(
        PptPoiNearbyRequest(
            area_id="history-1",
            center=[112.9, 28.2],
            radius_m=300,
            limit=10,
        )
    )

    assert response.total == 2
    assert [item.id for item in response.items] == ["poi-1", "poi-2"]
    assert response.items[0].distance_m == 0
    assert response.items[1].distance_m > response.items[0].distance_m


def test_create_ppt_data_package_returns_ready_source(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi"],
        package_mode="query",
        limit=2,
    )))

    assert response.source.id.startswith("package:poi:")
    assert response.source.status == "ready"
    assert response.source.selected is True
    assert response.source.meta["sourceKind"] == "package"
    assert response.source.meta["package"]["coordinate_system"] == "WGS84"
    assert response.source.meta["package"]["items"][0]["name"] == "长沙县政府原址"
    assert response.source.meta["package"]["package_mode"] == "query"


def test_create_ppt_evidence_package_uses_llm_plan(monkeypatch):
    async def fake_invoke_json_role(**kwargs):
        return {
            "package_title": "文教资源资料包",
            "selection_reason": "用于说明区域文化展示资源。",
            "evidence_groups": [
                {
                    "name": "文教展示资源",
                    "purpose": "说明区域文化展示资源。",
                    "query_terms": ["展示馆"],
                    "categories": ["科教文化"],
                    "target_count": 3,
                }
            ],
        }

    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.ppt_planning.data_tools._invoke_json_role", fake_invoke_json_role)

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi"],
        package_mode="evidence",
        intent="文教资源",
        limit=10,
    )))

    package = response.source.meta["package"]
    assert response.source.title == "文教资源资料包"
    assert package["package_mode"] == "evidence"
    assert package["intent_plan"]["evidence_groups"][0]["categories"] == ["科教文化"]
    assert package["selection_reason"] == "用于说明区域文化展示资源。"
    assert package["groups"][0]["name"] == "文教展示资源"
    assert package["items"][0]["id"] == "poi-2"


def test_create_ppt_evidence_package_uses_current_request_center(monkeypatch):
    seen_area_context = {}

    async def fake_invoke_json_role(**kwargs):
        seen_area_context.update(kwargs["user_payload"]["area_context"])
        return {
            "package_title": "中心文教资源资料包",
            "selection_reason": "用于说明当前等时圈中心周边资源。",
            "evidence_groups": [
                {
                    "name": "中心周边展示资源",
                    "purpose": "说明当前中心点周边的文教资源。",
                    "queries": [
                        {
                            "name": "展示馆近邻",
                            "query_terms": ["展示馆"],
                            "nearby_required": True,
                            "radius_m": 500,
                            "target_count": 3,
                        }
                    ],
                }
            ],
        }

    request_center_wgs84 = [112.901, 28.201]
    request_center_gcj02 = list(wgs84_to_gcj02(request_center_wgs84[0], request_center_wgs84[1]))
    expected_center = list(gcj02_to_wgs84(request_center_gcj02[0], request_center_gcj02[1]))
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.ppt_planning.data_tools._invoke_json_role", fake_invoke_json_role)

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi"],
        package_mode="evidence",
        intent="中心周边文教资源",
        limit=10,
        center=request_center_gcj02,
        center_coord_type="gcj02",
        radius_m=1200,
    )))

    package = response.source.meta["package"]

    assert seen_area_context["center_source"] == "request_current_isochrone_center"
    assert seen_area_context["center_coord_type"] == "wgs84"
    assert seen_area_context["radius_m"] == 1200
    assert seen_area_context["center"] == pytest.approx(expected_center)
    assert seen_area_context["center"] != _fake_detail()["params"]["center"]
    assert package["center"] == pytest.approx(expected_center)
    assert package["center_coord_type"] == "wgs84"
    assert package["groups"][0]["queries"][0]["total"] >= 1


def test_create_ppt_evidence_package_merges_group_queries(monkeypatch):
    async def fake_invoke_json_role(**kwargs):
        return {
            "package_title": "夜间消费资料包",
            "selection_reason": "用于说明夜间消费活力。",
            "evidence_groups": [
                {
                    "name": "夜间消费活力",
                    "purpose": "说明夜间经济和社交消费潜力。",
                    "target_count": 4,
                    "queries": [
                        {
                            "name": "酒吧娱乐",
                            "categories": ["体育休闲"],
                            "subcategories": ["娱乐场所"],
                            "query_terms": ["酒吧"],
                            "target_count": 2,
                        },
                        {
                            "name": "夜宵烧烤",
                            "categories": ["餐饮"],
                            "query_terms": ["夜宵", "烧烤"],
                            "target_count": 2,
                        },
                    ],
                }
            ],
        }

    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_night_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.ppt_planning.data_tools._invoke_json_role", fake_invoke_json_role)

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi"],
        package_mode="evidence",
        intent="夜间消费",
        limit=4,
    )))

    package = response.source.meta["package"]
    group = package["groups"][0]
    item_ids = {item["id"] for item in group["items"]}

    assert item_ids == {"poi-4", "poi-5"}
    assert group["queries"][0]["name"] == "酒吧娱乐"
    assert group["plan_repair"][0]["from"] == "体育休闲"
    assert group["plan_repair"][0]["to"] == "体育"


def test_create_ppt_nightlife_package_aligns_poi_with_nightlight_cells(monkeypatch):
    def fake_artifacts(area_id, artifact_type="", params_hash=""):
        del area_id, params_hash
        if artifact_type == "poi_raster_grid":
            return [{
                "payload": {
                    "grid": {
                        "features": [{
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[
                                    [112.901, 28.201],
                                    [112.904, 28.201],
                                    [112.904, 28.204],
                                    [112.901, 28.204],
                                    [112.901, 28.201],
                                ]],
                            },
                            "properties": {"cell_id": "r0_c0"},
                        }],
                    },
                },
            }]
        if artifact_type == "nightlight":
            return [{
                "payload": {
                    "layer_cells": [{
                        "cell_id": "r0_c0",
                        "value": 12.5,
                        "class_key": "core_hotspot",
                        "class_label": "核心热点",
                        "has_data": True,
                    }],
                },
            }]
        return []

    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_night_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", fake_artifacts)

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:nightlight"],
        package_mode="evidence",
        intent="整理夜生活与夜间消费相关 POI，并与夜光格子对应",
        limit=10,
    )))

    package = response.source.meta["package"]
    items_by_id = {item["id"]: item for item in package["items"]}

    assert response.source.title == "夜生活 POI × 夜光格子资料包"
    assert package["source_ids"] == ["system:nightlight", "system:poi"]
    assert package["alignment"]["join_key"] == "cell_id"
    assert package["alignment"]["matched_item_count"] >= 2
    assert "intent_plan" in package
    assert {group["name"] for group in package["intent_plan"]["evidence_groups"]} >= {"夜间社交娱乐", "夜宵与轻餐饮"}
    assert items_by_id["poi-4"]["cell_id"] == "r0_c0"
    assert items_by_id["poi-4"]["nightlight_cell"]["class_label"] == "核心热点"
    assert items_by_id["poi-5"]["nightlight_cell"]["radiance"] == 12.5
    assert "poi-6" not in items_by_id
    assert "poi-7" not in items_by_id
    assert items_by_id["poi-8"]["nightlight_cell"]["radiance"] == 12.5


def test_create_ppt_nightlife_package_uses_nearest_cell_for_edge_poi(monkeypatch):
    def fake_artifacts(area_id, artifact_type="", params_hash=""):
        del area_id, params_hash
        if artifact_type == "poi_raster_grid":
            return [{
                "payload": {
                    "grid": {
                        "features": [{
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[
                                    [112.901, 28.201],
                                    [112.904, 28.201],
                                    [112.904, 28.204],
                                    [112.901, 28.204],
                                    [112.901, 28.201],
                                ]],
                            },
                            "properties": {"cell_id": "r0_c0"},
                        }],
                    },
                },
            }]
        if artifact_type == "nightlight":
            return [{
                "payload": {
                    "layer_cells": [{
                        "cell_id": "r0_c0",
                        "value": 18.25,
                        "class_label": "边缘热点",
                        "has_data": True,
                    }],
                },
            }]
        return []

    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_near_edge_night_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", fake_artifacts)

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:nightlight"],
        package_mode="evidence",
        intent="整理夜生活与夜间消费相关 POI，并与夜光格子对应",
        limit=10,
    )))

    package = response.source.meta["package"]
    item = package["items"][0]

    assert item["id"] == "poi-edge"
    assert item["cell_id"] == "r0_c0"
    assert item["alignment_status"] == "matched_nearest_cell"
    assert item["cell_match_distance_m"] <= 30
    assert item["nightlight_cell"]["radiance"] == 18.25
    assert package["alignment"]["nearest_matched_item_count"] == 1


def test_create_ppt_carrier_package_detects_block_loop_and_layers(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_carrier_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", _fake_carrier_artifacts())

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
        package_mode="evidence",
        intent="识别当前区域 POI、路网、人口、夜光共同支撑的空间载体",
        limit=10,
    )))

    package = response.source.meta["package"]
    carrier = package["carriers"][0]

    assert response.source.title == "POI × 路网空间载体资料包"
    assert response.source.id.startswith("package:poi-road-carriers:")
    assert package["evidence_layers"] == ["road_syntax", "poi", "population", "nightlight"]
    assert package["carrier_summary"]["block_loop_count"] >= 1
    assert package["road_context"]["source"] == "road_syntax.roads.features"
    assert package["road_context"]["coverage"] == "complete"
    assert package["road_context"]["total"] == 4
    assert package["road_context"]["included"] == 4
    assert package["road_context"]["features"][0]["path"]
    assert package["road_context"]["features"][0]["is_skeleton"] is True
    assert carrier["carrier_type"] == "block_loop"
    assert carrier["carrier_id"].startswith("block_loop_")
    assert carrier["road_metrics"]["road_count"] >= 4
    assert carrier["road_metrics"]["choice_score"] >= 0.8
    assert carrier["poi_metrics"]["total_related_poi_count"] >= 3
    assert carrier["population_metrics"]["total_population"] == 1800
    assert carrier["nightlight_metrics"]["hotspot_cell_count"] == 1
    assert carrier["carrier_label"] in {"成熟商业街区", "夜间消费街区"}
    assert carrier["geometry"]["polygon"]
    assert package["items"]
    assert package["alignment"]["alignment_level"] == "carrier_geometry_to_shared_cell_intersection"


def test_create_ppt_carrier_package_limits_representative_pois_per_carrier(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_dense_carrier_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", _fake_carrier_artifacts())

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
        package_mode="evidence",
        intent="识别当前区域 POI、路网、人口、夜光共同支撑的空间载体",
        limit=50,
    )))

    package = response.source.meta["package"]
    carrier = package["carriers"][0]

    assert carrier["poi_metrics"]["total_related_poi_count"] > 20
    assert len(carrier["representative_pois"]) == 3
    assert len([item for item in package["items"] if item["carrier_id"] == carrier["carrier_id"]]) <= 3
    assert package["carrier_summary"]["carrier_count"] == len(package["carriers"])


def test_create_ppt_carrier_package_does_not_claim_density_as_total_population(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_carrier_pois())
    monkeypatch.setattr(
        "modules.ppt_planning.data_tools.analysis_artifact_repo.list",
        _fake_carrier_artifacts(population_view="density"),
    )

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
        package_mode="evidence",
        intent="识别当前区域 POI、路网、人口、夜光共同支撑的空间载体",
        limit=10,
    )))

    carrier = response.source.meta["package"]["carriers"][0]
    population_metrics = carrier["population_metrics"]

    assert population_metrics["population_value_mode"] == "density_or_layer_value"
    assert population_metrics["total_population"] is None
    assert population_metrics["mean_cell_value"] == 8800
    assert population_metrics["unit"] == "人/平方公里"
    assert "人口密度均值 8800" in carrier["summary"]
    assert "服务人口约 8800" not in carrier["summary"]


def test_create_ppt_carrier_package_turns_open_roads_into_corridor_not_loop(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_carrier_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", _fake_carrier_artifacts(road_mode="corridor"))

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
        package_mode="evidence",
        intent="识别当前区域 POI、路网、人口、夜光共同支撑的空间载体",
        limit=10,
    )))

    package = response.source.meta["package"]
    carriers = package["carriers"]

    assert package["carrier_summary"]["block_loop_count"] == 0
    assert package["carrier_summary"]["corridor_count"] >= 1
    assert carriers[0]["carrier_type"] == "corridor"
    assert carriers[0]["carrier_id"].startswith("corridor_")
    assert carriers[0]["geometry"]["boundary"]
    assert carriers[0]["road_metrics"]["road_count"] >= 2


def test_create_ppt_carrier_package_turns_single_road_into_segment(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_carrier_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", _fake_carrier_artifacts(road_mode="segment"))

    response = asyncio.run(create_ppt_data_package(PptDataPackageRequest(
        area_id="history-1",
        source_ids=["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
        package_mode="evidence",
        intent="识别当前区域 POI、路网、人口、夜光共同支撑的空间载体",
        limit=10,
    )))

    package = response.source.meta["package"]
    carrier = package["carriers"][0]

    assert package["carrier_summary"]["block_loop_count"] == 0
    assert package["carrier_summary"]["corridor_count"] == 0
    assert package["carrier_summary"]["segment_count"] == 1
    assert carrier["carrier_type"] == "segment"
    assert carrier["road_metrics"]["road_count"] == 1
    assert carrier["carrier_label"] in {"重要通达路段", "高 choice 穿行路段", "高 integration 到达路段", "高潜力路段"}


def test_create_ppt_carrier_package_requires_population_and_nightlight(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_carrier_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", _fake_carrier_artifacts(missing_population=True))

    with pytest.raises(PptDataSourceNotFound, match="carrier_package_missing_population"):
        asyncio.run(create_ppt_data_package(PptDataPackageRequest(
            area_id="history-1",
            source_ids=["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
            package_mode="evidence",
            intent="识别当前区域 POI、路网、人口、夜光共同支撑的空间载体",
            limit=10,
        )))


def test_create_ppt_evidence_package_requires_llm(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.is_llm_enabled", lambda: False)

    with pytest.raises(PptDataIntentLlmUnavailable):
        asyncio.run(create_ppt_data_package(PptDataPackageRequest(
            area_id="history-1",
            source_ids=["system:poi"],
            package_mode="evidence",
        )))


def test_create_ppt_evidence_package_rejects_empty_llm_plan(monkeypatch):
    async def fake_invoke_json_role(**kwargs):
        return {"query_terms": [], "categories": [], "subcategories": [], "typecodes": [], "nearby_required": False}

    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.is_llm_enabled", lambda: True)
    monkeypatch.setattr("modules.ppt_planning.data_tools._invoke_json_role", fake_invoke_json_role)

    with pytest.raises(PptDataInvalidIntentPlan):
        asyncio.run(create_ppt_data_package(PptDataPackageRequest(
            area_id="history-1",
            source_ids=["system:poi"],
            package_mode="evidence",
        )))


def test_list_ppt_sources_marks_scope_and_poi_ready(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", lambda *args, **kwargs: [])

    sources = {item.id: item for item in list_ppt_sources("history-1")}

    assert sources["system:scope"].status == "ready"
    assert sources["system:poi"].status == "ready"
    assert sources["system:poi"].count == 3
    assert sources["system:h3"].status == "pending"


def test_list_ppt_sources_includes_document_evidence_sources(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    AiBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = factory()
    try:
        session.add(
            Document(
                id="doc-1",
                title="更新政策研究",
                file_name="policy.pdf",
                file_type="pdf",
                file_path="/tmp/policy.pdf",
                document_role="policy_document",
                upload_time=datetime(2026, 6, 12, 1, 0, 0),
                status="parsed",
            )
        )
        session.add(
            DocumentIndexNode(
                document_id="doc-1",
                node_id="n1",
                parent_node_id="root",
                title="政策要求",
                level=1,
                ordinal=1,
                start_block_index=0,
                end_block_index=1,
                page_start=3,
                page_end=3,
                summary="政策要求完善公共服务设施。",
                text="政策要求完善公共服务设施。",
                created_at=datetime(2026, 6, 12, 1, 0, 0),
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr("modules.ppt_planning.data_tools.AiSessionLocal", factory)
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_detail", lambda area_id, include_pois=False: _fake_detail())
    monkeypatch.setattr("modules.ppt_planning.data_tools.history_repo.get_pois", lambda area_id, year=None: _fake_pois())
    monkeypatch.setattr("modules.ppt_planning.data_tools.analysis_artifact_repo.list", lambda *args, **kwargs: [])

    sources = {item.id: item for item in list_ppt_sources("history-1")}

    source = sources["document:doc-1"]
    assert source.type == "document"
    assert source.status == "ready"
    assert source.count == 1
    assert source.summary == "章节 1 个"
    assert source.meta["sourceKind"] == "document"
    assert source.meta["document"]["document_role"] == "policy_document"
    assert source.meta["document"]["index_count"] == 1
    assert source.meta["document_index_preview"][0]["title"] == "政策要求"
