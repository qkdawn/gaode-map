# Source inventory

## Local project evidence

- `n8n/workflow-generators/urban-renewal-agent.workflow.mjs`
- `tests/domain/test_n8n_rag_workflows.py`
- `modules/spatial_action/spatial_evidence.py`
- `modules/spatial_projects/mcp_server.py`
- `modules/spatial_strategy/literature_evidence.py`
- `modules/embedding_service.py`
- `scripts/literature_evidence.py`
- `scripts/verify_graphrag_index.py`
- `runtime/graphrag-public-knowledge/source_manifest.json`
- `docker/rag-db/init/001_schema.sql`
- `runtime/client-decision-spatial-strategy/825d012f-3585-4acf-babf-2e26bc94b80e/spatial-strategy-report.md`
- PostgreSQL records for analysis run `825d012f-3585-4acf-babf-2e26bc94b80e`
- PostgreSQL records for failed analysis runs `990025f2-685d-4b6d-ab8a-f51d21894b56` and `d4da9a3f-b663-403d-8760-11d32bb6158f`
- `docs/researchwrite/isochrone-multi-agent-regional-analysis/06_engineering_decision_log.md`

## Literature sources

1. https://doi.org/10.1016/j.jtrangeo.2019.102556
2. https://doi.org/10.1038/s41597-023-02691-1
3. https://arxiv.org/abs/2406.13948
4. https://arxiv.org/abs/2402.19273
5. https://arxiv.org/abs/2601.16965
6. https://arxiv.org/abs/2509.05933
7. https://doi.org/10.18653/v1/2026.rag4reports-1.14

## Evidence boundary

The local report is a feasibility artifact, not an independent evaluation dataset. Failed runs are fault-localization evidence, not negative quality results. GraphRAG index coverage is not retrieval-quality evidence. Literature metadata and claims must be rechecked before journal submission, especially preprints and 2026 conference papers.
