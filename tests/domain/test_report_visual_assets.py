from __future__ import annotations

import json

import pytest

from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule
from modules.spatial_action.metric_tools import MetricResult
from modules.spatial_action.source_index import SourceIndex, SourceIndexItem
from modules.spatial_action.visual_contracts import VisualPlanItem
from core.svg_safety import validate_safe_svg
from modules.scope_datasets.service import ScopeRecord
from modules.spatial_projects.query_snapshot_store import SpatialQuerySnapshotStore
from shapely.geometry import LineString, Point, Polygon
from store.analysis_run_storage import AnalysisRunStorage

SAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><title>ArcGIS visual</title><rect width="10" height="10"/></svg>'


class _Bridge:
    def __init__(self, *, available: bool = True, svg: str = SAFE_SVG, status: str = "available", quality_svg: str | None = None, manifest_overrides: dict | None = None) -> None:
        self.available = available
        self.svg = svg
        self.status = status
        self.quality_svg = quality_svg
        self.manifest_overrides = manifest_overrides or {}
        self.calls: list[dict] = []

    def capabilities(self) -> dict:
        templates = [
            ("chart.bar.v1", "report_chart"), ("chart.line.v1", "report_chart"),
            ("chart.scatter.v1", "report_chart"), ("chart.timeline.v1", "report_chart"),
            ("chart.relationship.v1", "report_chart"), ("map.thematic.v1", "thematic_map"),
        ]
        return {"render_manifest_version": "1.0", "pixel_qa_version": "1.0", "max_thematic_features": 10000, "templates": [
            {"template_id": template_id, "operation": operation, "version": "v1", "implementation_status": "implemented" if self.available else "unavailable"}
            for template_id, operation in templates
        ]}

    def execute_report_operation(self, payload: dict) -> dict:
        self.calls.append(payload)
        svg = self.svg
        if payload.get("map_layout", {}).get("quality_profile") == "decision-map-v1":
            layer_labels = {
                "road_basemap": "道路底图", "road_corridor": "结构走廊", "grid_theme": "主题网格",
                "analysis_reference": "分析参考点", "study_scope": "数据覆盖范围", "direction_context": "方向参照",
            }
            layers = "".join(f"<text>{layer_labels[layer]}</text>" for layer in payload["map_layout"]["required_layers"])
            svg = self.quality_svg if self.quality_svg is not None else (
                '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600">'
                '<text>图例</text><text>N</text><text>比例尺</text><text>限制</text>'
                f'{layers}<rect x="0" y="0" width="800" height="500"/>'
                '<line x1="0" y1="0" x2="500" y2="300"/><line x1="10" y1="0" x2="510" y2="300"/>'
                '<line x1="20" y1="0" x2="520" y2="300"/><line x1="30" y1="0" x2="530" y2="300"/>'
                '<line x1="40" y1="0" x2="540" y2="300"/><circle cx="400" cy="250" r="8"/>'
                '<polygon points="0,0 1,1 2,0"/></svg>'
            )
        response = {"status": self.status, "summary": "已由 ArcGIS 导出。", "limitations": ["仅表达已有结果。"], "svg": svg if self.status == "available" else None}
        input_manifest = payload.get("input_manifest")
        if isinstance(input_manifest, dict):
            layers = [{**item, "rendered_feature_count": item["normalized_feature_count"], "actual_layer_names": [item["layer_id"]]} for item in input_manifest["input_layer_manifest"]]
            road_count = sum(item["normalized_feature_count"] for item in layers if item["role"] == "road_context")
            response["visual_manifest"] = {
                "schema_version": "1.0", "input_result_ids": input_manifest["input_result_ids"],
                "input_layer_manifest": layers,
                "input_feature_count": input_manifest["input_feature_count"],
                "rendered_feature_count": input_manifest["input_feature_count"],
                "geometry_types": input_manifest["geometry_types"], "bbox": input_manifest["bbox"],
                "crs": "EPSG:4326", "basemap_status": "approved",
                "road_context_status": "rendered" if road_count else "not_provided",
                "legend_items": [item["layer_id"] for item in layers], "warnings": [],
                "quality_status": "passed", "pixel_quality": {"status": "passed"},
                **self.manifest_overrides,
            }
        return response


