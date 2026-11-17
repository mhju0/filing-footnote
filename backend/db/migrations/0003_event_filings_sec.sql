-- Let event_filings hold SEC 8-K filings beside DART ones (Filing Footnote M4).
--
-- source says which regulator a row came from. For source 'sec' the existing columns hold:
--   rcept_no = 'sec:<accession>' (also in original_rcept_no), corp_code = 10-digit CIK,
--   stock_code = ticker, report_nm = form ('8-K' or '8-K/A'), rm = ''.
-- body_text is the plain text kept for summaries (cut at a fixed character limit);
-- body_truncated says it was cut. Both are NULL/false for DART rows.
-- Keep the added columns and constraint identical to the end of db/init.sql's event_filings.

BEGIN;

ALTER TABLE event_filings ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'dart';
ALTER TABLE event_filings ADD COLUMN IF NOT EXISTS body_text text;
ALTER TABLE event_filings ADD COLUMN IF NOT EXISTS body_truncated boolean NOT NULL DEFAULT false;
ALTER TABLE event_filings DROP CONSTRAINT IF EXISTS event_filings_source_check;
ALTER TABLE event_filings
    ADD CONSTRAINT event_filings_source_check CHECK (source IN ('dart', 'sec'));

COMMIT;
