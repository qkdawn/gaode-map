from __future__ import annotations

import pytest
from PIL import Image

from modules.spatial_strategy import visuals


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
            {
                "title": "道路与活动点关系",
                "format": "map",
                "rationale": "检查道路与 POI 的空间关系",
                "dataset_id": "",
                "layers": [
                    {"dataset_id": "road_edges", "role": "line", "color": "#2563eb", "metric_field": ""},
                    {"dataset_id": "poi", "role": "point", "color": "#e11d48", "metric_field": ""},
                ],
                "group_by": "",
                "metric_op": "count",
                "metric_field": "",
            },
            {
                "title": "POI 全量分类",
                "format": "chart",
                "rationale": "查看全量 POI 的分类结构",
                "dataset_id": "poi",
                "layers": [],
                "group_by": "category",
                "metric_op": "count",
                "metric_field": "",
            },
            {
                "title": "项目全量数据汇总",
                "format": "table",
                "rationale": "汇总各数据集记录数",
                "dataset_id": "",
                "layers": [],
                "group_by": "",
                "metric_op": "count",
                "metric_field": "",
            },
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
        visual_plan=[{
            "title": "夜光热点与梯度",
            "format": "map",
            "rationale": "展示夜光梯度与热点",
            "dataset_id": "nightlight",
            "layers": [{"dataset_id": "nightlight", "role": "polygon", "color": "#F2C94C", "metric_field": "radiance"}],
            "group_by": "year",
            "metric_op": "avg",
            "metric_field": "radiance",
        }],
        root=tmp_path,
    )

    asset = package["assets"][0]
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
        "road_edges": [{"road_class": "主干路", "length_m": 1200, "geometry": {"type": "LineString", "coordinates": [[116.38, 39.90], [116.40, 39.91]]}}],
        "poi": [
            {"category": "餐饮服务", "name": "甲方餐厅", "location": [116.385, 39.902]},
            {"category": "科教文化服务", "name": "城市文化馆", "location": [116.395, 39.907]},
        ],
        "population": [{"population_total": 1200, "age_5_19": 200, "age_30_39": 300, "age_50_64": 180, "geometry": polygon}],
    }
    monkeypatch.setattr(visuals, "_resolve_history_id", lambda _: "history-1")
    monkeypatch.setattr(visuals._DATA, "_all_spatial_records", lambda _, dataset_id: records[dataset_id])

    plans = [
        {
            "title": "设施连接",
            "format": "map",
            "map_variant": "poi_access",
            "layers": [
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
            ],
        },
        {
            "title": "完整区域关系",
            "format": "map",
            "map_variant": "context_full",
            "layers": [
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
            ],
        },
        {
            "title": "区域角色",
            "format": "map",
            "map_variant": "regional_role",
            "layers": [
                {"dataset_id": "road_edges", "role": "line"},
                {"dataset_id": "poi", "role": "point"},
                {"dataset_id": "population", "role": "polygon", "metric_field": "population_total"},
            ],
        },
        {"title": "供给结构", "format": "chart", "chart_variant": "poi_supply", "dataset_id": "poi"},
        {"title": "人口画像", "format": "chart", "chart_variant": "population_profile", "dataset_id": "population"},
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
    assert package["visual_plan"][0]["map_variant"] == "poi_access"
    assert package["visual_plan"][1]["map_variant"] == "context_full"
    assert package["visual_plan"][4]["chart_variant"] == "population_profile"
