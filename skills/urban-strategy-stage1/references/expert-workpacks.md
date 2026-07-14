# Expert Workpacks

All workpacks must use the shared `evidence_nodes.jsonl`. Save each file under `work/expert_workpacks/`.

## Common schema

```json
{
  "workpack_type": "urban_planning",
  "questions_answered": [],
  "findings": [
    {
      "finding_id": "planning-f-01",
      "statement": "",
      "evidence_refs": ["ev-0001"],
      "interpretation": "",
      "limitations": [],
      "strategy_implications": []
    }
  ],
  "contradictions": [],
  "critical_gaps": [],
  "recommended_next_actions": []
}
```

Do not add recommendations that cannot be linked to a finding, explicit project goal, or hypothesis with a validation action.

## Urban planning and spatial structure

File: `urban_planning.json`

Analyze:

- regional role and surrounding functional relationships;
- project boundary versus wider analysis circles;
- land use, public service, ecological, and transport structure;
- nodes, corridors, edges, barriers, interfaces, and catchments;
- access and movement at relevant modes and times;
- spatial opportunity zones and hard planning constraints.

Output additional keys:

- `spatial_structure`
- `planning_constraints`
- `opportunity_zones`
- `connections_to_strengthen`

## Cultural tourism and experience

File: `cultural_tourism.json`

Analyze:

- locally evidenced cultural, historical, natural, educational, and community assets;
- resident, student, worker, and visitor journeys;
- daytime/nighttime, weekday/weekend, and seasonal differences;
- content, event, interpretation, and experience opportunities;
- local distinctiveness and risks of generic cultural-commercial packaging.

Output additional keys:

- `cultural_assets`
- `audience_journeys`
- `experience_programs`
- `tourism_risks`

## Urban renewal and implementation

File: `urban_renewal.json`

Analyze:

- retain, repair, adapt, replace, and temporary-use principles;
- existing building and open-space adaptability;
- ownership, approval, engineering, fire, logistics, noise, and neighborhood constraints;
- quick wins, pilots, phased capital works, and governance;
- public value and displacement/gentrification risks.

Output additional keys:

- `renewal_actions`
- `implementation_constraints`
- `phasing_strategy`
- `governance_requirements`

## Commercial, users, and operations

File: `commercial_operations.json`

Analyze:

- demand proxies and their limitations;
- existing supply, complementarity, competition, and missing services;
- core, supporting, public, event, and back-of-house programs;
- operating hours, tenant/self-operation balance, partnerships, and content cadence;
- assumptions that need survey, interview, footfall, rental, or financial validation.

Output additional keys:

- `demand_signals`
- `supply_conditions`
- `program_mix_candidates`
- `operating_assumptions`

Never claim actual footfall, spending, rent tolerance, or financial viability unless a source directly measures it.
