from __future__ import annotations

from typing import Any, Mapping

from modules.spatial_action.metric_tools import (
    MetricCatalogItem,
    MetricCompareBy,
    MetricDetail,
    MetricInterpretWith,
    MetricMeasures,
    MetricResult,
    MetricUseFor,
    MetricWatchOut,
)
from modules.spatial_action.source_index import SourceIndexItem
from modules.spatial_projects.skill_tools import SpatialBusinessSkillTools
from modules.spatial_projects.visual_asset_store import SpatialReportVisualAssetStore


_ENVELOPE_KEYS = {
    "status",
    "result",
    "evidence",
    "artifacts",
    "warnings",
    "limitations",
    "spatial_scope",
    "time_scope",
    "method",
    "comparison_basis",
}
_FORBIDDEN_SEMANTIC_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bridge",
    "bridge_url",
    "connection",
    "connection_string",
    "database",
    "db",
    "engine",
    "file_path",
    "host",
    "password",
    "path",
    "renderer",
    "secret",
    "token",
    "url",
    "coordinates",
    "features",
    "geometry",
    "polygon",
    "polygon_wgs84",
}


def _catalog_item() -> MetricCatalogItem:
    return MetricCatalogItem(
        tool_id="poi.grid_density",
        name="POI 网格密度",
        purpose="识别候选区域的设施密度。",
        question_tags=["设施供给"],
        primary_spatial_unit="H3 网格",
        action_targets=["候选门店"],
        implementation_status="implemented",
    )


def _metric_detail() -> MetricDetail:
    return MetricDetail(
        tool_id="poi.grid_density",
        name="POI 网格密度",
        measures=MetricMeasures(
            definition="每个网格内的 POI 数量。",
            unit="个/网格",
            outputs=["网格密度"],
            calculation="POI count / H3 cell",
            spatial_units=["H3 网格"],
            time_semantics="使用选定数据快照。",
            method_version="test-v1",
        ),
        use_for=MetricUseFor(decision_questions=["哪里供给较强？"], action_targets=["候选门店"]),
        compare_by=MetricCompareBy(
            candidate_targets="候选门店",
            area_units="同级 H3 网格",
            normalization="相同口径",
            consistency_rules=["使用相同数据年份。"],
        ),
        interpret_with=MetricInterpretWith(combinations=["结合人口栅格"], conflict_prompts=["核查营业状态"]),
        watch_out=MetricWatchOut(risks=["分类覆盖不足"], field_checks=["抽样复核"]),
        unavailable_semantics="缺少数据时明确返回 unavailable。",
        asset_types=["svg"],
    )


class FakeSpatialProjectService:
    def __init__(self, project: Mapping[str, Any] | None = None) -> None:
        self.project = dict(project or _history_project())
        self.read_history_ids: list[str] = []

    def read_history_project(self, history_id: str) -> dict[str, Any]:
        self.read_history_ids.append(history_id)
        if history_id != "history-001":
            raise LookupError(history_id)
        return self.project


class FakeMetricToolService:
    def __init__(self) -> None:
        self.catalog_item = _catalog_item()
        self.detail_item = _metric_detail()
        self.execute_calls: list[dict[str, Any]] = []

    def catalog(self) -> list[MetricCatalogItem]:
        return [self.catalog_item]

    def detail(self, tool_id: str) -> MetricDetail:
        assert tool_id == self.catalog_item.tool_id
        return self.detail_item

    def execute(self, **kwargs: Any) -> MetricResult:
        self.execute_calls.append(kwargs)
        return MetricResult(
            result_id="result:poi.grid_density:test",
            tool_id="poi.grid_density",
            tool_version="test-v1",
            status="available",
            summary="候选区域的设施供给较强。",
            structured_result={
                "density": 12.5,
                "token": "do-not-return",
                "renderer": {"name": "internal-map-renderer"},
                "geometry": {"type": "Polygon", "coordinates": [[[113.0, 28.0]]]},
                "project_internal_comparison": {
                    "comparison_design": "candidate_vs_baseline",
                    "baseline": "city-median",
                    "access_token": "do-not-return",
                    "polygon_wgs84": [[113.0, 28.0]],
                },
                "data_health": [
                    {
                        "source_id": "poi-snapshot",
                        "status": "limited",
                        "limitations": ["部分分类缺失"],
                        "geometry": {"coordinates": [[113.0, 28.0]]},
                    }
                ],
            },
            input_sources=["poi-snapshot", "document:brief-1"],
            spatial_scope={
                "primary_spatial_unit": "H3 网格",
                "polygon": [[113.0, 28.0]],
                "renderer": "internal-map-renderer",
            },
            time_scope={"year": 2024, "coordinates": [[113.0, 28.0]]},
            limitations=["需结合现场核验"],
            asset_ids=["asset:metric-map"],
        )


