from modules.poi import aggregation
from modules.poi.aggregation import build_poi_shared_grid
from modules.poi.schemas import PoiCategoryRequest


def test_build_poi_shared_grid_aggregates_points_by_population_cell(monkeypatch):
    monkeypatch.setattr(
        aggregation,
        "get_population_grid",
        lambda polygon, coord_type: {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                    "properties": {"cell_id": "r0_c0", "row": 0, "col": 0, "centroid_gcj02": [0.5, 0.5]},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]],
                    },
                    "properties": {"cell_id": "r0_c1", "row": 0, "col": 1, "centroid_gcj02": [1.5, 0.5]},
                },
            ]
        },
    )

    payload = build_poi_shared_grid(
        polygon=[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]],
        coord_type="gcj02",
        pois=[
            {"id": "a", "location": [0.25, 0.25], "type": "050100"},
            {"id": "b", "location": [0.75, 0.25], "type": "050200"},
            {"id": "c", "location": [1.25, 0.25], "type": "060100"},
            {"id": "outside", "location": [3, 3], "type": "050100"},
        ],
        poi_coord_type="gcj02",
        categories=[
            PoiCategoryRequest(id="food", name="餐饮", types="050000"),
            PoiCategoryRequest(id="retail", name="购物", types="060000"),
        ],
    )

    assert payload["grid_type"] == "raster"
    assert payload["summary"]["grid_count"] == 2
    assert payload["summary"]["assigned_poi_count"] == 3
    assert payload["summary"]["active_cell_count"] == 2

    rows = {item["properties"]["cell_id"]: item["properties"] for item in payload["features"]}
    assert rows["r0_c0"]["poi_count"] == 2
    assert rows["r0_c0"]["category_counts"] == {"food": 2}
    assert rows["r0_c0"]["dominant_category_name"] == "餐饮"
    assert rows["r0_c1"]["poi_count"] == 1
    assert rows["r0_c1"]["category_counts"] == {"retail": 1}
