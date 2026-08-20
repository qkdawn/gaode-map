from __future__ import annotations

import pytest
from PIL import Image

from modules.spatial_strategy import visuals


def _decision_plan(**values):
    return {
        "rationale": "使用完整项目数据检验当前决策判断",
        "decision_question": "这些空间证据如何改变项目定位和实施选择",
        "caption": "图中证据用于比较候选路径并说明成立条件，不直接代表客流或收入。",
        **values,
    }


def test_chinese_wrapping_does_not_orphan_punctuation():
    assert visuals._wrap_text("项目应改善连接与识别，而非复制普通商业。", 20) == [
        "项目应改善连接与识别，而非复制普通商业。",
    ]


def test_visual_package_uses_full_project_records_and_writes_pngs(monkeypatch, tmp_path):
    records = {
        "road_nodes": [],
        "road_edges": [
            {"road_class": "主干路", "length_m": 1200, "geometry": {"type": "LineString", "coordinates": [[116.38, 39.90], [116.40, 39.91]]}},
            {"road_class": "次干路", "length_m": 800, "geometry": {"type": "LineString", "coordinates": [[116.39, 39.89], [116.40, 39.91]]}},
        ],
        "poi": [
            {"category": "餐饮", "location": [116.385, 39.902]},
            {"category": "零售", "location": [116.395, 39.907]},
        ],
        "population": [
            {"population_total": 1200, "geometry": {"type": "Polygon", "coordinates": [[[116.38, 39.90], [116.39, 39.90], [116.39, 39.91], [116.38, 39.91], [116.38, 39.90]]]}},
        ],
        "nightlight": [
            {"radiance": 8.5, "geometry": {"type": "Polygon", "coordinates": [[[116.39, 39.90], [116.40, 39.90], [116.40, 39.91], [116.39, 39.91], [116.39, 39.90]]]}},
        ],
    }
    monkeypatch.setattr(visuals, "_resolve_history_id", lambda _: "history-1")
    monkeypatch.setattr(visuals._DATA, "_all_spatial_records", lambda _, dataset_id: records[dataset_id])

    package = visuals.build_spatial_strategy_visuals(
        run_id="31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2",
        history_id="history-1",
        visual_plan=[
            _decision_plan(
                title="道路与活动点关系",
                format="map",
                map_variant="poi_access",
                dataset_id="",
                layers=[
                    {"dataset_id": "road_edges", "role": "line", "color": "#2563eb", "metric_field": ""},
                    {"dataset_id": "poi", "role": "point", "color": "#e11d48", "metric_field": ""},
                ],
                group_by="",
                metric_op="count",
                metric_field="",
            ),
            _decision_plan(
                title="POI 全量分类",
                format="chart",
                chart_variant="poi_supply",
                dataset_id="poi",
                layers=[],
                group_by="category",
                metric_op="count",
                metric_field="",
            ),
            _decision_plan(
                title="项目全量数据汇总",
                format="table",
                dataset_id="",
                layers=[],
                group_by="",
                metric_op="count",
                metric_field="",
            ),
        ],
        root=tmp_path,
    )

    images = [asset for asset in package["assets"] if asset["kind"] == "image"]
    assert len(images) == 2
    assert all((tmp_path / "31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2" / asset["relative_path"]).is_file() for asset in images)
    table = next(asset for asset in package["assets"] if asset["kind"] == "table")
    assert "poi" in table["markdown"]
    assert "road_edges" in table["markdown"]
    assert images[0]["source_datasets"]
    assert all(item["complete"] for item in images[0]["source_datasets"])
    assert package["visual_plan"][0]["title"] == "道路与活动点关系"


def test_visual_plan_rejects_fields_outside_dataset_schema():
    with pytest.raises(ValueError, match="visual_group_by_invalid:poi:invented_field"):
        visuals._normalize_plan(
            [
                {
                    "title": "非法聚合字段",
                    "format": "chart",
                    "dataset_id": "poi",
                    "layers": [],
                    "group_by": "invented_field",
                    "metric_op": "count",
                    "metric_field": "",
                }
            ],
            {"poi": []},
        )