def test_arcgis_report_status_checks_bridge_credentials_and_all_templates():
    status = ArcGISSpatialToolModule(client=_Bridge()).report_status()

    assert status["ready"] is True
    assert status["checks"]["service_connection"] == {"ready": True, "status": "reachable"}
    assert status["checks"]["credentials"] == {"ready": True, "status": "valid"}
    assert status["checks"]["thematic_map_templates"]["ready"] is True
    assert status["checks"]["report_chart_templates"]["ready"] is True


def test_arcgis_report_status_distinguishes_unauthorized_bridge():
    class UnauthorizedBridge(_Bridge):
        def capabilities(self) -> dict:
            return {"status": "unauthorized", "templates": []}

    status = ArcGISSpatialToolModule(client=UnauthorizedBridge()).report_status()

    assert status["ready"] is False
    assert status["checks"]["service_connection"] == {"ready": True, "status": "reachable"}
    assert status["checks"]["credentials"] == {"ready": False, "status": "invalid"}
    assert "凭据无效" in status["limitations"][0]


def test_arcgis_report_status_reports_missing_templates():
    status = ArcGISSpatialToolModule(client=_Bridge(available=False)).report_status()

    assert status["ready"] is False
    assert status["checks"]["credentials"] == {"ready": True, "status": "valid"}
    assert status["checks"]["thematic_map_templates"]["missing"] == ["map.thematic.v1"]
    assert len(status["checks"]["report_chart_templates"]["missing"]) == 5


def test_arcgis_service_readiness_requires_render_manifest_and_pixel_qa_capabilities():
    class LegacyBridge(_Bridge):
        def capabilities(self):
            payload = super().capabilities()
            payload.pop("render_manifest_version")
            payload.pop("pixel_qa_version")
            payload.pop("max_thematic_features")
            return payload

    status = ArcGISSpatialToolModule(client=LegacyBridge()).report_status()

    assert status["ready"] is False
    assert status["checks"]["render_quality_contract"]["ready"] is False


def _result() -> MetricResult:
    return MetricResult(
        result_id="result:poi.count:abc",
        tool_id="poi.count",
        tool_version="catalog-4",
        status="available",
        summary="POI 数量",
        structured_result={"count": 3},
        input_sources=["dataset:poi"],
        spatial_scope={"scope_id": "scope:one"},
        time_scope={"year": 2024},
    )


def _source_index() -> SourceIndex:
    return SourceIndex(run_id="run-v4", items=[SourceIndexItem(resource_id="dataset:poi", resource_type="dataset", title="POI 数据")])


