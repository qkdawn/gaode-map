from __future__ import annotations

import json

from modules.h3.arcgis_report_map import render_h3_structure_report_maps
from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule


_SAFE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg"><title>ArcGIS H3 map</title>'
    '<rect width="600" height="400"/></svg>'
)


class _Bridge:
    def __init__(self, *, available: bool = True, status: str = "available") -> None:
        self.available = available
        self.status = status
        self.calls: list[dict] = []

    def capabilities(self) -> dict:
        return {
            "status": "available",
            "render_manifest_version": "1.0",
            "pixel_qa_version": "1.0",
            "max_thematic_features": 10_000,
            "templates": [{
                "template_id": "map.thematic.v1",
                "operation": "thematic_map",
                "version": "v1",
                "implementation_status": "implemented" if self.available else "unavailable",
            }],
        }

    def execute_report_operation(self, payload: dict) -> dict:
        self.calls.append(payload)
        input_manifest = payload["input_manifest"]
        layers = [
            {
                **item,
                "rendered_feature_count": item["normalized_feature_count"],
                "actual_layer_names": [item["layer_id"]],
            }
            for item in input_manifest["input_layer_manifest"]
        ]
        return {
            "status": self.status,
            "summary": "已由 ArcGIS 导出。",
            "limitations": [],
            "svg": _SAFE_SVG if self.status == "available" else None,
            "visual_manifest": {
                "schema_version": "1.0",
                "input_result_ids": input_manifest["input_result_ids"],
                "input_layer_manifest": layers,
                "input_feature_count": input_manifest["input_feature_count"],
                "rendered_feature_count": input_manifest["input_feature_count"],
                "geometry_types": input_manifest["geometry_types"],
                "bbox": input_manifest["bbox"],
                "crs": "EPSG:4326",
                "basemap_status": "approved",
                "road_context_status": "not_provided",
                "legend_items": [item["layer_id"] for item in layers],
                "warnings": [],
                "quality_status": "passed",
                "pixel_quality": {"status": "passed"},
            },
        }


def _polygon() -> list[list[float]]:
    return [
        [121.47, 31.23], [121.48, 31.23], [121.48, 31.24],
        [121.47, 31.24], [121.47, 31.23],
    ]


def _grid_features() -> list[dict]:
    polygon = _polygon()
    return [{
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [polygon]},
        "properties": {"h3_id": "8a123", "gi_star_z_score": 1.2, "lisa_i": 0.3},
    }]


def test_h3_structure_maps_are_rendered_by_arcgis_with_metric_specific_data():
    bridge = _Bridge()
    maps = render_h3_structure_report_maps(
        grid_features=_grid_features(), polygon=_polygon(), coord_type="wgs84", resolution=10,
        renderer=ArcGISSpatialToolModule(client=bridge),
    )

    assert set(maps) == {"gi_z", "lisa_i"}
    assert all(item["status"] == "available" for item in maps.values())
    assert all(item["svg"] == _SAFE_SVG for item in maps.values())
    assert len(bridge.calls) == 2

    gi_call, lisa_call = bridge.calls
    assert all(call["operation"] == "thematic_map" for call in bridge.calls)
    assert all(call["template_id"] == "map.thematic.v1" for call in bridge.calls)
    assert all(call["data_view"]["style"] == "graduated" for call in bridge.calls)
    assert gi_call["data_view"]["features"][0]["value"] == 1.2
    assert lisa_call["data_view"]["features"][0]["value"] == 0.3
    assert isinstance(gi_call["data_view"]["features"][-2]["geometry"]["coordinates"], list)
    assert "data:image" not in json.dumps(bridge.calls, ensure_ascii=False)
    assert "image_url" not in json.dumps(maps, ensure_ascii=False)


def test_h3_structure_maps_report_arcgis_unavailability_without_local_image_fallback():
    bridge = _Bridge(available=False)
    maps = render_h3_structure_report_maps(
        grid_features=_grid_features(), polygon=_polygon(), coord_type="wgs84", resolution=10,
        renderer=ArcGISSpatialToolModule(client=bridge),
    )

    assert {name: item["status"] for name, item in maps.items()} == {
        "gi_z": "unavailable", "lisa_i": "unavailable",
    }
    assert all(item["svg"] is None for item in maps.values())
    assert bridge.calls == []
