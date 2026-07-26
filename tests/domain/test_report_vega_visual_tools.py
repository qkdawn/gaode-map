from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.svg_safety import validate_safe_svg
from modules.report_visuals.agent_tools import ReportVegaVisualTools
from modules.report_visuals.asset_store import ReportVegaVisualAssetStore
from modules.spatial_action.metric_result_registry import MetricResultRegistry


class _Projects:
    def read_history_project(self, history_id: str) -> dict:
        if history_id != "history-1":
            raise LookupError("history_not_found")
        return {"history_id": history_id}


def _supply_payload() -> dict:
    """A persisted poi.supply_structure result using its public tool contract."""
    return {
        "poi_supply_structure": {
            "status": "partial",
            "year": 2026,
            "source_id": "current:dataset:poi",
            "scope": {
                "kind": "verified_walking_isochrone",
                "time_min": 15,
                "mode": "walking",
                "geometry_source": "history.result_polygon_wgs84",
                "point_inclusion_method": "covers",
            },
            "five_minute_accessibility_status": "partial",
            "taxonomy_audit": {"source": "share/type_map.json", "unmapped_type_codes": [], "unmapped_poi_count": 0},
            "isochrone_audit": {"included_poi_count": 25, "outside_isochrone_poi_count": 0, "missing_coordinate_poi_count": 0, "invalid_coordinate_poi_count": 0},
            "groups": [
                {"group_id": "food", "title": "餐饮与轻饮", "role": "complementary_anchor", "statement_ref": "supply-1", "status": "available"},
                {"group_id": "culture", "title": "文化生活类对标", "role": "comparison_supply", "statement_ref": "supply-2", "status": "available"},
            ],
            "classified_rows": [
                {"role": "complementary_anchor", "main_category": "餐饮", "subcategory": "中餐厅", "isochrone_poi_count": 18, "nearby_5_min_poi_count": 6, "selected_type_codes": ["050100"], "source_group_ids": ["food"], "statement_refs": ["supply-1"]},
                {"role": "complementary_anchor", "main_category": "餐饮", "subcategory": "咖啡厅", "isochrone_poi_count": 4, "nearby_5_min_poi_count": 1, "selected_type_codes": ["050500"], "source_group_ids": ["food"], "statement_refs": ["supply-1"]},
                {"role": "comparison_supply", "main_category": "科教文化", "subcategory": "博物馆", "isochrone_poi_count": 7, "nearby_5_min_poi_count": 2, "selected_type_codes": ["140100"], "source_group_ids": ["culture"], "statement_refs": ["supply-2"]},
            ],
        }
    }


def _result(*, result_id: str = "result-poi-supply", tool_id: str = "poi.supply_structure", payload: dict | None = None) -> dict:
    return {
        "resource_id": result_id,
        "resource_type": "analysis_result",
        "title": tool_id,
        "status": "available",
        "payload": {
            "tool_id": tool_id,
            "status": "available",
            "structured_result": payload or _supply_payload(),
        },
    }


def _plan(**overrides: object) -> dict:
    item = {
        "template_id": "poi_supply_structure",
        "statement_ref": "supply-decision-02",
        "chapter_anchor": "<!-- report-anchor:poi-supply-structure -->",
        "metric_ids": ["poi.supply_structure"],
        "metric_result_ids": ["result-poi-supply"],
        "supports_judgment": "用于对比项目所需配套与同类对标的现状供给。",
        "does_not_prove": "不证明客流、消费、合作或市场规模。",
        "selection_reason": "删除图表会削弱相邻的供给结构判断。",
        "template_input": {},
    }
    item.update(overrides)
    return {"schema_version": "report-visual-plan.v1", "run_id": "wave5-01", "items": [item]}


def _tools(tmp_path: Path, items: list[dict] | None = None) -> ReportVegaVisualTools:
    registry = MetricResultRegistry()
    for item in items or [_result()]:
        payload = item["payload"]
        registry.register(
            history_id="history-1",
            result_id=item["resource_id"],
            tool_id=payload["tool_id"],
            status=payload["status"],
            structured_result=payload["structured_result"],
            time_scope=item.get("time_scope") or {},
        )
    return ReportVegaVisualTools(
        project_service=_Projects(),
        result_registry=registry,
        asset_store=ReportVegaVisualAssetStore(tmp_path / "bundles"),
    )


def test_catalog_only_exposes_approved_templates_and_minimal_inputs(tmp_path: Path) -> None:
    catalog = _tools(tmp_path).template_catalog()
    templates = {item["template_id"]: item for item in catalog["result"]["templates"]}

    assert "poi_supply_structure" in templates
    assert templates["population_supply_context"]["required_metric_ids"] == ["population.age_structure", "poi.supply_structure"]
    assert templates["poi_supply_structure"]["required_metric_ids"] == ["poi.supply_structure"]
    assert templates["poi_supply_structure"]["allowed_template_input_keys"] == []
    assert templates["directional_action_priority_matrix"]["allowed_template_input_keys"] == ["editorial_actions"]
    assert "focused_poi_walking_accessibility" not in templates
    assert "complementary_poi_walking_accessibility" not in templates
    assert "comparison_poi_walking_accessibility" not in templates
    # The catalog may identify its constrained renderer, but it must not expose
    # a user-supplied spec/SVG/payload field on any selectable template.
    assert all("spec" not in item and "svg" not in item and "raw_metric" not in item for item in templates.values())


