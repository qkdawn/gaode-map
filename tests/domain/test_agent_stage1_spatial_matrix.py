import pytest
from modules.agent.stage1_spatial_matrix import (
    SpatialMatrixContractError,
    compile_spatial_programming_matrix,
)


def _movement_routes(visitor_binding=None):
    bindings = {
        "visitor": visitor_binding
        or {"status": "unavailable", "spatial_object_id": "", "reason": "游客路径待测绘"},
        "resident": {"status": "unavailable", "spatial_object_id": "", "reason": "居民路径待访谈"},
        "service": {"status": "unavailable", "spatial_object_id": "", "reason": "后勤路径待运营核验"},
        "fire": {"status": "unavailable", "spatial_object_id": "", "reason": "消防路径待专项核验"},
    }
    labels = {"visitor": "游客主游线", "resident": "居民日常流线", "service": "后勤流线", "fire": "消防应急流线"}
    return [
        {
            "route_id": f"route-{movement_type}",
            "movement_type": movement_type,
            "title": labels[movement_type],
            "role": "连接南侧道路与礼堂",
            "origin": "南侧道路",
            "destinations": ["原县政府礼堂"],
            "affected_space_ids": ["space-auditorium"],
            "operating_windows": ["日常开放时段"],
            "constraints": ["无障碍连续性待核验"],
            "conflicts": [] if movement_type != "service" else ["与游客到达存在交叉"],
            "evidence_refs": ["evidence-1"],
            "assumptions": [],
            "validation_actions": ["现场踏勘并复核路径宽度"],
            "status": "proposed",
            "map_binding": bindings[movement_type],
        }
        for movement_type in ("visitor", "resident", "service", "fire")
    ]


def _matrix():
    return {
        "matrix_version": "2.0",
        "positioning_option_id": "option-a",
        "spatial_hierarchy": [
            {
                "id": "system-yard",
                "title": "一院",
                "level": "system",
                "parent_id": "",
                "role": "公共文化与核心体验系统",
                "member_space_ids": [],
            },
            {
                "id": "cluster-culture",
                "title": "公共文化组团",
                "level": "cluster",
                "parent_id": "system-yard",
                "role": "形成可独立运营的公共文化体验",
                "member_space_ids": [],
            },
            {
                "id": "unit-auditorium",
                "title": "礼堂单元",
                "level": "unit",
                "parent_id": "cluster-culture",
                "role": "承载社区文化活动",
                "member_space_ids": ["space-auditorium"],
            },
        ],
        "space_decisions": [
            {
                "space_id": "space-auditorium",
                "hierarchy_id": "unit-auditorium",
                "space_name": "原县政府礼堂",
                "future_role": "社区文化锚点",
                "core_audiences": ["社区家庭"],
                "movement_role": "主游线目的地",
                "value_role": "公共服务与活动引流",
                "current_state_category": "vacant",
                "current_state": {"summary": "礼堂当前闲置"},
                "change_logic": {"reason": "补足社区文化活动空间"},
                "candidate_functions": [
                    {"id": "culture", "name": "文化活动"},
                    {"id": "retail", "name": "社区零售"},
                ],
                "preferred_function": {"id": "culture", "name": "文化活动"},
                "compatible_functions": [{"id": "exhibition", "name": "社区展览"}],
                "excluded_functions": [{"id": "heavy-food", "name": "重餐饮"}],
                "audience_scenarios": ["社区周末活动"],
                "access_and_movement": {"visitor_origin": "南侧道路"},
                "operation_strategy": {"operator": "社区文化运营主体"},
                "renovation_and_delivery": {"scope": "轻量改造"},
                "implementation_phase": "phase_1",
                "risk_level": "high",
                "risk_summary": "消防和结构条件尚待核验",
                "preconditions": ["完成消防评估"],
                "evidence_refs": ["evidence-1"],
                "hard_constraint_refs": ["fire_safety"],
                "assumptions": [],
                "validation_actions": ["开展消防与结构核验"],
                "recommendation_status": "conditional",
                "confidence": "medium",
                "map_binding": {
                    "status": "bound",
                    "spatial_object_id": "building:auditorium",
                },
            }
        ],
        "movement_routes": _movement_routes(
            {"status": "bound", "spatial_object_id": "path:main"}
        ),
        "portfolio_checks": ["公共服务与经营功能平衡"],
    }


