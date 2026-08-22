import asyncio

import modules.agent.tool_adapters.business_tools as business_tools
import modules.agent.tool_adapters.h3_tools as h3_tools
import modules.agent.tool_adapters.road_tools as road_tools
import modules.agent.tool_adapters.scenario_tools as scenario_tools
from modules.agent.schemas import AnalysisSnapshot, ToolResult


def _snapshot_with_scope() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        scope={
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        }
    )


def _snapshot_with_reusable_site_selection_base() -> AnalysisSnapshot:
    snapshot = _snapshot_with_scope()
    snapshot.h3 = {"summary": {"grid_count": 4, "poi_count": 2}}
    snapshot.frontend_analysis = {
        "h3": {
            "derived_stats": {
                "gapSummary": {
                    "opportunityCount": 1,
                    "rows": [
                        {
                            "h3_id": "h3-1",
                            "gap_zone_label": "高需求低供给",
                            "gap_score": 0.56,
                            "demand_pct": 0.8,
                            "supply_pct": 0.2,
                        }
                    ],
                },
            },
            "target_category_label": "咖啡店",
        }
    }
    return snapshot


def _snapshot_with_h3_cells_for_gap() -> AnalysisSnapshot:
    snapshot = _snapshot_with_scope()
    snapshot.h3 = {
        "summary": {"grid_count": 3, "poi_count": 30},
        "poi_h3_evidence": {
            "evidence_version": "poi_h3_evidence_v1",
            "category_meta": [
                {"key": "group-7", "label": "餐饮"},
                {"key": "group-4", "label": "商务住宅"},
                {"key": "group-3", "label": "交通"},
                {"key": "group-13", "label": "科教文化"},
                {"key": "group-10", "label": "医疗"},
            ],
            "ui": {"target_category": "group-7", "target_category_label": "餐饮"},
            "cells": [
                {
                    "h3_id": "h3-gap",
                    "poi_count": 10,
                    "density_poi_per_km2": 100,
                    "category_counts": {
                        "group-7": 0,
                        "group-4": 4,
                        "group-3": 4,
                        "group-13": 1,
                        "group-10": 1,
                    },
                    "subcategory_counts": {"type-050700": 0},
                },
                {
                    "h3_id": "h3-balanced",
                    "poi_count": 10,
                    "density_poi_per_km2": 80,
                    "category_counts": {
                        "group-7": 5,
                        "group-4": 2,
                        "group-3": 1,
                        "group-13": 1,
                        "group-10": 1,
                    },
                    "subcategory_counts": {"type-050700": 5},
                },
            ],
        },
    }
    return snapshot


