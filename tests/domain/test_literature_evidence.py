from __future__ import annotations

import json
import subprocess

import pandas as pd
import pytest

from modules.spatial_strategy.literature_evidence import LiteratureEvidenceService
from scripts.literature_evidence import _evidence_from_units, _query_timeout_seconds


def test_query_timeout_uses_default(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_QUERY_TIMEOUT_SECONDS", raising=False)

    assert _query_timeout_seconds() == 120


@pytest.mark.parametrize("value", ["0", "invalid"])
def test_query_timeout_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("GRAPHRAG_QUERY_TIMEOUT_SECONDS", value)

    with pytest.raises(RuntimeError):
        _query_timeout_seconds()


def test_evidence_projection_deduplicates_documents_and_hides_paths():
    evidence = _evidence_from_units(
        [
            {"id": "unit-1", "human_readable_id": 42, "document_id": "doc-1", "text": "First evidence."},
            {"id": "unit-2", "human_readable_id": 43, "document_id": "doc-1", "text": "Duplicate document."},
            {"id": "unit-3", "human_readable_id": 44, "document_id": "doc-2", "text": "Second evidence."},
        ],
        pd.DataFrame([
            {"id": "doc-1", "title": "source-one.pdf", "text": "First evidence."},
            {"id": "doc-2", "title": "source-two.pdf", "text": "Second evidence."},
        ]),
        top_k=5,
    )

    assert [item["evidence_id"] for item in evidence] == [
        "literature:text_unit:42",
        "literature:text_unit:44",
    ]
    assert evidence[0]["page_start"] == 1
    assert "source_url" not in evidence[0]
    assert "D:/" not in json.dumps(evidence)


def test_service_returns_runner_contract(monkeypatch, tmp_path):
    runner = tmp_path / "runtime" / "graphrag-venv" / "Scripts" / "python.exe"
    script = tmp_path / "scripts" / "literature_evidence.py"
    runner.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    runner.touch()
    script.touch()
    result = {
        "schema_version": "1.0",
        "status": "available",
        "mode": "focused",
        "question": "Historic Urban Landscape",
        "answer": None,
        "evidence": [{"evidence_id": "literature:text_unit:1"}],
        "coverage": {"complete": True, "evidence_count": 1},
        "limitations": [],
        "method": "graphrag_lancedb_vector",
        "provenance": {"index": "microsoft_graphrag"},
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(result), ""),
    )

    assert LiteratureEvidenceService(project_root=tmp_path).search(
        question=" Historic Urban Landscape ", mode="focused", top_k=4
    ) == result


@pytest.mark.parametrize(
    ("question", "mode", "top_k", "error"),
    [
        ("", "focused", 6, "question_required"),
        ("question", "invalid", 6, "mode_invalid"),
        ("question", "focused", 0, "top_k_out_of_range"),
        ("question", "focused", 11, "top_k_out_of_range"),
    ],
)
def test_service_rejects_invalid_requests(question, mode, top_k, error):
    result = LiteratureEvidenceService().search(question=question, mode=mode, top_k=top_k)

    assert result["status"] == "invalid_request"
    assert result["error"] == error
    assert result["evidence"] == []


def test_service_reports_missing_runtime_without_fallback(tmp_path):
    result = LiteratureEvidenceService(project_root=tmp_path).search(
        question="Historic Urban Landscape", mode="synthesis", top_k=6
    )

    assert result["status"] == "unavailable"
    assert result["mode"] == "synthesis"
    assert result["answer"] is None
    assert result["evidence"] == []
    assert result["error"] == "literature_runtime_not_installed"
