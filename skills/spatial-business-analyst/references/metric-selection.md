# Evidence capabilities and internal metric selection

Use this reference when an `AnalysisBlueprint` needs deterministic metric, spatial, or comparison execution, or when interpreting a metric-backed EvidenceSnapshot result.

## Public capability contract

Agents request semantic capabilities, not raw Metric IDs. The authoritative application capability registry defines the accepted keys, registry version, eligible metric families, required inputs, parameter policy, adapters, execution order, fallback behavior, and output contract.

Canonical examples include:

- `project_constraints`
- `facility_supply_structure`
- `spatial_concentration`
- `network_access_structure`
- `entrance_comparison`
- `population_context`
- `night_activity_context`
- `temporal_change`

These examples are not an independent registry. Always validate against the runtime registry. An unknown key invalidates the blueprint; never reinterpret it as free text or silently substitute a similarly named capability.

Each executable evidence requirement records:

- `kind`: `metric`, `spatial`, or `comparison`;
- `objective`: what the result must prove or exclude;
- `evidence_capability`: one registry key;
- required source contracts and intended scope;
- `failure_effect`: what cannot be judged if execution fails.

Document and gap requirements do not need a capability unless deterministic processing is required.

## Evidence-engine selection protocol

The deterministic evidence engine, not an Agent, performs this sequence:

1. Resolve the capability against the locked registry version.
2. Discover eligible metric candidates from `metric-catalog-index.yaml` and current source coverage.
3. Use `analysis-recipes.md` only to form candidate combinations.
4. Query detailed semantics only for shortlisted IDs:

   ```bash
   python skills/spatial-business-analyst/scripts/metric_catalog.py describe poi.grid_density spatial.gi_star
   ```

5. Check implementation status, inputs, spatial granularity, baseline, comparison validity, quality requirements, supported interpretation, prohibited interpretation, and actionability.
6. Resolve parameters, adapters, activation rules, and execution order deterministically.
7. Persist the resolved internal plan and every terminal attempt in `EvidenceSnapshot.execution_lineage`.

Never load the detailed `references/metric-catalog.yaml` at startup. It is authoritative for shortlisted `metric_id` semantics only. For each shortlist, enforce `does_not_support`, `valid_comparisons`, `quality_requirements`, and `comparison_baseline` as well as implementation and input requirements.

## Internal roles and activation

The engine may classify internal entries as `primary`, `supporting`, `diagnostic`, or `excluded`. These are private execution details and never become public report orchestration objects.

Conditional activation may use `always`, `if_primary_blocked`, `if_quality_failed`, or `if_pattern_detected`. A condition that does not activate still receives a terminal `not_applicable` attempt in execution lineage.

Unavailable decision-critical candidates remain terminal blocked or failed attempts and create public gaps. Exclusion is allowed only for analytical irrelevance, not unavailable execution.

## Baseline policy

Read each shortlisted metric's `comparison_baseline` before treating a value as high, low, concentrated, deficient, improved, or preferable.

- `required: true`: no comparative judgment is allowed until a preferred baseline exists.
- `required: false`: a within-scope descriptive result may be reported, but stronger comparison still needs a baseline.
- `preferred`: allowed controlled baseline designs.
- `if_missing`: the required collection action and temporary reporting limit.

A missing required baseline creates a public gap and stop condition, not an unqualified opportunity claim.

## Execution invariants

- Every blueprint requirement has at least one terminal internal attempt.
- Only succeeded non-gap attempts create positive evidence.
- Positive EvidenceSnapshot entries use only `measured` or `proxy`.
- Every blocked, failed, or registered-gap outcome that limits a question creates a public gap; primary failures always do.
- Evidence IDs preserve requirement, source, transformation, metric, parameter, spatial object, and attempt lineage internally.
- Prompt projections omit `execution_lineage`; specialists cite only assigned public evidence IDs, gap IDs, and visual IDs.
- No report citation may bypass requirement-to-attempt-to-evidence lineage.