def test_run_business_site_advice_chains_l1_tools(monkeypatch):
    calls = []

    async def fake_fetch(*, arguments, snapshot, artifacts, question):
        del snapshot, question
        calls.append(("poi", dict(arguments)))
        assert arguments["keywords"] == "咖啡厅"
        return ToolResult(
            tool_name="fetch_pois_in_scope",
            status="success",
            result={"poi_count": 2},
            artifacts={
                "current_pois": [{"id": "coffee-1"}, {"id": "coffee-2"}],
                "current_poi_summary": {"total": 2, "types": arguments["types"], "keywords": arguments["keywords"]},
            },
        )

    async def fake_h3(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        calls.append(("h3", {"poi_count": len(artifacts.get("current_pois") or [])}))
        return ToolResult(
            tool_name="compute_h3_metrics_from_scope_and_pois",
            status="success",
            result={"grid_count": 4, "poi_count": 2},
            artifacts={"current_poi_h3_summary": {"grid_count": 4, "avg_density_poi_per_km2": 1.5}},
        )

    async def fake_population(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        calls.append(("population", {}))
        return ToolResult(
            tool_name="compute_population_overview_from_scope",
            status="success",
            artifacts={"current_population_summary": {"total_population": 1000}},
        )

    async def fake_nightlight(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        calls.append(("nightlight", {}))
        return ToolResult(
            tool_name="compute_nightlight_overview_from_scope",
            status="success",
            artifacts={"current_nightlight_summary": {"max_radiance": 6.0}},
        )

    async def fake_road(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        calls.append(("road", {}))
        return ToolResult(
            tool_name="compute_road_syntax_from_scope",
            status="success",
            artifacts={"current_road_summary": {"node_count": 5, "edge_count": 6}},
        )

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fake_fetch)
    monkeypatch.setattr(business_tools, "compute_h3_metrics_from_scope_and_pois", fake_h3)
    monkeypatch.setattr(business_tools, "compute_population_overview_from_scope", fake_population)
    monkeypatch.setattr(business_tools, "compute_nightlight_overview_from_scope", fake_nightlight)
    monkeypatch.setattr(business_tools, "compute_road_syntax_from_scope", fake_road)

    snapshot = _snapshot_with_scope()
    artifacts = {"scope_polygon": snapshot.scope["polygon"]}

    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={},
            snapshot=snapshot,
            artifacts=artifacts,
            question="我想在这里开一家咖啡店，给我建议",
        )
    )

    assert result.status == "success"
    assert [name for name, _args in calls] == ["poi", "h3", "population", "nightlight", "road"]
    assert result.artifacts["business_site_advice"]["place_type"] == "咖啡厅"
    assert result.artifacts["current_poi_summary"]["total"] == 2
    assert result.artifacts["current_poi_h3_summary"]["grid_count"] == 4
    assert result.artifacts["current_population_summary"]["total_population"] == 1000
    assert result.artifacts["current_nightlight_summary"]["max_radiance"] == 6.0
    assert result.artifacts["current_road_summary"]["node_count"] == 5


def test_run_business_site_advice_reuses_ready_snapshot_before_local_fetch(monkeypatch):
    async def fail_fetch(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        raise AssertionError("local POI fetch should not run when current H3 gap evidence is ready")

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fail_fetch)

    snapshot = _snapshot_with_reusable_site_selection_base()
    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={"place_type": "咖啡店"},
            snapshot=snapshot,
            artifacts={
                "scope_polygon": snapshot.scope["polygon"],
                "current_poi_h3_summary": snapshot.h3["summary"],
                "current_frontend_analysis": snapshot.frontend_analysis,
            },
            question="分析适合开在哪里",
        )
    )

    assert result.status == "success"
    assert result.artifacts["business_site_advice"]["reused_current_results"] is True
    assert result.result["place_type"] == "咖啡厅"
    assert result.result["h3_grid_count"] == 4


def test_run_business_site_advice_reuses_h3_cells_to_build_gap(monkeypatch):
    async def fail_fetch(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        raise AssertionError("local POI fetch should not run when H3 category cells can build gap evidence")

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fail_fetch)

    snapshot = _snapshot_with_h3_cells_for_gap()
    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={"place_type": "奶茶店"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"], "current_poi_h3_summary": snapshot.h3["summary"]},
            question="分析适合开在哪里",
        )
    )

    assert result.status == "success"
    assert result.artifacts["business_site_advice"]["reused_current_results"] is True


def test_run_business_site_advice_does_not_reuse_broad_category_for_small_type(monkeypatch):
    async def fail_fetch(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(tool_name="fetch_pois_in_scope", status="failed", error="expected_small_type_fetch")

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fail_fetch)

    snapshot = _snapshot_with_h3_cells_for_gap()
    for cell in snapshot.h3["poi_h3_evidence"]["cells"]:
        cell.pop("subcategory_counts", None)
    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={"place_type": "奶茶店"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"], "current_poi_h3_summary": snapshot.h3["summary"]},
            question="分析适合开在哪里",
        )
    )

    assert result.status == "failed"
    assert result.error == "expected_small_type_fetch"


def test_run_business_site_advice_requires_resolved_place_type():
    snapshot = _snapshot_with_scope()
    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={"place_type": "不存在的业态"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"]},
            question="我想在这里开一家不存在的业态",
        )
    )

    assert result.status == "failed"
    assert result.error == "unresolved_place_type"


def test_run_business_site_advice_infers_target_from_descriptive_place_type(monkeypatch):
    async def fake_fetch(*, arguments, snapshot, artifacts, question):
        del snapshot, artifacts, question
        return ToolResult(
            tool_name="fetch_pois_in_scope",
            status="success",
            artifacts={
                "current_pois": [],
                "current_poi_summary": {"total": 0, "types": arguments["types"], "keywords": arguments["keywords"]},
            },
        )

    async def fake_h3(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="compute_h3_metrics_from_scope_and_pois",
            status="success",
            artifacts={"current_poi_h3_summary": {"grid_count": 1, "poi_count": 0}},
        )

    async def fake_optional(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(tool_name="optional", status="success")

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fake_fetch)
    monkeypatch.setattr(business_tools, "compute_h3_metrics_from_scope_and_pois", fake_h3)
    monkeypatch.setattr(business_tools, "compute_population_overview_from_scope", fake_optional)
    monkeypatch.setattr(business_tools, "compute_nightlight_overview_from_scope", fake_optional)
    monkeypatch.setattr(business_tools, "compute_road_syntax_from_scope", fake_optional)

    snapshot = _snapshot_with_scope()
    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={"place_type": "咖啡店选址"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"]},
            question="分析适合开在哪里",
        )
    )

    assert result.status == "success"
    assert result.result["place_type"] == "咖啡厅"


