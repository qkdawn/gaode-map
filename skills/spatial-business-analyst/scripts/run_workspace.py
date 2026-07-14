#!/usr/bin/env python3
"""Create, validate, and publish AnalysisRun workspaces for this skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store.analysis_run_storage import AnalysisRunStorage


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _artifact_payloads(workspace: Path, manifest: dict) -> dict:
    folders = {"evidence_nodes": "evidence", "report": "report", "diagnostic_report": "diagnostics"}
    payloads = {}
    for artifact in manifest.get("output_artifact_refs") or []:
        artifact_id = str(artifact.get("artifact_id") or "")
        filename = Path(str(artifact.get("filename") or artifact_id)).name
        folder = folders.get(str(artifact.get("artifact_type") or ""), "artifacts")
        path = workspace / folder / filename
        if not path.exists():
            continue
        payloads[artifact_id] = path.read_text(encoding="utf-8") if path.suffix.lower() == ".md" else json.loads(path.read_text(encoding="utf-8"))
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "finalize", "validate"))
    parser.add_argument("--root", default="")
    parser.add_argument("--capability-id", default="spatial-business-analyst")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--history-id", default="")
    parser.add_argument("--manifest")
    parser.add_argument("--request")
    parser.add_argument("--payloads", help="JSON map keyed by output artifact ID")
    args = parser.parse_args()
    storage = AnalysisRunStorage(args.root or None)
    if args.command == "validate":
        storage.validate(args.capability_id, args.run_id)
        print(storage._path(args.capability_id, args.run_id))
        return 0
    if not args.manifest or not args.request:
        parser.error("--manifest and --request are required for init/finalize")
    manifest, request = _load(args.manifest), _load(args.request)
    history_id = args.history_id or str(request.get("history_id") or "")
    if args.command == "init":
        staging = storage.root / args.capability_id / f".{args.run_id}.workspace"
        staging.mkdir(parents=True, exist_ok=True)
        for folder in ("inputs/upstream", "artifacts", "evidence", "report", "diagnostics"):
            (staging / folder).mkdir(parents=True, exist_ok=True)
        (staging / "analysis-run.json").write_text(json.dumps({"history_id": history_id, "manifest": manifest}, ensure_ascii=False), encoding="utf-8")
        (staging / "inputs" / "execution-request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        print(staging)
        return 0
    workspace = storage.root / args.capability_id / f".{args.run_id}.workspace"
    payloads = _load(args.payloads) if args.payloads else _artifact_payloads(workspace, manifest)
    storage.create(history_id=history_id, manifest=manifest, artifact_payloads=payloads, execution_request=request)
    if workspace.exists():
        import shutil
        shutil.rmtree(workspace)
    print(storage._path(args.capability_id, args.run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
