# Decision framework

Use this reference to create a complete project-specific `AnalysisBlueprint` before evidence execution.

## Begin with the real decision

Identify who decides, what action follows, known and missing spatial scope, irreversible commitments, competing alternatives, required evidence, missing inputs, and the judgments and visuals the report must support.

Do not begin with a preferred concept, fixed agenda taxonomy, fixed chapter list, Metric ID, or available dataset.

## Draft decision questions

Write each question so its answer changes a project choice. Attach:

- a stable question ID and decision use;
- competing hypotheses or same-level alternatives;
- necessary document, metric, spatial, comparison, and gap requirements;
- spatial and temporal scope;
- irreversible risk and disconfirming conditions;
- decision-relevant visual intent.

Executable analytic requirements identify a stable `evidence_capability`. They do not expose Metric IDs, adapter names, or execution order. A question may require no analytic capability when documents, comparisons, or an explicit gap are the correct path.

## Complete the first lock

The embedded independent `completeness_review` checks that:

- every material decision is represented;
- each question is decision-relevant and falsifiable;
- alternatives are comparable;
- irreversible risks and missing boundaries are visible;
- every question has evidence coverage or an explicit gap;
- evidence kinds and capabilities are appropriate;
- every capability exists in the authoritative registry;
- exclusions name their rationale;
- desired visuals can be evidence-bound.

Use `accepted` only when all obligations pass. Revise once for correctable blueprint defects. Use `waiting_for_user` only when acceptance requires external input, authority, or a user decision. Otherwise an unresolved invalid blueprint becomes `publication_blocked`.

The saved blueprint is already locked. Its lock binds the source snapshot hash, canonical blueprint content hash, and capability-registry version. Changing question semantics, evidence requirements, scope, source contracts, or exclusions requires a new Run.

## Interpret evidence readiness

After deterministic execution, use the EvidenceSnapshot question dispositions:

- `ready`: bounded judgment is supportable;
- `conditional`: judgment requires named assumptions and gates;
- `gap_bound`: only the evidence limit and collection gate are supportable;
- `not_reportable`: current evidence cannot safely answer the question.

The second lock is `ChapterAssignments`. Create it only after every blueprint requirement has a terminal evidence or gap outcome.

## Compare same-level alternatives

Define two to four complete alternatives when a genuine choice exists. Compare them against the same questions, spatial units, evidence boundaries, delivery constraints, activation conditions, and stop conditions.

Use this chain:

```text
observed pattern or evidence limit
→ comparison basis
→ plausible mechanism
→ project implication
→ option or spatial action
→ critical assumption
→ disconfirming test
```

Project intentions do not validate demand, customers, operators, payment, competitive advantage, cost, or feasibility.

## Evidence and claim states

EvidenceSnapshot uses only `measured` and `proxy` for positive evidence. Population is not customers; nightlight is not traffic or spending; POI is not demand; road syntax is not observed movement; an isochrone is not a project boundary.

Chapter claims may additionally use `inference`, `recommendation`, and `experimental_assumption`. Never upgrade a source beyond its actual state.

## From evidence to chapters

Group questions into dynamic chapters only after readiness is known. Separate chapters when expertise, evidence, alternatives, or implementation logic genuinely differ. Merge workstreams when separation would create shallow or duplicative chapters.

Every question has exactly one owning chapter. Evidence may be shared only through explicit assignment authorization.

An ArgumentUnit is complete when it has a traceable claim, evidence or gap, comparison basis, mechanism, implication, action, assumptions, and stop condition. Prose length may trigger an editorial warning but is never a standalone validity gate.

## Main-analyst judgment

The main analyst reviews chapters, requests at most one targeted revision, adjudicates conflicts, and writes claim-bound synthesis. It does not author specialist ArgumentUnits or accepted-claim records.

Every executive-summary, transition, integrated recommendation, implementation sequence, or conflict statement must cite system-generated accepted claim IDs. Synthesis cannot become more certain, broader in scope, or less qualified than its sources.
