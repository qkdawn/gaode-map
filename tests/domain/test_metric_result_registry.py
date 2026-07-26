from __future__ import annotations

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
