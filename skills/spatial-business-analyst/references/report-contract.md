# Schema v3 report contract

## Contents

- Common rules
- AnalysisBlueprint
- EvidenceSnapshot
- ChapterAssignments
- ChapterPackage and chapter index
- EditorialReview and accepted claims
- ReportAssembly
- AnalysisRun v3 manifest
- Compiler invariants

## Common rules

Every new root object uses:

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01"
}
```

Use canonical JSON for all content hashes. IDs are unique within the Run. Root models and ReportAssembly use `extra = "forbid"`. Hashes use `sha256:<lowercase hex>`.

EvidenceSnapshot positive evidence uses only `measured` or `proxy`. Chapter claims may use `measured`, `proxy`, `inference`, `recommendation`, or `experimental_assumption`; a claim may not exceed the weakest cited source.

## AnalysisBlueprint

`analysis-blueprint.json` combines the accepted project blueprint, evidence requirements, independent completeness review, and first lock.

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "blueprint_id": "blueprint:project-01",
  "project_judgment": "本次项目真正需要决定什么",
  "decision_questions": [
    {
      "question_id": "question:01",
      "question": "...",
      "decision_use": "...",
      "hypotheses": ["..."],
      "scope": {"spatial": "...", "temporal": "..."},
      "irreversible_risks": ["..."],
      "disconfirming_conditions": ["..."]
    }
  ],
  "evidence_requirements": [
    {
      "requirement_id": "requirement:01",
      "question_id": "question:01",
      "kind": "metric",
      "objective": "证明或排除什么",
      "evidence_capability": "facility_supply_structure",
      "required_source_ids": ["current:dataset:poi"],
      "scope": {},
      "failure_effect": "缺失时不能判断什么"
    },
    {
      "requirement_id": "requirement:02",
      "question_id": "question:01",
      "kind": "gap",
      "objective": "验证运营承诺",
      "required_source_ids": ["project:operator-plan"],
      "scope": {},
      "failure_effect": "不能确认长期运营可交付性"
    }
  ],
  "excluded_topics": [
    {"topic": "...", "reason": "..."}
  ],
  "report_logic": {
    "audience": "...",
    "judgment_sequence": ["..."],
    "shared_terms": {"...": "..."}
  },
  "completeness_review": {
    "review_id": "blueprint-review:01",
    "reviewer_role": "independent_blueprint_reviewer",
    "status": "accepted",
    "findings": [],
    "repair_instructions": []
  },
  "lock": {
    "source_snapshot_hash": "sha256:...",
    "capability_registry_version": "3.0.0",
    "content_hash": "sha256:...",
    "locked_at": "..."
  }
}
```

Allowed requirement kinds are `document`, `metric`, `spatial`, `comparison`, and `gap`. Executable `metric`, `spatial`, and `comparison` requirements use an authoritative registry key when deterministic execution is needed. Raw Metric IDs, adapter names, and execution order are forbidden in the public blueprint.

Every question needs one or more requirements. Every exclusion needs a reason. `completeness_review.status` must be `accepted` before persistence as the authoritative blueprint.

## EvidenceSnapshot

