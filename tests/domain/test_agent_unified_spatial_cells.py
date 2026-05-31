import asyncio
import json

from modules.agent.llm_digest import tool_result_llm_digest
from modules.agent.schemas import AnalysisSnapshot, ToolResult
from modules.agent.tool_adapters import spatial_cell_tools
from modules.poi.schemas import PoiCategoryRequest
from modules.spatial_cells import service as spatial_cell_service


def _feature(cell_id, west, south, east, north):
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, north], [east, north], [east, south], [west, south], [west, north]]],
        },
        "properties": {
            "cell_id": cell_id,
            "h3_id": cell_id,
            "row": 0,
            "col": 0,
            "centroid_gcj02": [(west + east) / 2, (south + north) / 2],
        },
    }


def test_unified_spatial_cells_aggregates_poi_population_nightlight_and_road(monkeypatch):
    features = [_feature("c0", 0.0, 0.0, 1.0, 1.0), _feature("c1", 1.0, 0.0, 2.0, 1.0)]
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_grid",
        lambda *args, **kwargs: {"scope_id": "scope-1", "cell_count": len(features), "features": features},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_population_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "c0", "value": 1200}, {"cell_id": "c1", "value": 800}]},
    )
    monkeypatch.setattr(
        spatial_cell_service,
        "get_nightlight_layer",
        lambda *args, **kwargs: {"cells": [{"cell_id": "c0", "value": 8.5}, {"cell_id": "c1", "value": 0.0}]},
    )

    payload = spatial_cell_service.build_unified_spatial_cells(
        polygon=[],
        pois=[
            {"id": "food-1", "location": [0.25, 0.25], "type": "050100"},
            {"id": "food-2", "location": [0.75, 0.25], "type": "050200"},
            {"id": "shop-1", "location": [1.25, 0.25], "type": "060100"},
        ],
        road_features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.5], [2.0, 0.5]]},
                "properties": {"integration_score": 0.6, "connectivity_score": 0.4},
            }
        ],
        categories=[
            PoiCategoryRequest(id="food", name="餐饮", types="050000"),
            PoiCategoryRequest(id="retail", name="购物", types="060000"),
        ],
    )

    assert payload["grid_type"] == "shared_raster"
    assert payload["cell_id_source"] == "population_nightlight_shared_cell_id"
    assert payload["summary"]["cell_count"] == 2
    assert payload["summary"]["active_poi_cell_count"] == 2
    assert payload["summary"]["lit_cell_count"] == 1
    assert payload["summary"]["road_covered_cell_count"] == 2

    rows = {item["properties"]["cell_id"]: item["properties"] for item in payload["features"]}
    assert rows["c0"]["poi_count"] == 2
    assert rows["c0"]["dominant_category"] == "food"
    assert rows["c0"]["dominant_category_name"] == "餐饮"
    assert rows["c0"]["population_density"] == 1200
    assert rows["c0"]["nightlight_radiance"] == 8.5
    assert rows["c0"]["road_integration"] == 0.6
    assert rows["c0"]["road_connectivity"] == 0.4
    assert rows["c0"]["road_length_km_per_km2"] > 0
    assert rows["c1"]["poi_count"] == 1


def test_agent_tool_reuses_existing_road_features(monkeypatch):
    called = {"road": False}

    async def fake_compute_road_features(**kwargs):
        called["road"] = True
        return []

    def fake_build(**kwargs):
        assert kwargs["road_features"][0]["properties"]["integration_score"] == 0.7
        return {
            "grid_type": "shared_raster",
            "cell_id_source": "population_nightlight_shared_cell_id",
            "cell_count": 1,
            "features": [{"type": "Feature", "properties": {"cell_id": "c0"}, "geometry": {}}],
            "summary": {
                "cell_count": 1,
                "active_poi_cell_count": 1,
                "lit_cell_count": 1,
                "road_covered_cell_count": 1,
                "top_cells": [],
                "coverage": {},
            },
        }

    monkeypatch.setattr(spatial_cell_tools, "_compute_road_features", fake_compute_road_features)
    monkeypatch.setattr(spatial_cell_tools, "build_unified_spatial_cells", fake_build)

    result = asyncio.run(
        spatial_cell_tools.build_unified_spatial_cells_tool(
            arguments={},
            snapshot=AnalysisSnapshot(),
            artifacts={
                "scope_polygon": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                "current_pois": [{"id": "poi-1"}],
                "current_road": {
                    "roads": {
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                                "properties": {"integration_score": 0.7, "connectivity_score": 0.2},
                            }
                        ]
                    }
                },
            },
            question="总结商业特征",
        )
    )

    assert called["road"] is False
    assert result.status == "success"
    assert result.result["road_source"] == "reused_current_road_features"
    assert "current_road" not in result.artifacts
    assert "current_unified_spatial_cells" in result.artifacts
    assert "current_unified_spatial_cells_summary" in result.artifacts


def test_agent_tool_computes_road_features_without_storing_raw_roads(monkeypatch):
    called = {"road": False}

    async def fake_compute_road_features(**kwargs):
        called["road"] = True
        return [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "properties": {"integration_score": 0.5, "connectivity_score": 0.3},
            }
        ]

    def fake_build(**kwargs):
        assert len(kwargs["road_features"]) == 1
        return {
            "grid_type": "shared_raster",
            "cell_id_source": "population_nightlight_shared_cell_id",
            "cell_count": 1,
            "features": [{"type": "Feature", "properties": {"cell_id": "c0"}, "geometry": {}}],
            "summary": {
                "cell_count": 1,
                "active_poi_cell_count": 0,
                "lit_cell_count": 0,
                "road_covered_cell_count": 1,
                "top_cells": [],
                "coverage": {},
            },
        }

    monkeypatch.setattr(spatial_cell_tools, "_compute_road_features", fake_compute_road_features)
    monkeypatch.setattr(spatial_cell_tools, "build_unified_spatial_cells", fake_build)

    result = asyncio.run(
        spatial_cell_tools.build_unified_spatial_cells_tool(
            arguments={"road_mode": "walking"},
            snapshot=AnalysisSnapshot(),
            artifacts={"scope_polygon": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]},
            question="总结商业特征",
        )
    )

    assert called["road"] is True
    assert result.result["road_source"] == "computed_for_unified_cells"
    assert "current_road" not in result.artifacts


def test_unified_spatial_cells_digest_does_not_inline_large_features():
    features = [
        {"type": "Feature", "properties": {"cell_id": f"cell-{index}"}, "geometry": {}}
        for index in range(300)
    ]
    result = ToolResult(
        tool_name="build_unified_spatial_cells",
        status="success",
        result={"cell_count": 300},
        artifacts={
            "current_unified_spatial_cells": {"features": features, "summary": {"cell_count": 300}},
            "current_unified_spatial_cells_summary": {"cell_count": 300},
        },
    )

    digest = tool_result_llm_digest(result)
    encoded = json.dumps(digest, ensure_ascii=False)
    assert "artifacts" not in digest
    assert "cell-299" not in encoded
    assert digest["artifact_keys"] == ["current_unified_spatial_cells", "current_unified_spatial_cells_summary"]
    assert digest["artifact_shapes"]["current_unified_spatial_cells"]["keys"] == ["features", "summary"]
