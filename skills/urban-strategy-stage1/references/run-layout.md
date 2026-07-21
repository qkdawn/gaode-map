# Run Layout

Use one immutable input area and separate generated work/output areas:

```text
<run-dir>/
  input/
    urban_project_analysis_package.json
    ppt_sources_full_export.json
    project_brief.md
    analysis_scope.geojson
    documents/
    images/
    maps/
  work/
    source_readiness.json
    evidence_nodes.jsonl
    conflict_register.json
    expert_workpacks/
      urban_planning.json
      cultural_tourism.json
      urban_renewal.json
      commercial_operations.json
    strategy_options.json
    decision_matrix.json
  output/
    stage1_report.md
    evidence_appendix.md
    design_handoff.json
    run_manifest.json
```

Do not modify files under `input/`. Record generated file hashes and timestamps in `run_manifest.json`.
