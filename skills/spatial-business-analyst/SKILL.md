---
name: spatial-business-analyst
description: Analyze locked Spatial Project MCP snapshots or versioned history-backed projects to produce decision-oriented, site-specific commercial geography and spatial-programming recommendations. Use for urban-regeneration positioning, trade-area analysis, customer-source analysis, commercial opportunity screening, competition review, site suitability, or allocating functions to entrances, streets, buildings, courtyards, and public spaces. Normalize spatial comparisons, distinguish positioning from feasibility, and convert evidence into project decisions instead of generic dataset summaries.
---

# Spatial Business Analyst

## Objective

Produce a spatial decision document, not a dataset inventory or compliance memo.

The report must answer:

1. What spatial patterns exist?
2. What causes or mechanisms may explain them?
3. How do they affect this project?
4. Which strategic direction performs best?
5. How should the recommendation change the site, functions, entrances, routes, or operations?
6. Which unresolved assumption could overturn the recommendation?

Preserve evidence discipline, but do not let missing data prevent reasonable, clearly labeled inference.

## Startup Metric Selection Protocol

Execute these steps in order before calculating, querying, or interpreting metric values. Do not skip ahead or load the detailed catalog as a startup resource.

1. **Frame the question and hypotheses.** Identify the decision question, study boundary, time range, project constraints, and 2–4 competing hypotheses when the question is broad.
2. **Discover candidates from the lightweight Index.** Read the complete `references/metric-catalog-index.yaml` and use only its data domains, source IDs, metric families, metric IDs, implementation groups, and `use_when` tags to discover candidates.
3. **Match a combination recipe.** Read the complete `references/analysis-recipes.md` and match the question and hypotheses to a named recipe. Use the recipe only to form a candidate question-to-metric plan. If no recipe matches, form a candidate combination from the Index `use_when` tags and require at least two independent metric families for a material multi-source claim.
4. **Intersect candidates with the current run.** Compare the candidate source IDs and metric IDs with the current AnalysisRun `source_versions`, years, spatial scopes, and available outputs. Remove candidates that have no current source or output; retain unavailable but decision-critical candidates only as explicit evidence gaps.
5. **Query detailed semantics by metric ID.** For only the remaining candidate metric IDs, call `scripts/metric_catalog.py describe`. Treat `references/metric-catalog.yaml` as the only source of detailed metric semantics, but never load it in full at startup or query unrelated entries.

```bash
python skills/spatial-business-analyst/scripts/metric_catalog.py describe poi.grid_density poi.lq
```

6. **Validate before use.** Check `implementation_status`, actual AnalysisRun execution status and output, required inputs, unit, time scope, spatial scope, category schema, grid resolution, method, `valid_comparisons`, `quality_requirements`, `supports`, and `does_not_support`. Calculate or cite a metric only after every applicable check passes.

## Run Workspace Protocol

Read `references/run-layout.md` before execution. Start every run with
`scripts/run_workspace.py init`; write all scripts and report outputs only inside
that workspace. Place normalized metric JSON in `artifacts/`, EvidenceNodes in
`evidence/`, metric attempts and validation output in `diagnostics/`, and the
decision report plus technical appendix as separate Markdown files in `report/`.

Finish with `scripts/run_workspace.py finalize`, then `validate`. Do not create
or alter `.complete` directly. If report publication fails, preserve diagnostics
and evidence in staging but do not publish a complete run.

## 1. Frame the decision

Before analysis, identify:

- Decision question.
- Locked snapshot and study boundary.
- Data and document time ranges.
- Project stage.
- Target category, if specified.
- Intended audience and required decision.
- Known project constraints.
- Whether the task concerns project positioning, a target category, or spatial allocation.
- Whether the source is a locked snapshot or a mutable history-backed project.

If the question is broad, define 2–4 competing strategic hypotheses before querying data.

Examples:

- Visitor-oriented cultural destination.
- Community cultural and service hub.
- Cultural events plus creative commerce.
- Conventional leasing-led commercial project.

Do not begin with a preferred conclusion.

## 2. Validate the evidence

Read the locked snapshot, dataset manifest, project documents, and relevant records before forming conclusions.

For each important dataset:

- Confirm spatial coverage, geometry, year, units, field names, missing values, and duplicate risks.
- Inspect representative records before running aggregates.
- Verify that aggregate fields contain usable numeric values.
- Identify conflicts between documents and datasets.
- Distinguish current conditions from historical records and proposed design intentions.
- Check duplicate POIs and normalize category codes to one classification level before aggregation.

Verify reproducibility before analysis:

