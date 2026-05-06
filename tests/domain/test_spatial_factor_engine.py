from modules.spatial_factor_engine import build_point_spatial_factors, build_subcategory_spatial_trends


def test_point_spatial_factors_classify_direction_and_rings():
    points = [
        {"lng": 112.00, "lat": 28.00, "subcategory": "咖啡厅"},
        {"lng": 112.01, "lat": 28.01, "subcategory": "咖啡厅"},
        {"lng": 112.02, "lat": 28.02, "subcategory": "咖啡厅"},
        {"lng": 112.03, "lat": 28.03, "subcategory": "咖啡厅"},
    ]

    result = build_point_spatial_factors(points, center=[112.0, 28.0])

    assert result["point_count"] == 4
    assert result["direction_factor"]["dominant_direction"] == "东北"
    assert result["ring_factor"]["dominant_ring"] in {"核心圈层", "中圈层", "外围圈层"}
    assert result["ring_factor"]["max_distance_m"] > 0


def test_subcategory_spatial_trends_report_centroid_shift_and_hotspots():
    summaries = [
        {
            "year": 2023,
            "subcategory_counts": {"咖啡厅": 2},
            "top_subcategories": [{"name": "咖啡厅", "parent": "餐饮"}],
            "points": [
                {"lng": 112.00, "lat": 28.00, "subcategory": "咖啡厅", "category": "餐饮", "area": "一区"},
                {"lng": 112.001, "lat": 28.001, "subcategory": "咖啡厅", "category": "餐饮", "area": "一区"},
            ],
        },
        {
            "year": 2025,
            "subcategory_counts": {"咖啡厅": 4},
            "top_subcategories": [{"name": "咖啡厅", "parent": "餐饮"}],
            "points": [
                {"lng": 112.03, "lat": 28.03, "subcategory": "咖啡厅", "category": "餐饮", "area": "二区"},
                {"lng": 112.031, "lat": 28.031, "subcategory": "咖啡厅", "category": "餐饮", "area": "二区"},
                {"lng": 112.032, "lat": 28.032, "subcategory": "咖啡厅", "category": "餐饮", "area": "二区"},
                {"lng": 112.033, "lat": 28.033, "subcategory": "咖啡厅", "category": "餐饮", "area": "二区"},
            ],
        },
    ]

    result = build_subcategory_spatial_trends(summaries, center=[112.0, 28.0])
    row = result["subcategory_spatial_trend_rows"][0]

    assert result["spatial_factors"]["geometry_mode"] == "point"
    assert row["name"] == "咖啡厅"
    assert row["delta"] == 2
    assert row["dominant_direction"] == "东北"
    assert row["centroid_shift_direction"] == "东北"
    assert row["centroid_shift_m"] > 0
    assert row["hotspot_grid_count"] >= 1
    assert row["top_area"] == "二区"
    assert result["subcategory_spatial_summary"]
