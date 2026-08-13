ALTER TABLE kb_documents
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'restricted',
    ADD COLUMN IF NOT EXISTS access_groups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'kb_documents_visibility_check'
    ) THEN
        ALTER TABLE kb_documents
            ADD CONSTRAINT kb_documents_visibility_check
            CHECK (visibility IN ('public', 'restricted'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS kb_documents_tenant_access_idx
    ON kb_documents (tenant_id, status, visibility);
CREATE INDEX IF NOT EXISTS kb_documents_access_groups_idx
    ON kb_documents USING GIN (access_groups);

CREATE OR REPLACE FUNCTION hybrid_search_kb(
    p_query_text TEXT,
    p_query_embedding VECTOR(768),
    p_tenant_id TEXT,
    p_access_groups TEXT[] DEFAULT ARRAY[]::TEXT[],
    p_decision_steps TEXT[] DEFAULT ARRAY[]::TEXT[],
    p_project_types TEXT[] DEFAULT ARRAY[]::TEXT[],
    p_geography TEXT[] DEFAULT ARRAY[]::TEXT[],
    p_metadata_filter JSONB DEFAULT '{}'::JSONB,
    p_result_limit INTEGER DEFAULT 40,
    p_candidate_limit INTEGER DEFAULT 100
)
RETURNS TABLE (
    chunk_id UUID,
    chunk_key TEXT,
    document_id UUID,
    title TEXT,
    source_type TEXT,
    source_url TEXT,
    object_key TEXT,
    page_start INTEGER,
    page_end INTEGER,
    section TEXT,
    ordinal INTEGER,
    content TEXT,
    metadata JSONB,
    keyword_score DOUBLE PRECISION,
    vector_score DOUBLE PRECISION,
    fused_score DOUBLE PRECISION
)
LANGUAGE SQL
STABLE
AS $$
WITH eligible AS MATERIALIZED (
    SELECT
        c.*,
        d.title,
        d.source_type,
        d.source_url,
        d.object_key,
        d.metadata || c.metadata AS effective_metadata
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE d.status = 'published'
      AND d.source_type <> 'project_document'
      AND d.tenant_id = p_tenant_id
      AND (d.source_type <> 'test_fixture' OR COALESCE(p_metadata_filter->>'fixture', '') = 'true')
      AND (
          d.visibility = 'public'
          OR d.access_groups && COALESCE(p_access_groups, ARRAY[]::TEXT[])
      )
      AND (
          COALESCE(cardinality(p_decision_steps), 0) = 0
          OR COALESCE(cardinality(c.decision_steps), 0) = 0
          OR c.decision_steps && p_decision_steps
      )
      AND (
          COALESCE(cardinality(p_project_types), 0) = 0
          OR COALESCE(cardinality(c.project_types), 0) = 0
          OR c.project_types && p_project_types
      )
      AND (
          COALESCE(cardinality(p_geography), 0) = 0
          OR COALESCE(cardinality(c.geography), 0) = 0
          OR c.geography && p_geography
      )
      AND (d.metadata || c.metadata) @> COALESCE(p_metadata_filter, '{}'::JSONB)
),
query_terms AS (
    SELECT DISTINCT btrim(term) AS term
    FROM regexp_split_to_table(lower(COALESCE(p_query_text, '')), '[[:space:][:punct:]]+') AS split(term)
    WHERE length(btrim(term)) >= 2
    UNION
    SELECT DISTINCT substring(lower(COALESCE(p_query_text, '')) FROM position FOR 2) AS term
    FROM generate_series(1, GREATEST(length(COALESCE(p_query_text, '')) - 1, 0)) AS positions(position)
    WHERE substring(lower(COALESCE(p_query_text, '')) FROM position FOR 2) ~ '^[^[:space:][:punct:]]{2}$'
),
keyword_scored AS (
    SELECT
        e.id,
        (
            CASE
                WHEN e.content ILIKE '%' || p_query_text || '%' THEN 1.5
                WHEN e.search_terms ILIKE '%' || p_query_text || '%' THEN 1.0
                ELSE 0.0
            END
            + ts_rank_cd(e.search_vector, websearch_to_tsquery('simple', p_query_text))
            + word_similarity(p_query_text, e.search_terms || ' ' || e.content)
            + LEAST(1.5, COALESCE((SELECT count(*)::DOUBLE PRECISION * 0.15 FROM query_terms q WHERE e.content ILIKE '%' || q.term || '%'), 0.0))
        )::DOUBLE PRECISION AS score
    FROM eligible e
    WHERE NULLIF(btrim(p_query_text), '') IS NOT NULL
      AND (
          e.search_vector @@ websearch_to_tsquery('simple', p_query_text)
          OR e.content ILIKE '%' || p_query_text || '%'
          OR e.search_terms ILIKE '%' || p_query_text || '%'
          OR p_query_text <% e.content
          OR EXISTS (SELECT 1 FROM query_terms q WHERE e.content ILIKE '%' || q.term || '%')
      )
),
keyword_ranked AS (
    SELECT
        id,
        score,
        row_number() OVER (ORDER BY score DESC, id) AS rank
    FROM keyword_scored
    ORDER BY score DESC, id
    LIMIT GREATEST(1, LEAST(p_candidate_limit, 500))
),
vector_scored AS (
    SELECT
        e.id,
        (1 - (e.embedding <=> p_query_embedding))::DOUBLE PRECISION AS score
    FROM eligible e
    WHERE p_query_embedding IS NOT NULL
      AND e.embedding IS NOT NULL
    ORDER BY e.embedding <=> p_query_embedding, e.id
    LIMIT GREATEST(1, LEAST(p_candidate_limit, 500))
),
vector_ranked AS (
    SELECT
        id,
        score,
        row_number() OVER (ORDER BY score DESC, id) AS rank
    FROM vector_scored
),
fused AS (
    SELECT
        candidates.id,
        max(candidates.keyword_score)::DOUBLE PRECISION AS keyword_score,
        max(candidates.vector_score)::DOUBLE PRECISION AS vector_score,
        sum(candidates.rrf_score)::DOUBLE PRECISION AS fused_score
    FROM (
        SELECT
            id,
            score AS keyword_score,
            NULL::DOUBLE PRECISION AS vector_score,
            1.0 / (60.0 + rank) AS rrf_score
        FROM keyword_ranked
        UNION ALL
        SELECT
            id,
            NULL::DOUBLE PRECISION,
            score,
            1.0 / (60.0 + rank)
        FROM vector_ranked
    ) candidates
    GROUP BY candidates.id
)
SELECT
    e.id,
    e.chunk_key,
    e.document_id,
    e.title,
    e.source_type,
    e.source_url,
    e.object_key,
    e.page_start,
    e.page_end,
    e.section,
    e.ordinal,
    e.content,
    e.effective_metadata,
    f.keyword_score,
    f.vector_score,
    f.fused_score
FROM fused f
JOIN eligible e ON e.id = f.id
ORDER BY f.fused_score DESC, e.id
LIMIT GREATEST(1, LEAST(p_result_limit, 200));
$$;

CREATE OR REPLACE FUNCTION expand_kb_context(
    p_chunk_ids UUID[],
    p_radius INTEGER DEFAULT 1
)
RETURNS TABLE (
    hit_rank INTEGER,
    chunk_id UUID,
    chunk_key TEXT,
    document_id UUID,
    title TEXT,
    source_type TEXT,
    source_url TEXT,
    object_key TEXT,
    page_start INTEGER,
    page_end INTEGER,
    section TEXT,
    ordinal INTEGER,
    content TEXT,
    metadata JSONB,
    is_direct_hit BOOLEAN
)
LANGUAGE SQL
STABLE
AS $$
WITH hits AS (
    SELECT
        hit_id,
        ordinality::INTEGER AS hit_rank
    FROM unnest(COALESCE(p_chunk_ids, ARRAY[]::UUID[]))
        WITH ORDINALITY AS requested(hit_id, ordinality)
),
expanded AS (
    SELECT
        h.hit_rank,
        c.id AS chunk_id,
        c.chunk_key,
        c.document_id,
        d.title,
        d.source_type,
        d.source_url,
        d.object_key,
        c.page_start,
        c.page_end,
        c.section,
        c.ordinal,
        c.content,
        c.metadata,
        c.id = h.hit_id AS is_direct_hit
    FROM hits h
    JOIN kb_chunks base ON base.id = h.hit_id
    JOIN kb_chunks c
      ON c.document_id = base.document_id
     AND c.ordinal BETWEEN base.ordinal - GREATEST(0, LEAST(p_radius, 3))
                       AND base.ordinal + GREATEST(0, LEAST(p_radius, 3))
    JOIN kb_documents d ON d.id = c.document_id
)
SELECT DISTINCT ON (expanded.chunk_id)
    expanded.hit_rank,
    expanded.chunk_id,
    expanded.chunk_key,
    expanded.document_id,
    expanded.title,
    expanded.source_type,
    expanded.source_url,
    expanded.object_key,
    expanded.page_start,
    expanded.page_end,
    expanded.section,
    expanded.ordinal,
    expanded.content,
    expanded.metadata,
    expanded.is_direct_hit
FROM expanded
ORDER BY expanded.chunk_id, expanded.hit_rank, expanded.ordinal;
$$;
