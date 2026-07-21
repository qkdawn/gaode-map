"""ArcGIS direct thematic-map output for completed H3 structure analyses."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

from core.spatial import to_wgs84_geometry
from shapely.geometry import mapping, shape

if TYPE_CHECKING:
    from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule

StructureMapMode = Literal["gi_z", "lisa_i"]


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}"


def _bbox(geometries: list[dict[str, Any]]) -> list[float]:
    bounds = [shape(geometry).bounds for geometry in geometries]
    return [
        min(item[0] for item in bounds), min(item[1] for item in bounds),
        max(item[2] for item in bounds), max(item[3] for item in bounds),
    ]


def _geojson_geometry(geometry: Any) -> dict[str, Any]:
    """Return a JSON-native geometry accepted by the ArcGIS renderer contract."""
    raw = mapping(shape(geometry))

    def _to_list(value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [_to_list(item) for item in value]
        return value

    return {"type": raw["type"], "coordinates": _to_list(raw["coordinates"])}


def _map_definition(
    *,
    mode: StructureMapMode,
    grid_features: list[dict[str, Any]],
    study_scope_geometry: dict[str, Any],
    resolution: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    field = "gi_star_z_score" if mode == "gi_z" else "lisa_i"
    title = "H3 Gi* 热点结构专题图" if mode == "gi_z" else "H3 LISA 局部空间自相关专题图"
    label = "Gi* Z-score" if mode == "gi_z" else "LISA I"
    grid_layer_id = "layer:h3-structure-grid"
    scope_layer_id = "layer:h3-study-scope"
    locator_layer_id = "layer:h3-analysis-locator"

    themed_features: list[dict[str, Any]] = []
    grid_geometries: list[dict[str, Any]] = []
    for feature in grid_features:
        properties = feature.get("properties") if isinstance(feature, dict) else {}
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        cell_id = str((properties or {}).get("h3_id") or "").strip()
        if not cell_id or not isinstance(geometry, dict):
            continue
        try:
            value = float((properties or {}).get(field))
            if value != value:
                continue
            shape(geometry)
        except (TypeError, ValueError):
            continue
        grid_geometries.append(geometry)
        themed_features.append({
            "id": f"h3:{cell_id}",
            "layer_id": grid_layer_id,
            "label": label,
            "role": "grid_metric",
            "geometry": geometry,
            "value": value,
        })
    if not themed_features:
        raise ValueError("H3 structure map has no valid grid metrics")

    scope_shape = shape(study_scope_geometry)
    if scope_shape.is_empty:
        raise ValueError("H3 study scope is empty")
    center = scope_shape.representative_point()
    locator_geometry = {"type": "Point", "coordinates": [float(center.x), float(center.y)]}
    themed_features.extend([
        {
            "id": "h3:study-scope",
            "layer_id": scope_layer_id,
            "label": "本次分析范围",
            "role": "study_scope",
            "geometry": study_scope_geometry,
        },
        {
            "id": "h3:analysis-locator",
            "layer_id": locator_layer_id,
            "label": "分析参考点",
            "role": "context_point",
            "geometry": locator_geometry,
            "value": 0.0,
        },
    ])

    all_geometries = [*grid_geometries, study_scope_geometry, locator_geometry]
    source_id = _stable_id("h3-structure", {"mode": mode, "resolution": resolution, "cells": [item["id"] for item in themed_features]})
    layer_manifest = [
        {
            "layer_id": grid_layer_id, "snapshot_id": "", "source_id": source_id,
            "role": "grid_metric", "required": True, "source_record_count": len(grid_geometries),
            "normalized_feature_count": len(grid_geometries), "geometry_types": ["Polygon"],
            "bbox": _bbox(grid_geometries),
        },
        {
            "layer_id": scope_layer_id, "snapshot_id": "", "source_id": "h3:study-scope",
            "role": "study_scope", "required": True, "source_record_count": 1,
            "normalized_feature_count": 1, "geometry_types": [study_scope_geometry["type"]],
            "bbox": list(scope_shape.bounds),
        },
        {
            "layer_id": locator_layer_id, "snapshot_id": "", "source_id": "h3:analysis-locator",
            "role": "context_point", "required": True, "source_record_count": 1,
            "normalized_feature_count": 1, "geometry_types": ["Point"],
            "bbox": [float(center.x), float(center.y), float(center.x), float(center.y)],
        },
    ]
    input_manifest = {
        "schema_version": "1.0",
        "input_result_ids": [source_id],
        "input_layer_manifest": layer_manifest,
        "input_feature_count": len(themed_features),
        "geometry_types": sorted({str(geometry["type"]) for geometry in all_geometries}),
        "bbox": _bbox(all_geometries),
        "analysis_locator": locator_geometry["coordinates"],
    }
    visual = {
        "visual_id": f"h3-structure-{mode}",
        "visual_type": "thematic_map",
        "title": title,
        "purpose": f"展示本次 H3 网格的 {label} 空间结构。",
        "data": {"style": "graduated", "features": themed_features},
        "layout_version": "h3-structure-map-v1",
        "source_note": "来源：本次 H3 网格与 ArcGIS 空间结构计算结果。",
        "limitation_note": "限制：仅表达本次范围与输入 POI 的空间结构；分析参考点仅用于地图定位。",
        "what_it_shows": f"每个网格按 {label} 连续值着色。",
        "how_to_read": "对照图例比较网格的相对空间结构强度，并结合原始 POI 覆盖进一步核验。",
        "does_not_prove": "不单独证明商业需求、客流或因果关系。",
        "next_validation": "结合实地踏勘、业务数据和时间序列继续验证。",
        "cartographic_requirements": {
            "title": True, "legend": True, "orientation": True, "distance_reference": True,
            "geographic_context": True, "analysis_locator": True, "data_period": True, "limitation_note": True,
        },
        "map_layout": {
            "view": "regional",
            "required_layers": ["road_basemap", "grid_theme", "analysis_reference", "study_scope"],
        },
    }
    return visual, input_manifest, {"source_id": source_id, "title": title}


def _asset_payload(asset: Any, mode: StructureMapMode) -> dict[str, Any]:
    payload = getattr(asset, "payload", {}) if asset is not None else {}
    return {
        "status": str(getattr(asset, "status", "failed")),
        "mode": mode,
        "asset_id": str(getattr(asset, "resource_id", "")),
        "title": str(getattr(asset, "title", "")),
        "summary": str(getattr(asset, "summary", "")),
        "limitations": list(getattr(asset, "limitations", []) or []),
        "svg": payload.get("svg") if isinstance(payload, dict) else None,
        "visual_manifest": payload.get("visual_manifest") if isinstance(payload, dict) else None,
    }


def render_h3_structure_report_maps(
    *,
    grid_features: list[dict[str, Any]],
    polygon: list,
    coord_type: str,
    resolution: int,
    renderer: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Render Gi* and LISA as ArcGIS-owned thematic maps, with no local SVG fallback."""
    if not grid_features:
        return {}
    study_scope = _geojson_geometry(to_wgs84_geometry(polygon, coord_type))
    if renderer is None:
        from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule
        tool = ArcGISSpatialToolModule()
    else:
        tool = renderer
    from modules.spatial_action.metric_tools import MetricResult
    from modules.spatial_action.source_index import SourceIndex

    results: dict[str, dict[str, Any]] = {}
    for mode in ("gi_z", "lisa_i"):
        visual, input_manifest, result_meta = _map_definition(
            mode=mode, grid_features=grid_features, study_scope_geometry=study_scope, resolution=resolution,
        )
        result = MetricResult(
            result_id=result_meta["source_id"], tool_id="h3.arcgis_structure", tool_version="1",
            status="available", summary=visual["purpose"], spatial_scope={"kind": "h3_analysis"},
            time_scope={"basis": "current H3 analysis"},
        )
        source_index = SourceIndex(run_id=_stable_id("h3-render", {"mode": mode, "result": result.result_id}), project_name="H3 分析")
        asset = tool.create_report_visual_asset(
            result=result, visual=visual, source_index=source_index,
            dependency_ids=[result.result_id], study_scope={"kind": "h3_analysis", "resolution": resolution},
            input_manifest=input_manifest,
        )
        results[mode] = _asset_payload(asset, mode)
    return results