`evidence-snapshot.json` combines usable evidence, gaps, readiness, visuals, and private execution lineage.

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "snapshot_id": "evidence-snapshot:project-01",
  "blueprint_id": "blueprint:project-01",
  "blueprint_hash": "sha256:...",
  "evidence": [
    {
      "evidence_id": "evidence:01",
      "requirement_ids": ["requirement:01"],
      "question_ids": ["question:01"],
      "state": "measured",
      "source_ids": ["current:dataset:poi"],
      "scope": {"spatial": {}, "temporal": {}},
      "method": "...",
      "result": {"category_count": 12},
      "limitations": [],
      "object_ids": ["scope:project-context"]
    }
  ],
  "gaps": [
    {
      "gap_id": "gap:01",
      "requirement_ids": ["requirement:02"],
      "question_id": "question:01",
      "missing_inputs": ["已承诺运营主体和期限"],
      "decision_limit": "不能确认长期运营可交付性",
      "collection_action": "取得签署的运营协议",
      "stop_condition": "补数前禁止将运营意向表述为已落实",
      "next_run_trigger": "运营协议纳入锁定来源"
    }
  ],
  "question_readiness": {
    "question:01": "conditional"
  },
  "visuals": [
    {
      "visual_id": "visual:01",
      "title": "设施供给结构",
      "visual_type": "bar_chart",
      "evidence_ids": ["evidence:01"],
      "data_fields": ["result.category_count"],
      "object_ids": [],
      "coordinate_system": "",
      "transformations": ["..."],
      "render_spec": {},
      "filename": "visual-01.svg",
      "spec_hash": "sha256:...",
      "asset_hash": "sha256:...",
      "interpretation_boundary": "仅表示已记录设施供给"
    }
  ],
  "execution_lineage": {
    "capability_registry_version": "3.0.0",
    "requirement_resolutions": [],
    "internal_metric_plan": [],
    "attempts": [],
    "transformations": []
  },
  "content_hash": "sha256:..."
}
```

Readiness values are `ready`, `conditional`, `gap_bound`, and `not_reportable`.

Every blueprint requirement has a terminal attempt in `execution_lineage` and is covered by positive evidence or a public gap when it limits a decision. Attempt statuses are `succeeded`, `blocked`, `failed`, `not_applicable`, and `registered_gap`.

Only succeeded non-gap attempts create positive evidence. An `inference`, recommendation, failed attempt, or gap cannot appear as positive evidence. Numeric visuals require succeeded evidence and exact result-field lineage. Gap visuals are semantic evidence-gate structures without fabricated values.

Agent prompt projections always omit `execution_lineage`. Specialist projections also omit every unassigned evidence, gap, and visual record.

## ChapterAssignments

`chapter-assignments.json` is the second lock.

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "assignment_bundle_id": "assignments:project-01",
  "blueprint_hash": "sha256:...",
  "evidence_snapshot_hash": "sha256:...",
  "assignments": [
    {
      "assignment_id": "assignment:market",
      "chapter_id": "chapter:market",
      "working_title": "市场与需求基础",
      "role": "市场与需求分析师",
      "objective": "...",
      "question_ids": ["question:01"],
      "subsection_tasks": [
        {"subsection_id": "market:01", "title": "...", "task": "..."}
      ],
      "required_argument_units": [
        {"argument_id": "argument:market:01", "purpose": "...", "suggested_characters": [600, 1000]}
      ],
      "evidence_access": {
        "primary": ["evidence:01"],
        "shared": [],
        "gaps": ["gap:01"],
        "visuals": ["visual:01"],
        "forbidden": []
      },
      "dependencies": [],
      "assignment_hash": "sha256:..."
    }
  ],
  "content_hash": "sha256:..."
}
```

Every decision question appears in exactly one assignment's `question_ids`. Access lists are disjoint; unlisted items are forbidden. Every assigned visual is a required chapter placement. Each assignment hash binds its content, blueprint hash, and evidence snapshot hash.

## ChapterPackage and chapter index

Each `chapters/<chapter-id>.vN.json` is immutable.

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "chapter_id": "chapter:market",
  "chapter_version_id": "chapter:market:v1",
  "assignment_id": "assignment:market",
  "assignment_hash": "sha256:...",
  "evidence_snapshot_hash": "sha256:...",
  "analyst_role": "市场与需求分析师",
  "title": "...",
  "thesis": "...",
  "subsections": [
    {
      "subsection_id": "market:01",
      "title": "...",
      "body": "可直接发布的正文……",
      "argument_units": [
        {
          "argument_id": "argument:market:01",
          "claim": "...",
          "claim_state": "inference",
          "evidence_refs": [
            {"evidence_id": "evidence:01", "result_paths": ["result.category_count"]}
          ],
          "gap_ids": ["gap:01"],
          "baseline": "...",
          "mechanism": "...",
          "project_implication": "...",
          "action": "...",
          "assumptions": ["..."],
          "stop_condition": "..."
        }
      ],
      "structure_blocks": [],
      "visual_refs": [
        {"visual_id": "visual:01", "caption": "...", "interpretation": "..."}
      ]
    }
  ],
  "unresolved_tensions": [],
  "warnings": [],
  "content_hash": "sha256:..."
}
```

Every required subsection and ArgumentUnit appears exactly once. Numeric claims identify source result paths. Evidence, gaps, and visuals must be assignment-authorized. Assigned visuals must be placed exactly once unless the assignment explicitly allows repeated placement.

`analyst-chapters.json` indexes immutable versions:

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "chapters": [
    {
      "chapter_id": "chapter:market",
      "versions": [
        {
          "chapter_version_id": "chapter:market:v1",
          "filename": "market.v1.json",
          "content_hash": "sha256:...",
          "review_status": "revision_required"
        },
        {
          "chapter_version_id": "chapter:market:v2",
          "filename": "market.v2.json",
          "content_hash": "sha256:...",
          "review_status": "accepted"
        }
      ],
      "accepted_version_id": "chapter:market:v2"
    }
  ],
  "content_hash": "sha256:..."
}
```

