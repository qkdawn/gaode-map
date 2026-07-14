# AnalysisRun Workspace Layout

Every spatial business analysis writes to a staging workspace and publishes once:

```text
runtime/analysis-runs/<capability_id>/<run_id>/
  analysis-run.json
  artifact-index.json
  inputs/execution-request.json
  inputs/upstream/
  artifacts/
  evidence/
  report/
  diagnostics/
  .complete
```

`analysis-run.json` is the immutable run manifest and `inputs/execution-request.json`
is the normalized AgentTurnRequest. Copy each selected upstream artifact under
`inputs/upstream/`; never depend on a source run remaining available.

Write structured values as UTF-8 JSON. Preserve Markdown as `.md`. Put evidence
nodes in `evidence/`, decision and appendix reports in `report/`, validation output
and metric attempts in `diagnostics/`, and all other deliverables in `artifacts/`.

`artifact-index.json` records direction, artifact identity, logical digest, relative
path, and SHA-256 for every artifact. Only `run_workspace.py finalize` may create
`.complete`. A directory containing `.complete` is immutable; use a new run ID for
any correction.
