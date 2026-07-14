from __future__ import annotations

import json

import pytest

from store.analysis_run_storage import AnalysisRunStorage, AnalysisRunStorageError


def _manifest(run_id="run-1", *, source_run_id=""):
    return {
        "run_id": run_id,
        "capability_id": "test-capability",
        "input_artifact_refs": ([{"artifact_id": "output", "artifact_type": "structured_data", "title": "input", "filename": "source.json", "source_run_id": source_run_id, "content_digest": "sha256:input"}] if source_run_id else []),
        "output_artifact_refs": [{"artifact_id": "output", "artifact_type": "report", "title": "report", "filename": "report.md", "content_digest": "sha256:output"}],
    }


def test_storage_publishes_atomically_and_rejects_tampering(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    storage.create(history_id="history", manifest=_manifest(), artifact_payloads={"output": "# report"}, execution_request={"history_id": "history", "analysis_snapshot": {}})
    run_dir = tmp_path / "test-capability" / "run-1"
    assert (run_dir / ".complete").is_file()
    assert storage.read("test-capability", "run-1")["artifacts"][0]["payload"] == "# report"
    (run_dir / "report" / "report.md").write_text("changed", encoding="utf-8")
    with pytest.raises(AnalysisRunStorageError, match="analysis_run_storage_corrupt"):
        storage.read("test-capability", "run-1")


def test_storage_copies_upstream_and_rejects_unsafe_filenames(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    storage.create(history_id="history", manifest=_manifest("source"), artifact_payloads={"output": "# source"}, execution_request={"history_id": "history"})
    downstream = _manifest("downstream", source_run_id="source")
    downstream["output_artifact_refs"] = []
    storage.create(history_id="history", manifest=downstream, artifact_payloads={}, execution_request={"history_id": "history"})
    copied = tmp_path / "test-capability" / "downstream" / "inputs" / "upstream" / "source" / "report.md"
    assert copied.read_text(encoding="utf-8") == "# source"
    unsafe = _manifest("unsafe")
    unsafe["output_artifact_refs"][0]["filename"] = "../escape.md"
    with pytest.raises(ValueError, match="analysis_run_filename_invalid"):
        storage.create(history_id="history", manifest=unsafe, artifact_payloads={"output": "# report"}, execution_request={})
