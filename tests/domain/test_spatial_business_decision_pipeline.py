from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, mapping

from modules.agent.analysis_runs import AnalysisRun
from modules.spatial_action import (
    DestinationAnchor,
    EntranceAnchor,
    LocalizedPatternInputCell,
    RoadSegmentRef,
    SpatialActionService,
)
from modules.spatial_action.valhalla import ValhallaRoute


class _FixtureValhalla:
    def route(self, origin, destination):
        geometry = mapping(LineString([origin, (origin[0], (origin[1] + destination[1]) / 2), destination]))
        return ValhallaRoute(geometry=geometry, distance_m=300.0, duration_s=240.0)


def _square(x: float, y: float, size: float = 0.0005):
    return mapping(Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size), (x, y)]))


def test_daily_entrance_decision_pipeline_remains_a_focused_diagnostic_without_project_report(tmp_path: Path):
    service = SpatialActionService(route_adapter=_FixtureValhalla())
    local_patterns = service.analyze_local_patterns(
        [
            LocalizedPatternInputCell(
                cell_id="north-a",
                metric_id="spatial.gi_star",
                value=12,
                geometry=_square(116.0017, 39.0032),
                p_value=0.001,
                z_score=3.4,
                cluster_type="hotspot",
                neighbor_ids=["north-b"],
            ),
            LocalizedPatternInputCell(
                cell_id="north-b",
                metric_id="spatial.gi_star",
                value=11,
                geometry=_square(116.0022, 39.0032),
                p_value=0.002,
                z_score=3.1,
                cluster_type="hotspot",
                neighbor_ids=["north-a"],
            ),
            LocalizedPatternInputCell(
                cell_id="east-outlier",
                metric_id="spatial.gi_star",
                value=9,
                geometry=_square(116.0032, 39.0017),
                p_value=0.01,
                z_score=2.8,
                cluster_type="hotspot",
            ),
        ]
    )
    north_zone = next(zone for zone in local_patterns.zones if len(zone.cell_ids) == 2)
    assert local_patterns.evidence_state == "measured"
    assert north_zone.geometry["type"] in {"Polygon", "MultiPolygon"}

    entrances = [
        EntranceAnchor(
            entrance_id="entrance:north",
            geometry=mapping(Point(116.002, 39.004)),
            label="北入口",
            source_type="project_planned",
            source_ref="project:entrances",
        ),
        EntranceAnchor(
            entrance_id="entrance:south",
            geometry=mapping(Point(116.002, 39.000)),
            label="南入口",
            source_type="project_planned",
            source_ref="project:entrances",
        ),
    ]
    roads = [
        RoadSegmentRef(
            segment_id="road:north",
            geometry=mapping(LineString([(116.002, 39.004), (116.002, 39.002)])),
            integration=0.9,
            choice=0.95,
        ),
        RoadSegmentRef(
            segment_id="road:south",
            geometry=mapping(LineString([(116.002, 39.000), (116.002, 39.002)])),
            integration=0.2,
            choice=0.25,
        ),
        RoadSegmentRef(
            segment_id="road:east",
            geometry=mapping(LineString([(116.002, 39.002), (116.004, 39.002)])),
            integration=0.35,
            choice=0.3,
        ),
        RoadSegmentRef(
            segment_id="road:west",
            geometry=mapping(LineString([(116.000, 39.002), (116.002, 39.002)])),
            integration=0.4,
            choice=0.35,
        ),
    ]
    entrance_results = service.analyze_entrance_relations(
        entrances=entrances,
        road_segments=roads,
        hotspot_zones=local_patterns.zones,
    )
    north_entrance = next(item for item in entrance_results if item.entrance_id == "entrance:north")
    assert north_entrance.geometry == entrances[0].geometry
    assert north_entrance.source_type == "project_planned"
    assert north_zone.zone_id in north_entrance.nearby_hotspot_zone_ids
    assert north_entrance.snapped_road_segment_id == "road:north"

    destination = DestinationAnchor(
        destination_id="destination:daily-program",
        geometry=mapping(Point(116.002, 39.002)),
        destination_type="internal_program",
        source_ref="project:programs",
    )
    route = service.analyze_path_relations(
        entrances=entrances,
        destinations=[destination],
        pairs=[("entrance:north", "destination:daily-program")],
        road_segments=roads,
    )[0]
    assert route.geometry["type"] == "LineString"
    assert route.network_distance_m == 300.0
    assert route.detour_ratio and route.detour_ratio > 1
    assert "road:north" in route.road_segment_ids
    assert route.high_choice_overlap_ratio and route.high_choice_overlap_ratio > 0

    plan = {
        "catalog_version": "2.0.0",
        "decision_questions": [
            {
                "question_id": "question:daily-entrance",
                "text": "哪个方向、哪个入口最适合作为日常入口？",
                "decision_target": "entrance",
                "hypotheses": [
                    {
                        "hypothesis_id": "hypothesis:north",
                        "statement": "北侧连续热点和真实步行路径共同支持北入口。",
                        "disconfirming_condition": "入口计数或真实到达路径不支持北侧。",
                    },
                    {
                        "hypothesis_id": "hypothesis:south",
                        "statement": "南入口具有更低门槛的日常到达条件。",
                        "disconfirming_condition": "南侧路网和设施暴露弱于北侧。",
                    },
                ],
            }
        ],
        "entries": [
            {
                "plan_entry_id": "plan:route-detour",
                "metric_id": "road.walk_detour_ratio",
                "role": "primary",
                "decision_question_id": "question:daily-entrance",
                "hypothesis_ids": ["hypothesis:north", "hypothesis:south"],
                "planned_spatial_target": {"unit": "route", "source": "planned entrance-destination pairs", "runtime_parameters": []},
                "selection_reason": "真实步行路径能够直接改变入口推荐。",
                "expected_decision_use": "比较入口至日常目的地的路径效率。",
                "required_source_ids": ["current:dataset:road"],
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "",
            },
            {
                "plan_entry_id": "plan:local-hotspot",
                "metric_id": "spatial.gi_star",
                "role": "supporting",
                "decision_question_id": "question:daily-entrance",
                "hypothesis_ids": ["hypothesis:north"],
                "planned_spatial_target": {"unit": "hotspot_zone", "source": "significant H3 cells", "runtime_parameters": ["alpha", "neighbor_ring"]},
                "selection_reason": "用独立空间统计家族定位日常接触机会。",
                "expected_decision_use": "交叉印证入口方向。",
                "required_source_ids": ["current:dataset:poi"],
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "",
            },
            {
                "plan_entry_id": "plan:entrance-snap",
                "metric_id": "road.entrance_distance",
                "role": "diagnostic",
                "decision_question_id": "question:daily-entrance",
                "hypothesis_ids": [],
                "planned_spatial_target": {"unit": "entrance", "source": "project entrance anchors", "runtime_parameters": []},
                "selection_reason": "检查入口是否能可靠挂接步行路网。",
                "expected_decision_use": "诊断路径结论是否可用。",
                "required_source_ids": ["current:dataset:road"],
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "",
            },
            {
                "plan_entry_id": "plan:nightlight-excluded",
                "metric_id": "nightlight.mean",
                "role": "excluded",
                "decision_question_id": "question:daily-entrance",
                "hypothesis_ids": [],
                "planned_spatial_target": {"unit": "scope", "source": "project scope", "runtime_parameters": []},
                "selection_reason": "",
                "expected_decision_use": "",
                "required_source_ids": [],
                "activation": {"type": "always", "source_entry_ids": [], "rule": ""},
                "exclusion_reason": "全局夜光不能定位具体入口或真实步行路径。",
            },
        ],
    }
    attempts = [
        {
            "plan_entry_id": "plan:route-detour",
            "metric_id": "road.walk_detour_ratio",
            "spatial_target": {"unit": "route", "target_id": route.route_id},
            "execution_status": "succeeded",
            "reason": "",
            "evidence_node_ids": ["evidence:route:north"],
        },
        {
            "plan_entry_id": "plan:local-hotspot",
            "metric_id": "spatial.gi_star",
            "spatial_target": {"unit": "hotspot_zone", "target_id": north_zone.zone_id},
            "execution_status": "succeeded",
            "reason": "",
            "evidence_node_ids": ["evidence:hotspot"],
        },
        {
            "plan_entry_id": "plan:entrance-snap",
            "metric_id": "road.entrance_distance",
            "spatial_target": {"unit": "entrance", "target_id": north_entrance.entrance_id},
            "execution_status": "succeeded",
            "reason": "",
            "evidence_node_ids": ["evidence:entrance:north"],
        },
    ]
    run = AnalysisRun.model_validate(
        {
            "run_id": "run:daily-entrance",
            "capability_id": "spatial-business-analyst",
            "catalog_version": "2.0.0",
            "source_versions": [
                {"source_id": "current:dataset:road", "year": 2024, "sha256": "sha256:road", "record_count": len(roads)},
                {"source_id": "current:dataset:poi", "year": 2024, "sha256": "sha256:poi", "record_count": 3},
            ],
            "decision_agenda": {
                "agenda_id": "agenda:daily-entrance",
                "user_question": "哪个入口适合作为日常入口？",
                "analysis_scope": "focused_diagnostic",
                "decision_questions": plan["decision_questions"],
            },
            "metric_plan": plan,
            "metric_attempts": attempts,
            "status": "completed",
            "created_at": "2026-07-16T00:00:00Z",
            "completed_at": "2026-07-16T00:05:00Z",
        }
    )
    assert {entry.role for entry in run.metric_plan.entries} == {"primary", "supporting", "diagnostic", "excluded"}
    assert {attempt.spatial_target.target_id for attempt in run.metric_attempts} == {
        route.route_id,
        north_zone.zone_id,
        north_entrance.entrance_id,
    }

    evidence = [
        {
            "id": "evidence:hotspot",
            "title": "北侧连续显著热点",
            "summary": "两个相邻显著单元形成连续热点区。",
            "method": "Gi* with BH FDR",
            "quality_flags": [],
        },
        {
            "id": "evidence:entrance:north",
            "title": "北入口路网关系",
            "summary": "北入口正式挂接北侧路段并邻近热点。",
            "method": "projected entrance-road relation",
            "quality_flags": [],
        },
        {
            "id": "evidence:route:north",
            "title": "北入口真实步行路径",
            "summary": "Valhalla 路径保留距离、时间、绕行率和句法重合。",
            "method": "Valhalla and depthmapX segment matching",
            "quality_flags": [],
        },
    ]
    finding = {
        "finding_id": "finding:daily-entrance",
        "decision_question_id": "question:daily-entrance",
        "observed_pattern": "北侧形成连续显著热点，北入口挂接高选择度路段且具有真实步行路径。",
        "evidence_ids": [item["id"] for item in evidence],
        "evidence_state": "inference",
        "mechanism_hypothesis": "北侧日常设施接触机会与路网路径条件共同提高日常到达可能性。",
        "project_implication": "优先把北入口作为日常入口测试对象。",
        "recommended_action": "先实施低门槛界面并布设入口计数，不创建不可解释的综合分。",
        "critical_assumption": "设施热点和路径条件能够转化为真实到达。",
        "disconfirming_test": "分时入口计数或轨迹观测不支持北入口。",
    }
    assert "confidence" not in finding
    assert finding["critical_assumption"] and finding["disconfirming_test"]

    assert run.decision_agenda.analysis_scope == "focused_diagnostic"
    assert finding["finding_id"] and finding["decision_question_id"] == "question:daily-entrance"
    assert not (tmp_path / "report" / "project-report.md").exists()
