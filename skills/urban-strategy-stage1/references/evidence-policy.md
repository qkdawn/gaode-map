# Evidence Policy

## Evidence classes

Use exactly these values:

- `project_fact`: confirmed present condition or constraint from core project material.
- `policy_or_plan`: statutory, policy, or superior-plan evidence.
- `measured_spatial_result`: computed GIS or database result.
- `observed_visual_evidence`: map, photo, drawing, or image observation.
- `external_reference`: external market, case, academic, or web evidence.
- `design_intent`: desired future state stated by the client or design material.
- `inference`: analyst interpretation derived from cited evidence.
- `hypothesis`: proposition requiring validation.

Use exactly these statuses:

- `confirmed`
- `pending_verification`
- `conflicting`
- `not_available`
- `not_applicable`

## Ledger record

Write one JSON object per line to `evidence_nodes.jsonl`:

```json
{
  "evidence_id": "ev-0001",
  "topic": "regional_role",
  "statement": "Minimal evidence-bearing statement",
  "evidence_class": "project_fact",
  "status": "confirmed",
  "confidence": "high",
  "source_id": "document:project-brief",
  "evidence_node_id": "node-12",
  "locator": "项目任务书，第3页",
  "spatial_scope": "project_boundary",
  "time_scope": "2026",
  "limitations": [],
  "supports_questions": ["q-01"]
}
```

Use confidence values `high`, `medium`, or `low`. Confidence is evidence quality, not recommendation strength.

## Claim construction

Every report-level claim should identify:

- `claim_id`;
- claim text;
- claim type: `fact`, `interpretation`, `recommendation`, or `hypothesis`;
- supporting `evidence_refs`;
- limitations or decision conditions.

A recommendation may cite inference records, but the inference must itself cite underlying evidence in its workpack.

## Source precedence

Use this precedence when sources conflict; do not hide the conflict:

1. core project brief and confirmed legal/technical documents;
2. statutory policy or superior planning documents;
3. measured current-scope analysis with known method and date;
4. verified project photos, drawings, and surveys;
5. external authoritative references;
6. design vision and precedents;
7. analyst hypothesis.

Higher precedence does not automatically make an older source current. Record dates and explain the choice.

## Forbidden transformations

Do not state:

- POI count as actual demand or spending;
- nightlight as revenue or visitor volume;
- road centrality as pedestrian flow;
- population raster as project customer count;
- an external case as proof the same model will work locally;
- design intent as an existing asset;
- a visually inferred place name as a confirmed named object.

## Conflict register

Record conflicts in `conflict_register.json`:

```json
{
  "conflicts": [
    {
      "conflict_id": "conflict-001",
      "topic": "site_area",
      "statements": [
        {"value": "12 ha", "evidence_ref": "ev-0010"},
        {"value": "15 ha", "evidence_ref": "ev-0011"}
      ],
      "severity": "critical",
      "resolution": "unresolved",
      "decision_impact": "Program capacity cannot be fixed",
      "next_action": "Confirm cadastral boundary"
    }
  ]
}
```

Use severity `critical`, `material`, or `minor`; resolution `resolved`, `provisional`, or `unresolved`.
