CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS kb_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key TEXT NOT NULL,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    object_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'parsing', 'review', 'published', 'superseded', 'failed')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    checksum TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_key, version),
    UNIQUE (checksum)
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    search_terms TEXT NOT NULL DEFAULT '',
    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', COALESCE(search_terms, ''))
    ) STORED,
    page_start INTEGER CHECK (page_start IS NULL OR page_start > 0),
    page_end INTEGER CHECK (page_end IS NULL OR page_end > 0),
    section TEXT NOT NULL DEFAULT '',
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    decision_steps TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    project_types TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    geography TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    embedding VECTOR(768),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, ordinal),
    CHECK (page_end IS NULL OR page_start IS NULL OR page_end >= page_start)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    history_id TEXT NOT NULL DEFAULT '',
    workflow_execution_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    current_step TEXT NOT NULL DEFAULT '',
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analysis_step_outputs (
    run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'revision_required', 'failed', 'skipped')),
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagnostics JSONB NOT NULL DEFAULT '[]'::jsonb,
    revision_count INTEGER NOT NULL DEFAULT 0 CHECK (revision_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, step)
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    run_id UUID PRIMARY KEY REFERENCES analysis_runs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'failed')),
    markdown TEXT NOT NULL DEFAULT '',
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    asset_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS kb_documents_status_idx ON kb_documents (status);
CREATE INDEX IF NOT EXISTS kb_documents_source_type_idx ON kb_documents (source_type);
CREATE INDEX IF NOT EXISTS kb_documents_metadata_idx ON kb_documents USING GIN (metadata);
CREATE INDEX IF NOT EXISTS kb_chunks_document_idx ON kb_chunks (document_id, ordinal);
CREATE INDEX IF NOT EXISTS kb_chunks_search_idx ON kb_chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS kb_chunks_content_trgm_idx ON kb_chunks USING GIN (content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS kb_chunks_decision_steps_idx ON kb_chunks USING GIN (decision_steps);
CREATE INDEX IF NOT EXISTS kb_chunks_project_types_idx ON kb_chunks USING GIN (project_types);
CREATE INDEX IF NOT EXISTS kb_chunks_geography_idx ON kb_chunks USING GIN (geography);
CREATE INDEX IF NOT EXISTS kb_chunks_metadata_idx ON kb_chunks USING GIN (metadata);
CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw_idx
    ON kb_chunks USING HNSW (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS analysis_runs_status_idx ON analysis_runs (status, created_at DESC);
CREATE INDEX IF NOT EXISTS analysis_runs_history_idx ON analysis_runs (history_id, created_at DESC);
CREATE INDEX IF NOT EXISTS analysis_step_outputs_status_idx ON analysis_step_outputs (status, updated_at DESC);

DROP TRIGGER IF EXISTS kb_documents_set_updated_at ON kb_documents;
CREATE TRIGGER kb_documents_set_updated_at
BEFORE UPDATE ON kb_documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS kb_chunks_set_updated_at ON kb_chunks;
CREATE TRIGGER kb_chunks_set_updated_at
BEFORE UPDATE ON kb_chunks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS analysis_runs_set_updated_at ON analysis_runs;
CREATE TRIGGER analysis_runs_set_updated_at
BEFORE UPDATE ON analysis_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS analysis_step_outputs_set_updated_at ON analysis_step_outputs;
CREATE TRIGGER analysis_step_outputs_set_updated_at
BEFORE UPDATE ON analysis_step_outputs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS analysis_reports_set_updated_at ON analysis_reports;
CREATE TRIGGER analysis_reports_set_updated_at
BEFORE UPDATE ON analysis_reports
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
