from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Iterator


class LatencyRecorder:
    def __init__(self) -> None:
        self._started_at = time.perf_counter()
        self._values: Dict[str, int] = {}

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int(round((time.perf_counter() - started_at) * 1000.0)))

    @contextmanager
    def track(self, key: str) -> Iterator[None]:
        started_at = time.perf_counter()
        try:
            yield
        finally:
            self._values[key] = self._elapsed_ms(started_at)

    def set(self, key: str, value: int) -> None:
        self._values[key] = max(0, int(value or 0))

    def finish(self) -> Dict[str, int]:
        self._values["total"] = self._elapsed_ms(self._started_at)
        return self.snapshot()

    def snapshot(self) -> Dict[str, int]:
        return dict(self._values)