def test_visual_plan_drops_empty_model_placeholder_and_records_warning(monkeypatch, tmp_path):
    records = {
        "road_edges": [{"road_class": "主干路", "length_m": 100, "geometry": {"type": "LineString", "coordinates": [[116.38, 39.90], [116.40, 39.91]]}}],
        "poi": [{"category": "餐饮", "location": [116.385, 39.902]}],
    }
    monkeypatch.setattr(visuals, "_resolve_history_id", lambda _: "history-1")
    monkeypatch.setattr(visuals._DATA, "_all_spatial_records", lambda _, dataset_id: records[dataset_id])
    package = visuals.build_spatial_strategy_visuals(
        run_id="placeholder-run",
        history_id="history-1",
        project_context={"datasets": [{"dataset_id": "road_edges"}, {"dataset_id": "poi"}]},
        visual_plan=[
            {"title": "", "caption": "", "decision_question": "", "rationale": "模型保留的空槽位"},
            _decision_plan(title="道路与活动点关系", format="map", map_variant="poi_access", layers=[
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
            ]),
            _decision_plan(title="设施结构统计", format="chart", chart_variant="poi_supply", dataset_id="poi"),
            _decision_plan(title="道路数据汇总", format="table", dataset_id="road_edges"),
        ],
        root=tmp_path,
    )
    assert package["warnings"] == ["visual_plan_items_dropped:1"]
    assert len(package["visual_plan"]) == 3


def test_nightlight_map_uses_platform_palette_and_hotspot_thresholds(monkeypatch, tmp_path):
    cells = []
    for index, radiance in enumerate([1.0, 4.0, 12.0, 30.0, 80.0]):
        x0 = 116.38 + index * 0.01
        cells.append({
            "cell_id": f"cell-{index}",
            "radiance": radiance,
            "has_data": True,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[x0, 39.90], [x0 + 0.01, 39.90], [x0 + 0.01, 39.91], [x0, 39.91], [x0, 39.90]]],
            },
        })
    records = {"nightlight": cells, "road_edges": []}
    monkeypatch.setattr(visuals, "_resolve_history_id", lambda _: "history-1")
    monkeypatch.setattr(visuals._DATA, "_all_spatial_records", lambda _, dataset_id: records[dataset_id])

    package = visuals.build_spatial_strategy_visuals(
        run_id="31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2",
        history_id="history-1",
        project_context={"datasets": [{"dataset_id": "nightlight"}]},
        visual_plan=[_decision_plan(
            title="夜光热点与梯度",
            format="map",
            map_variant="context_full",
            dataset_id="nightlight",
            layers=[{"dataset_id": "nightlight", "role": "polygon", "color": "#F2C94C", "metric_field": "radiance"}],
            group_by="year",
            metric_op="avg",
            metric_field="radiance",
        ), _decision_plan(
            title="夜光年度统计",
            format="chart",
            dataset_id="nightlight",
            layers=[],
            group_by="year",
            metric_op="avg",
            metric_field="radiance",
        ), _decision_plan(
            title="夜光数据汇总",
            format="table",
            dataset_id="nightlight",
            layers=[],
            group_by="",
            metric_op="count",
            metric_field="",
        )],
        root=tmp_path,
    )

    asset = package["assets"][0]
    assert package["visual_plan"][0]["map_variant"] == ""
    style = asset["design"]["nightlight_style"]
    assert style["palette"] == "platform_radiance_v1"
    assert style["domain"] == "positive_p5_p98"
    assert style["boundary_modes"] == ["hotspot", "gradient"]
    assert style["p90"] > style["p75"] > style["min_value"]
    assert int(style["hotspot_analysis"]["core_hotspot_count"]) > 0
    assert int(style["gradient_analysis"]["fringe_band_count"]) > 0
    assert asset["design"]["projection"]["method"] == "local_equirectangular_wgs84"
    assert asset["design"]["projection"]["axis_scale_delta_percent"] == 0.0
    image = Image.open(asset["path"]).convert("RGB")
    assert len(image.getcolors(maxcolors=image.width * image.height) or []) > 20