- For a locked snapshot, record the snapshot-specific dataset IDs and version metadata.
- For a history-backed project, do not call it locked. Record the history ID, source ID, query year, content hash or version token, and analysis time.
- If neither a locked copy nor a stable version/hash exists, classify the run as reproducibility-limited and preserve the aggregate results used by the report.
- On rerun, compare the recorded hash or version token before reusing prior conclusions.

If a critical field is null or unusable, mark that dataset unavailable for the corresponding analysis. Do not treat record count alone as evidence of population, activity, demand, or market potential.

Use only the unified EvidenceNode contract for readable evidence. Keep execution status and missing inputs in AnalysisRun, metric interpretation boundaries in Metric Catalog, and report-to-node relationships in the citation map. Do not create an internal evidence ledger or a parallel claim evidence object.

### 2.1 Metric Use Guardrails

Apply these rules after completing the Startup Metric Selection Protocol:

- Select values only from metrics with `implementation_status: implemented`, a succeeded AnalysisRun metric attempt, and an actual current output.
- Treat `implementation_status: not_implemented` or a blocked/not-applicable/failed metric attempt only as an AnalysisRun gap. Do not create an EvidenceNode or substitute a similarly named field.
- Treat metrics with `proxy: true` explicitly as proxies. Never upgrade them into observed demand, performance, saturation, revenue, or causality.
- Enforce every selected metric's `does_not_support`, `valid_comparisons`, and `quality_requirements` rules.
- Support every material spatial or market claim with at least two metrics from independent families, unless it is explicitly limited to a single-family descriptive observation.
- Use only canonical Catalog metric IDs in EvidenceNode `metric_ids`. Generate one independently readable node for a coherent source/year/scope/method result, not one node per scalar value. Do not create nodes for unsuccessful metric attempts.

For each selected metric, record internally:

- Canonical `metric_id`.
- Observed value and unit.
- Spatial and time scope.
- Comparison baseline or reason no comparison is valid.
- Method and parameters.
- Quality status.
- Supported interpretation.
- Prohibited interpretation.
- Companion metrics.
- Contradictory evidence.

## 3. Construct the spatial model

Analyze the site and its surroundings as spatial relationships, not only as totals.

### 3.1 Project spatial units

When evidence permits, identify:

- Buildings.
- Courtyards.
- Entrances.
- Street frontages.
- Internal routes.
- Public open spaces.
- Resident or sensitive interfaces.
- Service, loading, parking, and back-of-house areas.
- Physical barriers and inactive edges.

### 3.2 Surrounding context

Cut the study area using at least two meaningful spatial dimensions:

- Direction: north, south, east, west, or relevant street-facing sectors.
- Walking-time or distance bands.
- Entrance catchments.
- Main routes and intersections.
- Street frontage versus internal blocks.
- Barrier-separated areas.
- High- and low-concentration clusters.

Prefer a walk-network boundary over a simple radius when available.

Before interpreting directional or distance-band totals, pass the quantitative spatial validity gate:

- Calculate reachable land area or another defensible denominator for every spatial unit.
- Do not rank sectors or distance bands using raw POI totals alone.
- Report count and normalized density together.
- Use location quotient or category share when claiming specialization.
- Normalize POI categories to one classification level before aggregation.
- Check duplicate records and mixed parent/child category codes.
- Do not label a distance band or sector "strongest," "most active," or "core" without normalized comparison or observed activity evidence.

When point locations and the boundary are available, run `scripts/normalized_spatial_metrics.py`. For a repository history project:

```bash
python skills/spatial-business-analyst/scripts/normalized_spatial_metrics.py \
  --history-id <history_id> --year <year> \
  --output <metrics.json>
```

History mode reads the canonical WGS84 analysis origin directly from `params.center` and does not accept a center override. Do not copy coordinates from the display title. Coordinate conversion belongs at the application input/save boundary; standalone JSON input to this script must already provide `center_crs: wgs84`. Preserve `dataset_content_sha256`, `analysis_spec_sha256`, and `run_sha256`; metric EvidenceNode IDs must use the run hash so a different origin or partition specification cannot reuse an existing node ID.

Use its reachable-area density, density index, LQ, duplicate diagnostics, content hash, and structured `evidence_nodes`. If normalization is impossible, describe raw totals only as a count distribution and prohibit market-strength language.

Confirm that every `evidence_nodes[].metric_id` returned by the script exists in the catalog before using it.

### 3.3 Activity and supply

Locate and compare:

- Residential sources.
- Employment and institutional sources.
- Schools, hospitals, transport, parks, attractions, and other demand generators.
- Daily services.
- Food, retail, accommodation, culture, leisure, and target-category supply.
- Competitors and substitutes.
- Daytime, evening, weekday, and weekend activity proxies.

Use raw totals only as a starting point. Prefer:

