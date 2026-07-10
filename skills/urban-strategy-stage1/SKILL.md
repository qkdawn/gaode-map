---
name: urban-strategy-stage1
description: Build an evidence-grounded Stage 1 urban and regional strategy from exported project sources, GIS results, documents, images, web evidence, and a project brief. Use when Codex must simulate an urban planning analyst, cultural-tourism strategist, urban-renewal consultant, and commercial/operations analyst to decide what a place should do, compare positioning options, produce a professional Chinese planning report, and create a structured handoff for a later architecture/site-design stage.
---

# Urban Strategy Stage 1

Produce a decision dossier, not a long-form answer assembled from role-play.

## Required outcome

Answer: **what should this place do, for whom, why here, under which constraints, and through what spatial, operational, and phased strategy?**

Do not design building form, façade, structure, or construction details. End with a design handoff that lets Stage 2 solve those questions.

## Start here

If the user only has a full source export, scaffold a run first:

```powershell
python scripts/prepare_project_run.py --sources-export <ppt_sources_full_export.json> --out <run-dir> --project-name "<项目名>" --boundary <project_boundary.geojson>
```

The initializer refuses to overwrite a non-empty target directory. Edit the generated `project_brief.md` and package before analysis.

1. Locate `urban_project_analysis_package.json`.
2. Run:

```powershell
python scripts/validate_project_package.py <package-path> --write-readiness <run-dir>/work/source_readiness.json
```

3. Stop confident synthesis if the package lacks a project brief, a usable scope, or readable core project documents. Produce a readiness report and missing-input request instead.
4. Read only the references needed for the current step:
   - evidence rules: `references/evidence-policy.md`
   - expert outputs: `references/expert-workpacks.md`
   - final report: `references/report-template.md`
5. Create the run folders shown in `references/run-layout.md`.

## Workflow

### 1. Inspect and normalize

- Treat the package as the project boundary of truth.
- Resolve referenced files relative to the package file.
- Record source dates, spatial scopes, locators, and quality limitations.
- Separate project facts, policy/plan evidence, measured GIS results, visual observations, external references, design intent, inference, and hypotheses.
- Never silently reconcile conflicting area, function, ownership, date, or positioning statements.

Write:

- `work/source_readiness.json`
- `work/conflict_register.json`
- `work/evidence_ledger.jsonl`

### 2. Define research questions

Translate the brief into a compact set of decision questions covering:

- regional role and spatial structure;
- target users and unmet needs;
- cultural/tourism assets and experience opportunities;
- existing-space adaptability and renewal constraints;
- program, operation, governance, and phasing;
- conditions that would invalidate a proposed direction.

Do not let source availability alone determine the research agenda.

### 3. Produce shared-evidence expert workpacks

Create the four workpacks defined in `references/expert-workpacks.md`:

- urban planning and spatial structure;
- cultural tourism and experience;
- urban renewal and implementation;
- commercial, users, and operations.

Each workpack must cite evidence IDs from the shared ledger. Roles may interpret shared evidence differently, but may not create separate facts.

### 4. Generate and challenge options

Create 2–4 genuinely different positioning options. For each option record:

- positioning statement;
- target users and problem solved;
- core, supporting, public, and excluded programs;
- required spatial carriers;
- operating model;
- evidence support;
- assumptions and prerequisites;
- risks and disconfirming evidence;
- minimum viable validation.

Compare options qualitatively using evidence support, local distinctiveness, demand fit, spatial fit, renewal feasibility, operational sustainability, public value, and testability. Do not manufacture precise composite scores.

Write:

- `work/strategy_options.json`
- `work/decision_matrix.json`

### 5. Synthesize the preferred strategy

Use a conditional recommendation:

> Under the current evidence and constraints, option A is preferred because … . It depends on conditions X and Y. If condition Z fails, switch to option B.

Translate the recommendation into:

- function and program mix;
- spatial zones, anchors, connections, interfaces, and day/night use;
- content, operation, governance, and partnerships;
- renewal principles and phasing;
- early experiments and verification actions;
- explicit exclusions and unresolved decisions.

### 6. Write and audit deliverables

Create:

- `output/stage1_report.md`
- `output/evidence_appendix.md`
- `output/design_handoff.json`
- `output/run_manifest.json`

Use `references/report-template.md`. Validate outputs:

```powershell
python scripts/validate_stage1_outputs.py <run-dir>
```

Fix missing evidence references, invalid statuses, unresolved critical conflicts hidden from the report, and handoff sections that are empty.

## Evidence rules

- Cite project documents by filename and page/image/table locator.
- Cite GIS results by artifact/source ID, spatial scope, year, and method or metric name.
- Describe map/image observations as observations, not measured facts.
- Never convert POI, population, H3, nightlight, or road-network proxies into footfall, spending, revenue, or investment-return facts.
- Treat design vision as intent, not current reality.
- Mark unsupported but useful ideas as hypotheses and attach a validation action.
- Prefer ranges, levels, and decision conditions over false precision.
- If evidence is insufficient, make the gap part of the product behavior.

## Completion gate

A run is complete only when:

- the preferred recommendation traces to ledger evidence;
- alternative options and rejection reasons are visible;
- conflicts and critical gaps are disclosed;
- the report distinguishes fact, inference, and hypothesis;
- program recommendations connect to spatial carriers and operations;
- `design_handoff.json` contains constraints, open questions, and evidence refs;
- both validation scripts pass.