def test_visual_variants_render_evidence_templates(monkeypatch, tmp_path):
    polygon = {
        "type": "Polygon",
        "coordinates": [[[116.38, 39.90], [116.39, 39.90], [116.39, 39.91], [116.38, 39.91], [116.38, 39.90]]],
    }
    records = {
        "road_edges": [{"road_name": "潘家坪路", "road_class": "主干路", "length_m": 1200, "geometry": {"type": "LineString", "coordinates": [[116.38, 39.90], [116.40, 39.91]]}}],
        "poi": [
            {"category": "餐饮服务", "name": "甲方餐厅", "location": [116.385, 39.902]},
            {"category": "科教文化服务", "name": "城市文化馆", "location": [116.395, 39.907]},
        ],
        "population": [{"population_total": 1200, "age_5_19": 200, "age_30_39": 300, "age_50_64": 180, "geometry": polygon}],
    }
    monkeypatch.setattr(visuals, "_resolve_history_id", lambda _: "history-1")
    monkeypatch.setattr(visuals._DATA, "_all_spatial_records", lambda _, dataset_id: records[dataset_id])

    plans = [
        _decision_plan(
            title="设施连接",
            format="map",
            map_variant="poi_access",
            layers=[
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
            ],
        ),
        _decision_plan(
            title="完整区域关系",
            format="map",
            map_variant="context_full",
            layers=[
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
            ],
        ),
        _decision_plan(
            title="区域角色",
            format="map",
            map_variant="regional_role",
            layers=[
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
                {"dataset_id": "population", "role": "polygon", "metric_field": "population_total"},
            ],
        ),
        _decision_plan(title="供给结构", format="chart", chart_variant="poi_supply", dataset_id="poi"),
        _decision_plan(title="人口画像", format="chart", chart_variant="population_profile", dataset_id="population"),
    ]
    package = visuals.build_spatial_strategy_visuals(
        run_id="31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2",
        history_id="history-1",
        visual_plan=plans,
        root=tmp_path,
    )

    images = [asset for asset in package["assets"] if asset["kind"] == "image"]
    assert len(images) == 5
    assert all(Image.open(asset["path"]).size[0] >= 1200 for asset in images)
    assert Image.open(images[1]["path"]).size == (2400, 1500)
    assert Image.open(images[3]["path"]).size == (1600, 900)
    assert Image.open(images[4]["path"]).size == (1600, 900)
    assert package["visual_plan"][0]["map_variant"] == "poi_access"
    assert package["visual_plan"][1]["map_variant"] == "context_full"
    assert package["visual_plan"][4]["chart_variant"] == "population_profile"
    assert images[0]["design"]["poi_style"]["palette"] == "facility_category_v1"
    assert images[0]["design"]["poi_style"]["named_label_count"] == 1
    assert images[0]["design"]["named_pois"][0]["name"] == "城市文化馆"
    assert images[0]["design"]["named_roads"] == [{"name": "潘家坪路", "road_class": "主干路"}]
    assert len(set(images[0]["design"]["poi_style"]["category_colors"].values())) == 2
    assert images[2]["design"]["population_style"]["palette"] == "population_blue_v1"


def test_visual_plan_quality_rejects_poi_without_road_context():
    plan = [
        _decision_plan(
            title="设施散点分布",
            format="map",
            map_variant="context_full",
            layers=[{"dataset_id": "poi", "role": "point"}],
        ),
        _decision_plan(title="设施结构统计", format="chart", chart_variant="poi_supply", dataset_id="poi"),
        _decision_plan(
            title="设施分类表格",
            format="table",
            dataset_id="poi",
            group_by="category",
            metric_op="count",
        ),
    ]

    with pytest.raises(ValueError, match="visual_plan_poi_map_requires_road_context"):
        visuals._normalize_plan(plan, {"poi": [], "road_edges": []})


