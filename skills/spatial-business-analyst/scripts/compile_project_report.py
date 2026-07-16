#!/usr/bin/env python3
"""Validate a schema-v3 Run directory and compile its one project report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.spatial_action.report_orchestration import (  # noqa: E402
    AnalysisBlueprint,
    AnalystChapterIndex,
    ChapterAssignments,
    ChapterPackage,
    EditorialReview,
    EvidenceSnapshot,
    ReportAssembly,
    validate_report_assembly,
    validate_chapter_package,
    validate_v3_contracts,
)
from modules.spatial_action.report_visuals import validate_safe_svg  # noqa: E402

CITATION_TOKEN = re.compile(r"\[\[cite:([^\]]+)\]\]")


class ReportCompileError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportCompileError(f"cannot read JSON artifact: {path}") from exc


def _model(model: type[BaseModel], payload: Any, label: str) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ReportCompileError(f"invalid {label}: {exc}") from exc


def _escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _replace_citations(text: str, labels: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        evidence_id = match.group(1)
        if evidence_id not in labels:
            raise ReportCompileError(f"chapter cites unknown evidence: {evidence_id}")
        return f"[{labels[evidence_id]}]"
    return CITATION_TOKEN.sub(replace, text)


def _render_statement(statement: Any, claim_labels: dict[str, str]) -> str:
    refs = " ".join(f"[{claim_labels[item]}]" for item in statement.claim_ids)
    return f"{statement.text} {refs}".rstrip()


def _render_argument_table(subsection: Any, evidence_labels: dict[str, str]) -> list[str]:
    lines = [
        "| 论点 | 证据状态 | 比较基准 | 作用机制 | 项目影响 | 行动与停止条件 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for argument in subsection.argument_units:
        refs = " ".join(f"[{evidence_labels[item]}]" for item in argument.evidence_refs if item in evidence_labels)
        evidence = f"{argument.evidence_state} {refs}".strip()
        action = f"{argument.action}；停止条件：{argument.stop_condition}"
        lines.append(
            f"| {_escape(argument.claim)} | {_escape(evidence)} | {_escape(argument.baseline)} | "
            f"{_escape(argument.mechanism)} | {_escape(argument.project_implication)} | {_escape(action)} |"
        )
    return [*lines, ""]


def _render_structured_block(block: Any, evidence_labels: dict[str, str]) -> list[str]:
    lines = [f"#### {_escape(block.title)}", "", _escape(block.purpose), ""]
    if block.kind in {"data_table", "comparison_matrix"}:
        lines.append("| " + " | ".join(_escape(item) for item in block.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in block.columns) + " |")
        lines.extend("| " + " | ".join(_escape(item) for item in row) + " |" for row in block.rows)
    else:
        for item in block.items:
            title_key = next((key for key in ("gate", "title", "phase", "action", "item", "label") if key in item), None)
            title = str(item.get(title_key) or "结构项")
            labels = {"collect": "补证动作", "pass": "通过标准", "blocks": "阻止的决策"}
            details = []
            for key in ("collect", "pass", "blocks"):
                if key in item:
                    details.append(f"{labels[key]}：{item[key]}")
            for key in sorted(item):
                if key != title_key and key not in labels:
                    details.append(f"{key}：{item[key]}")
            suffix = "；".join(details)
            lines.append(f"- **{_escape(title)}**" + (f" — {_escape(suffix)}" if suffix else ""))
    refs = " ".join(f"[{evidence_labels[item]}]" for item in block.evidence_ids if item in evidence_labels)
    if refs:
        lines.extend(["", f"证据：{refs}"])
    return [*lines, ""]


def _load(run_dir: Path, filename: str, model: type[BaseModel]) -> Any:
    path = run_dir / filename
    if not path.is_file():
        raise ReportCompileError(f"schema-v3 Run is missing {filename}")
    return _model(model, _load_json(path), filename)


def _load_chapters(run_dir: Path, index: AnalystChapterIndex) -> tuple[list[ChapterPackage], dict[str, ChapterPackage]]:
    versions: list[ChapterPackage] = []
    accepted: dict[str, ChapterPackage] = {}
    for record in index.chapters:
        for reference in record.versions:
            path = run_dir / "chapters" / reference.filename
            chapter = _model(ChapterPackage, _load_json(path), reference.filename)
            if chapter.chapter_id != record.chapter_id or chapter.chapter_version_id != reference.chapter_version_id:
                raise ReportCompileError("analyst-chapters.json differs from immutable chapter version")
            if chapter.content_hash != reference.content_hash or chapter.assignment_hash != reference.assignment_hash:
                raise ReportCompileError("chapter index hash lineage mismatch")
            versions.append(chapter)
            if reference.chapter_version_id == record.accepted_version_id:
                accepted[record.chapter_id] = chapter
        if record.accepted_version_id and record.chapter_id not in accepted:
            raise ReportCompileError("accepted chapter version is missing")
    return versions, accepted


def _validate(
    run_dir: Path,
    blueprint: AnalysisBlueprint,
    snapshot: EvidenceSnapshot,
    assignments: ChapterAssignments,
    index: AnalystChapterIndex,
    chapters: list[ChapterPackage],
    accepted: dict[str, ChapterPackage],
    review: EditorialReview,
    assembly: ReportAssembly,
    *,
    delivery_view: bool,
) -> dict[str, str]:
    try:
        validate_v3_contracts(blueprint, snapshot, assignments)
        if not delivery_view:
            validate_report_assembly(assembly, review, list(accepted.values()))
    except ValueError as exc:
        raise ReportCompileError(str(exc)) from exc
    source_run_ids = {blueprint.run_id, snapshot.run_id, assignments.run_id, index.run_id, review.run_id}
    if len(source_run_ids) != 1:
        raise ReportCompileError("schema-v3 source artifacts reference different Runs")
    if not delivery_view and assembly.run_id != blueprint.run_id:
        raise ReportCompileError("full-analysis ReportAssembly references another Run")

    assignment_by_id = {item.chapter_id: item for item in assignments.chapters}
    if set(accepted) != set(assignment_by_id):
        raise ReportCompileError("accepted chapters must exactly cover ChapterAssignments")
    known_evidence = {item.evidence_id for item in snapshot.evidence}
    known_gaps = {item.gap_id for item in snapshot.gaps}
    known_visuals = {item.visual_id: item for item in snapshot.visuals}
    used_visuals: set[str] = set()
    for chapter in chapters:
        assignment = assignment_by_id.get(chapter.chapter_id)
        if assignment is None:
            raise ReportCompileError("chapter version has no assignment")
        revision = 2 if chapter.chapter_version_id.lower().endswith("v2") else 1
        try:
            validate_chapter_package(chapter, assignment, snapshot, expected_revision=revision)
        except ValueError as exc:
            raise ReportCompileError(str(exc)) from exc
        if chapter.assignment_hash != assignment.assignment_hash or chapter.evidence_snapshot_hash != snapshot.snapshot_hash:
            raise ReportCompileError("chapter does not bind its assignment and evidence snapshot")
        allowed_evidence = set(assignment.evidence_access.primary + assignment.evidence_access.shared)
        allowed_gaps = set(assignment.evidence_access.gaps)
        allowed_visuals = set(assignment.evidence_access.visuals)
        chapter_visuals = set()
        for subsection in chapter.subsections:
            if not set(subsection.evidence_ids) <= allowed_evidence or not set(subsection.evidence_gap_ids) <= allowed_gaps:
                raise ReportCompileError("chapter subsection used evidence outside its assignment")
            if not set(CITATION_TOKEN.findall(subsection.body)) <= set(subsection.evidence_ids):
                raise ReportCompileError("chapter prose cites undeclared evidence")
            for argument in subsection.argument_units:
                if not set(argument.evidence_refs) <= allowed_evidence or not set(argument.evidence_gap_refs) <= allowed_gaps:
                    raise ReportCompileError("ArgumentUnit used evidence outside its assignment")
            chapter_visuals.update(item.visual_id for item in subsection.visual_refs)
        if chapter_visuals != allowed_visuals:
            raise ReportCompileError("accepted chapter must place every assigned visual")
        used_visuals.update(chapter_visuals)
    if not used_visuals <= set(known_visuals):
        raise ReportCompileError("chapter references an unknown visual")
    if any(not set(item.evidence_refs) <= known_evidence or not set(item.evidence_gap_refs) <= known_gaps for item in review.accepted_claims):
        raise ReportCompileError("accepted claim references unknown evidence or gaps")
    if review.publication_decision != "ready":
        raise ReportCompileError("EditorialReview has not approved publication")

    accepted_refs = {item.chapter_id: item for item in assembly.accepted_chapters}
    if assembly.chapter_order != [item.chapter_id for item in assembly.accepted_chapters] or set(accepted_refs) != set(accepted):
        raise ReportCompileError("ReportAssembly chapter selection differs from accepted versions")
    for chapter_id, reference in accepted_refs.items():
        chapter = accepted[chapter_id]
        if reference.chapter_version_id != chapter.chapter_version_id or reference.content_hash != chapter.content_hash:
            raise ReportCompileError("ReportAssembly accepted chapter hash mismatch")

    assets_dir = run_dir / "report" / "assets"
    asset_hashes: dict[str, str] = {}
    for visual_id in used_visuals:
        visual = known_visuals[visual_id]
        path = assets_dir / visual.filename
        if not path.is_file():
            raise ReportCompileError(f"missing SVG asset: {visual.filename}")
        svg = path.read_text(encoding="utf-8")
        try:
            validate_safe_svg(svg)
        except ValueError as exc:
            raise ReportCompileError(f"unsafe SVG asset: {visual.filename}") from exc
        digest = f"sha256:{hashlib.sha256(svg.encode('utf-8')).hexdigest()}"
        if digest != visual.asset_hash:
            raise ReportCompileError(f"SVG asset hash mismatch: {visual.filename}")
        asset_hashes[visual.filename] = digest
    actual_assets = {item.name for item in assets_dir.glob("*.svg")} if assets_dir.is_dir() else set()
    expected_assets = {known_visuals[item].filename for item in used_visuals}
    if actual_assets != expected_assets:
        raise ReportCompileError("report/assets must contain exactly the visuals used by accepted chapters")
    return asset_hashes


def compile_run_directory(run_dir: Path, *, validate_only: bool = False) -> tuple[str, dict[str, Any]]:
    run_dir = run_dir.resolve()
    source_dir = run_dir
    delivery_view = False
    manifest_path = run_dir / "analysis-run.json"
    if not (run_dir / "analysis-blueprint.json").is_file() and manifest_path.is_file():
        payload = _load_json(manifest_path)
        manifest = payload.get("manifest", payload) if isinstance(payload, dict) else {}
        if manifest.get("run_kind") == "delivery_view" and str(manifest.get("upstream_run_id") or ""):
            source_dir = run_dir.parent / str(manifest["upstream_run_id"])
            delivery_view = True

    blueprint = _load(source_dir, "analysis-blueprint.json", AnalysisBlueprint)
    snapshot = _load(source_dir, "evidence-snapshot.json", EvidenceSnapshot)
    assignments = _load(source_dir, "chapter-assignments.json", ChapterAssignments)
    index = _load(source_dir, "analyst-chapters.json", AnalystChapterIndex)
    review = _load(source_dir, "editorial-review.json", EditorialReview)
    assembly = _load(run_dir, "report-assembly.json", ReportAssembly)
    chapters, accepted = _load_chapters(source_dir, index)
    asset_hashes = _validate(
        run_dir, blueprint, snapshot, assignments, index, chapters, accepted,
        review, assembly, delivery_view=delivery_view,
    )

    evidence_labels = {item.evidence_id: f"E{number}" for number, item in enumerate(snapshot.evidence, start=1)}
    claim_labels = {item.claim_id: f"C{number}" for number, item in enumerate(review.accepted_claims, start=1)}
    visual_by_id = {item.visual_id: item for item in snapshot.visuals}
    transition_by_chapter = {item.before_chapter_id: item for item in assembly.transitions}
    lines = [f"# {assembly.title}", "", "## 执行摘要", "", _render_statement(assembly.executive_summary, claim_labels), ""]
    for chapter_number, chapter_id in enumerate(assembly.chapter_order, start=1):
        chapter = accepted[chapter_id]
        lines.extend([f"## {chapter_number} {_escape(chapter.title)}", "", chapter.thesis, ""])
        for subsection_number, subsection in enumerate(chapter.subsections, start=1):
            lines.extend([
                f"### {chapter_number}.{subsection_number} {_escape(subsection.title)}", "",
                _replace_citations(subsection.body, evidence_labels), "",
            ])
            lines.extend(_render_argument_table(subsection, evidence_labels))
            for block in subsection.structured_blocks:
                lines.extend(_render_structured_block(block, evidence_labels))
            for visual_ref in subsection.visual_refs:
                visual = visual_by_id[visual_ref.visual_id]
                lines.extend([
                    f"**{visual_ref.caption}**", "",
                    f"![{_escape(visual.title)}](assets/{visual.filename})", "",
                    visual_ref.interpretation, "",
                ])
        transition = transition_by_chapter.get(chapter_id)
        if transition:
            lines.extend([_render_statement(transition, claim_labels), ""])
    if assembly.integrated_recommendations:
        lines.extend(["## 综合建议", ""])
        for statement in assembly.integrated_recommendations:
            lines.extend([f"- {_render_statement(statement, claim_labels)}", ""])
    lines.extend(["## 证据与结论索引", "", "### 证据", "", "| 编号 | 证据 | 状态 | 使用边界 |", "| --- | --- | --- | --- |"])
    for evidence in snapshot.evidence:
        lines.append(f"| [{evidence_labels[evidence.evidence_id]}] | {_escape(evidence.evidence_id)} | {evidence.state} | {_escape('；'.join(evidence.limitations) or '仅限声明范围')} |")
    if snapshot.gaps:
        lines.extend(["", "### 证据缺口", "", "| 缺口 | 决策限制 | 补数动作 | 停止条件 |", "| --- | --- | --- | --- |"])
        for gap in snapshot.gaps:
            lines.append(f"| `{_escape(gap.gap_id)}` | {_escape(gap.decision_limit)} | {_escape(gap.collection_action)} | {_escape(gap.stop_condition)} |")
    lines.extend(["", "### 已接受结论", "", "| 编号 | 主张 | 状态 | 来源 |", "| --- | --- | --- | --- |"])
    for claim in review.accepted_claims:
        source = claim.source_chapter_id or claim.source_conflict_id
        lines.append(f"| [{claim_labels[claim.claim_id]}] | {_escape(claim.claim)} | {_escape(claim.evidence_state)} | `{_escape(source)}` |")
    report = "\n".join(lines).rstrip() + "\n"
    output = run_dir / "report" / "project-report.md"
    if not validate_only:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8", newline="\n")
    return report, {
        "path": str(output), "validated_only": validate_only,
        "chapter_count": len(accepted), "evidence_count": len(snapshot.evidence),
        "gap_count": len(snapshot.gaps), "asset_hashes": asset_hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        report, metadata = compile_run_directory(args.run_dir, validate_only=args.validate_only)
    except ReportCompileError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(), **metadata}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
