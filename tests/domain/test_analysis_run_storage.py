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


def _v3_ref(artifact_id, artifact_type, filename=""):
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "title": artifact_id,
        "filename": filename,
    }


def test_v3_failed_run_is_inspectable_without_complete_or_report_files(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    manifest = {
        "schema_version": "3.0",
        "run_id": "failed-run",
        "capability_id": "spatial-business-analyst",
        "status": "chapter_failed",
        "output_artifact_refs": [
            _v3_ref("blueprint", "analysis_blueprint", "analysis-blueprint.json"),
            _v3_ref("chapters", "analyst_chapters", "analyst-chapters.json"),
            _v3_ref("review", "editorial_review", "editorial-review.json"),
        ],
    }
    storage.create(
        history_id="history",
        manifest=manifest,
        artifact_payloads={"blueprint": {}, "chapters": {}, "review": {}},
        execution_request={"history_id": "history"},
    )

    run_dir = tmp_path / "spatial-business-analyst" / "failed-run"
    assert not (run_dir / ".complete").exists()
    assert (run_dir / ".run-state.json").is_file()
    assert (run_dir / "analysis-blueprint.json").is_file()
    assert not list((run_dir / "report").glob("*"))
    assert not (run_dir / "artifacts").exists()
    assert not (run_dir / "evidence").exists()
    assert not (run_dir / "diagnostics").exists()
    assert storage.read("spatial-business-analyst", "failed-run")["run"]["status"] == "chapter_failed"


def test_v3_failed_run_rejects_report_artifacts(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    manifest = {
        "schema_version": "3.0",
        "run_id": "invalid-failed-run",
        "capability_id": "spatial-business-analyst",
        "status": "publication_blocked",
        "output_artifact_refs": [
            _v3_ref("report", "report", "project-report.md"),
        ],
    }
    with pytest.raises(AnalysisRunStorageError, match="analysis_run_storage_corrupt"):
        storage.create(
            history_id="history",
            manifest=manifest,
            artifact_payloads={"report": "# 不应发布"},
            execution_request={"history_id": "history"},
        )


def test_v3_completed_run_routes_six_root_artifacts_and_report(tmp_path):
    storage = AnalysisRunStorage(tmp_path)
    roots = [
        ("blueprint", "analysis_blueprint", "analysis-blueprint.json"),
        ("evidence", "evidence_snapshot", "evidence-snapshot.json"),
        ("assignments", "chapter_assignments", "chapter-assignments.json"),
        ("chapter-index", "analyst_chapters", "analyst-chapters.json"),
        ("review", "editorial_review", "editorial-review.json"),
        ("assembly", "report_assembly", "report-assembly.json"),
    ]
    refs = [_v3_ref(*item) for item in roots]
    refs.extend(
        [
            _v3_ref("chapter-market-v1", "report_chapter", "market.v1.json"),
            _v3_ref("report", "report", "project-report.md"),
        ]
    )
    manifest = {
        "schema_version": "3.0",
        "run_id": "complete-run",
        "capability_id": "spatial-business-analyst",
        "status": "completed",
        "output_artifact_refs": refs,
    }
    payloads = {artifact_id: {} for artifact_id, _, _ in roots}
    payloads.update({"chapter-market-v1": {}, "report": "# 项目报告"})
    storage.create(
        history_id="history",
        manifest=manifest,
        artifact_payloads=payloads,
        execution_request={"history_id": "history"},
    )

    run_dir = tmp_path / "spatial-business-analyst" / "complete-run"
    assert (run_dir / ".complete").is_file()
    assert not (run_dir / ".run-state.json").exists()
    for _, _, filename in roots:
        assert (run_dir / filename).is_file()
    assert (run_dir / "chapters" / "market.v1.json").is_file()
    assert (run_dir / "report" / "project-report.md").read_text(encoding="utf-8") == "# 项目报告"
