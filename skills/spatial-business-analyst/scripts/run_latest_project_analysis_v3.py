#!/usr/bin/env python3
"""Run the latest history through the schema-v3 six-object report pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.agent.analysis_runs import (  # noqa: E402
    AnalysisRunV3,
    AnalysisSourceVersion,
    AnalysisStageRecord,
    artifact_ref,
)
from modules.spatial_action.project_context import ProjectSpatialAnalysisService  # noqa: E402
from modules.spatial_action.report_orchestration import (  # noqa: E402
    AnalystChapterIndex,
    ChapterVersionRecord,
    ChapterVersionRef,
    OrchestrationError,
)
from modules.spatial_action.report_pipeline_v3 import (  # noqa: E402
    SpatialReportOrchestratorV3,
    build_evidence_snapshot,
    build_metric_execution_plan,
)
from store.analysis_run_repo import AnalysisRunRepo  # noqa: E402
from store.history_repo import HistoryRepo  # noqa: E402

CAPABILITY_ID = "spatial-business-analyst"
DOCUMENT_SNAPSHOT = ROOT / "runtime" / "project-document-extracts.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_documents() -> dict[str, Any]:
    if not DOCUMENT_SNAPSHOT.is_file():
        return {"project_name": "", "documents": [], "conflicts": []}
    return json.loads(DOCUMENT_SNAPSHOT.read_text(encoding="utf-8"))


def latest_history_id(repo: HistoryRepo) -> str:
    rows = repo.get_list(limit=1)
    if not rows:
        raise RuntimeError("no analysis history is available")
    row = rows[0]
    return str(row.get("id") if isinstance(row, dict) else getattr(row, "id", ""))


def _run(coro: Any, stage: str) -> Any:
    timeout = float(os.environ.get("SPATIAL_REPORT_LLM_TIMEOUT_SECONDS", "120"))
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
    except TimeoutError as exc:
        raise OrchestrationError(f"{stage} timed out", run_status="system_failed") from exc


def _manifest(run: AnalysisRunV3) -> dict[str, Any]:
    candidate = run.model_copy(deep=True)
    candidate.manifest_sha256 = candidate.canonical_manifest_sha256()
    return candidate.model_dump(mode="json")


def _stage(stage_id: str, status: str, summary: str = "", diagnostics: list[str] | None = None) -> AnalysisStageRecord:
    return AnalysisStageRecord(
        stage_id=stage_id,
        title=stage_id.replace("_", " "),
        status=status,
        summary=summary,
        diagnostics=diagnostics or [],
        completed_at=utc_now() if status not in {"pending", "running"} else "",
    )


def _save_failure(
    *,
    repo: AnalysisRunRepo,
    run_id: str,
    history_id: str,
    status: str,
    stage: str,
    message: str,
    request: dict[str, Any],
    payloads: list[tuple[Any, Any]] | None = None,
) -> Path:
    artifacts = payloads or []
    run = AnalysisRunV3(
        run_id=run_id,
        capability_id=CAPABILITY_ID,
        status=status,
        current_stage=stage,
        diagnostics=[message],
        stage_records=[_stage(stage, "waiting_for_user" if status == "waiting_for_user" else "failed", diagnostics=[message])],
        output_artifact_refs=[item[0] for item in artifacts],
        project_context={"history_id": history_id},
        configuration_snapshot={"history_id": history_id},
        execution_profile={"skill_id": CAPABILITY_ID, "schema_version": "3.0"},
        created_at=request["requested_at"],
        completed_at=utc_now(),
    )
    repo.save(
        history_id=history_id,
        manifest=_manifest(run),
        artifact_payloads={ref.artifact_id: payload for ref, payload in artifacts},
        execution_request=request,
    )
    return repo.storage._path(CAPABILITY_ID, run_id)


def _root_artifact(artifact_type: str, filename: str, payload: Any, *, evidence_refs: list[str] | None = None):
    return artifact_ref(
        artifact_id=f"artifact:{artifact_type}",
        artifact_type=artifact_type,
        title=filename,
        filename=filename,
        payload=payload,
        evidence_refs=evidence_refs or [],
        version="3.0",
    ), payload


def _write_workspace(workspace: Path, artifacts: list[tuple[Any, Any]]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "chapters").mkdir(exist_ok=True)
    (workspace / "report" / "assets").mkdir(parents=True, exist_ok=True)
    root_types = {
        "analysis_blueprint", "evidence_snapshot", "chapter_assignments",
        "analyst_chapters", "editorial_review", "report_assembly",
    }
    for reference, payload in artifacts:
        if reference.artifact_type in root_types:
            path = workspace / reference.filename
        elif reference.artifact_type == "report_chapter":
            path = workspace / "chapters" / reference.filename
        elif reference.artifact_type == "report_visual":
            path = workspace / "report" / "assets" / reference.filename
        elif reference.artifact_type == "report":
            path = workspace / "report" / reference.filename
        else:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8", newline="\n")
        else:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-id", default="")
    parser.add_argument("--confirm-llm", action="store_true")
    parser.add_argument("--user-question", default="")
    args = parser.parse_args()

    history_repo = HistoryRepo()
    history_id = args.history_id.strip() or latest_history_id(history_repo)
    detail = history_repo.get_detail(history_id, include_pois=False)
    if not detail:
        raise RuntimeError(f"history not found: {history_id}")
    documents = load_documents()
    service = ProjectSpatialAnalysisService()
    preview = service.inspect_history_snapshot(history_id=history_id, project_documents=documents)
    run_id = f"project-spatial-v3-{history_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    request = {
        "schema_version": "3.0",
        "run_id": run_id,
        "history_id": history_id,
        "user_question": args.user_question.strip(),
        "requested_action": "run_latest_project_analysis",
        "requested_at": utc_now(),
        "llm_confirmation": args.confirm_llm,
    }
    repo = AnalysisRunRepo()
    if not args.confirm_llm:
        path = _save_failure(repo=repo, run_id=run_id, history_id=history_id, status="waiting_for_user", stage="llm_confirmation", message="LLM execution requires explicit --confirm-llm.", request=request)
        print(json.dumps({"run_id": run_id, "status": "waiting_for_user", "run_path": str(path)}, ensure_ascii=False))
        return 0

    persisted: list[tuple[Any, Any]] = []
    try:
        orchestrator = SpatialReportOrchestratorV3()
        blueprint = _run(orchestrator.plan_project_v3(
            run_id=run_id,
            project_documents=documents,
            source_versions=preview["source_versions"],
            data_preview={**preview["data_preview"], "execution_capabilities": preview["execution_capabilities"]},
            analysis_scope="full_project",
            user_question=args.user_question.strip(),
        ), "analysis blueprint")
        persisted.append(_root_artifact("analysis_blueprint", "analysis-blueprint.json", blueprint.model_dump(mode="json")))

        metric_entries, _requirement_by_entry = build_metric_execution_plan(blueprint)
        analysis = service.analyze_history_snapshot(
            history_id=history_id,
            history_detail=detail,
            project_documents=documents,
            decision_questions=[item.model_dump(mode="json") for item in blueprint.decision_questions],
            metric_plan_entries=metric_entries,
        )
        snapshot, svg_assets = build_evidence_snapshot(
            blueprint=blueprint,
            metric_attempts=analysis.metric_attempts,
            evidence_nodes=analysis.evidence_nodes,
            spatial_action_map=analysis.spatial_action_map,
        )
        persisted.append(_root_artifact("evidence_snapshot", "evidence-snapshot.json", snapshot.model_dump(mode="json"), evidence_refs=[item.evidence_id for item in snapshot.evidence]))

        assignments = _run(orchestrator.assign_chapters_v3(blueprint, snapshot), "chapter assignments")
        persisted.append(_root_artifact("chapter_assignments", "chapter-assignments.json", assignments.model_dump(mode="json")))
        chapters, versions, review = _run(orchestrator.author_chapters_v3(
            blueprint=blueprint,
            snapshot=snapshot,
            assignments=assignments,
            project_documents=documents,
        ), "specialist chapters")
        assembly = _run(orchestrator.assemble_with_main_agent_v3(blueprint=blueprint, chapters=chapters, review=review), "report assembly")

        accepted_ids = {item.chapter_version_id for item in review.chapter_decisions if item.status == "accepted"}
        records = []
        for assignment in assignments.chapters:
            chapter_versions = [item for item in versions if item.chapter_id == assignment.chapter_id]
            refs = []
            for chapter in chapter_versions:
                revision = 2 if chapter.chapter_version_id.lower().endswith("v2") else 1
                filename = f"{chapter.chapter_id}.v{revision}.json"
                refs.append(ChapterVersionRef(
                    chapter_version_id=chapter.chapter_version_id,
                    revision=revision,
                    filename=filename,
                    assignment_hash=chapter.assignment_hash,
                    evidence_snapshot_hash=chapter.evidence_snapshot_hash,
                    content_hash=chapter.content_hash,
                ))
                persisted.append((artifact_ref(
                    artifact_id=f"artifact:chapter:{chapter.chapter_version_id}",
                    artifact_type="report_chapter",
                    title=chapter.title,
                    filename=filename,
                    payload=chapter.model_dump(mode="json"),
                    evidence_refs=sorted({ref for subsection in chapter.subsections for ref in subsection.evidence_ids}),
                    version=chapter.chapter_version_id,
                ), chapter.model_dump(mode="json")))
            accepted = next((item.chapter_version_id for item in chapter_versions if item.chapter_version_id in accepted_ids), "")
            records.append(ChapterVersionRecord(chapter_id=assignment.chapter_id, versions=refs, accepted_version_id=accepted))
        index_payload = {"schema_version": "3.0", "run_id": run_id, "chapters": [item.model_dump(mode="json") for item in records]}
        from modules.agent.analysis_runs import content_digest
        index_payload["content_hash"] = content_digest(index_payload)
        index = AnalystChapterIndex.model_validate(index_payload)
        persisted.extend([
            _root_artifact("analyst_chapters", "analyst-chapters.json", index.model_dump(mode="json")),
            _root_artifact("editorial_review", "editorial-review.json", review.model_dump(mode="json")),
            _root_artifact("report_assembly", "report-assembly.json", assembly.model_dump(mode="json")),
        ])
        assigned_visual_ids = {
            visual_id for item in assignments.chapters for visual_id in item.evidence_access.visuals
        }
        for visual in snapshot.visuals:
            if visual.visual_id not in assigned_visual_ids:
                continue
            svg = svg_assets[visual.filename]
            persisted.append((artifact_ref(
                artifact_id=f"artifact:visual:{visual.visual_id}",
                artifact_type="report_visual",
                title=visual.title,
                filename=visual.filename,
                payload=svg,
                evidence_refs=visual.evidence_ids,
                version=visual.asset_hash,
            ), svg))

        workspace = repo.storage.root / CAPABILITY_ID / f".{run_id}.workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        _write_workspace(workspace, persisted)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("compile_project_report.py")), "--run-dir", str(workspace)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise OrchestrationError(result.stderr.strip() or result.stdout.strip(), run_status="publication_blocked")
        report = (workspace / "report" / "project-report.md").read_text(encoding="utf-8")
        report_ref = artifact_ref(
            artifact_id="artifact:report",
            artifact_type="report",
            title=assembly.title,
            filename="project-report.md",
            payload=report,
            evidence_refs=[item.evidence_id for item in snapshot.evidence],
            version=assembly.content_hash,
        )
        persisted.append((report_ref, report))
        stages = [
            _stage("blueprint", "completed"), _stage("evidence", "completed"),
            _stage("chapter_authoring", "completed"), _stage("editorial_review", "completed"),
            _stage("report_compilation", "completed"),
        ]
        run = AnalysisRunV3(
            run_id=run_id,
            capability_id=CAPABILITY_ID,
            source_versions=[AnalysisSourceVersion.model_validate(item) for item in preview["source_versions"]],
            project_context={"history_id": history_id, "project_name": documents.get("project_name", "")},
            configuration_snapshot={"history_id": history_id, "user_question": args.user_question.strip()},
            execution_profile={"skill_id": CAPABILITY_ID, "schema_version": "3.0"},
            status="completed_with_warnings" if analysis.diagnostics else "completed",
            current_stage="report_compilation",
            stage_records=stages,
            diagnostics=analysis.diagnostics,
            output_artifact_refs=[item[0] for item in persisted],
            created_at=request["requested_at"],
            completed_at=utc_now(),
        )
        repo.save(
            history_id=history_id,
            manifest=_manifest(run),
            artifact_payloads={ref.artifact_id: payload for ref, payload in persisted},
            execution_request=request,
        )
        if workspace.exists():
            shutil.rmtree(workspace)
        final = repo.storage._path(CAPABILITY_ID, run_id)
        print(json.dumps({"run_id": run_id, "status": run.status, "report_path": str(final / "report" / "project-report.md"), "compiler": json.loads(result.stdout)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        status = exc.run_status if isinstance(exc, OrchestrationError) else "system_failed"
        if status not in {"waiting_for_user", "chapter_failed", "publication_blocked", "system_failed"}:
            status = "system_failed"
        safe_payloads = [(ref, payload) for ref, payload in persisted if ref.artifact_type not in {"report", "report_visual"}]
        path = _save_failure(repo=repo, run_id=run_id, history_id=history_id, status=status, stage="v3_pipeline", message=str(exc), request=request, payloads=safe_payloads)
        print(json.dumps({"run_id": run_id, "status": status, "run_path": str(path), "diagnostics": [str(exc)]}, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
