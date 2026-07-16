from __future__ import annotations

import json
import importlib.util
import shutil
from pathlib import Path

from modules.spatial_action.report_orchestration import (
    AnalystChapterIndex,
    ChapterAssignments,
    ChapterPackage,
    EditorialReviewDraft,
    ReportAssembly,
    _digest,
    build_editorial_review,
)
from tests.domain.test_spatial_business_report_contracts_v3 import _assignments, _blueprint, _chapter, _snapshot

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "compile_project_report_v3",
    ROOT / "skills" / "spatial-business-analyst" / "scripts" / "compile_project_report.py",
)
assert SPEC and SPEC.loader
COMPILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPILER)
compile_run_directory = COMPILER.compile_run_directory


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_v3_compiler_loads_one_run_directory_and_preserves_chapter_text(tmp_path: Path):
    blueprint = _blueprint()
    snapshot_payload = _snapshot().model_dump(mode="json")
    snapshot_payload["visuals"] = []
    snapshot_payload["snapshot_hash"] = _digest({key: value for key, value in snapshot_payload.items() if key != "snapshot_hash"})
    from modules.spatial_action.report_orchestration import EvidenceSnapshot
    snapshot = EvidenceSnapshot.model_validate(snapshot_payload)

    assignments_payload = _assignments().model_dump(mode="json")
    assignments_payload["evidence_snapshot_hash"] = snapshot.snapshot_hash
    assignment = assignments_payload["chapters"][0]
    assignment["evidence_access"]["visuals"] = []
    assignment["assignment_hash"] = _digest({
        "blueprint_hash": blueprint.lock.content_hash,
        "evidence_snapshot_hash": snapshot.snapshot_hash,
        "assignment": {key: value for key, value in assignment.items() if key != "assignment_hash"},
    })
    assignments_payload["content_hash"] = _digest({key: value for key, value in assignments_payload.items() if key != "content_hash"})
    assignments = ChapterAssignments.model_validate(assignments_payload)

    chapter_payload = _chapter().model_dump(mode="json")
    chapter_payload["assignment_hash"] = assignments.chapters[0].assignment_hash
    chapter_payload["evidence_snapshot_hash"] = snapshot.snapshot_hash
    chapter_payload["subsections"][0]["visual_refs"] = []
    chapter_payload["content_hash"] = _digest({key: value for key, value in chapter_payload.items() if key != "content_hash"})
    chapter = ChapterPackage.model_validate(chapter_payload)
    review = build_editorial_review(EditorialReviewDraft.model_validate({
        "schema_version": "3.0",
        "run_id": blueprint.run_id,
        "review_id": "review:v3",
        "chapter_decisions": [{
            "chapter_id": chapter.chapter_id,
            "chapter_version_id": chapter.chapter_version_id,
            "status": "accepted",
            "reason": "论证链完整。",
            "repair_instructions": [],
        }],
        "conflicts": [],
        "terminology_rules": {},
        "publication_decision": "ready",
    }), [chapter])
    index_payload = {
        "schema_version": "3.0",
        "run_id": blueprint.run_id,
        "chapters": [{
            "chapter_id": chapter.chapter_id,
            "versions": [{
                "chapter_version_id": chapter.chapter_version_id,
                "revision": 1,
                "filename": "chapter:role.v1.json",
                "assignment_hash": chapter.assignment_hash,
                "evidence_snapshot_hash": chapter.evidence_snapshot_hash,
                "content_hash": chapter.content_hash,
            }],
            "accepted_version_id": chapter.chapter_version_id,
        }],
    }
    index_payload["content_hash"] = _digest(index_payload)
    index = AnalystChapterIndex.model_validate(index_payload)
    assembly_payload = {
        "schema_version": "3.0",
        "run_id": blueprint.run_id,
        "assembly_id": "assembly:v3",
        "title": blueprint.report_title,
        "accepted_chapters": [{
            "chapter_id": chapter.chapter_id,
            "chapter_version_id": chapter.chapter_version_id,
            "content_hash": chapter.content_hash,
        }],
        "chapter_order": [chapter.chapter_id],
        "executive_summary": {"text": "先以低承诺试点验证。", "claim_ids": ["claim:role"]},
        "transitions": [],
        "integrated_recommendations": [],
        "conflict_references": [],
    }
    assembly_payload["content_hash"] = _digest(assembly_payload)
    assembly = ReportAssembly.model_validate(assembly_payload)

    _write(tmp_path / "analysis-blueprint.json", blueprint.model_dump(mode="json"))
    _write(tmp_path / "evidence-snapshot.json", snapshot.model_dump(mode="json"))
    _write(tmp_path / "chapter-assignments.json", assignments.model_dump(mode="json"))
    _write(tmp_path / "analyst-chapters.json", index.model_dump(mode="json"))
    _write(tmp_path / "editorial-review.json", review.model_dump(mode="json"))
    _write(tmp_path / "report-assembly.json", assembly.model_dump(mode="json"))
    _write(tmp_path / "chapters" / "chapter:role.v1.json", chapter.model_dump(mode="json"))
    (tmp_path / "report" / "assets").mkdir(parents=True)

    report, metadata = compile_run_directory(tmp_path)
    assert "短正文也允许，完整性由结构化论证链保证。" in report
    assert metadata["chapter_count"] == 1
    output = tmp_path / "report" / "project-report.md"
    assert output.read_text(encoding="utf-8") == report
    output.unlink()
    compile_run_directory(tmp_path, validate_only=True)
    assert not output.exists()

    derived = tmp_path.parent / f"{tmp_path.name}-delivery"
    derived.mkdir()
    derived_assembly_payload = assembly.model_dump(mode="json", exclude={"content_hash"})
    derived_assembly_payload.update({"run_id": "run:delivery", "assembly_id": "assembly:delivery"})
    derived_assembly_payload["content_hash"] = _digest(derived_assembly_payload)
    _write(derived / "report-assembly.json", derived_assembly_payload)
    _write(derived / "analysis-run.json", {
        "history_id": "history:v3",
        "manifest": {
            "schema_version": "3.0",
            "run_kind": "delivery_view",
            "upstream_run_id": tmp_path.name,
            "run_id": "run:delivery",
            "capability_id": "spatial-business-analyst",
            "status": "running",
            "created_at": "2026-07-17T00:00:00Z",
        },
    })
    (derived / "report" / "assets").mkdir(parents=True)
    derived_report, _ = compile_run_directory(derived)
    assert "短正文也允许" in derived_report
    shutil.rmtree(derived)
