"""Thread-safe runtime registry for immutable spatial metric results."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    return text


@dataclass(frozen=True)
class RuntimeMetricResult:
    history_id: str
    result_id: str
    tool_id: str
    status: str
    structured_result: dict[str, Any]
    time_scope: dict[str, Any]


class MetricResultRegistry:
    """Shares current-session metric results without creating analysis runs."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._results: dict[tuple[str, str], RuntimeMetricResult] = {}

    def register(
        self,
        *,
        history_id: str,
        result_id: str,
        tool_id: str,
        status: str,
        structured_result: Mapping[str, Any],
        time_scope: Mapping[str, Any] | None = None,
    ) -> RuntimeMetricResult:
        record = RuntimeMetricResult(
            history_id=_required_text(history_id, "history_id"),
            result_id=_required_text(result_id, "result_id"),
            tool_id=_required_text(tool_id, "tool_id"),
            status=_required_text(status, "status"),
            structured_result=deepcopy(dict(structured_result)),
            time_scope=deepcopy(dict(time_scope or {})),
        )
        key = (record.history_id, record.result_id)
        with self._lock:
            existing = self._results.get(key)
            if existing is not None and existing != record:
                raise ValueError("runtime_metric_result_immutable")
            self._results[key] = record
        return self._copy(record)

    def get(self, history_id: str, result_id: str) -> RuntimeMetricResult | None:
        key = (
            _required_text(history_id, "history_id"),
            _required_text(result_id, "result_id"),
        )
        with self._lock:
            record = self._results.get(key)
            return self._copy(record) if record is not None else None

    def list(self, history_id: str) -> list[RuntimeMetricResult]:
        normalized_history_id = _required_text(history_id, "history_id")
        with self._lock:
            return [
                self._copy(record)
                for (record_history_id, _), record in self._results.items()
                if record_history_id == normalized_history_id
            ]

    def register_persisted_artifact(self, artifact_path: str | Path) -> RuntimeMetricResult:
        """Load one immutable, versioned result produced outside this process."""
        path = Path(artifact_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != "spatial-runtime-metric-result.v1":
            raise ValueError("persisted_metric_result_schema_invalid")
        required = ("history_id", "result_id", "tool_id", "status", "structured_result", "time_scope")
        if any(field not in payload for field in required):
            raise ValueError("persisted_metric_result_fields_missing")
        return self.register(
            history_id=payload["history_id"],
            result_id=payload["result_id"],
            tool_id=payload["tool_id"],
            status=payload["status"],
            structured_result=payload["structured_result"],
            time_scope=payload["time_scope"],
        )

    @staticmethod
    def _copy(record: RuntimeMetricResult) -> RuntimeMetricResult:
        return RuntimeMetricResult(
            history_id=record.history_id,
            result_id=record.result_id,
            tool_id=record.tool_id,
            status=record.status,
            structured_result=deepcopy(record.structured_result),
            time_scope=deepcopy(record.time_scope),
        )


metric_result_registry = MetricResultRegistry()


__all__ = ["MetricResultRegistry", "RuntimeMetricResult", "metric_result_registry"]