- Category share.
- Density.
- Concentration.
- Directional distribution.
- Distance to the project.
- Relationship to entrances and routes.
- Comparison between spatial bands.
- Comparison with a relevant baseline.

Never report only that facilities are “numerous” without explaining where they are and how they relate to the project.

Classify customer evidence explicitly:

- **Confirmed customers:** observed or documented users, such as current residents.
- **Spatially reachable generators:** nearby institutions or facilities whose users may reach the site.
- **Unverified target customers:** groups desired by the strategy but not demonstrated by source evidence.

For each material customer group, trace: origin → reason to visit → time → entrance → likely dwell time → product used → payment status. Treat company POIs as facilities, not employment, and nearby institutions as possible generators, not confirmed flows.

## 4. Convert evidence into spatial insights

A material insight must follow this structure:

> Spatial pattern → plausible mechanism → project implication → recommended action

Example:

> Office and food-service facilities cluster along the eastern approach, but the internal courtyard lacks direct visibility from that route. The opportunity is therefore not simply “more food demand”; it is to convert passing weekday activity into project entry. Prioritize the eastern entrance as the daily interface and place low-threshold functions there, while reserving internal courtyards for destination activities.

For every material insight, distinguish:

- **Measured fact:** directly supported by a dataset or confirmed document.
- **Proxy:** indirectly indicates activity or market conditions.
- **Inference:** reasoned interpretation from the available evidence.
- **Recommendation:** proposed response rather than an existing fact.

Do not repeat these labels mechanically in every paragraph. Use them only where the distinction affects the decision.

## 5. Separate project intentions from market validation

Project documents may establish:

- Existing conditions.
- Ownership and resident issues.
- Protected buildings.
- Approved constraints.
- Previous design intentions.

A design vision may generate a hypothesis, but it does not validate market fit.

Do not use a project document proposing “cultural creativity,” “community coexistence,” or “historical activation” as independent proof that the same positioning is commercially suitable.

Explicitly show:

> Original proposal → independent evidence supporting or challenging it → resulting modification

The final recommendation must add something that was not already stated in the source documents.

## 6. Test competing strategies

For broad positioning work, compare at least three materially different, complete scenarios at the same conceptual level. Do not compare a customer orientation, a public-service principle, a mixed operating model, and an asset model as if they were equivalent strategies.

Define every scenario using the same fields:

- Primary customer.
- Core product.
- Daily operating base.
- Revenue mechanism.
- Spatial intensity.
- Required operator and technical conditions.

Evaluate each strategy against consistent criteria such as:

- Identifiable customer source.
- Fit with buildings and open spaces.
- Relationship to surrounding supply.
- Differentiation.
- Daily versus event-based usage.
- Revenue and operating logic.
- Resident and neighborhood conflict.
- Fire, access, logistics, and technical constraints.
- Content and operator requirements.
- Ability to support phased implementation.

Separately assess spatial fit, customer evidence, competitive differentiation, operational feasibility, technical feasibility, and financial evidence. Use high/medium/low only when explicit criteria support the rating; otherwise use `unknown` or `unverified`.

Do not create precise numerical scores from weak or incomplete evidence.
Do not convert an unverified revenue mechanism into medium or high feasibility. A direction can be worth testing while its market, operations, and finances remain unverified.

A commercial opportunity or feasibility report must identify named or geolocated direct competitors and substitutes when source data permits. POI category totals do not satisfy this requirement. Build a matrix covering location/access, core product, customer, opening periods, price or fee status, activity frequency, and relationship to the project. Mark unavailable operating fields as unknown.

If named competitors or operating evidence are unavailable, explicitly classify the result as a spatial positioning study rather than a commercial feasibility study.

For a target-category task, test:

- Customer source.
- Competitive and substitute supply.
- Site and building fit.
- Required operating conditions.
- Differentiation.
- Evidence that would disconfirm the opportunity.

## 7. Translate strategy into space and operations

A recommendation is incomplete until it changes the proposed use of the site.

Define:

- Project role in the surrounding area.
- Primary and secondary customer groups.
- Main usage occasions.
- Core attraction.
- Daily-use functions.
- Supporting commercial functions.
- Community or public functions.
- Functions to control or exclude.
- Arrival sequence and entrance hierarchy.
- Day, evening, weekday, and weekend operating pattern.
- Phasing and prototype tests.

Treat an architecturally distinctive space as a **candidate anchor** until evidence validates its operating attraction. Define measurable promotion thresholds such as safe capacity, monthly usable event frequency, average attendance, non-event utilization, onward conversion, event cost, and resident complaints.

When spatial units are available, provide a functional allocation table:

| Spatial unit | Spatial role | Target users | Time pattern | Recommended function | Site-specific reason | Constraints |
| --- | --- | --- | --- | --- | --- | --- |

