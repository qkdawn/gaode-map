#!/usr/bin/env python3
"""Create immutable schema-v3 delivery views without rewriting accepted chapters."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.agent.analysis_runs import AnalysisRunV3, artifact_ref, content_digest  # noqa: E402
from modules.spatial_action.report_orchestration import ReportAssembly  # noqa: E402
from store.analysis_run_repo import AnalysisRunRepo  # noqa: E402

CAPABILITY_ID = "spatial-business-analyst"
PROFILES = ("diagnostic_note", "positioning_report", "opportunity_report", "spatial_program", "feasibility_report")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest(run: AnalysisRunV3) -> dict[str, Any]:
    candidate = run.model_copy(deep=True)
    candidate.manifest_sha256 = candidate.canonical_manifest_sha256()
    return candidate.model_dump(mode="json")


def _assembly(source: ReportAssembly, *, run_id: str, profile: str) -> ReportAssembly:
    payload = source.model_dump(mode="json", exclude={"content_hash"})
    payload.update({
        "run_id": run_id,
        "assembly_id": f"{source.assembly_id}:{profile}",
        "title": f"{source.title}（{profile}）",
    })
    payload["content_hash"] = content_digest(payload)
    return ReportAssembly.model_validate(payload)


def create_delivery_views(source_dir: Path, profiles: tuple[str, ...]) -> list[dict[str, Any]]:
    repo = AnalysisRunRepo()
    source_payload = _load(source_dir / "analysis-run.json")
    source_manifest = source_payload.get("manifest", source_payload)
    source = AnalysisRunV3.model_validate(source_manifest)
    if source.run_kind != "full_analysis" or source.status not in {"completed", "completed_with_warnings"}:
        raise RuntimeError("delivery views require a completed schema-v3 full_analysis Run")
    source_assembly = ReportAssembly.model_validate(_load(source_dir / "report-assembly.json"))
    source_refs = [item.model_copy(update={"source_run_id": source.run_id}, deep=True) for item in source.output_artifact_refs]
    source_visuals = [item for item in source.output_artifact_refs if item.artifact_type == "report_visual"]
    outputs = []
    history_id = str(source_payload.get("history_id") or source.project_context.get("history_id") or "")
    for profile in profiles:
        run_id = f"{source.run_id}-{profile}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        assembly = _assembly(source_assembly, run_id=run_id, profile=profile)
        assembly_ref = artifact_ref(
            artifact_id=f"artifact:report-assembly:{profile}",
            artifact_type="report_assembly",
            title="report-assembly.json",
            filename="report-assembly.json",
            payload=assembly.model_dump(mode="json"),
            source_run_id=source.run_id,
            source_artifact_refs=["artifact:report_assembly"],
            version=assembly.content_hash,
        )
        workspace = source_dir.parent / f".{run_id}.workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        (workspace / "report" / "assets").mkdir(parents=True)
        (workspace / "report-assembly.json").write_text(json.dumps(assembly.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        running = AnalysisRunV3(
            run_kind="delivery_view",
            upstream_run_id=source.run_id,
            run_id=run_id,
            capability_id=CAPABILITY_ID,
            project_context={"history_id": history_id, "delivery_profile": profile},
            configuration_snapshot={"source_run_id": source.run_id, "delivery_profile": profile},
            execution_profile={"assembly_mode": "reuse_accepted_chapters", "schema_version": "3.0"},
            input_artifact_refs=source_refs,
            output_artifact_refs=[assembly_ref],
            status="running",
            current_stage="report_compilation",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        (workspace / "analysis-run.json").write_text(json.dumps({"history_id": history_id, "manifest": _manifest(running)}, ensure_ascii=False), encoding="utf-8")
        visual_payloads: list[tuple[Any, str]] = []
        for reference in source_visuals:
            svg = (source_dir / "report" / "assets" / reference.filename).read_text(encoding="utf-8")
            (workspace / "report" / "assets" / reference.filename).write_text(svg, encoding="utf-8")
            derived_ref = artifact_ref(
                artifact_id=f"{reference.artifact_id}:derived:{profile}",
                artifact_type="report_visual",
                title=reference.title,
                filename=reference.filename,
                payload=svg,
                source_run_id=source.run_id,
                source_artifact_refs=[reference.artifact_id],
                evidence_refs=reference.evidence_refs,
                version=reference.version,
            )
            visual_payloads.append((derived_ref, svg))
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("compile_project_report.py")), "--run-dir", str(workspace)],
            cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        report = (workspace / "report" / "project-report.md").read_text(encoding="utf-8")
        report_ref = artifact_ref(
            artifact_id=f"artifact:report:{profile}", artifact_type="report", title=assembly.title,
            filename="project-report.md", payload=report, source_run_id=source.run_id,
            source_artifact_refs=[assembly_ref.artifact_id], version=assembly.content_hash,
        )
        completed = running.model_copy(update={
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "output_artifact_refs": [assembly_ref, *[item[0] for item in visual_payloads], report_ref],
        }, deep=True)
        repo.save(
            history_id=history_id,
            manifest=_manifest(completed),
            artifact_payloads={
                assembly_ref.artifact_id: assembly.model_dump(mode="json"),
                **{ref.artifact_id: svg for ref, svg in visual_payloads},
                report_ref.artifact_id: report,
            },
            execution_request={
                "schema_version": "3.0", "history_id": history_id, "source_run_id": source.run_id,
                "delivery_profile": profile, "assembly_mode": "reuse_accepted_chapters",
            },
        )
        if workspace.exists():
            shutil.rmtree(workspace)
        final = repo.storage._path(CAPABILITY_ID, run_id)
        outputs.append({
            "run_id": run_id, "delivery_profile": profile, "status": "completed",
            "report_path": str(final / "report" / "project-report.md"),
            "sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
        })
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", action="append", choices=PROFILES)
    args = parser.parse_args()
    source = AnalysisRunRepo().storage._path(CAPABILITY_ID, args.run_id.strip())
    outputs = create_delivery_views(source, tuple(args.profile or PROFILES))
    print(json.dumps({"source_run_id": args.run_id, "derived_runs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