def test_render_resolves_same_session_result_without_analysis_run_and_exposes_safe_resources(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    response = tools.render(
        history_id="history-1",
        report_id="report-1",
        report_markdown="# 决策报告\n\nPOI 供给判断。\n\n<!-- report-anchor:poi-supply-structure -->\n",
        visual_plan=_plan(),
    )

    result = response["result"]
    assert result["report_resource_uri"] == "report-vega-report://history-1/report-1"
    assert result["visual_plan_resource_uri"] == "report-vega-visual-plan://history-1/report-1"
    assert result["visual_manifest_resource_uri"] == "report-vega-visual-manifest://history-1/report-1"
    assert "证据结果：`result-poi-supply`" in tools.read_report(
        history_id="history-1", report_id="report-1"
    )
    assert result["assets"] == [
        {
            "asset_id": "poi_supply_structure",
            "template_id": "poi_supply_structure",
            "title": "15 分钟等时圈内的 POI 供给结构（2026）",
            "resource_uri": "report-vega-visual://history-1/report-1/poi_supply_structure",
        }
    ]

    report = tools.read_report(history_id="history-1", report_id="report-1")
    assert "assets/poi-supply-structure.svg" in report
    assert "report-visual:poi_supply_structure:start" in report
    svg = tools.read_asset(history_id="history-1", report_id="report-1", asset_id="poi_supply_structure")
    validate_safe_svg(svg)
    assert "项目所需配套" in svg and "同类对标供给" in svg

    plan = json.loads(tools.read_plan(history_id="history-1", report_id="report-1"))
    assert plan["items"][0]["statement_ref"] == "supply-decision-02"
    assert plan["items"][0]["metric_result_ids"] == ["result-poi-supply"]
    manifest = tools.read_manifest(history_id="history-1", report_id="report-1")["result"]["visual_manifest"]
    item = manifest["items"][0]
    assert item["asset_id"] == "poi_supply_structure"
    assert item["metric_result_ids"] == ["result-poi-supply"]
    assert item["resource_uri"] == "report-vega-visual://history-1/report-1/poi_supply_structure"
    assert "report_path" not in json.dumps(manifest, ensure_ascii=False)


def test_render_rejects_foreign_or_mismatched_metric_result_ids(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    with pytest.raises(ValueError, match="visual_metric_result_not_found"):
        tools.render(
            history_id="history-1",
            report_id="report-1",
            report_markdown="<!-- report-anchor:poi-supply-structure -->",
            visual_plan=_plan(metric_result_ids=["result-from-another-history"]),
        )

    mismatched = _tools(tmp_path, [_result(tool_id="population.age_structure")])
    with pytest.raises(ValueError, match="visual_metric_result_tool_mismatch"):
        mismatched.render(
            history_id="history-1",
            report_id="report-1",
            report_markdown="<!-- report-anchor:poi-supply-structure -->",
            visual_plan=_plan(),
        )


def test_render_rejects_free_specs_and_missing_editorial_audit_fields(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    bad_spec = _plan(template_input={"spec": {"mark": "bar"}})
    with pytest.raises(ValueError, match="template_input_forbidden"):
        tools.render(
            history_id="history-1",
            report_id="report-1",
            report_markdown="<!-- report-anchor:poi-supply-structure -->",
            visual_plan=bad_spec,
        )

    foreign_registry = MetricResultRegistry()
    item = _result()
    foreign_registry.register(
        history_id="history-2",
        result_id=item["resource_id"],
        tool_id=item["payload"]["tool_id"],
        status="available",
        structured_result=item["payload"]["structured_result"],
    )
    foreign = ReportVegaVisualTools(
        project_service=_Projects(),
        result_registry=foreign_registry,
        asset_store=ReportVegaVisualAssetStore(tmp_path / "foreign-bundles"),
    )
    with pytest.raises(ValueError, match="visual_metric_result_not_found"):
        foreign.render(
            history_id="history-1",
            report_id="report-1",
            report_markdown="<!-- report-anchor:poi-supply-structure -->",
            visual_plan=_plan(),
        )


    missing_ref = _plan()
    del missing_ref["items"][0]["statement_ref"]
    with pytest.raises(ValueError, match="requires_statement_ref"):
        tools.render(
            history_id="history-1",
            report_id="report-1",
            report_markdown="<!-- report-anchor:poi-supply-structure -->",
            visual_plan=missing_ref,
        )


def test_missing_anchor_omits_visual_without_breaking_report_or_asset_access(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    response = tools.render(
        history_id="history-1",
        report_id="report-1",
        report_markdown="# 没有锚点\n",
        visual_plan=_plan(),
    )

    assert response["result"]["assets"] == []
    assert response["result"]["omitted"][0]["template_id"] == "poi_supply_structure"
    assert "没有锚点" in tools.read_report(history_id="history-1", report_id="report-1")
    with pytest.raises(LookupError, match="report_vega_visual_asset_not_found"):
        tools.read_asset(history_id="history-1", report_id="report-1", asset_id="poi_supply_structure")
