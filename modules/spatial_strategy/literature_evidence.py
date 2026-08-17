from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from core.config import PROJECT_ROOT


class LiteratureEvidenceService:
    """Hide the isolated GraphRAG runtime behind one literature contract."""

    def __init__(self, *, project_root: Path = PROJECT_ROOT) -> None:
        self._project_root = project_root

    def search(
        self,
        *,
        question: str,
        mode: Literal["focused", "synthesis"] = "focused",
        top_k: int = 6,
    ) -> dict[str, Any]:
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return self._invalid("question_required", mode=mode, question="")
        if len(normalized_question) > 2000:
            return self._invalid("question_too_long", mode=mode, question=normalized_question)
        if mode not in {"focused", "synthesis"}:
            return self._invalid("mode_invalid", mode=str(mode), question=normalized_question)
        if not 1 <= int(top_k) <= 10:
            return self._invalid("top_k_out_of_range", mode=mode, question=normalized_question)

        runner = self._project_root / "runtime" / "graphrag-venv" / "Scripts" / "python.exe"
        script = self._project_root / "scripts" / "literature_evidence.py"
        if not runner.exists() or not script.exists():
            return self._unavailable("literature_runtime_not_installed", mode=mode, question=normalized_question)

        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        try:
            completed = subprocess.run(
                [str(runner), str(script)],
                cwd=str(self._project_root),
                input=json.dumps({"question": normalized_question, "mode": mode, "top_k": int(top_k)}, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=150,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._unavailable("literature_evidence_timeout:150", mode=mode, question=normalized_question)
        except OSError:
            return self._unavailable("literature_runner_unavailable", mode=mode, question=normalized_question)

        result = self._last_json_object(completed.stdout)
        if completed.returncode != 0 or result is None:
            error = str((result or {}).get("error") or completed.stderr.strip() or "literature_evidence_failed")
            return self._unavailable(error, mode=mode, question=normalized_question)
        if result.get("status") not in {"available", "unavailable", "invalid_request"}:
            return self._unavailable(str(result.get("error") or "literature_evidence_failed"), mode=mode, question=normalized_question)
        return result

    @staticmethod
    def _last_json_object(output: str) -> dict[str, Any] | None:
        for line in reversed([line.strip() for line in output.splitlines() if line.strip()]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _invalid(error: str, *, mode: str, question: str) -> dict[str, Any]:
        return LiteratureEvidenceService._empty("invalid_request", error, mode=mode, question=question)

    @staticmethod
    def _unavailable(error: str, *, mode: str, question: str) -> dict[str, Any]:
        return LiteratureEvidenceService._empty("unavailable", error, mode=mode, question=question)

    @staticmethod
    def _empty(status: str, error: str, *, mode: str, question: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": status,
            "mode": mode,
            "question": question,
            "answer": None,
            "evidence": [],
            "coverage": {"complete": False, "evidence_count": 0},
            "limitations": ["文献索引或推理服务当前不可用，未返回文献结论。"] if status == "unavailable" else [],
            "method": "",
            "provenance": {},
            "error": error,
        }
