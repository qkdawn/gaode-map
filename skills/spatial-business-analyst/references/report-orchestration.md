# Schema v3 report orchestration

## Contents

- Pipeline and ownership
- First lock: AnalysisBlueprint
- Evidence execution and projections
- Second lock: ChapterAssignments
- Versioned specialist chapters
- Editorial review and accepted claims
- Assembly and compilation
- Derived delivery views
- Failure and compatibility rules

## Pipeline and ownership

```text
project sources + locked history snapshot
→ main analyst: AnalysisBlueprint draft
→ independent role: completeness review
→ save locked AnalysisBlueprint
→ deterministic engine: EvidenceSnapshot
→ main analyst: locked ChapterAssignments
→ specialist subagents: versioned ChapterPackages
→ main analyst: EditorialReview
→ at most one targeted specialist revision
→ system: accepted claims
→ main analyst: ReportAssembly
→ compiler: project-report.md + referenced SVG assets
```

The six root domain objects are `AnalysisBlueprint`, `EvidenceSnapshot`, `ChapterAssignments`, `ChapterPackage`, `EditorialReview`, and `ReportAssembly`. `analyst-chapters.json` is an immutable version index, not a seventh reasoning object.

The main analyst owns framing, assignments, editorial decisions, conflict adjudication, and claim-bound synthesis. Specialists own publication-ready chapter prose. The evidence engine owns all deterministic selection, execution, gaps, visuals, and provenance.

## First lock: AnalysisBlueprint

Create a mutable draft from the actual project decision. Include project judgment, ordered decision questions, evidence requirements, exclusions with reasons, report logic, and shared terminology.

Commission an independent completeness review. It returns `accepted` or `revise` and records obligation-level findings and repair instructions. The main analyst may repair a correctable draft once. Missing external authority or input produces `waiting_for_user`; unresolved structural invalidity produces `publication_blocked`.

Write `analysis-blueprint.json` only after acceptance. The embedded first lock binds:

- source snapshot hash;
- canonical content hash;
- capability-registry version;
- ordered question and requirement semantics.

Changing any locked semantic creates a new Run. Drafts and independent-review raw responses may remain in provider trace storage but are not public Run artifacts.

## Evidence execution and projections

The evidence engine resolves each semantic capability into its private metric plan, parameters, adapters, spatial targets, activation rules, and execution order. Every requirement receives a terminal attempt.

EvidenceSnapshot exposes:

- positive evidence with state `measured` or `proxy`;
- explicit gaps with decision limits, collection actions, and stop conditions;
- question readiness;
- ready, evidence-bound visual specifications and hashes;
- private `execution_lineage` for audit and diagnostics.

Nothing disappears: blocked, failed, or registered-gap requirements that limit a decision become public gaps. `not_applicable` remains in lineage and creates a gap when its absence limits the question.

Create role-specific projections before prompting an Agent:

- main-analyst projection: public evidence, gaps, readiness, and visual metadata; omit execution lineage and rendered data not needed for framing;
- specialist projection: only evidence, gaps, and visuals authorized by that specialist's assignment; omit execution lineage and all unassigned items.

Never ask an LLM to repair attempts, infer missing numeric values, or author visual provenance.

### Visual safety

Render deterministic SVG bytes before assignment. Each ready visual binds evidence IDs, source and transformation lineage, spatial objects and CRS where applicable, rendering specification, `spec_hash`, and `asset_hash`.

Reject scripts, event attributes, `foreignObject`, JavaScript URLs, remote styles or fonts, external images or resources, network references, and non-fragment links. A visual may not exceed the weakest source evidence state. Missing inputs produce a gap or evidence-gate block, never a placeholder numeric chart.

## Second lock: ChapterAssignments

Create final chapters only after the EvidenceSnapshot is complete. Chapter boundaries follow coherent professional arguments, not a fixed taxonomy or data-source ownership.

Every decision question has exactly one owning chapter. An assignment declares:

- professional role, objective, question IDs, subsection tasks, and required ArgumentUnits;
- `primary`, `shared`, `gaps`, `visuals`, and `forbidden` access;
- dependencies and assignment hash.

