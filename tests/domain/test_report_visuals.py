from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.svg_safety import validate_safe_svg
from modules.report_visuals.schemas import EditorialAction
from modules.report_visuals.service import render_report_visuals
from modules.report_visuals.templates import (
    normalize_age_structure,
    normalize_directional_matrix,
)


AGE_ANCHOR = "由此形成四类优先使用情境："
DIRECTION_ANCHOR = "<!-- report-anchor:directional-action-priority -->"
POPULATION_SUPPLY_CONTEXT_ANCHOR = "<!-- report-anchor:population-supply-context -->"
POI_ROUTE_MAP_ANCHOR = "<!-- report-anchor:poi-route-map -->"
POI_SUPPLY_STRUCTURE_ANCHOR = "<!-- report-anchor:poi-supply-structure -->"


def _report(tmp_path: Path, *, route_anchor: bool = True, supply_anchor: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    report = tmp_path / "decision-report.md"
    lines = [
        "# 决策报告",
        "## 3. 人群与供给",
        "年龄结构描述。",
        AGE_ANCHOR,
        "四类使用情境表。",
        POPULATION_SUPPLY_CONTEXT_ANCHOR,
        *( [POI_SUPPLY_STRUCTURE_ANCHOR] if supply_anchor else [] ),
        *( [POI_ROUTE_MAP_ANCHOR] if route_anchor else [] ),
        "## 4. 空间与可达性",
        "方向矩阵结论。",
        DIRECTION_ANCHOR,
    ]
    report.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return report


def _age() -> dict:
    return {"year": 2026, "age_distribution": [
        {"age_band_label": "0–14", "ratio": 0.1249}, {"age_band_label": "15–24", "ratio": 0.1510},
        {"age_band_label": "25–44", "ratio": 0.3711}, {"age_band_label": "45–59", "ratio": 0.2142},
        {"age_band_label": "60+", "ratio": 0.1388},
    ]}


def _matrix() -> dict:
    rows = []
    for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW"):
        for band in ("0-500m", "500-1000m", "1000-1600m"):
            rows.append({
                "sector": direction, "distance_band": band, "population_density": 100,
                "poi_density": 10, "nightlight_mean": 2, "road_integration": 0.2,
                "road_coverage_ratio": 0.2, "signals": {"road_coverage_available": True},
            })
    return {
        "sectors": rows,
        "source_versions": {
            "poi": {"year": 2024},
            "nightlight": {"year": 2025},
            "population": {"year": 2026},
            "road": {"year": None},
        },
    }


def _focused() -> dict:
    return {"focused_poi_accessibility": {
        "status": "partial", "year": 2026, "origin": [120.001, 30.001],
        "groups": [
            {"group_id": "food", "title": "餐饮配套", "role": "complementary_anchor", "status": "available", "statement_ref": "section-3:food", "pois": [
                {"name": "社区食堂北门店", "category": "050101", "walking_distance_m": 620, "walking_duration_s": 510, "route_status": "available"},
                {"name": "邻里咖啡站", "category": "050500", "walking_distance_m": 840, "walking_duration_s": 690, "route_status": "available"},
            ]},
            {"group_id": "benchmark", "title": "同类对标", "role": "comparison_supply", "status": "available", "statement_ref": "section-5:benchmark", "pois": [
                {"name": "城市社区生活馆示范店", "category": "060200", "walking_distance_m": 900, "walking_duration_s": 720, "route_status": "available"},
            ]},
            {"group_id": "late", "title": "无路线组", "role": "comparison_supply", "status": "omitted", "statement_ref": "section-5:benchmark", "omission_reason": "no_route_verified_pois", "pois": []},
        ],
    }}


def _supply_structure() -> dict:
    return {"poi_supply_structure": {
        "status": "partial", "year": 2026, "source_id": "current:dataset:poi",
        "scope": {"kind": "verified_walking_isochrone", "time_min": 15, "mode": "walking", "geometry_source": "history.result_polygon_wgs84", "point_inclusion_method": "covers"},
        "five_minute_accessibility_status": "partial",
        "taxonomy_audit": {"source": "share/type_map.json", "unmapped_type_codes": ["990001"], "unmapped_poi_count": 1},
        "isochrone_audit": {"included_poi_count": 30, "outside_isochrone_poi_count": 2, "missing_coordinate_poi_count": 1, "invalid_coordinate_poi_count": 0},
        "groups": [
            {"group_id": "food", "title": "餐饮与轻饮", "role": "complementary_anchor", "statement_ref": "section-3:food", "status": "available"},
            {"group_id": "culture", "title": "文化生活类对标", "role": "comparison_supply", "statement_ref": "section-3:culture", "status": "available"},
            {"group_id": "omitted", "title": "无效组", "role": "comparison_supply", "statement_ref": "section-3:omit", "status": "unavailable", "omission_reason": "requested_type_code_not_in_poi_snapshot"},
        ],
        "classified_rows": [
            {"role": "complementary_anchor", "main_category": "餐饮", "subcategory": "中餐厅", "isochrone_poi_count": 18, "nearby_5_min_poi_count": 6, "selected_type_codes": ["050100"], "source_group_ids": ["food"], "statement_refs": ["section-3:food"]},
            {"role": "complementary_anchor", "main_category": "餐饮", "subcategory": "外国餐厅", "isochrone_poi_count": 8, "nearby_5_min_poi_count": 2, "selected_type_codes": ["050200"], "source_group_ids": ["food"], "statement_refs": ["section-3:food"]},
            {"role": "complementary_anchor", "main_category": "餐饮", "subcategory": "快餐厅", "isochrone_poi_count": 4, "nearby_5_min_poi_count": None, "selected_type_codes": ["050300"], "source_group_ids": ["food"], "statement_refs": ["section-3:food"]},
            {"role": "complementary_anchor", "main_category": "餐饮", "subcategory": "咖啡厅", "isochrone_poi_count": 3, "nearby_5_min_poi_count": 1, "selected_type_codes": ["050500"], "source_group_ids": ["food"], "statement_refs": ["section-3:food"]},
            {"role": "complementary_anchor", "main_category": "购物", "subcategory": "商场", "isochrone_poi_count": 4, "nearby_5_min_poi_count": None, "selected_type_codes": ["060100"], "source_group_ids": ["food"], "statement_refs": ["section-3:food"]},
            {"role": "comparison_supply", "main_category": "科教文化", "subcategory": "博物馆", "isochrone_poi_count": 7, "nearby_5_min_poi_count": 2, "selected_type_codes": ["140100"], "source_group_ids": ["culture"], "statement_refs": ["section-3:culture"]},
        ],
    }}

def _actions() -> list[dict]:
    return [
        {"direction": "N", "distance_band": "0-500m", "action": "导向验证", "evidence_label": "人口+路网", "required_evidence": ["population", "road"]},
        {"direction": "NW", "distance_band": "500-1000m", "action": "导向验证", "evidence_label": "POI+路网", "required_evidence": ["poi", "road"]},
        {"direction": "SW", "distance_band": "0-500m", "action": "通达诊断", "evidence_label": "POI+低覆盖", "required_evidence": ["poi", "low_road_coverage"]},
        {"direction": "E", "distance_band": "1000-1600m", "action": "夜间联动测试", "evidence_label": "夜光+低整合", "required_evidence": ["nightlight", "low_road_integration"]},
    ]


def test_current_metric_payloads_normalize_for_age_and_direction() -> None:
    age_rows = [
        {"age_band": code, "total": total}
        for code, total in (
            ("00", 1), ("01", 4), ("05", 5), ("10", 5),
            ("15", 5), ("20", 5), ("25", 5), ("30", 5),
            ("35", 5), ("40", 5), ("45", 5), ("50", 5),
            ("55", 5), ("60", 5), ("65", 5), ("70", 5),
            ("75", 5), ("80", 5), ("85", 5), ("90", 5),
        )
    ]
    normalized_age = normalize_age_structure({
        "evidence:population:scope-profile": {"age_distribution": age_rows},
        "time_scope": {
            "datasets": [
                {"source_id": "current:dataset:population", "year": 2026}
            ]
        },
    })
    assert not isinstance(normalized_age, str)
    assert normalized_age[0] == 2026
    assert sum(item["share"] for item in normalized_age[1]) == pytest.approx(100, abs=0.05)

    rows = [
        {
            "sector": direction,
            "distance_band": band,
            "population_density_mean": 1,
            "poi_count": 1,
            "nightlight_mean": 1,
            "road_integration_covered_mean": 1,
            "road_coverage_ratio": 1,
        }
        for band in ("0-500m", "500-1000m", "1000-1600m")
        for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    ]
    normalized_direction = normalize_directional_matrix(
        {"directional_evidence_matrix": {"rows": rows}},
        [EditorialAction.model_validate(item) for item in _actions()],
    )
    assert not isinstance(normalized_direction, str)
    assert len(normalized_direction) == 24


def _plan(*template_ids: str) -> dict:
    anchors = {
        "population_age_structure": AGE_ANCHOR,
        "population_supply_context": POPULATION_SUPPLY_CONTEXT_ANCHOR,
        "directional_action_priority_matrix": DIRECTION_ANCHOR,
        "focused_poi_walking_route_map": POI_ROUTE_MAP_ANCHOR,
        "poi_supply_structure": POI_SUPPLY_STRUCTURE_ANCHOR,
    }
    metrics = {
        "population_age_structure": ["population.age_structure"],
        "population_supply_context": ["population.age_structure", "poi.supply_structure"],
        "directional_action_priority_matrix": ["regional.directional_evidence_matrix"],
        "focused_poi_walking_route_map": ["poi.focused_accessibility"],
        "poi_supply_structure": ["poi.supply_structure"],
    }
    return {"schema_version": "report-visual-plan.v1", "run_id": "test-run", "items": [
        {
            "template_id": identifier, "chapter_anchor": anchors[identifier], "metric_ids": metrics[identifier],
            "supports_judgment": "这张图删除后会改变相邻的已审校判断。", "does_not_prove": "不表示客流、营收或合作关系。",
            "selection_reason": "视觉证据编辑已确认其支持相邻判断。",
            "template_input": {"editorial_actions": _actions()} if identifier == "directional_action_priority_matrix" else {},
        } for identifier in template_ids
    ]}


def _request(report: Path, *template_ids: str) -> dict:
    return {
        "run_id": "test-run", "report_path": str(report), "visual_plan": _plan(*template_ids),
        "age_structure": _age(), "directional_evidence_matrix": _matrix(), "focused_poi_accessibility": _focused(), "poi_supply_structure": _supply_structure(),
    }


def test_visual_plan_drives_exactly_selected_assets_and_persists_both_manifests(tmp_path: Path) -> None:
    report = _report(tmp_path)
    request = _request(report, "population_age_structure", "directional_action_priority_matrix", "poi_supply_structure")

    manifest = render_report_visuals(request)

    assert [item.template_id for item in manifest.items] == ["population_age_structure", "directional_action_priority_matrix", "poi_supply_structure"]
    assert all(item.status == "generated" for item in manifest.items)
    assert (tmp_path / "visual-plan.json").is_file()
    assert (tmp_path / "visual-manifest.json").is_file()
    text = report.read_text(encoding="utf-8")
    assert "assets/population-age-structure.svg" in text
    assert "assets/directional-action-priority.svg" in text
    assert "assets/poi-supply-structure.svg" in text

    plan = json.loads((tmp_path / "visual-plan.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "visual-manifest.json").read_text(encoding="utf-8"))
    assert plan["items"][2]["template_id"] == "poi_supply_structure"
    assert final["items"][2]["data_scope"]["scope"]["kind"] == "verified_walking_isochrone"

    svg = (tmp_path / "assets" / "poi-supply-structure.svg").read_text(encoding="utf-8")
    validate_safe_svg(svg)
    assert "项目所需配套" in svg and "同类对标供给" in svg


def test_population_supply_context_combines_both_results_without_scoring(tmp_path: Path) -> None:
    report = _report(tmp_path)
    manifest = render_report_visuals(_request(report, "population_supply_context"))

    assert manifest.items[0].status == "generated"
    assert manifest.items[0].data_scope["population_year"] == 2026
    assert manifest.items[0].data_scope["poi_year"] == 2026
    svg = (tmp_path / "assets" / "population-supply-context.svg").read_text(encoding="utf-8")
    validate_safe_svg(svg)
    assert "居民使用背景与周边供给结构" in svg
    assert "人口使用背景" in svg and "周边 POI 供给" in svg
    spec = json.loads((tmp_path / "assets" / "population-supply-context.vl.json").read_text(encoding="utf-8"))
    assert '"score"' not in json.dumps(spec, ensure_ascii=False)


def test_plan_rejects_unapproved_anchor_duplicate_template_and_omitted_reason(tmp_path: Path) -> None:
    report = _report(tmp_path)
    request = _request(report, "population_age_structure")
    request["visual_plan"]["items"][0]["chapter_anchor"] = "wrong"
    with pytest.raises(ValueError, match="approved report anchor"):
        render_report_visuals(request)

    request = _request(report, "population_age_structure", "population_age_structure")
    with pytest.raises(ValueError, match="at most once"):
        render_report_visuals(request)

    request = _request(report, "population_age_structure")
    request["visual_plan"]["items"][0]["status"] = "omitted"
    with pytest.raises(ValueError, match="require omission_reason"):
        render_report_visuals(request)


def _focused_with_route_map() -> dict:
    focused = deepcopy(_focused())
    payload = focused["focused_poi_accessibility"]
    payload["routing_algorithm"] = "local_road_network_shortest_path"
    payload["duration_method"] = "road_network_length_at_4_5_km_per_hour"
    payload["map_context"] = {
        "road_source_id": "current:dataset:road_edges",
        "routing_algorithm": "local_road_network_shortest_path",
        "origin": [120.001, 30.001],
        "analysis_geometry": {
            "type": "Polygon",
            "coordinates": [[[120.000, 30.000], [120.000, 30.002], [120.002, 30.002], [120.002, 30.000], [120.000, 30.000]]],
        },
        "road_edges": [
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[119.999, 30.001], [120.002, 30.001], [120.004, 30.001], [120.006, 30.001]]}, "properties": {"edge_id": "main"}},
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[120.003, 30.001], [120.0032, 30.0014], [120.0034, 30.0018], [120.0038, 30.002]]}, "properties": {"edge_id": "branch"}},
        ],
        "road_edges_clipped_count": 2,
        "road_edges_rendered_count": 2,
    }
    route_specs = [
        ([[120.001, 30.001], [120.002, 30.001], [120.003, 30.001]], [120.003, 30.001]),
        ([[120.001, 30.001], [120.002, 30.001], [120.003, 30.001], [120.0032, 30.0014], [120.0034, 30.0018], [120.0038, 30.002]], [120.0038, 30.002]),
        ([[120.001, 30.001], [120.002, 30.001], [120.004, 30.001]], [120.004, 30.001]),
    ]
    routed_pois = [poi for group in payload["groups"] if group["status"] == "available" for poi in group["pois"]]
    for poi, (coordinates, location) in zip(routed_pois, route_specs):
        poi.update({
            "location": location,
            "route_geometry": {"type": "LineString", "coordinates": coordinates},
            "route_geometry_status": "available",
            "route_length_m": poi["walking_distance_m"],
            "origin_snap": [120.001, 30.001],
            "destination_snap": location,
            "origin_snap_distance_m": 0,
            "destination_snap_distance_m": 0,
            "routing_algorithm": "local_road_network_shortest_path",
        })
    return focused


