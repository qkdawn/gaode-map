import asyncio

import pytest

from modules.ppt_planning.data_tools import (
    PptDataIntentLlmUnavailable,
    PptDataInvalidIntentPlan,
    create_ppt_data_package,
    list_ppt_sources,
    query_nearby_poi_points,
    query_poi_points,
)
from modules.ppt_planning.schemas import PptDataPackageRequest, PptPoiNearbyRequest, PptPoiQueryRequest


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