@pytest.mark.parametrize(
    ("visual_type", "expected_operation", "expected_template", "data"),
    [
        ("bar", "report_chart", "chart.bar.v1", {"series": [{"name": "基准", "points": [{"label": "A", "value": 2}]}]}),
        ("line", "report_chart", "chart.line.v1", {"series": [{"name": "趋势", "points": [{"label": "2025", "value": 2}]}]}),
        ("scatter", "report_chart", "chart.scatter.v1", {"series": [{"name": "样本", "points": [{"x": 1, "y": 3, "label": "A"}]}]}),
        ("timeline", "report_chart", "chart.timeline.v1", {"items": [{"label": "试点", "detail": "核验", "order": 1}]}),
        ("diagram", "report_chart", "chart.relationship.v1", {"nodes": [{"id": "a", "label": "输入"}], "links": []}),
    ],
)
def test_arcgis_module_covers_all_report_visual_semantics(visual_type, expected_operation, expected_template, data):
    bridge = _Bridge()
    module = ArcGISSpatialToolModule(client=bridge)
    result = _result()
    source_index = _source_index()

    asset = module.create_report_visual_asset(
        result=result,
        source_index=source_index,
        visual={"visual_type": visual_type, "title": "项目判断", "purpose": "解释已有结果", "data": data},
    )

    assert asset.status == "available"
    assert asset.resource_id in result.asset_ids
    assert asset.payload["filename"].endswith(".svg")
    assert asset.payload["asset_category"] == ("thematic_map" if visual_type == "thematic_map" else "report_chart")
    if visual_type == "thematic_map":
        assert asset.payload["cartographic_requirements"]["legend"] is True
        assert bridge.calls[0]["cartographic_requirements"]["analysis_locator"] is True
    assert bridge.calls[0]["operation"] == expected_operation
    assert bridge.calls[0]["template_id"] == expected_template
    assert "renderer" not in json.dumps(asset.payload, ensure_ascii=False).lower()
    validate_safe_svg(asset.payload["svg"])


def test_arcgis_assets_reuse_stable_id_and_do_not_rerender():
    bridge = _Bridge()
    module = ArcGISSpatialToolModule(client=bridge)
    result, source_index = _result(), _source_index()
    visual = {"visual_type": "bar", "title": "POI 对比", "purpose": "展示 POI 数量", "data": {"series": [{"name": "POI", "points": [{"label": "分析范围", "value": 3}]}]}}

    first = module.create_report_visual_asset(result=result, visual=visual, source_index=source_index)
    second = module.create_report_visual_asset(result=result, visual=visual, source_index=source_index)

    assert first.resource_id == second.resource_id
    assert len(bridge.calls) == 1
    assert result.asset_ids == [first.resource_id]


def test_arcgis_unavailable_or_unsafe_svg_never_creates_fallback_asset():
    unavailable = ArcGISSpatialToolModule(client=_Bridge(available=False))
    result, source_index = _result(), _source_index()
    asset = unavailable.create_report_visual_asset(result=result, source_index=source_index, visual={"visual_type": "bar", "title": "比较", "purpose": "已有结果", "data": {"series": [{"name": "POI", "points": [{"label": "分析范围", "value": 3}]}]}})
    assert asset.status == "unavailable"
    assert "svg" not in asset.payload
    assert not result.asset_ids

    unsafe = ArcGISSpatialToolModule(client=_Bridge(svg='<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>'))
    failed = unsafe.create_report_visual_asset(result=_result(), source_index=_source_index(), visual={"visual_type": "bar", "title": "比较", "purpose": "已有结果", "data": {"series": [{"name": "POI", "points": [{"label": "分析范围", "value": 3}]}]}})
    assert failed.status == "failed"
    assert "svg" not in failed.payload


@pytest.mark.parametrize(
    "unsafe_svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div>unsafe</div></foreignObject></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x.svg"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><path fill="url(https://example.com/pattern)"/></svg>',
    ],
)
def test_validate_safe_svg_rejects_active_content_and_external_links(unsafe_svg):
    with pytest.raises(ValueError):
        validate_safe_svg(unsafe_svg)



def test_arcgis_module_rejects_unapproved_visual_payload_before_bridge_execution():
    bridge = _Bridge()
    module = ArcGISSpatialToolModule(client=bridge)
    with pytest.raises(ValueError, match="unsupported or missing fields"):
        module.create_report_visual_asset(
            result=_result(),
            source_index=_source_index(),
            visual={
                "visual_type": "bar",
                "title": "比较",
                "purpose": "解释已有结果",
                "data": {"series": [{"name": "POI", "points": [{"label": "分析范围", "value": 3, "renderer": "injected"}]}]},
            },
        )
    assert not bridge.calls