Every proposed function must answer:

- Why this function?
- Why at this project?
- Who uses it?
- When do they use it?
- Where should it be placed?
- What operational mechanism sustains it?

Define functions as product units rather than generic tenancy labels. For every material product unit specify:

- Product content and format.
- Customer evidence state.
- Time pattern and expected dwell time.
- Spatial and technical requirements.
- Capacity or a method to determine it.
- Pricing or payment model.
- Operating owner.
- Linkage with anchors, routes, and courtyards.
- Conditions required for launch or expansion.

If building-level geometry is unavailable, provide allocation principles rather than inventing building assignments.

## 8. Handle uncertainty without becoming noncommittal

Missing information is not automatically a reason to stop analysis.

Use the available evidence to produce the strongest defensible conditional judgment and state the condition that could overturn it.

Only elevate a missing input when it could:

- Reverse the preferred strategy.
- Change a building or entrance assignment.
- Make an operation technically infeasible.
- Materially alter the customer or revenue logic.

Limit the final report to the five most decision-critical unknowns. Put secondary limitations in the evidence appendix.

For every critical unknown, specify a concrete verification method and the decision it affects.

## 9. Evidence boundaries

Do not:

- Treat population as purchasing power.
- Treat nightlight as sales, footfall, or revenue.
- Treat POI count as operating performance or market demand.
- Treat road connectivity as observed pedestrian flow.
- Treat theoretical walking range as actual customer conversion.
- Treat a proposed design intention as an existing condition.
- Claim saturation, shortage, leakage, surplus, or unmet demand without a relevant baseline.
- Quantify investment return without rent, cost, revenue, and operating assumptions.
- Combine incompatible years into a single market total.
- Infer causal change from cross-year POI totals without checking coverage and classification consistency.

These restrictions do not prohibit conditional inference. State what the proxy suggests, what it does not prove, and how the project should respond.

## 10. Output separation

Produce two separate artifacts.

### Decision report

Keep it concise and stakeholder-facing, normally with six parts:

1. Core judgment.
2. Spatial pattern and customer sources.
3. Competition and opportunity.
4. Scenario comparison.
5. Recommended products and spatial requirements.
6. Implementation and validation.

Use compact evidence labels such as `[E1]` and return a citation map from every label to real EvidenceNode IDs in the same AnalysisRun. Keep raw source IDs, field checks, and internal process details out of the report body. Mark it `needs_review` in metadata. State whether it is a spatial positioning study, commercial opportunity study, or commercial feasibility study based on the evidence actually available.

### Technical evidence appendix

Include:

- Snapshot/history identity, source IDs, version/hash, and analysis time.
- Query parameters and preserved aggregate results.
- Reachable-area denominators, density and LQ methods.
- Representative records and named competitor evidence.
- Field checks, duplicate checks, document conflicts, and limitations.
- Decision-critical unknowns and disconfirming evidence.

Do not expose the internal quality checklist in either final artifact.

## 11. Quality gate

Before finalizing, verify that:

- The report contains spatial relationships, not only area-wide counts.
- The startup index matches the detailed catalog hash, and only current AnalysisRun sources are selected.
- Every used metric ID exists in `metric-catalog.yaml`, is implemented, has a succeeded metric attempt, and appears in a current EvidenceNode.
- Every metric interpretation respects `does_not_support`, `valid_comparisons`, and `quality_requirements`.
- Every material multi-source claim combines at least two independent metric families.
- Direction and distance claims use normalized denominators, or are explicitly limited to count distribution.
- Category specialization uses a consistent classification level and LQ or share baseline.
- Every major conclusion changes a project decision.
- Every core recommendation is site-specific.
- At least three complete, same-level scenarios were tested when the question was broad.
- Unknown market, operating, technical, and financial evidence remains unknown rather than becoming a favorable rating.
- Named competitors and substitutes are assessed, or the deliverable is explicitly limited to a spatial positioning study.
- The recommendation is not merely a restatement of the design brief.
- Functions are connected to customers, time patterns, spatial units, and operations.
- Generic functions are converted into defined product units with owners and launch conditions.
- Candidate anchors have measurable validation thresholds.
- Missing data is prioritized rather than repeatedly listed.
- Proxy limitations appear once and do not dominate the narrative.
- Generic phrases such as “activate history,” “integrate culture and commerce,” or “create a cultural destination” are followed by a concrete product, location, user, and operating mechanism.
- The conclusion states what evidence would cause it to be rejected or revised.
- The decision report and technical evidence appendix are separate files, and neither exposes the internal checklist.

If these conditions are not met, continue analysis instead of expanding the report with generic prose.