The access lists are disjoint. Unlisted evidence is forbidden. `shared` enables explicit cross-chapter use; `gaps` supports only limits and collection gates. Assigned visuals require a factual caption and bounded interpretation in the chapter.

The bundle and each assignment bind the blueprint hash and evidence snapshot hash. Any change after this lock requires a new Run.

## Versioned specialist chapters

Each specialist returns a `ChapterPackage` that covers exactly one assignment. Every substantive ArgumentUnit contains:

```text
claim
→ evidence or gap
→ comparison basis
→ mechanism
→ project implication
→ action
→ assumptions
→ stop condition
```

Subsections contain publication-ready prose and structured blocks such as comparison matrices, implementation timelines, evidence gates, metric cards, and action lists. Specialists reference visual IDs and write captions; they never create chart values.

Hard failures include missing tasks, incomplete reasoning, fabricated numbers, evidence-field mismatch, unauthorized evidence or visuals, treating a gap as positive evidence, and presenting inference as measurement. Length targets create warnings only.

Persist `chapters/<chapter-id>.v1.json`. Never overwrite it. A targeted repair becomes `v2`; `v3` is forbidden. Update `analyst-chapters.json` with both versions and exactly one accepted version per accepted chapter.

## Editorial review and accepted claims

Review concrete chapter version IDs. Preserve every decision:

- accept a valid version;
- request one targeted revision with specific failed obligations;
- reject `v2` and set `chapter_failed` when the repair remains invalid.

The main analyst cannot edit specialist prose. It may define terminology rules and identify conflicts. Every cross-chapter conflict names source ArgumentUnits and ends in a ruling, targeted revision, or block; never merge conflicts silently.

After chapter decisions and conflict rulings, the system generates `accepted_claims` inside EditorialReview from accepted ArgumentUnits and accepted conflict rulings. LLM output must not supply these records. A conflict ruling inherits the weakest evidence state, narrowest scope, and all material caveats of its sources.

Editorial publication decision is `ready`, `revision_required`, or `blocked`. Only `ready` permits assembly.

## Assembly and compilation

ReportAssembly stores only accepted chapter references, order, title, executive summary, transitions, integrated recommendations, conflict references, and a content hash. Its synthesis statements cite accepted claim IDs. It cannot contain specialist prose, ArgumentUnits, or replacement chapter fields.

Compile with:

```bash
python skills/spatial-business-analyst/scripts/compile_project_report.py --run-dir <run-directory>
python skills/spatial-business-analyst/scripts/compile_project_report.py --run-dir <run-directory> --validate-only
```

The compiler loads the Run objects and chapter index, validates all hashes and cross-object invariants, and renders accepted prose without rewriting it. It resolves numbering, evidence citations, structural blocks, and visual links. `--validate-only` performs no publication writes.

Successful compilation publishes exactly `report/project-report.md` and the SVG files referenced by accepted chapters, then creates `.complete`. Failure removes or leaves absent the report directory and `.complete`.

## Derived delivery views

A `delivery_view` references one completed schema v3 full Run through hash-bound upstream references. Chained delivery views are forbidden.

The derived Run creates a new ReportAssembly and compiled report by selecting or reordering accepted chapters and approved structural blocks. It does not call Agents, create new evidence or claims, change chapter prose, or copy unused SVG assets.

Schema v1 and v2 Runs cannot be delivery-view sources.

## Failure and compatibility rules

- `waiting_for_user`: required external input, decision, source, or authority is missing.
- `chapter_failed`: a required ChapterPackage remains invalid after `v2`.
- `publication_blocked`: blueprint, evidence, coverage, lineage, conflict, claim, asset, or assembly validation prevents safe publication.
- `system_failed`: unexpected provider, runtime, storage, serialization, or infrastructure failure.

All new writes use schema v3. Historical v1 and v2 Runs remain readable for inspection, audit, and lineage display only. Never mutate, repair, append chapters, rebuild indexes, derive views, or republish them.
