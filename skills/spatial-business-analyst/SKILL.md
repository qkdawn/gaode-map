---
name: spatial-business-analyst
description: Analyze locked spatial-project snapshots or versioned history-backed projects and produce evidence-grounded professional reports through a reviewed AnalysisBlueprint, deterministic EvidenceSnapshot, dynamically assigned specialist ChapterPackages, claim-controlled EditorialReview, and direct compilation. Use for trade areas, positioning, demand, competition, access, spatial programming, operations, delivery, feasibility, or any full-project spatial business report that needs specialist subagents, secure SVG evidence, explicit gaps, and auditable conclusions.
---

# Spatial Business Analyst

## Objective

Produce a traceable project judgment rather than a dataset inventory. Connect every material conclusion to evidence or a named gap, a comparison basis, mechanism, project implication, action, assumption, and stop condition.

Use schema v3 for every new Run:

```text
AnalysisBlueprint
→ EvidenceSnapshot
→ ChapterAssignments
→ versioned ChapterPackages
→ EditorialReview, with at most one targeted revision
→ ReportAssembly
→ compiler
→ report/project-report.md + report/assets/*.svg
```

Treat v1 and v2 Runs as immutable inspection sources. Never repair, derive, or republish them in place.

## Roles

The main analyst creates the project-specific blueprint and assignments, commissions an independent completeness review, reviews chapter versions, adjudicates conflicts, and writes only synthesis bound to accepted claim IDs. It must not write, rewrite, or silently replace specialist ArgumentUnits.

The deterministic evidence engine owns capability-to-metric mapping, parameters, adapters, attempts, gaps, readiness, visual rendering, provenance, and hashes. Agents do not author or repair its execution lineage.

Each specialist receives one assignment plus an authorized projection of the EvidenceSnapshot and returns one publication-ready ChapterPackage. It cannot change locked questions, widen evidence access, invent evidence or visual values, publish files, or create `.complete`.

## Load references

1. Read `references/decision-framework.md` before creating an AnalysisBlueprint.
2. Read `references/metric-selection.md` when defining or interpreting an `evidence_capability`; the evidence engine, not the Agent, selects Metric IDs.
3. Read `references/spatial-inference-rules.md` for spatial objects and proxy boundaries.
4. Read `references/report-orchestration.md` before delegation, review, revision, derived delivery views, or failure handling.
5. Read `references/report-contract.md` before writing any schema v3 report object.
6. Read `references/run-layout.md` before persistence, validation, compilation, or publication.
7. Read the lightweight `references/metric-catalog-index.yaml`, then `references/analysis-recipes.md`, only when evaluating candidate metric families. Query shortlisted metric semantics with `scripts/metric_catalog.py describe <metric_ids>`; never load the detailed catalog at startup.

## Required workflow

### Lock the analysis blueprint

Translate the actual project decision into dynamic questions and evidence requirements. Use `document`, `metric`, `spatial`, `comparison`, or `gap`; executable analytic requirements use stable `evidence_capability` keys rather than raw Metric IDs. Embed an independent completeness review and save the blueprint only after acceptance. Its lock binds the source snapshot, content, and capability-registry version.

### Execute and freeze evidence

Let the evidence engine resolve capabilities and produce one EvidenceSnapshot. Every requirement must terminate as usable `measured` or `proxy` evidence, or as an explicit gap with a decision limit and stop condition. Keep attempts and internal MetricPlan details in `execution_lineage`; omit that private field from main-analyst and specialist prompt projections.

Only evidence-bound deterministic visuals may enter the snapshot. Reject SVG scripts, event handlers, external resources, non-fragment links, and `foreignObject`. Missing or failed data produces a gap structure block, never a fabricated numeric chart.

### Lock dynamic assignments

Create final chapters only after evidence execution. Give every decision question exactly one owning chapter. Declare `primary`, `shared`, `gaps`, `visuals`, and `forbidden` access; unlisted evidence is forbidden. Every assigned visual is a required chapter deliverable.

### Author and review chapters

Build each chapter from complete ArgumentUnits:

```text
claim → evidence or gap → baseline → mechanism → project implication
→ action → assumptions → stop condition
```

Length diagnostics are warnings only. Missing reasoning links, omitted tasks, unauthorized citations, fabricated values, or unassigned visuals are hard failures.

Store immutable versions at `chapters/<chapter-id>.vN.json`. Accept `v1` or issue one targeted repair. If `v2` remains invalid, set `chapter_failed`; the main analyst must not author the missing chapter.

Generate `accepted_claims` deterministically from accepted ArgumentUnits and conflict rulings after editorial decisions. The main analyst never writes claim-registry records and cannot synthesize beyond the weakest source state, scope, or caveat.

### Assemble and publish

ReportAssembly contains order, accepted chapter references, transitions, executive summary, and integrated recommendations; it never contains specialist chapter prose. Every substantive synthesis statement cites accepted claim IDs.

Compile from the Run directory. Publish exactly one stakeholder report plus its referenced secure SVG assets. Only successful compilation creates `.complete`.

Use precise failures:

- `waiting_for_user`: required external input, decision, source, or authority is missing;
- `chapter_failed`: a required chapter remains invalid after `v2`;
- `publication_blocked`: contract, lineage, coverage, claim, asset, or assembly validation prevents publication;
- `system_failed`: unexpected runtime or infrastructure failure.

## Completion gate

Verify both locks, complete requirement outcomes, filtered evidence access, immutable chapter versions, one-revision enforcement, system-generated accepted claims, secure visual hashes, claim-bound synthesis, exact report contents, and absence of `.complete` on failure.