def test_validate_safe_svg_allows_only_bounded_embedded_png():
    png = "iVBORw0KGgo="  # PNG magic bytes; a visual renderer may embed only this MIME type.
    validate_safe_svg(f'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,{png}"/></svg>')
    with pytest.raises(ValueError):
        validate_safe_svg('<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/svg+xml;base64,PHN2Zy8+"/></svg>')


def test_report_visual_svg_round_trips_through_run_storage(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    manifest = {
        "run_id": "visual-run", "capability_id": "visual-capability", "input_artifact_refs": [],
        "output_artifact_refs": [{"artifact_id": "visual:bar", "artifact_type": "report_visual", "title": "bar", "filename": "pilot-usage", "content_digest": "sha256:visual"}],
    }
    created = storage.create(history_id="history", manifest=manifest, artifact_payloads={"visual:bar": SAFE_SVG}, execution_request={"history_id": "history"})
    storage.validate("visual-capability", "visual-run")
    target = tmp_path / "visual-capability" / "visual-run" / "report" / "assets" / "pilot-usage.svg"
    assert target.read_text(encoding="utf-8") == SAFE_SVG
    assert created["artifacts"][0]["payload"] == SAFE_SVG

def test_old_simple_map_visual_type_is_not_a_v4_contract():
    module = ArcGISSpatialToolModule(client=_Bridge())
    with pytest.raises(ValueError, match="unsupported ArcGIS report visual type"):
        module.create_report_visual_asset(
            result=_result(),
            source_index=_source_index(),
            visual={"visual_type": "simple_map", "title": "旧地图", "purpose": "不应再调用", "data": {}},
        )


def test_real_scope_geometry_is_repaired_split_and_keeps_holes_before_bridge():
    bridge = _Bridge()
    module = ArcGISSpatialToolModule(client=bridge)
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[112.0, 28.0], [112.2, 28.0], [112.2, 28.2], [112.0, 28.2], [112.0, 28.0]], [[112.04, 28.04], [112.08, 28.04], [112.08, 28.08], [112.04, 28.08], [112.04, 28.04]]],
            [[[112.3, 28.0], [112.4, 28.0], [112.4, 28.1], [112.3, 28.1], [112.3, 28.0]]],
        ],
    }

    first = module.normalize_polygon_features(geometry=geometry, role="study_scope", upstream_id="scope:analysis", label="分析范围")
    second = module.normalize_polygon_features(geometry=geometry, role="study_scope", upstream_id="scope:analysis", label="分析范围")

    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert len(first) == 2
    assert all(item["geometry"]["type"] == "Polygon" for item in first)
    assert len(first[0]["geometry"]["coordinates"]) == 2  # exterior + preserved hole


def test_aggregate_result_without_geometry_snapshot_is_rejected():
    bridge = _Bridge()
    module = ArcGISSpatialToolModule(client=bridge)
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="scope:analysis", resource_type="spatial_scope", title="分析范围"),
        SourceIndexItem(
            resource_id="result:poi.grid_density:one", resource_type="analysis_result", title="poi.grid_density",
            payload={"structured_result": {"zones": [{"geometry": {"type": "MultiPolygon", "coordinates": [[[[112.05, 28.05], [112.1, 28.05], [112.1, 28.1], [112.05, 28.1], [112.05, 28.05]]]]}, "density": 8}]}},
        ),
    ])
    visual_plan = VisualPlanItem(
        visual_id="visual:poi-concentration", chapter_id="opportunity", placement="chapter:opportunity",
        decision_question="哪些片区优先踏勘？", purpose="解释设施代理的相对集中区。", visual_semantics="thematic_map",
        required_result_ids=["result:poi.grid_density:*"], required_source_ids=["scope:analysis"], selection_rule="仅在结果和范围均有效时生成。",
        priority="high", status="approved",
    )

    asset = module.create_approved_visual_asset(
        visual_plan=visual_plan, source_index=source_index,
        history_detail={"scope": {"geometry": {"type": "Polygon", "coordinates": [[[112.0, 28.0], [112.2, 28.0], [112.2, 28.2], [112.0, 28.2], [112.0, 28.0]]]}}},
    )

    assert asset.status == "unavailable"
    assert asset.payload["bridge_status"] == "geometry_snapshot_required"
    assert not bridge.calls


