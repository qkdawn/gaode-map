ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS access_groups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS decision_state JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS revision_log JSONB NOT NULL DEFAULT '[]'::JSONB;

ALTER TABLE analysis_step_outputs
    ADD COLUMN IF NOT EXISTS step_order INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS quality_gate JSONB NOT NULL DEFAULT '{}'::JSONB;

ALTER TABLE kb_documents
    DROP CONSTRAINT IF EXISTS kb_documents_checksum_key;

CREATE UNIQUE INDEX IF NOT EXISTS kb_documents_tenant_source_version_uidx
    ON kb_documents (tenant_id, source_key, version);
CREATE INDEX IF NOT EXISTS kb_documents_tenant_checksum_idx
    ON kb_documents (tenant_id, checksum);
CREATE INDEX IF NOT EXISTS analysis_runs_tenant_status_idx
    ON analysis_runs (tenant_id, status, created_at DESC);
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