Only `v1` and optional `v2` are allowed. Exactly one accepted version exists for every accepted chapter; prior review history is never overwritten.

## EditorialReview and accepted claims

`editorial-review.json` preserves version-specific decisions and embeds system-generated accepted claims.

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "review_id": "editorial-review:project-01",
  "chapter_decisions": [
    {
      "chapter_version_id": "chapter:market:v1",
      "decision": "revise",
      "failed_obligations": ["..."],
      "repair_instructions": ["..."]
    },
    {
      "chapter_version_id": "chapter:market:v2",
      "decision": "accepted",
      "failed_obligations": [],
      "repair_instructions": []
    }
  ],
  "conflicts": [
    {
      "conflict_id": "conflict:01",
      "argument_ids": ["argument:market:01", "argument:access:01"],
      "tension": "...",
      "decision": "resolved",
      "ruling": "..."
    }
  ],
  "terminology_rules": {},
  "accepted_claims": [
    {
      "claim_id": "claim:argument:market:01",
      "source_type": "argument_unit",
      "source_ids": ["argument:market:01"],
      "chapter_version_ids": ["chapter:market:v2"],
      "text": "...",
      "evidence_ids": ["evidence:01"],
      "gap_ids": ["gap:01"],
      "state": "inference",
      "scope": {},
      "caveats": ["..."]
    }
  ],
  "publication_decision": "ready",
  "content_hash": "sha256:..."
}
```

Chapter decisions are `accepted`, `revise`, or `rejected`. Publication decision is `ready`, `revision_required`, or `blocked`.

The system creates `accepted_claims` only after validating decisions. Agent-authored accepted claims are invalid. Claims come only from accepted ArgumentUnits or resolved conflict rulings and inherit the weakest state, narrowest scope, and all material caveats. Rejected chapter versions contribute no claims.

## ReportAssembly

`report-assembly.json` contains assembly instructions, never specialist prose.

```json
{
  "schema_version": "3.0",
  "run_id": "run:project-01",
  "assembly_id": "report-assembly:project-01",
  "title": "项目报告",
  "editorial_review_id": "editorial-review:project-01",
  "accepted_chapters": [
    {"chapter_id": "chapter:market", "chapter_version_id": "chapter:market:v2"}
  ],
  "chapter_order": ["chapter:market"],
  "executive_summary": {
    "text": "...",
    "claim_ids": ["claim:argument:market:01"]
  },
  "transitions": [],
  "integrated_recommendations": [
    {"text": "...", "claim_ids": ["claim:argument:market:01"]}
  ],
  "conflict_ids": ["conflict:01"],
  "content_hash": "sha256:..."
}
```

Accepted chapters and order must match the chapter index and EditorialReview. Every substantive synthesis statement cites known accepted claim IDs. Fields for chapter body, subsections, ArgumentUnits, or rewritten specialist content are forbidden.

## AnalysisRun v3 manifest

`analysis-run.json` is an infrastructure manifest, not a report reasoning object. v3 removes public `decision_agenda`, `metric_plan`, and `metric_attempts` fields. It records:

- `schema_version: "3.0"`, run identity, kind, capability, status, and stage;
- input artifact digest and upstream references;
- typed artifact references and hashes for the six root objects and chapter index;
- diagnostics derived from EvidenceSnapshot execution lineage and publication state;
- failure state and reason when applicable.

Use `run_kind: full_analysis` for source reports and `run_kind: delivery_view` for a derived selection/reordering of one completed v3 Run. A delivery view cannot reference another delivery view.

API readers may return a union of v3 and legacy v1/v2 read-only views. New writes, comparison outputs, and delivery views use v3 only.

## Compiler invariants

The compiler validates:

- schema v3 and legacy read-only boundaries;
- blueprint completeness, registry key validity, and first-lock hash;
- terminal coverage for every evidence requirement;
- evidence/gap/readiness consistency and private-lineage hash;
- deterministic visual provenance, security, spec hash, and asset hash;
- one question owner, assignment access, and second-lock hash;
- chapter task coverage, ArgumentUnit completeness, result-field lineage, visual placement, immutable versions, and one-revision limit;
- version-specific editorial decisions, explicit conflict handling, and system-generated accepted claims;
- ReportAssembly claim references and prohibition on specialist prose;
- exact publication contents.

The compiler preserves specialist body text. It changes only numbering, evidence citation labels, structural-block rendering, and visual links.

It publishes:

```text
report/project-report.md
report/assets/<referenced-visual>.svg
```

No failure state writes report files or `.complete`.