def test_route_map_contains_paths_and_poi_details_in_one_visual(tmp_path: Path) -> None:
    report = _report(tmp_path)
    request = _request(report, "focused_poi_walking_route_map")
    request["focused_poi_accessibility"] = _focused_with_route_map()

    manifest = render_report_visuals(request)

    assert [item.status for item in manifest.items] == ["generated"]
    text = report.read_text(encoding="utf-8")
    assert text.index("assets/focused-poi-walking-route-map.svg") < text.index(POI_ROUTE_MAP_ANCHOR)
    assert "focused-poi-walking-accessibility.svg" not in text

    svg = (tmp_path / "assets" / "focused-poi-walking-route-map.svg").read_text(encoding="utf-8")
    spec = json.loads((tmp_path / "assets" / "focused-poi-walking-route-map.vl.json").read_text(encoding="utf-8"))
    validate_safe_svg(svg)
    assert "重点 POI 步行路线与当前路网" in svg
    assert "当前路网快照" in svg and "本地最短路径" in svg
    assert "社区食堂北门店" in svg and "城市社区生活馆示范店" in svg
    assert "高德" not in svg and "综合得分" not in svg and "客流" not in svg and "营收" not in svg
    assert manifest.items[0].data_scope["road_source_id"] == "current:dataset:road_edges"
    assert manifest.items[0].data_scope["route_poi_count"] == 3
    role_layer = spec["hconcat"][1]["layer"][2]
    assert role_layer["mark"]["align"] == "right"
    assert role_layer["encoding"]["x"]["datum"] == 386
    assert spec["padding"]["bottom"] == 36


