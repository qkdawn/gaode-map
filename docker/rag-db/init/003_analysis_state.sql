ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS access_groups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS decision_state JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS revision_log JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

ALTER TABLE analysis_step_outputs
    ADD COLUMN IF NOT EXISTS step_order INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS quality_gate JSONB NOT NULL DEFAULT '{}'::JSONB;

ALTER TABLE kb_documents
    DROP CONSTRAINT IF EXISTS kb_documents_checksum_key;

ALTER TABLE kb_documents
    DROP CONSTRAINT IF EXISTS kb_documents_source_key_version_key;

ALTER TABLE kb_chunks
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';

UPDATE kb_chunks AS c
SET tenant_id = d.tenant_id
FROM kb_documents AS d
WHERE d.id = c.document_id
  AND c.tenant_id = 'default'
  AND d.tenant_id <> 'default';

ALTER TABLE kb_chunks
    DROP CONSTRAINT IF EXISTS kb_chunks_chunk_key_key;

UPDATE analysis_runs
SET heartbeat_at = COALESCE(heartbeat_at, updated_at),
    lease_expires_at = COALESCE(lease_expires_at, updated_at + INTERVAL '15 minutes')
WHERE status = 'running';

CREATE UNIQUE INDEX IF NOT EXISTS kb_documents_tenant_source_version_uidx
    ON kb_documents (tenant_id, source_key, version);
CREATE UNIQUE INDEX IF NOT EXISTS kb_chunks_tenant_chunk_key_uidx
    ON kb_chunks (tenant_id, chunk_key);
CREATE INDEX IF NOT EXISTS kb_documents_tenant_checksum_idx
    ON kb_documents (tenant_id, checksum);
CREATE INDEX IF NOT EXISTS analysis_runs_tenant_status_idx
    ON analysis_runs (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS analysis_runs_lease_idx
    ON analysis_runs (status, lease_expires_at)
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS analysis_step_outputs_run_order_idx
    ON analysis_step_outputs (run_id, step_order);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'analysis_step_outputs_step_order_check'
    ) THEN
        ALTER TABLE analysis_step_outputs
            ADD CONSTRAINT analysis_step_outputs_step_order_check
            CHECK (step_order BETWEEN 0 AND 99);
    END IF;
END;
$$;
