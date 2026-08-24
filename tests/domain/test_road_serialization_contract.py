import math
import time

from shapely.geometry import Polygon

from modules.road.schemas import RoadSyntaxResponse
from modules.road.serialize import build_road_analysis_result, empty_result


def _result():
    polygon = Polygon(
        [
            (112.98, 28.19),
            (112.99, 28.19),
            (112.99, 28.20),
            (112.98, 28.20),
            (112.98, 28.19),
        ]
    )
    rows = [
        {
            "x1": "112.981",
            "y1": "28.191",
            "x2": "112.989",
            "y2": "28.191",
            "T1024 Choice": "2",
            "T1024 Integration": "3",
            "T1024 Node Count": "10",
            "T1024 Total Depth": "20",
            "Connectivity": "1",
        }
    ]
    return build_road_analysis_result(
        rows=rows,
        fieldnames=list(rows[0]),
        edge_inputs=[
            {
                "x1": 112.981,
                "y1": 28.191,
                "x2": 112.989,
                "y2": 28.191,
                "road_name": "测试路",
                "highway": "residential",
            }
        ],
        context_wgs_poly=polygon,
        output_wgs_poly=polygon,
        mode="walking",
        local_radii=[],
        requested_local_labels=[],
        render_metric="choice",
        include_geojson=True,
        max_edge_features=None,
        merge_geojson_edges=False,
        merge_bucket_step=0.025,
        use_arcgis_webgl=False,
        arcgis_timeout_sec=20,
        arcgis_metric_field=None,
        analysis_engine_label="test",
        started_at=time.perf_counter(),
    )


def test_full_road_records_are_wgs84_and_topologically_closed():
    result = _result()

    assert result["schema_version"] == "spatial_records/v1"
    assert result["geometry_coord_type"] == "wgs84"
    assert result["render_geometry_coord_type"] == "gcj02"
    node_ids = {feature["properties"]["node_id"] for feature in result["nodes"]["features"]}
    assert all(node_id.startswith("node:") for node_id in node_ids)

    edge = result["road_edges"]["features"][0]
    properties = edge["properties"]
    assert properties["edge_id"].startswith("edge:")
    assert {properties["from_node"], properties["to_node"]} <= node_ids
    assert properties["road_name"] == "测试路"
    assert properties["road_class"] == "residential"
    assert properties["length_m"] > 0
    assert properties["metrics"] == {
        "integration": properties["integration_score"],
        "choice": properties["choice_score"],
        "connectivity": 1.0,
        "depth": 0.0,
        "control": 0.0,
    }
    assert properties["connectivity_score"] == 0.0
    assert result["summary"]["avg_connectivity"] == 1.0
    assert "integration_global" in properties
    assert properties["nain_global"] == round(10**1.2 / 20, 8)
    assert properties["nach_global"] == round(math.log(3) / math.log(23), 8)
    assert properties["node_count_global"] == 10
    assert properties["total_depth_global"] == 20
    assert edge["geometry"]["coordinates"] == [[112.981, 28.191], [112.989, 28.191]]
    assert result["nodes"]["features"][0]["geometry"]["type"] == "Point"
    assert result["summary"]["context_edge_count"] == 1
    assert result["summary"]["output_edge_count"] == 1
    assert result["summary"]["quality_diagnostics"]["connected_component_count"] == 1

    assert result["roads"]["features"][0]["geometry"]["coordinates"] != edge["geometry"]["coordinates"]
    RoadSyntaxResponse.model_validate(result)


def test_axial_headers_derive_total_depth_from_mean_depth_for_nain_and_nach():
    polygon = Polygon(
        [
            (112.98, 28.19),
            (112.99, 28.19),
            (112.99, 28.20),
            (112.98, 28.20),
            (112.98, 28.19),
        ]
    )
    row = {
        "x1": "112.981",
        "y1": "28.191",
        "x2": "112.989",
        "y2": "28.191",
        "Choice": "2",
        "Choice R600": "1",
        "Integration [HH]": "3",
        "Integration [HH] R600": "2",
        "Node Count": "10",
        "Node Count R600": "6",
        "Mean Depth": "2",
        "Mean Depth R600": "1.5",
        "Connectivity": "1",
    }

    result = build_road_analysis_result(
        rows=[row],
        fieldnames=list(row),
        context_wgs_poly=polygon,
        output_wgs_poly=polygon,
        mode="walking",
        local_radii=[600],
        requested_local_labels=["r600"],
        render_metric="choice",
        include_geojson=True,
        max_edge_features=None,
        merge_geojson_edges=False,
        merge_bucket_step=0.025,
        use_arcgis_webgl=False,
        arcgis_timeout_sec=20,
        arcgis_metric_field=None,
        analysis_engine_label="depthmapxcli-axial",
        started_at=time.perf_counter(),
    )

    properties = result["road_edges"]["features"][0]["properties"]
    global_total_depth = 2 * (10 - 1)
    local_total_depth = 1.5 * (6 - 1)
    assert properties["nain_global"] == round(10**1.2 / global_total_depth, 8)
    assert properties["nach_global"] == round(math.log(3) / math.log(global_total_depth + 3), 8)
    assert properties["nain_r600"] == round(6**1.2 / local_total_depth, 8)
    assert properties["nach_r600"] == round(math.log(2) / math.log(local_total_depth + 3), 8)
    assert properties["total_depth_global"] == global_total_depth
    assert properties["total_depth_r600"] == local_total_depth
    RoadSyntaxResponse.model_validate(result)


def test_missing_connectivity_remains_null_instead_of_becoming_a_zero_score():
    polygon = Polygon(
        [
            (112.98, 28.19),
            (112.99, 28.19),
            (112.99, 28.20),
            (112.98, 28.20),
            (112.98, 28.19),
        ]
    )
    row = {
        "x1": "112.981",
        "y1": "28.191",
        "x2": "112.989",
        "y2": "28.191",
        "T1024 Choice": "2",
        "T1024 Integration": "3",
    }

    result = build_road_analysis_result(
        rows=[row],
        fieldnames=list(row),
        context_wgs_poly=polygon,
        output_wgs_poly=polygon,
        mode="walking",
        local_radii=[],
        requested_local_labels=[],
        render_metric="choice",
        include_geojson=True,
        max_edge_features=None,
        merge_geojson_edges=False,
        merge_bucket_step=0.025,
        use_arcgis_webgl=False,
        arcgis_timeout_sec=20,
        arcgis_metric_field=None,
        analysis_engine_label="test",
        started_at=time.perf_counter(),
    )

    properties = result["road_edges"]["features"][0]["properties"]
    assert properties["metrics"]["connectivity"] is None
    assert properties["connectivity_score"] is None
    assert result["summary"]["avg_connectivity"] is None
    RoadSyntaxResponse.model_validate(result)


def test_contract_metadata_is_present_for_empty_results():
    result = empty_result("walking", "wgs84")

    assert result["schema_version"] == "spatial_records/v1"
    assert result["geometry_coord_type"] == "wgs84"
    assert result["render_geometry_coord_type"] == "gcj02"
    RoadSyntaxResponse.model_validate(result)