def test_adaptive_map_layout_centers_tall_extent_and_uses_chinese_legends(monkeypatch, tmp_path):
    population = []
    for index, value in enumerate((600, 900, 1300, 1800)):
        y0 = 39.88 + index * 0.01
        population.append({
            "population_total": value,
            "age_5_19": value * 0.14,
            "age_30_39": value * 0.2,
            "age_50_64": value * 0.22,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[116.38, y0], [116.39, y0], [116.39, y0 + 0.01], [116.38, y0 + 0.01], [116.38, y0]]],
            },
        })
    records = {
        "population": population,
        "road_edges": [{
            "road_class": "主干路",
            "geometry": {"type": "LineString", "coordinates": [[116.385, 39.88], [116.385, 39.92]]},
        }],
    }
    monkeypatch.setattr(visuals, "_resolve_history_id", lambda _: "history-1")
    monkeypatch.setattr(visuals._DATA, "_all_spatial_records", lambda _, dataset_id: records[dataset_id])

    package = visuals.build_spatial_strategy_visuals(
        run_id="31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2",
        history_id="history-1",
        project_context={"datasets": [{"dataset_id": "population"}, {"dataset_id": "road_edges"}]},
        visual_plan=[
            _decision_plan(
                title="常住人口空间分布",
                format="map",
                layers=[{"dataset_id": "population", "role": "polygon", "metric_field": "population_total"}],
            ),
            _decision_plan(title="重点年龄人口结构", format="chart", chart_variant="population_profile", dataset_id="population"),
            _decision_plan(
                title="道路层级与连接骨架",
                format="map",
                layers=[{"dataset_id": "road_edges", "role": "line"}],
            ),
        ],
        root=tmp_path,
    )

    population_map = package["assets"][0]
    road_map = package["assets"][2]
    assert Image.open(population_map["path"]).size == (900, 1400)
    assert population_map["design"]["projection"]["content_occupancy_ratio"] >= 0.25
    assert any(label.startswith("常住人口") for label in population_map["design"]["legend_labels"])
    assert "population" not in population_map["design"]["legend_labels"]
    assert road_map["design"]["legend_labels"] == ["道路层级"]
    assert population_map["design"]["population_style"]["domain"] == "positive_p5_p95"
    assert population_map["design"]["population_style"]["palette"] == "population_blue_v1"
    assert all(asset["design"]["caption"] for asset in package["assets"])


def test_render_quality_rejects_internal_legend_labels_and_missing_color_scales():
    plan = [_decision_plan(title="空间证据图", format="map")]
    base_design = {
        "format": "map",
        "caption": "该图用于检验空间证据如何改变项目定位和实施选择。",
        "projection": {"content_occupancy_ratio": 0.8},
        "layers": [{"dataset_id": "population"}],
    }

    with pytest.raises(ValueError, match="visual_render_exposes_internal_dataset_label"):
        visuals._validate_rendered_assets(plan, [{
            "kind": "image",
            "design": {**base_design, "legend_labels": ["population"]},
        }])

    with pytest.raises(ValueError, match="visual_render_missing_population_color_scale"):
        visuals._validate_rendered_assets(plan, [{
            "kind": "image",
            "design": {**base_design, "legend_labels": ["常住人口"]},
        }])

    with pytest.raises(ValueError, match="visual_render_missing_poi_category_palette"):
        visuals._validate_rendered_assets(plan, [{
            "kind": "image",
            "design": {
                **base_design,
                "layers": [{"dataset_id": "poi"}, {"dataset_id": "road_edges"}],
                "legend_labels": ["餐饮", "科教文化", "道路层级"],
            },
        }])

    with pytest.raises(ValueError, match="visual_render_missing_nightlight_color_scale"):
        visuals._validate_rendered_assets(plan, [{
            "kind": "image",
            "design": {
                **base_design,
                "layers": [{"dataset_id": "nightlight"}, {"dataset_id": "road_edges"}],
                "legend_labels": ["夜光辐亮度", "道路层级"],
            },
        }])
