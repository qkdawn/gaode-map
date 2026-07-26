from __future__ import annotations

import json

import pytest

from modules.spatial_action.metric_result_registry import MetricResultRegistry


def test_registry_is_history_scoped_and_returns_defensive_copies() -> None:
    registry = MetricResultRegistry()
    source = {"rows": [{"value": 1}]}
    registry.register(
        history_id="history-1",
        result_id="result:test:1",
        tool_id="test.metric",
        status="available",
        structured_result=source,
        time_scope={"year": 2026},
    )
    source["rows"][0]["value"] = 99

    stored = registry.get("history-1", "result:test:1")
    assert stored is not None
    assert stored.structured_result == {"rows": [{"value": 1}]}
    stored.structured_result["rows"][0]["value"] = 88
    assert registry.get("history-1", "result:test:1").structured_result == {"rows": [{"value": 1}]}
    assert registry.get("history-2", "result:test:1") is None


def test_registry_rejects_mutating_an_existing_result_id() -> None:
    registry = MetricResultRegistry()
    arguments = {
        "history_id": "history-1",
        "result_id": "result:test:1",
        "tool_id": "test.metric",
        "status": "available",
        "structured_result": {"value": 1},
    }
    registry.register(**arguments)
    registry.register(**arguments)

    with pytest.raises(ValueError, match="runtime_metric_result_immutable"):
        registry.register(**{**arguments, "structured_result": {"value": 2}})


def test_registry_loads_a_versioned_persisted_metric_artifact(tmp_path) -> None:
    artifact = tmp_path / "metric.json"
    artifact.write_text(json.dumps({
        "schema": "spatial-runtime-metric-result.v1",
        "history_id": "history-1",
        "result_id": "result:poi-band",
        "tool_id": "poi.distance_band_supply_structure",
        "status": "available",
        "structured_result": {"poi_distance_band_supply_structure": {"year": 2024}},
        "time_scope": {"year": 2024, "scope_kind": "radial_distance_band"},
    }), encoding="utf-8")
    registry = MetricResultRegistry()

    loaded = registry.register_persisted_artifact(artifact)

    assert loaded.history_id == "history-1"
    assert loaded.tool_id == "poi.distance_band_supply_structure"
    assert registry.list("history-1")[0].time_scope["scope_kind"] == "radial_distance_band"