def test_route_map_uses_confirmed_analysis_origin_with_minimal_scope_geometry(tmp_path: Path) -> None:
    report = _report(tmp_path)
    request = _request(report, "focused_poi_walking_route_map")
    request["focused_poi_accessibility"] = _focused_with_route_map()
    request["focused_poi_accessibility"]["focused_poi_accessibility"]["map_context"]["analysis_geometry"] = {"type": "Polygon"}

    manifest = render_report_visuals(request)

    assert manifest.items[0].status == "generated"
    assert (tmp_path / "assets" / "focused-poi-walking-route-map.svg").is_file()
    spec_text = (tmp_path / "assets" / "focused-poi-walking-route-map.vl.json").read_text(encoding="utf-8")
    assert "分析中心（路线起点）" in spec_text


def test_route_map_omits_without_anchor_or_real_road_route_evidence(tmp_path: Path) -> None:
    report = _report(tmp_path, route_anchor=False)
    request = _request(report, "focused_poi_walking_route_map")
    request["focused_poi_accessibility"] = _focused_with_route_map()
    missing_anchor = render_report_visuals(request)
    assert missing_anchor.items[0].status == "omitted"
    assert "指定锚点" in str(missing_anchor.items[0].omission_reason)

    report = _report(tmp_path / "no-road")
    request = _request(report, "focused_poi_walking_route_map")
    request["focused_poi_accessibility"] = _focused_with_route_map()
    request["focused_poi_accessibility"]["focused_poi_accessibility"]["map_context"]["road_edges"] = []
    manifest = render_report_visuals(request)
    assert [item.status for item in manifest.items] == ["omitted"]
    assert "真实路网线" in str(manifest.items[0].omission_reason)