class _CapabilityBridge(_Bridge):
    def __init__(self, capability_status: str, **kwargs):
        super().__init__(**kwargs)
        self.capability_status = capability_status

    def capabilities(self) -> dict:
        if self.capability_status != "available":
            return {"status": self.capability_status, "templates": []}
        return super().capabilities()


class _FakeDatasetService:
    def __init__(self, records_by_source: dict[str, list[ScopeRecord]]):
        self.records_by_source = records_by_source
        self.calls: list[dict] = []

    def load_scope_records(self, *, history_id, source_id, year=None, require_geometry_metadata=False):
        self.calls.append({"history_id": history_id, "source_id": source_id, "year": year, "require_geometry_metadata": require_geometry_metadata})
        return list(self.records_by_source.get(source_id, [])), [], year


def _scope_record(source_id: str, record_id: str, geometry, properties=None, year=2024) -> ScopeRecord:
    return ScopeRecord(
        source_id=source_id,
        record_id=record_id,
        title=record_id,
        content=record_id,
        properties=dict(properties or {}),
        raw={},
        time_scope={"year": year},
        locator="test",
        citation="test",
        geometry=geometry,
    )


def _approved_map(source_ids: list[str], visual_id: str = "poi-road-map", snapshot_ids: list[str] | None = None) -> VisualPlanItem:
    return VisualPlanItem(
        visual_id=visual_id,
        chapter_id="ch01",
        placement="chapter:ch01",
        decision_question="哪些区域值得先核验？",
        purpose="表达真实空间分布",
        visual_semantics="thematic_map",
        required_result_ids=source_ids,
        input_snapshot_ids=list(snapshot_ids or []),
        required_source_ids=[],
        selection_rule="仅使用可用真实空间数据",
        priority="high",
        status="approved",
        what_it_shows="图中显示真实记录在研究范围内的空间分布。",
        how_to_read="颜色越深表示该空间单元的代理指标更高，线表示道路，边界表示研究范围。",
        supports_judgment="支持安排首轮空间核验方向。",
        does_not_prove="不能单独证明客流、消费或收益。",
        next_validation="结合现场踏勘和分时段观察核验。",
    )


def _snapshot(store, history_id, source_id, records):
    features = [{
        "id": f"{record.record_id}:part:1", "record_id": record.record_id,
        "source_id": source_id, "title": record.title, "properties": record.properties,
        "geometry": json.loads(json.dumps(record.geometry.__geo_interface__)),
    } for record in records if record.geometry is not None]
    return store.create(
        history_id=history_id, source_id=source_id, year=2024, filters=None, spatial=None,
        selection={"selected_year": 2024, "record_count": len(records), "warnings": [], "features": features},
    )["snapshot_id"]


