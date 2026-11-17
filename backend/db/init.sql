-- DB SCHEMA v0.3 for filing-digest backend.
-- Intended for docker-entrypoint-initdb.d (Postgres 16 + pgvector image).
-- Must stay in exact sync with backend/app/db/models.py.
-- Note: pg16 has gen_random_uuid() built in; only the vector extension is needed.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS companies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    name_en text,
    ticker text,
    market text,
    source text NOT NULL CHECK (source IN ('dart', 'sec')),
    dart_corp_code text UNIQUE,
    sec_cik text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS filings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source text NOT NULL,
    -- DART 접수번호. DART filing의 자연키이자 financials/document 조인키.
    -- SEC filing은 rcept_no가 없으므로 nullable. Postgres는 NULL을 서로 distinct로
    -- 취급하므로 UNIQUE 아래에서도 여러 SEC(NULL) row는 충돌하지 않고, DART rcept_no
    -- 끼리만 dedup된다. 이 UNIQUE가 ON CONFLICT (rcept_no) DO UPDATE의 inference target.
    rcept_no text UNIQUE,
    -- SEC accession number. SEC filing의 자연키; DART filing은 이 값이 없으므로
    -- nullable. Postgres는 NULL을 서로 distinct로 취급하므로 여러 DART(NULL) row는
    -- 이 UNIQUE에서 충돌하지 않고, SEC sec_accession_no끼리만 dedup된다. 이 UNIQUE가
    -- ON CONFLICT (sec_accession_no) DO UPDATE의 inference target.
    sec_accession_no text UNIQUE,
    filing_type text NOT NULL,
    title text NOT NULL,
    period text,
    filed_at date,
    url text,
    -- NULL while a Normalized Filing is pending/retrying indexing. Search joins
    -- through filings and exposes chunks only after the whole filing is ready.
    indexed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filings_company ON filings(company_id);

-- Column is named "meta" (not "metadata"): 'metadata' is a reserved attribute
-- name on SQLAlchemy Declarative models.
CREATE TABLE IF NOT EXISTS filing_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id uuid NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    chunk_index int NOT NULL,
    content text NOT NULL,
    -- [Verified] vector(1024): KURE-v1 (nlpai-lab/KURE-v1) dense dimension.
    -- Source: HuggingFace config.json hidden_size=1024 (bge-m3 / XLM-RoBERTa base).
    embedding vector(1024),
    meta jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (filing_id, chunk_index)
);

-- hnsw over cosine distance (<=>), matching the /search ORDER BY. Default
-- build parameters (m=16, ef_construction=64) are appropriate at the current
-- corpus scale (~1k chunks); revisit only if the corpus grows by orders of
-- magnitude.
CREATE INDEX IF NOT EXISTS idx_filing_chunks_embedding
    ON filing_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS financials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    filing_id uuid NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    fiscal_year int NOT NULL,
    fiscal_quarter int,
    period text NOT NULL,
    period_kind text NOT NULL DEFAULT 'duration'
        CHECK (period_kind IN ('instant', 'duration')),
    -- Exact dates remain NULL when the regulatory source does not provide them.
    period_start date,
    period_end date,
    metric text NOT NULL,
    value numeric(24, 4) NOT NULL,
    unit text NOT NULL,
    currency text,
    scale bigint NOT NULL DEFAULT 1 CHECK (scale > 0),
    source text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT financials_period_range_check
        CHECK (period_start IS NULL OR period_end IS NULL OR period_start <= period_end),
    UNIQUE (filing_id, period, metric)
);

-- Event-filing staging tables (M3). Keep identical to db/migrations/0002_event_filings.sql
-- plus 0003_event_filings_sec.sql (source, body_text, body_truncated).
CREATE TABLE IF NOT EXISTS event_filings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rcept_no text NOT NULL UNIQUE,
    corp_code text NOT NULL,
    stock_code text,
    corp_name text NOT NULL,
    report_nm text NOT NULL,
    filed_at date,
    rm text NOT NULL DEFAULT '',
    url text,
    category text,
    excluded_reason text,
    subsidiary boolean NOT NULL DEFAULT false,
    is_correction boolean NOT NULL DEFAULT false,
    matched_rule text NOT NULL,
    basis text,
    correction_link text NOT NULL DEFAULT 'none',
    original_rcept_no text,
    correction_first_filed_at date,
    correction_note text,
    is_latest boolean NOT NULL DEFAULT true,
    errors jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL DEFAULT 'dart',
    body_text text,
    body_truncated boolean NOT NULL DEFAULT false,
    CONSTRAINT event_filings_category_xor_reason_check
        CHECK ((category IS NULL) <> (excluded_reason IS NULL)),
    CONSTRAINT event_filings_correction_link_check
        CHECK (correction_link IN ('none', 'linked', 'unlinked', 'not_resolved_excluded')),
    CONSTRAINT event_filings_source_check CHECK (source IN ('dart', 'sec')),
    CONSTRAINT event_filings_link_shape_check
        CHECK (
            (correction_link = 'none' AND original_rcept_no IS NULL AND NOT is_correction)
            OR (correction_link = 'linked' AND original_rcept_no IS NOT NULL AND is_correction)
            OR (correction_link IN ('unlinked', 'not_resolved_excluded')
                AND original_rcept_no IS NULL AND is_correction)
        )
);

CREATE INDEX IF NOT EXISTS idx_event_filings_corp_filed
    ON event_filings(corp_code, filed_at DESC);

CREATE TABLE IF NOT EXISTS filing_facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_filing_id uuid NOT NULL REFERENCES event_filings(id) ON DELETE CASCADE,
    key text NOT NULL,
    kind text NOT NULL,
    unit text,
    source_field text NOT NULL,
    raw text NOT NULL,
    value_decimal numeric,
    value_date date,
    value_text text,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT filing_facts_event_filing_id_key_key UNIQUE (event_filing_id, key),
    CONSTRAINT filing_facts_kind_check
        CHECK (kind IN ('amount', 'date', 'count', 'ratio', 'text')),
    CONSTRAINT filing_facts_value_shape_check
        CHECK (
            (error IS NOT NULL
                AND value_decimal IS NULL AND value_date IS NULL AND value_text IS NULL)
            OR (error IS NULL AND (
                (kind IN ('amount', 'count', 'ratio')
                    AND value_decimal IS NOT NULL AND value_date IS NULL AND value_text IS NULL)
                OR (kind = 'date'
                    AND value_date IS NOT NULL AND value_decimal IS NULL AND value_text IS NULL)
                OR (kind = 'text'
                    AND value_text IS NOT NULL AND value_decimal IS NULL AND value_date IS NULL)
            ))
        )
);