def _registry():
    return {
        "path:main": {
            "spatial_object_id": "path:main",
            "object_type": "internal_path",
            "title": "南侧道路至礼堂路径",
            "source_ref": "project_gis.paths",
            "source_locator": "project_gis.paths/main",
            "feature": {
                "type": "Feature",
                "id": "path:main",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[112.0, 28.0], [112.1, 28.1]],
                },
            },
        },
        "building:auditorium": {
            "spatial_object_id": "building:auditorium",
            "object_type": "building",
            "title": "原县政府礼堂",
            "source_ref": "project_gis.buildings",
            "source_locator": "project_gis.buildings/auditorium",
            "feature": {
                "type": "Feature",
                "id": "building:auditorium",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1], [112.0, 28.0]]
                    ],
                },
            },
        }
    }


def test_compile_spatial_matrix_derives_hierarchy_and_map_modes():
    result = compile_spatial_programming_matrix(_matrix(), _registry())

    assert [item["id"] for item in result["map_presentation"]["modes"]] == [
        "current_state",
        "suggested_function",
        "recommendation_strength",
        "risk",
        "implementation_phase",
    ]
    item = result["map_presentation"]["items"][0]
    assert item["hierarchy_level"] == "unit"
    assert item["map_binding"]["feature"]["geometry"]["type"] == "Polygon"
    assert item["values"]["current_state"]["label"] == "闲置"
    assert item["values"]["suggested_function"]["label"] == "文化活动"
    assert item["values"]["recommendation_strength"]["label"] == "有条件推荐"
    assert item["values"]["risk"]["label"] == "高风险"
    assert item["values"]["implementation_phase"]["label"] == "一期"
    assert result["map_presentation"]["bound_item_count"] == 1
    assert result["movement_presentation"]["bound_item_count"] == 1
    assert [item["label"] for item in result["movement_presentation"]["types"]] == [
        "游客",
        "居民",
        "后勤",
        "消防应急",
    ]
    route = result["movement_presentation"]["items"][0]
    assert route["color"] == "#2563eb"
    assert route["map_binding"]["feature"]["geometry"]["type"] == "LineString"


def test_compile_spatial_matrix_rejects_flat_or_cross_level_hierarchy():
    matrix = _matrix()
    matrix["spatial_hierarchy"][2]["parent_id"] = "system-yard"

    with pytest.raises(SpatialMatrixContractError, match="必须引用一个 cluster 层"):
        compile_spatial_programming_matrix(matrix, _registry())


def test_compile_spatial_matrix_requires_decision_membership_in_hierarchy():
    matrix = _matrix()
    matrix["spatial_hierarchy"][2]["member_space_ids"] = []

    with pytest.raises(SpatialMatrixContractError, match="未登记在层级节点"):
        compile_spatial_programming_matrix(matrix, _registry())


def test_compile_spatial_matrix_requires_unique_decision_space_ids():
    matrix = _matrix()
    matrix["space_decisions"].append(matrix["space_decisions"][0].copy())

    with pytest.raises(SpatialMatrixContractError, match="重复稳定 space_id"):
        compile_spatial_programming_matrix(matrix, _registry())


def test_compile_spatial_matrix_rejects_uncontrolled_risk_or_phase_values():
    matrix = _matrix()
    matrix["space_decisions"][0]["risk_level"] = "probably-high"

    with pytest.raises(SpatialMatrixContractError):
        compile_spatial_programming_matrix(matrix, _registry())


def test_compile_spatial_matrix_requires_all_four_movement_systems():
    matrix = _matrix()
    matrix["movement_routes"].pop()

    with pytest.raises(SpatialMatrixContractError, match="movement_routes"):
        compile_spatial_programming_matrix(matrix, _registry())


def test_compile_spatial_matrix_rejects_unknown_movement_space_reference():
    matrix = _matrix()
    matrix["movement_routes"][0]["affected_space_ids"] = ["space-invented"]

    with pytest.raises(SpatialMatrixContractError, match="不存在的 affected_space_ids"):
        compile_spatial_programming_matrix(matrix, _registry())


def test_compile_spatial_matrix_rejects_non_line_route_binding():
    matrix = _matrix()
    matrix["movement_routes"][0]["map_binding"] = {
        "status": "bound",
        "spatial_object_id": "building:auditorium",
    }

    result = compile_spatial_programming_matrix(matrix, _registry())

    binding = result["movement_routes"][0]["map_binding"]
    assert binding["status"] == "unavailable"
    assert "LineString" in binding["reason"]
