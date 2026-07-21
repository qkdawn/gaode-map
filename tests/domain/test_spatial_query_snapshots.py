from __future__ import annotations

import pytest
from shapely.geometry import MultiPolygon, Point, box

from modules.scope_datasets.service import ScopeDatasetService, ScopeRecord
from modules.spatial_projects.query_snapshot_store import SpatialQuerySnapshotStore


def _record(record_id, geometry, **properties):
    return ScopeRecord(
        source_id="current:dataset:poi", record_id=record_id, title=record_id,
        content=record_id, properties=properties, raw={}, time_scope={"year": 2024},
        locator=record_id, citation="test", geometry=geometry,
    )


class _DatasetService(ScopeDatasetService):
    def __init__(self, records):
        self._records = records

    def _records_with_selection(self, **_kwargs):
        return list(self._records), [2024], 2024


def test_materialized_snapshot_normalizes_all_parts_without_pagination_or_truncation():
    service = _DatasetService([
        _record("point", Point(112.0, 28.0), category="餐饮"),
        _record("multi", MultiPolygon([box(112.0, 28.0, 112.01, 28.01), box(112.02, 28.0, 112.03, 28.01)]), category="餐饮"),
    ])

    result = service.materialize_query_snapshot(
        history_id="history-1", source_id="current:dataset:poi",
        filters={"category": "餐饮"},
    )

    assert result["status"] == "available"
    assert result["record_count"] == 2
    assert result["normalized_feature_count"] == 3
    assert len(result["features"]) == 3


def test_snapshot_is_content_addressed_and_query_changes_change_digest(tmp_path):
    store = SpatialQuerySnapshotStore(tmp_path)
    selection = {
        "record_count": 1, "normalized_feature_count": 1, "warnings": [],
        "selected_year": 2024,
        "features": [{
            "id": "one:part:1", "record_id": "one", "source_id": "current:dataset:poi",
            "title": "one", "properties": {"category": "餐饮"},
            "geometry": {"type": "Point", "coordinates": [112.0, 28.0]},
        }],
    }
    first = store.create(
        history_id="history-1", source_id="current:dataset:poi", year=2024,
        filters={"category": "餐饮"}, spatial=None, selection=selection,
    )
    repeated = store.create(
        history_id="history-1", source_id="current:dataset:poi", year=2024,
        filters={"category": "餐饮"}, spatial=None, selection=selection,
    )
    changed = store.create(
        history_id="history-1", source_id="current:dataset:poi", year=2024,
        filters={"category": "零售"}, spatial=None, selection=selection,
    )

    assert repeated["snapshot_id"] == first["snapshot_id"]
    assert repeated["digest"] == first["digest"]
    assert changed["snapshot_id"] != first["snapshot_id"]
    assert "features" not in first
    assert store.read(history_id="history-1", snapshot_id=first["snapshot_id"])["features"]
    with pytest.raises(LookupError, match="snapshot_not_found"):
        store.read(history_id="history-2", snapshot_id=first["snapshot_id"])


def test_materialization_rejects_over_limit_without_sampling():
    service = _DatasetService([_record(f"p-{index}", Point(112.0 + index / 1_000_000, 28.0)) for index in range(3)])

    result = service.materialize_query_snapshot(
        history_id="history-1", source_id="current:dataset:poi", max_features=2,
    )

    assert result["status"] == "unavailable"
    assert result["normalized_feature_count"] == 3
    assert result["features"] == []
    assert result["failure_reasons"] == ["normalized_feature_count_exceeds_limit:2"]
