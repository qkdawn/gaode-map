from __future__ import annotations

import pytest

from modules.spatial_projects.visual_asset_store import SpatialReportVisualAssetStore

SAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><title>Map</title><rect width="10" height="10"/></svg>'


def _manifest():
    return {
        "schema_version": "1.0", "input_result_ids": ["result:one"],
        "input_layer_manifest": [{
            "layer_id": "layer:one", "required": True,
            "normalized_feature_count": 1, "rendered_feature_count": 1,
        }],
        "input_feature_count": 1, "rendered_feature_count": 1,
        "geometry_types": ["Point"], "bbox": [112.0, 28.0, 112.0, 28.0],
        "crs": "EPSG:4326", "basemap_status": "approved",
        "road_context_status": "not_provided", "legend_items": ["点位"],
        "warnings": [], "quality_status": "passed",
        "pixel_quality": {"status": "passed"},
    }


def test_visual_asset_store_persists_and_reads_across_instances(tmp_path):
    first = SpatialReportVisualAssetStore(tmp_path)
    saved = first.save(
        history_id="history-1",
        asset_id="asset:visual:map:abc",
        filename="asset-visual-map-abc.svg",
        svg=SAFE_SVG,
        visual_manifest=_manifest(),
    )

    second = SpatialReportVisualAssetStore(tmp_path)
    assert saved["resource_uri"] == "spatial-report-visual://history-1/asset:visual:map:abc"
    assert second.metadata(history_id="history-1", asset_id="asset:visual:map:abc")["media_type"] == "image/svg+xml"
    assert second.read(history_id="history-1", asset_id="asset:visual:map:abc") == SAFE_SVG
    assert second.read_manifest(history_id="history-1", asset_id="asset:visual:map:abc") == _manifest()
    assert second.metadata(history_id="history-1", asset_id="asset:visual:map:abc")["quality_status"] == "passed"


def test_visual_asset_store_rejects_unsafe_svg_and_invalid_ids(tmp_path):
    store = SpatialReportVisualAssetStore(tmp_path)

    with pytest.raises(ValueError, match="forbidden element"):
        store.save(
            history_id="history-1",
            asset_id="asset:visual:map:abc",
            filename="asset-visual-map-abc.svg",
            svg="<svg><script/></svg>",
            visual_manifest=_manifest(),
        )
    with pytest.raises(ValueError, match="invalid_history_id"):
        store.read(history_id="../outside", asset_id="asset:visual:map:abc")


def test_legacy_svg_remains_readable_but_is_not_verified(tmp_path):
    target = tmp_path / "history-1" / "asset-visual-map-legacy.svg"
    target.parent.mkdir(parents=True)
    target.write_text(SAFE_SVG, encoding="utf-8")
    store = SpatialReportVisualAssetStore(tmp_path)

    assert store.read(history_id="history-1", asset_id="asset:visual:map:legacy") == SAFE_SVG
    manifest = store.read_manifest(history_id="history-1", asset_id="asset:visual:map:legacy")
    assert manifest["quality_status"] == "legacy_unverified"
    assert store.metadata(history_id="history-1", asset_id="asset:visual:map:legacy")["manifest_status"] == "legacy_unverified"