def test_approved_visual_builds_real_snapshot_layers_and_validates_manifest(tmp_path):
    bridge = _Bridge()
    records = {
        "current:dataset:poi_grid": [_scope_record("current:dataset:poi_grid", "grid-1", Polygon([(112, 28), (112.01, 28), (112.01, 28.01), (112, 28.01)]), {"density": 8})],
        "current:dataset:poi": [_scope_record("current:dataset:poi", "poi-1", Point(112.005, 28.005))],
        "current:dataset:road_edges": [_scope_record("current:dataset:road_edges", "road-1", LineString([(112, 28), (112.01, 28.01)]), {"integration_score": 3})],
    }
    store = SpatialQuerySnapshotStore(tmp_path)
    snapshot_ids = [
        _snapshot(store, "history-real", "current:dataset:poi_grid", records["current:dataset:poi_grid"]),
        _snapshot(store, "history-real", "current:dataset:road_edges", records["current:dataset:road_edges"]),
    ]
    module = ArcGISSpatialToolModule(client=bridge, query_snapshot_store=store)
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="scope:analysis", resource_type="spatial_scope", title="分析范围"),
        SourceIndexItem(resource_id="result:poi-grid:one", resource_type="analysis_result", title="POI grid", status="available", source_ids=["dataset:poi_grid"], time_scope={"year": 2024}),
        SourceIndexItem(resource_id="result:road-syntax:one", resource_type="analysis_result", title="road syntax", status="available", source_ids=["dataset:road_edges"], time_scope={"year": 2025}),
    ])
    visual = _approved_map(["result:poi-grid:*", "result:road-syntax:*"], snapshot_ids=snapshot_ids)
    asset = module.create_approved_visual_asset(
        visual_plan=visual,
        source_index=source_index,
        history_detail={"history_id": "history-real", "analysis_reference_point": [112.005, 28.005], "scope": {"geometry": {"type": "Polygon", "coordinates": [[[111.99, 27.99], [112.02, 27.99], [112.02, 28.02], [111.99, 28.02], [111.99, 27.99]]]}}},
    )
    assert asset.status == "available"
    assert asset.time_scope == {"poi": 2024, "road": 2025}
    roles = {feature["role"] for feature in bridge.calls[0]["data_view"]["features"]}
    assert roles == {"study_scope", "grid_metric", "road_context", "context_point"}
    manifest = asset.payload["visual_manifest"]
    assert manifest["quality_status"] == "passed"
    assert manifest["input_feature_count"] == manifest["rendered_feature_count"] == 4
    serialized = json.dumps(asset.model_dump(mode="json"), ensure_ascii=False)
    assert "renderer" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert "bridge" not in serialized.lower()
    assert "integration_score" not in serialized
    assert "coordinates" not in serialized


def test_decision_map_rejects_failed_pixel_quality_manifest(tmp_path):
    bridge = _Bridge(manifest_overrides={"quality_status": "failed", "pixel_quality": {"status": "failed"}})
    records = {
        "current:dataset:poi_grid": [_scope_record("current:dataset:poi_grid", "grid-1", Polygon([(112, 28), (112.01, 28), (112.01, 28.01), (112, 28.01)]), {"density": 8})],
        "current:dataset:road_edges": [_scope_record("current:dataset:road_edges", "road-1", LineString([(112, 28), (112.01, 28.01)]), {"integration_score": 3})],
    }
    store = SpatialQuerySnapshotStore(tmp_path)
    snapshot_ids = [
        _snapshot(store, "history-real", "current:dataset:poi_grid", records["current:dataset:poi_grid"]),
        _snapshot(store, "history-real", "current:dataset:road_edges", records["current:dataset:road_edges"]),
    ]
    module = ArcGISSpatialToolModule(client=bridge, query_snapshot_store=store)
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="result:poi-grid:one", resource_type="analysis_result", title="POI grid", status="available", source_ids=["dataset:poi_grid"], time_scope={"year": 2024}),
        SourceIndexItem(resource_id="result:road-syntax:one", resource_type="analysis_result", title="road syntax", status="available", source_ids=["dataset:road_edges"], time_scope={"year": 2024}),
    ])
    visual = _approved_map(["result:poi-grid:*", "result:road-syntax:*"], snapshot_ids=snapshot_ids)
    asset = module.create_approved_visual_asset(
        visual_plan=visual, source_index=source_index,
        history_detail={"history_id": "history-real", "analysis_reference_point": [112.005, 28.005], "scope": {"geometry": {"type": "Polygon", "coordinates": [[[111.99, 27.99], [112.02, 27.99], [112.02, 28.02], [111.99, 27.99]]]}}},
    )
    assert asset.status == "failed"
    assert asset.payload["bridge_status"] == "map_quality_rejected"
    assert "svg" not in asset.payload


