# Schema v3 AnalysisRun layout

Use one staging workspace and publish once:

```text
runtime/analysis-runs/spatial-business-analyst/<run_id>/
  analysis-run.json
  artifact-index.json
  inputs/
    execution-request.json
    upstream/
  analysis-blueprint.json
  evidence-snapshot.json
  chapter-assignments.json
  chapters/
    <chapter-id>.v1.json
    <chapter-id>.v2.json
  analyst-chapters.json
  editorial-review.json
  report-assembly.json
  report/
    project-report.md
    assets/
      <visual-id>.svg
  .complete
```

Every new domain object uses `schema_version: "3.0"`.

## Domain artifacts

- `analysis-blueprint.json`: accepted blueprint, embedded completeness review, evidence requirements, exclusions, and first lock.
- `evidence-snapshot.json`: positive evidence, gaps, readiness, visuals, and private execution lineage.
- `chapter-assignments.json`: final dynamic assignments, evidence authorization, dependencies, and second lock.
- `chapters/<chapter-id>.vN.json`: immutable specialist ChapterPackage versions.
- `analyst-chapters.json`: version index and accepted version per chapter.
- `editorial-review.json`: version-specific decisions, conflicts, terminology, publication decision, and system-generated accepted claims.
- `report-assembly.json`: accepted chapter references, order, transitions, and claim-bound synthesis.

`analysis-run.json`, `artifact-index.json`, `inputs/execution-request.json`, and `.complete` are storage infrastructure rather than report domain objects. Raw LLM responses and blueprint drafts may remain in provider trace or `inputs/upstream/` audit storage; they are not compiler inputs.

The `vN` in chapter filenames is the chapter revision, not the schema version. Never overwrite a version. Only `v1` and optional `v2` are valid.

## Workspace and state rules

- A running workspace uses `.<run_id>.workspace` and has no `.complete`.
- Persist the blueprint only after its independent completeness review is accepted.
- Changing a locked blueprint semantic requires a new Run.
- Persist ChapterAssignments only after EvidenceSnapshot completion; changing it requires a new Run.
- `waiting_for_user` means required external input, decision, source, or authority is missing.
- `chapter_failed` means a required chapter remains invalid after `v2`.
- `publication_blocked` means contract, lineage, coverage, conflict, claim, SVG, asset, or assembly validation prevents publication.
- `system_failed` means an unexpected provider, runtime, storage, serialization, or infrastructure failure.
- No failure state retains report files or `.complete`.
- Only successful compilation writes report contents and `.complete`, then atomically publishes the final immutable directory.

## Delivery views

A `delivery_view` Run references exactly one completed schema v3 `full_analysis` Run through hash-bound upstream refs. It stores a new ReportAssembly and only the compiled report plus used SVG assets. It does not duplicate or mutate source evidence, chapters, or EditorialReview.

Do not chain delivery views. Do not create delivery views from v1 or v2 Runs.

## Historical compatibility

Schema v1 and v2 Runs are read-only:

- allow list, detail, audit, and lineage inspection;
- do not mutate, repair, append chapter versions, rebuild indexes, compare into a new writable result, derive a delivery view, or republish;
- create a new schema v3 full Run for new evidence or reporting.

## Publication invariant

Every completed Run publishes exactly:

```text
report/project-report.md
report/assets/*.svg
```

Only SVG assets referenced by accepted chapters may appear. Assets must be self-contained and match EvidenceSnapshot `spec_hash` and `asset_hash`. The report directory contains no JSON, raster images, alternate reports, or nested delivery profiles.