def test_poi_supply_structure_renders_real_main_and_subcategories_from_verified_isochrone(tmp_path: Path) -> None:
    report = _report(tmp_path)
    manifest = render_report_visuals(_request(report, "poi_supply_structure"))

    assert manifest.items[0].status == "generated"
    assert manifest.items[0].asset_path == "assets/poi-supply-structure.svg"
    scope = manifest.items[0].data_scope
    assert scope["scope"]["kind"] == "verified_walking_isochrone"
    assert scope["scope"]["point_inclusion_method"] == "covers"
    assert scope["taxonomy_audit"]["unmapped_type_codes"] == ["990001"]
    assert scope["isochrone_audit"]["outside_isochrone_poi_count"] == 2
    assert scope["omitted_groups"][0]["reason"] == "requested_type_code_not_in_poi_snapshot"
    text = report.read_text(encoding="utf-8")
    assert "assets/poi-supply-structure.svg" in text
    assert text.index("assets/poi-supply-structure.svg") < text.index(POI_SUPPLY_STRUCTURE_ANCHOR)

    svg = (tmp_path / "assets" / "poi-supply-structure.svg").read_text(encoding="utf-8")
    validate_safe_svg(svg)
    assert "15 分钟等时圈内的 POI 供给结构（2026）" in svg
    assert "项目所需配套" in svg and "同类对标供给" in svg
    assert "餐饮｜中餐厅" in svg and "餐饮｜外国餐厅" in svg and "购物｜商场" in svg
    assert "科教文化｜博物馆" in svg and "其他已选附属类" in svg
    assert "餐饮与轻饮" not in svg and "文化生活类对标" not in svg
    assert "15 分钟等时圈内 POI" in svg and "≤5 分钟可达 POI" in svg
    assert "快照内总量" not in svg and "道路路径未形成" not in svg

    spec = json.loads((tmp_path / "assets" / "poi-supply-structure.vl.json").read_text(encoding="utf-8"))
    complementary_values = spec["hconcat"][0]["data"]["values"]
    assert any(row["category"] == "餐饮｜其他已选附属类" and row["count"] == 3 for row in complementary_values)
    assert any(row["category"] == "购物｜商场" for row in complementary_values)

def test_poi_supply_structure_omits_when_scope_or_semantic_anchor_is_missing(tmp_path: Path) -> None:
    report = _report(tmp_path, supply_anchor=False)
    request = _request(report, "poi_supply_structure")
    missing_anchor = render_report_visuals(request)
    assert missing_anchor.items[0].status == "omitted"
    assert "指定锚点" in str(missing_anchor.items[0].omission_reason)

    report = _report(tmp_path / "invalid-scope")
    request = _request(report, "poi_supply_structure")
    request["poi_supply_structure"]["poi_supply_structure"].pop("scope")
    invalid_scope = render_report_visuals(request)
    assert invalid_scope.items[0].status == "omitted"
    assert "15 分钟 walking 等时圈几何口径" in str(invalid_scope.items[0].omission_reason)
