-- Add the event-filing staging tables (Filing Footnote M3).
--
-- event_filings holds one row per DART event filing in the ingest window, including
-- filings the classifier excluded (kept with excluded_reason, counted but not shown).
-- filing_facts holds the structured figures and dates extracted for a filing.
-- Neither table touches companies/filings; both are safe to add to a live database.
-- Keep the two CREATE TABLE statements identical to the end of db/init.sql.

BEGIN;

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
    CONSTRAINT event_filings_category_xor_reason_check
        CHECK ((category IS NULL) <> (excluded_reason IS NULL)),
    CONSTRAINT event_filings_correction_link_check
        CHECK (correction_link IN ('none', 'linked', 'unlinked', 'not_resolved_excluded')),
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

COMMIT;