@pytest.mark.parametrize(
    "manifest_overrides",
    [
        {"rendered_feature_count": 3},
        {"crs": "EPSG:3857"},
        {"bbox": [0.0, 0.0, 1.0, 1.0]},
        {"road_context_status": "missing"},
    ],
)
def test_render_manifest_mismatch_rejects_svg_asset(tmp_path, manifest_overrides):
    bridge = _Bridge(manifest_overrides=manifest_overrides)
    poi = [_scope_record("current:dataset:poi", "poi-1", Point(112.005, 28.005))]
    roads = [_scope_record("current:dataset:road_edges", "road-1", LineString([(112, 28), (112.01, 28.01)]))]
    store = SpatialQuerySnapshotStore(tmp_path)
    snapshot_ids = [
        _snapshot(store, "history-real", "current:dataset:poi", poi),
        _snapshot(store, "history-real", "current:dataset:road_edges", roads),
    ]
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="result:poi:one", resource_type="analysis_result", title="POI", status="available"),
        SourceIndexItem(resource_id="result:road:one", resource_type="analysis_result", title="road", status="available"),
    ])
    asset = ArcGISSpatialToolModule(client=bridge, query_snapshot_store=store).create_approved_visual_asset(
        visual_plan=_approved_map(["result:poi:*", "result:road:*"], snapshot_ids=snapshot_ids),
        source_index=source_index,
        history_detail={"history_id": "history-real", "analysis_reference_point": [112.005, 28.005], "scope": {"geometry": {"type": "Polygon", "coordinates": [[[111.99, 27.99], [112.02, 27.99], [112.02, 28.02], [111.99, 27.99]]]}}},
    )

    assert asset.status == "failed"
    assert asset.payload["bridge_status"] == "map_quality_rejected"
    assert "svg" not in asset.payload


def test_cross_history_geometry_snapshot_is_rejected_before_bridge(tmp_path):
    bridge = _Bridge()
    store = SpatialQuerySnapshotStore(tmp_path)
    snapshot_id = _snapshot(
        store, "history-other", "current:dataset:poi",
        [_scope_record("current:dataset:poi", "poi-1", Point(112.005, 28.005))],
    )
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="result:poi:one", resource_type="analysis_result", title="POI", status="available"),
    ])
    asset = ArcGISSpatialToolModule(client=bridge, query_snapshot_store=store).create_approved_visual_asset(
        visual_plan=_approved_map(["result:poi:*"], snapshot_ids=[snapshot_id]), source_index=source_index,
        history_detail={"history_id": "history-real", "analysis_reference_point": [112.005, 28.005], "scope": {"geometry": {"type": "Polygon", "coordinates": [[[111.99, 27.99], [112.02, 27.99], [112.02, 28.02], [111.99, 27.99]]]}}},
    )

    assert asset.status == "unavailable"
    assert asset.payload["bridge_status"] == "geometry_snapshot_unavailable"
    assert not bridge.calls


