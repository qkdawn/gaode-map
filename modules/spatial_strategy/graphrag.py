from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from .schemas import GraphRAGQueryRequest


class GraphRAGQueryError(RuntimeError):
    """A controlled failure from the isolated GraphRAG runner."""


def query_graphrag(request: GraphRAGQueryRequest) -> dict[str, Any]:
    runner = PROJECT_ROOT / "runtime" / "graphrag-venv" / "Scripts" / "python.exe"
    script = PROJECT_ROOT / "scripts" / "graphrag_query.py"
    if not runner.exists() or not script.exists():
        raise GraphRAGQueryError("graphrag_runtime_not_installed")

    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [str(runner), str(script)],
            cwd=str(PROJECT_ROOT),
            input=json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GraphRAGQueryError("graphrag_query_timeout") from exc
    except OSError as exc:
        raise GraphRAGQueryError("graphrag_runner_unavailable") from exc

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    result: dict[str, Any] | None = None
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            result = candidate
            break
    if completed.returncode != 0 or not result:
        detail = str((result or {}).get("error") or completed.stderr.strip() or "graphrag_query_failed")
        raise GraphRAGQueryError(detail)
    if result.get("status") == "unavailable":
        return result
    if result.get("status") != "success":
        raise GraphRAGQueryError(str(result.get("error") or "graphrag_query_failed"))
    return result