def test_run_business_site_advice_degrades_optional_tool_failure(monkeypatch):
    async def fake_fetch(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="fetch_pois_in_scope",
            status="success",
            artifacts={"current_pois": [{"id": "coffee-1"}], "current_poi_summary": {"total": 1, "keywords": "咖啡厅"}},
        )

    async def fake_h3(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="compute_h3_metrics_from_scope_and_pois",
            status="success",
            artifacts={"current_poi_h3_summary": {"grid_count": 2, "avg_density_poi_per_km2": 0.5}},
        )

    async def fake_failed(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(tool_name="compute_population_overview_from_scope", status="failed", error="boom")

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fake_fetch)
    monkeypatch.setattr(business_tools, "compute_h3_metrics_from_scope_and_pois", fake_h3)
    monkeypatch.setattr(business_tools, "compute_population_overview_from_scope", fake_failed)
    monkeypatch.setattr(business_tools, "compute_nightlight_overview_from_scope", fake_failed)
    monkeypatch.setattr(business_tools, "compute_road_syntax_from_scope", fake_failed)

    snapshot = _snapshot_with_scope()
    result = asyncio.run(
        business_tools.run_business_site_advice(
            arguments={"place_type": "咖啡店"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"]},
            question="我想开咖啡店",
        )
    )

    assert result.status == "success"
    assert any("已降级继续" in warning for warning in result.warnings)


def test_compute_h3_metrics_uses_keyword_arguments(monkeypatch):
    seen = {}

    def fake_analyze_h3_grid(**kwargs):
        seen.update(kwargs)
        return {
            "grid": {"type": "FeatureCollection", "features": [], "count": 0},
            "summary": {"grid_count": 0, "poi_count": 0, "avg_density_poi_per_km2": 0.0},
            "charts": {},
        }

    monkeypatch.setattr(h3_tools, "analyze_h3_grid", fake_analyze_h3_grid)

    snapshot = _snapshot_with_scope()
    result = asyncio.run(
        h3_tools.compute_h3_metrics_from_scope_and_pois(
            arguments={"resolution": 10, "neighbor_ring": 1},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"], "current_pois": []},
            question="计算 H3",
        )
    )

    assert result.status == "success"
    assert seen["polygon"] == snapshot.scope["polygon"]
    assert seen["arcgis_timeout_sec"] == 240
    assert "progress_callback" not in seen


def test_compute_road_syntax_uses_keyword_arguments(monkeypatch):
    seen = {}

    def fake_analyze_road_syntax(**kwargs):
        seen.update(kwargs)
        return {"summary": {"node_count": 0, "edge_count": 0, "avg_choice": None}}

    monkeypatch.setattr(road_tools, "analyze_road_syntax", fake_analyze_road_syntax)

    snapshot = _snapshot_with_scope()
    result = asyncio.run(
        road_tools.compute_road_syntax_from_scope(
            arguments={"mode": "walking"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"]},
            question="计算路网",
        )
    )

    assert result.status == "success"
    assert seen["polygon"] == snapshot.scope["polygon"]
    assert seen["arcgis_timeout_sec"] == 60
    assert "progress_callback" not in seen


def test_run_area_character_pack_returns_tags_and_evidence_chain(monkeypatch):
    async def fake_bundle(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="get_area_data_bundle",
            status="success",
            artifacts={
                "scope_polygon": [[112.98, 28.19], [112.99, 28.19], [112.99, 28.20], [112.98, 28.20], [112.98, 28.19]],
                "current_poi_summary": {"total": 120},
                "current_population_summary": {"total_population": 22000},
                "current_nightlight_summary": {"total_radiance": 1300},
                "current_road_summary": {"node_count": 1800, "edge_count": 1900},
            },
        )

    async def fake_poi(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="analyze_poi_structure",
            status="success",
            artifacts=artifacts,
            result={"business_profile": "生活消费主导"},
        )

    async def fake_spatial(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(tool_name="analyze_spatial_structure", status="success", artifacts=artifacts, result={"distribution_pattern": "single_core"})

    async def fake_facts(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="build_area_facts",
            status="success",
            result={
                "poi": {"top_categories": [{"category": "餐饮", "count": 40, "ratio": 0.35}]},
                "population": {"total_population": 22000},
                "road": {"node_count": 1800},
            },
        )

    monkeypatch.setattr(scenario_tools, "get_area_data_bundle", fake_bundle)
    monkeypatch.setattr(scenario_tools, "analyze_poi_structure", fake_poi)
    monkeypatch.setattr(scenario_tools, "analyze_spatial_structure", fake_spatial)
    monkeypatch.setattr(scenario_tools, "build_area_facts", fake_facts)
    monkeypatch.setattr(
        scenario_tools,
        "build_poi_structure_analysis",
        lambda snapshot, artifacts: {"dominant_categories": ["餐饮"], "dining_ratio": 0.35, "evidence_ready": True},
    )
    monkeypatch.setattr(
        scenario_tools,
        "analyze_poi_mix",
        lambda snapshot, artifacts, poi_structure: {"business_profile": "生活消费主导", "dominant_functions": ["餐饮", "购物"]},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_population_profile_analysis",
        lambda snapshot, artifacts: {"top_age_band": "25-34岁", "total_population": 22000},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_nightlight_pattern_analysis",
        lambda snapshot, artifacts: {"core_hotspot_count": 2},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_road_pattern_analysis",
        lambda snapshot, artifacts: {"node_count": 1800},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_area_character_facts",
        lambda snapshot, artifacts, **kwargs: {
            "poi": {"top_categories": [{"category": "餐饮", "count": 40, "ratio": 0.35}]},
            "population": {"total_population": 22000},
            "road": {"node_count": 1800},
        },
    )

    result = asyncio.run(
        scenario_tools.run_area_fact_pack(
            arguments={"policy_key": "district_summary"},
            snapshot=_snapshot_with_scope(),
            artifacts={"scope_polygon": _snapshot_with_scope().scope["polygon"]},
            question="总结这个区域的商业特征",
        )
    )

    assert result.status == "success"
    assert result.result["facts"]["population"]["total_population"] == 22000
    assert result.result["facts"]["road"]["node_count"] == 1800
    assert "character_tags" not in result.result
    assert "confidence" not in result.result
    assert "evidence_chain" not in result.result


def test_run_site_selection_pack_returns_candidate_facts(monkeypatch):
    async def fake_business(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="run_business_site_advice",
            status="success",
            result={"place_type": "咖啡厅", "poi_count": 5},
            artifacts={**artifacts, "current_poi_summary": {"total": 5}},
        )

    async def fake_gap(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="analyze_target_supply_gap",
            status="success",
            result={"place_type": "咖啡厅", "candidate_zones": [{"display_title": "候选：人民路附近", "approx_address": "人民路附近"}]},
        )

    monkeypatch.setattr(scenario_tools, "run_business_site_advice", fake_business)
    monkeypatch.setattr(scenario_tools, "analyze_target_supply_gap_from_scope", fake_gap)
    monkeypatch.setattr(
        scenario_tools,
        "build_population_profile_analysis",
        lambda snapshot, artifacts: {"total_population": 20000, "density_level": "medium"},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_nightlight_pattern_analysis",
        lambda snapshot, artifacts: {"core_hotspot_count": 2, "peak_to_edge_ratio": 2.2},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_road_pattern_analysis",
        lambda snapshot, artifacts: {"node_count": 1800, "edge_count": 1900},
    )
    monkeypatch.setattr(
        scenario_tools,
        "build_site_candidate_facts",
        lambda snapshot, artifacts, **kwargs: {
            "candidate_count": 1,
            "candidate_sites": [{
                "source_order": 1,
                "display_title": "候选：人民路附近",
                "supply_demand": {"gap_value": 0.3, "demand_share": 0.6, "supply_share": 0.3},
            }],
        },
    )

    result = asyncio.run(
        scenario_tools.run_site_selection_pack(
            arguments={"place_type": "咖啡厅", "policy_key": "business_catchment_1km"},
            snapshot=_snapshot_with_scope(),
            artifacts={"scope_polygon": _snapshot_with_scope().scope["polygon"]},
            question="我想在这里开一家咖啡店，给我建议",
        )
    )

    assert result.status == "success"
    assert result.result["candidate_sites"][0]["display_title"] == "候选：人民路附近"
    assert result.result["candidate_sites"][0]["supply_demand"]["gap_value"] == 0.3
    assert "ranking" not in result.result
    assert "confidence" not in result.result


def test_run_site_selection_pack_injects_scope_from_snapshot(monkeypatch):
    seen = {}

    async def fake_business(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        seen["scope_polygon"] = artifacts.get("scope_polygon")
        return ToolResult(
            tool_name="run_business_site_advice",
            status="success",
            result={"place_type": "咖啡厅", "poi_count": 5},
            artifacts={**artifacts, "current_poi_summary": {"total": 5}},
        )

    async def fake_gap(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="analyze_target_supply_gap",
            status="success",
            result={"place_type": "咖啡厅", "candidate_zones": []},
        )

    monkeypatch.setattr(scenario_tools, "run_business_site_advice", fake_business)
    monkeypatch.setattr(scenario_tools, "analyze_target_supply_gap_from_scope", fake_gap)

    snapshot = _snapshot_with_scope()
    result = asyncio.run(
        scenario_tools.run_site_selection_pack(
            arguments={"place_type": "咖啡厅", "policy_key": "business_catchment_1km"},
            snapshot=snapshot,
            artifacts={},
            question="我想在这里开一家咖啡店，给我建议",
        )
    )

    assert result.status == "success"
    assert seen["scope_polygon"] == snapshot.scope["polygon"]


def test_run_site_selection_pack_uses_resolved_place_type_for_gap(monkeypatch):
    seen = {}

    async def fake_business(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, question
        return ToolResult(
            tool_name="run_business_site_advice",
            status="success",
            result={"place_type": "咖啡厅", "poi_count": 0},
            artifacts=artifacts,
        )

    async def fake_gap(*, arguments, snapshot, artifacts, question):
        del snapshot, artifacts, question
        seen["place_type"] = arguments.get("place_type")
        return ToolResult(
            tool_name="analyze_target_supply_gap",
            status="success",
            result={"place_type": arguments.get("place_type"), "candidate_zones": []},
        )

    monkeypatch.setattr(scenario_tools, "run_business_site_advice", fake_business)
    monkeypatch.setattr(scenario_tools, "analyze_target_supply_gap_from_scope", fake_gap)

    result = asyncio.run(
        scenario_tools.run_site_selection_pack(
            arguments={"place_type": "咖啡店选址", "policy_key": "business_catchment_1km"},
            snapshot=_snapshot_with_scope(),
            artifacts={"scope_polygon": _snapshot_with_scope().scope["polygon"]},
            question="分析适合开在哪里",
        )
    )

    assert result.status == "success"
    assert seen["place_type"] == "咖啡厅"
    assert result.result["place_type"] == "咖啡厅"


def test_run_site_selection_pack_hides_required_tool_exception_codes(monkeypatch):
    async def fake_business(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(
            tool_name="run_business_site_advice",
            status="failed",
            warnings=["Local query failed"],
            error="ValueError",
        )

    monkeypatch.setattr(scenario_tools, "run_business_site_advice", fake_business)

    result = asyncio.run(
        scenario_tools.run_site_selection_pack(
            arguments={"place_type": "咖啡厅", "policy_key": "business_catchment_1km"},
            snapshot=_snapshot_with_scope(),
            artifacts={"scope_polygon": _snapshot_with_scope().scope["polygon"]},
            question="分析适合开在哪里",
        )
    )

    assert result.status == "failed"
    assert result.error == "site_selection_base_failed"


def test_run_site_selection_pack_builds_candidates_from_h3_cells(monkeypatch):
    async def fail_fetch(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        raise AssertionError("local POI fetch should not run when reusable H3 cells are present")

    monkeypatch.setattr(business_tools, "fetch_pois_in_scope", fail_fetch)

    snapshot = _snapshot_with_h3_cells_for_gap()
    result = asyncio.run(
        scenario_tools.run_site_selection_pack(
            arguments={"place_type": "奶茶店", "policy_key": "business_catchment_1km"},
            snapshot=snapshot,
            artifacts={"scope_polygon": snapshot.scope["polygon"]},
            question="分析适合开在哪里",
        )
    )

    assert result.status == "success"
    candidates = result.artifacts["site_selection_pack"]["candidate_sites"]
    assert candidates
    assert candidates[0]["h3_id"] == "h3-gap"
