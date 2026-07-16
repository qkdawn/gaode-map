from __future__ import annotations

import importlib.util
from pathlib import Path

from modules.spatial_action.report_orchestration import ReportAssembly, _digest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "spatial-business-analyst" / "scripts" / "run_latest_delivery_profile_exports_v3.py"
SPEC = importlib.util.spec_from_file_location("delivery_exports_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source_assembly() -> ReportAssembly:
    payload = {
        "schema_version": "3.0",
        "run_id": "run:source",
        "assembly_id": "assembly:source",
        "title": "项目报告",
        "accepted_chapters": [{
            "chapter_id": "chapter:one",
            "chapter_version_id": "chapter:one:v1",
            "content_hash": "sha256:chapter",
        }],
        "chapter_order": ["chapter:one"],
        "executive_summary": {"text": "综合判断", "claim_ids": ["claim:one"]},
        "transitions": [],
        "integrated_recommendations": [{"text": "继续验证", "claim_ids": ["claim:one"]}],
        "conflict_references": [],
    }
    payload["content_hash"] = _digest(payload)
    return ReportAssembly.model_validate(payload)


def test_delivery_view_reuses_accepted_content_and_changes_only_assembly_identity():
    source = _source_assembly()
    derived = MODULE._assembly(source, run_id="run:derived", profile="positioning_report")
    assert derived.run_id == "run:derived"
    assert derived.accepted_chapters == source.accepted_chapters
    assert derived.chapter_order == source.chapter_order
    assert derived.executive_summary == source.executive_summary
    assert derived.integrated_recommendations == source.integrated_recommendations
    assert derived.title.endswith("（positioning_report）")


def test_delivery_view_script_never_calls_an_llm_or_rewrites_chapters():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "chat_json" not in source
    assert "SpatialReportOrchestrator" not in source
    assert "reuse_accepted_chapters" in source
    assert "upstream_run_id" in source
    assert '"--run-dir"' in source
