DROP INDEX IF EXISTS kb_chunks_embedding_hnsw_idx;

-- A dimension change means a model change. Existing vectors are deliberately
-- cleared so ingestion and query vectors can never be mixed across models.
ALTER TABLE kb_chunks
    ALTER COLUMN embedding TYPE VECTOR(768)
    USING NULL::VECTOR(768);

CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw_idx
    ON kb_chunks USING HNSW (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