def test_road_decision_map_requires_an_explicit_historical_reference_point(tmp_path):
    bridge = _Bridge()
    records = {
        "current:dataset:poi_grid": [_scope_record("current:dataset:poi_grid", "grid-1", Polygon([(112, 28), (112.01, 28), (112.01, 28.01), (112, 28.01)]), {"density": 8})],
        "current:dataset:road_edges": [_scope_record("current:dataset:road_edges", "road-1", LineString([(112, 28), (112.01, 28.01)]), {"integration_score": 3})],
    }
    store = SpatialQuerySnapshotStore(tmp_path)
    snapshot_ids = [
        _snapshot(store, "history-real", "current:dataset:poi_grid", records["current:dataset:poi_grid"]),
        _snapshot(store, "history-real", "current:dataset:road_edges", records["current:dataset:road_edges"]),
    ]
    module = ArcGISSpatialToolModule(client=bridge, query_snapshot_store=store)
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="result:poi-grid:one", resource_type="analysis_result", title="POI grid", status="available", source_ids=["dataset:poi_grid"], time_scope={"year": 2024}),
        SourceIndexItem(resource_id="result:road-syntax:one", resource_type="analysis_result", title="road syntax", status="available", source_ids=["dataset:road_edges"], time_scope={"year": 2024}),
    ])
    asset = module.create_approved_visual_asset(
        visual_plan=_approved_map(["result:poi-grid:*", "result:road-syntax:*"], snapshot_ids=snapshot_ids), source_index=source_index,
        history_detail={"history_id": "history-real", "scope": {"geometry": {"type": "Polygon", "coordinates": [[[111.99, 27.99], [112.02, 27.99], [112.02, 28.02], [111.99, 27.99]]]}}},
    )
    assert asset.status == "unavailable"
    assert asset.payload["bridge_status"] == "project_context_incomplete"
    assert not bridge.calls


def test_combined_time_scope_preserves_each_real_input_vintage():
    items = [
        SourceIndexItem(
            resource_id="result:nightlight:one", resource_type="analysis_result",
            title="夜光网格", source_ids=["dataset:nightlight-2025"],
            time_scope={"year": 2025},
        ),
        SourceIndexItem(
            resource_id="result:poi-grid:one", resource_type="analysis_result",
            title="POI 网格", source_ids=["dataset:poi-2024"],
            time_scope={},
        ),
        SourceIndexItem(
            resource_id="result:road:one", resource_type="analysis_result",
            title="路网结果", source_ids=["dataset:road-network-saved"],
            time_scope={},
        ),
    ]

    assert ArcGISSpatialToolModule._combined_time_scope(items) == {
        "nightlight": 2025, "poi": 2024, "road": "saved snapshot",
    }


def test_approved_visual_rejects_empty_geometry_snapshot(tmp_path):
    bridge = _Bridge()
    records = {
        "current:dataset:poi_grid": [_scope_record("current:dataset:poi_grid", "no-geometry", None, {"density": 99})],
    }
    store = SpatialQuerySnapshotStore(tmp_path)
    snapshot_id = _snapshot(store, "history-real", "current:dataset:poi_grid", records["current:dataset:poi_grid"])
    module = ArcGISSpatialToolModule(client=bridge, query_snapshot_store=store)
    source_index = SourceIndex(run_id="run-v4", items=[
        SourceIndexItem(resource_id="result:poi-grid:one", resource_type="analysis_result", title="POI grid", status="available", source_ids=["dataset:poi_grid"], time_scope={"year": 2024}),
    ])
    asset = module.create_approved_visual_asset(
        visual_plan=_approved_map(["result:poi-grid:*"], visual_id="poi-no-geometry", snapshot_ids=[snapshot_id]),
        source_index=source_index,
        history_detail={"history_id": "history-real", "scope": {"geometry": {"type": "Polygon", "coordinates": [[[112, 28], [112.01, 28], [112.01, 28.01], [112, 28],]]}}},
    )
    assert asset.status == "unavailable"
    assert asset.payload.get("bridge_status") == "required_layer_empty"
    assert not bridge.calls
    assert "svg" not in asset.payload


def test_bridge_capability_failure_is_recorded_without_calling_render_operation():
    for status in ("unavailable", "unauthorized", "timeout", "failed"):
        bridge = _CapabilityBridge(status)
        module = ArcGISSpatialToolModule(client=bridge)
        asset = module.create_report_visual_asset(
            result=_result(), source_index=_source_index(),
            visual={"visual_type": "bar", "title": "项目判断", "purpose": "解释已有结果", "data": {"series": [{"name": "POI", "points": [{"label": "分析范围", "value": 3}]}]}},
        )
        assert asset.status == "unavailable"
        assert asset.payload.get("bridge_status") == status
        assert not bridge.calls