def _history_project() -> dict[str, Any]:
    return {
        "project_name": "测试选址项目",
        "description": "用于验证 skill tool 上下文装配。",
        "scope": {
            "coordinate_system": "WGS84",
            "center": [113.005, 28.005],
            "polygon": [
                [113.00, 28.00],
                [113.01, 28.00],
                [113.01, 28.01],
                [113.00, 28.00],
            ],
        },
        "documents": [
            {
                "document_id": "brief-1",
                "title": "项目简报",
                "document_role": "brief",
                "status": "available",
            }
        ],
        "datasets": [
            {
                "source_id": "poi-snapshot",
                "selected_year": 2024,
                "record_count": 18,
                "status": "available",
                "warnings": ["来源覆盖有限"],
            }
        ],
        "warnings": ["项目级提醒"],
    }


def _tools(
    project_service: FakeSpatialProjectService | None = None,
    metric_service: FakeMetricToolService | None = None,
) -> SpatialBusinessSkillTools:
    return SpatialBusinessSkillTools(
        project_service=project_service or FakeSpatialProjectService(),
        metric_service=metric_service or FakeMetricToolService(),
    )


def _assert_semantic_only(value: Any) -> None:
    if isinstance(value, Mapping):
        assert not ({str(key).lower() for key in value} & _FORBIDDEN_SEMANTIC_KEYS)
        for nested in value.values():
            _assert_semantic_only(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_semantic_only(nested)


def test_metric_catalog_returns_only_the_strict_semantic_envelope():
    result = _tools().metric_catalog()

    assert set(result) == _ENVELOPE_KEYS
    assert result["status"] == "available"
    assert result["result"] == {
        "metrics": [
            {
                "tool_id": "poi.grid_density",
                "name": "POI 网格密度",
                "purpose": "识别候选区域的设施密度。",
                "question_tags": ["设施供给"],
                "primary_spatial_unit": "H3 网格",
                "action_targets": ["候选门店"],
                "execution_status": "implemented",
            }
        ]
    }
    assert result["method"] == {
        "kind": "metric_catalog",
        "selection_rule": "Read metric_detail before execution.",
    }
    _assert_semantic_only(result)


def test_metric_detail_returns_unavailable_for_an_unknown_metric():
    metrics = FakeMetricToolService()

    result = _tools(metric_service=metrics).metric_detail("unknown.metric")

    assert set(result) == _ENVELOPE_KEYS
    assert result["status"] == "unavailable"
    assert result["result"] == {}
    assert result["limitations"] == ["指定的指标工具未注册。"]
    assert result["method"] == {"tool_id": "unknown.metric"}


def test_execute_metric_assembles_history_context_and_scrubs_nonsemantic_values():
    projects = FakeSpatialProjectService()
    metrics = FakeMetricToolService()
    parameters = {"radius_meters": 800}
    comparison_context = {"comparison_design": "candidate_vs_baseline", "baseline": "city-median"}

    result = _tools(projects, metrics).execute_metric(
        "history-001",
        "poi.grid_density",
        parameters=parameters,
        comparison_context=comparison_context,
    )

    assert len(metrics.execute_calls) == 1
    call = metrics.execute_calls[0]
    assert call["tool_id"] == "poi.grid_density"
    assert call["history_id"] == "history-001"
    assert call["parameters"] == parameters
    assert call["project_anchors"] == comparison_context
    assert call["history_detail"] == {
        "history_id": "history-001",
        "project_name": "测试选址项目",
        "description": "用于验证 skill tool 上下文装配。",
        "analysis_geometry": {
            "type": "Polygon",
            "coordinates": [[
                [113.0, 28.0],
                [113.01, 28.0],
                [113.01, 28.01],
                [113.0, 28.0],
            ]],
        },
            "polygon": [[113.0, 28.0], [113.01, 28.0], [113.01, 28.01], [113.0, 28.0]],
            "coordinate_system": "wgs84",
            "analysis_reference_point": [113.005, 28.005],
        }
    assert call["project_documents"] == {
        "project_name": "测试选址项目",
        "description": "用于验证 skill tool 上下文装配。",
        "documents": [
            {
                "source_id": "document:brief-1",
                "id": "brief-1",
                "title": "项目简报",
                "document_role": "brief",
                "status": "available",
                "extracts": [],
            }
        ],
    }

    assert {item.resource_id for item in call["source_index"].items} == {
        "document:brief-1",
        "dataset:poi-snapshot",
        "scope:analysis",
        "result:poi.grid_density:test",
    }

    assert set(result) == _ENVELOPE_KEYS
    assert result["status"] == "available"
    assert result["result"] == {
        "result_id": "result:poi.grid_density:test",
        "tool_id": "poi.grid_density",
        "summary": "候选区域的设施供给较强。",
        "data": {"density": 12.5},
    }
    assert result["comparison_basis"] == {
        "comparison_design": "candidate_vs_baseline",
        "baseline": "city-median",
    }
    assert result["spatial_scope"] == {"primary_spatial_unit": "H3 网格"}
    assert result["time_scope"] == {"year": 2024}
    assert result["warnings"] == ["项目级提醒", "来源覆盖有限", "poi-snapshot：数据健康状态为 limited。"]
    assert result["limitations"] == ["需结合现场核验"]
    assert result["artifacts"] == [
        {"artifact_id": "asset:metric-map", "status": "available", "summary": "已生成的指标工件。"}
    ]
    assert result["evidence"] == [
        {
            "evidence_id": "dataset:poi-snapshot",
            "kind": "dataset",
            "status": "available",
            "summary": "记录数：18",
            "spatial_scope": {},
            "time_scope": {"year": 2024},
            "limitations": [],
        },
        {
            "evidence_id": "document:brief-1",
            "kind": "project_material",
            "status": "available",
            "summary": "",
            "spatial_scope": {},
            "time_scope": {},
            "limitations": [],
        },
        {
            "evidence_id": "health:poi-snapshot",
            "kind": "data_health",
            "status": "limited",
            "summary": "数据健康状态。",
            "spatial_scope": {},
            "time_scope": {},
            "limitations": ["部分分类缺失"],
        },
    ]
    _assert_semantic_only(result)


def test_execute_metric_uses_history_params_center_when_scope_has_none():
    project = _history_project()
    project["scope"].pop("center")
    project["params"] = {"center": [113.005, 28.005], "coord_type": "wgs84"}
    metrics = FakeMetricToolService()

    _tools(FakeSpatialProjectService(project), metrics).execute_metric(
        "history-001",
        "poi.grid_density",
    )

    context = metrics.execute_calls[0]["history_detail"]
    assert context["params"] == project["params"]
    assert context["analysis_reference_point"] == [113.005, 28.005]


def test_execute_metric_returns_unavailable_when_history_project_is_missing():
    projects = FakeSpatialProjectService()
    metrics = FakeMetricToolService()

    result = _tools(projects, metrics).execute_metric("history-missing", "poi.grid_density")

    assert set(result) == _ENVELOPE_KEYS
    assert result["status"] == "unavailable"
    assert result["limitations"] == ["指定的分析历史不存在或当前不可读取。"]
    assert result["method"]["tool_id"] == "poi.grid_density"
    assert metrics.execute_calls == []



class FakeArcGISVisualTools:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_approved_visual_asset(self, *, visual_plan: Any, source_index: Any, history_detail: dict[str, Any]) -> SourceIndexItem:
        self.calls.append({
            "visual_plan": visual_plan,
            "source_index": source_index,
            "history_detail": history_detail,
        })
        return SourceIndexItem(
            resource_id="asset:visual:poi-road-map:test",
            resource_type="asset",
            title="设施与道路空间关系",
            status="available",
            summary="真实 POI 与路网位置关系图已生成。",
            source_ids=list(visual_plan.required_result_ids),
            spatial_scope={"unit": "H3 网格", "geometry": {"type": "Polygon"}},
            time_scope={"year": 2024},
            limitations=["空间共位不等同于真实客流。"],
            payload={
                "filename": "asset-visual-poi-road-map-test.svg",
                "svg": '<svg xmlns="http://www.w3.org/2000/svg"><title>ArcGIS visual</title><rect width="10" height="10"/></svg>',
                "visual_manifest": {
                    "schema_version": "1.0", "input_result_ids": list(visual_plan.required_result_ids),
                    "input_layer_manifest": [{
                        "layer_id": "layer:test", "required": True,
                        "normalized_feature_count": 1, "rendered_feature_count": 1,
                    }],
                    "input_feature_count": 1, "rendered_feature_count": 1,
                    "geometry_types": ["Point"], "bbox": [112.0, 28.0, 112.1, 28.1],
                    "crs": "EPSG:4326", "basemap_status": "approved",
                    "road_context_status": "not_provided", "legend_items": ["设施"],
                    "warnings": [], "quality_status": "passed", "pixel_quality": {"status": "passed"},
                },
            },
        )


def test_create_spatial_report_visual_only_accepts_prior_results_and_returns_safe_asset_metadata(tmp_path):
    projects = FakeSpatialProjectService()
    metrics = FakeMetricToolService()
    visuals = FakeArcGISVisualTools()
    tools = SpatialBusinessSkillTools(
        project_service=projects,
        metric_service=metrics,
        visual_tools=visuals,
        visual_asset_store=SpatialReportVisualAssetStore(tmp_path),
    )

    metric = tools.execute_metric("history-001", "poi.grid_density")
    result = tools.create_spatial_report_visual(
        "history-001",
        {
            "visual_id": "poi-road-map",
            "placement": "区域机会",
            "decision_question": "设施集中区是否靠近道路结构较强的区域？",
            "purpose": "解释 POI 与路网的空间关系。",
            "selection_rule": "使用同一分析范围内已完成的 POI 网格结果。",
            "required_result_ids": [metric["result"]["result_id"]],
            "input_snapshot_ids": ["snapshot:poi:test"],
            "what_it_shows": "分析范围内 POI 与道路的相对位置。",
            "how_to_read": "颜色表示 POI 密度，线表示道路背景。",
            "supports_judgment": "帮助确定优先踏勘的外部连接区域。",
            "does_not_prove": "不证明真实客流或消费。",
            "next_validation": "现场观察步行和停留情况。",
        },
    )

    assert len(visuals.calls) == 1
    call = visuals.calls[0]
    assert call["visual_plan"].status == "generated"
    assert call["visual_plan"].owner == "chief_analyst"
    assert call["visual_plan"].visual_semantics == "thematic_map"
    assert call["visual_plan"].required_result_ids == ["result:poi.grid_density:test"]
    assert call["visual_plan"].input_snapshot_ids == ["snapshot:poi:test"]
    assert call["history_detail"]["history_id"] == "history-001"
    assert call["history_detail"]["analysis_reference_point"] == [113.005, 28.005]
    assert result["status"] == "available"
    assert result["result"]["asset_id"] == "asset:visual:poi-road-map:test"
    assert result["result"]["filename"] == "asset-visual-poi-road-map-test.svg"
    assert result["result"]["resource_uri"] == "spatial-report-visual://history-001/asset:visual:poi-road-map:test"
    assert result["result"]["reader_guidance"]["does_not_prove"] == "不证明真实客流或消费。"
    assert result["artifacts"] == [{
        "artifact_id": "asset:visual:poi-road-map:test",
        "status": "available",
        "filename": "asset-visual-poi-road-map-test.svg",
        "resource_uri": "spatial-report-visual://history-001/asset:visual:poi-road-map:test",
        "summary": "真实 POI 与路网位置关系图已生成。",
    }]
    assert "asset:visual:poi-road-map:test" in {item.resource_id for item in call["source_index"].items}
    metadata = tools.get_spatial_report_visual_asset("history-001", "asset:visual:poi-road-map:test")
    assert metadata["result"]["filename"] == "asset-visual-poi-road-map-test.svg"
    assert tools.read_spatial_report_visual_asset("history-001", "asset:visual:poi-road-map:test").startswith("<svg")
    _assert_semantic_only(result)


def test_create_spatial_report_visual_refuses_unexecuted_result_ids():
    tools = _tools()

    result = tools.create_spatial_report_visual(
        "history-001",
        {
            "visual_id": "poi-road-map",
            "placement": "区域机会",
            "decision_question": "设施集中区是否靠近道路结构较强的区域？",
            "purpose": "解释 POI 与路网的空间关系。",
            "selection_rule": "只使用已完成结果。",
            "required_result_ids": ["result:missing"],
            "input_snapshot_ids": ["snapshot:poi:test"],
        },
    )

    assert result["status"] == "unavailable"
    assert result["limitations"] == ["visual_request_results_not_available:result:missing"]
