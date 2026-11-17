# Build bundle (M8)

2026-11-17. How `python -m app.build.export` builds `footnote.sqlite` and how
`python -m app.build.verify` checks it. The code in `backend/app/build/` is the
authority; this page explains the choices behind it.

## Fingerprint

`build_meta.content_sha256` is the SHA-256 of the UTF-8 bytes of a canonical dump of
every table except `build_meta`:

- tables in name order, rows in primary-key order;
- one line per row, lines joined by `\n`, no trailing newline;
- each line is the JSON array `["<table>", {<row>}]`, where the object maps every column
  name to its stored value, keys sorted, no whitespace, non-ASCII characters written as
  themselves (`json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`).

It reads stored values back, so it does not depend on SQLite page layout. The column
list comes from the schema itself (`bundle.TABLES` is derived from `bundle.SCHEMA`), so
a new column is in the fingerprint without a second edit.

## `build_meta.allow_unapproved`

Section 4 of the build plan has no such column. It is added as
`INTEGER NOT NULL CHECK (allow_unapproved IN (0, 1))`: 1 for a development build made
with `--allow-unapproved`, 0 for a release. `verify --release` refuses 1, but never
trusts 0 on its own: it also re-reads every figure and fact from the pinned responses,
checks summary coverage and runs the neutrality guard on every summary line. A release
also refuses `prompt_version` `none`.

## Failed builds

Both output files are written in a fresh temporary directory beside `--out` and moved
into place only after both are complete. A failed build removes the bundle and report
that an earlier build left at the same paths, so a file at `--out` is always from the
latest successful run. Moving them aside was the alternative; removing them was chosen
so that nothing stale sits at the path the app build reads.

## Pinned responses

`backend/data/pinned/`, the default `--pinned` directory, holds regulator responses
downloaded for a build and is git-ignored. The synthetic fixtures the tests use live in
`backend/tests/fixtures/build/pinned/` and are tracked.

## DART period dates

OpenDART's annual financial rows carry no period dates. The exporter takes them from the
사업보고서 title: `사업보고서 (2025.12)` gives a fiscal year that ends on the last day of
that month, 2025-12-31, and starts the day after the same month-end a year earlier,
2025-01-01. The comparative year is the twelve months before that. A title without a
`(YYYY.MM)` month, or whose year is not the filing's fiscal year, is refused.

The rule assumes every fiscal year is twelve months long. After a company changes its
fiscal year end, the transition year is shorter, and the dates for it and for the
comparative year in the next report come out wrong. The build does not detect this yet;
such a company needs a fix before it is added.

## Event source hash

`filings.source_text_sha256` for an event filing with a stored body (an SEC 8-K whose
text M4 kept in `event_filings.body_text`) is the SHA-256 of that body text and each
fact's key, source field and raw text. A DART event filing stores no body, so its value
is a placeholder: the SHA-256 of the regulator's list row (filing key, company, report
name, filing date, `rm`, SEC items) and the same fact fields. No bundle was released
with the earlier placeholder-only rule, so `schema_version` stays 1. When DART bodies
are stored and hashed too, bump `schema_version`, because the same filing then gets a
different value.

## Which filings are exported

Event filings: those filed in the twelve months ending on `--as-of`, both ends included.
Correction chains are the ingest's: a linked correction joins its original's chain, and
unlinked corrections the ingest groups as orphans share one (DART: same company, base
report name, subsidiary flag and stated first filing date; SEC: same CIK, event date and
an item other than 9.01). Each chain shows its newest member filed on or before
`--as-of`. A DART filing whose `rm` carries 정 is shown only when a correction of that
filing can be resolved and was filed after `--as-of`. A correction of it is one linked to
it, or an unlinked one whose body names the filing's date as the first filing date, with
the same company, base report name and subsidiary flag; a same-name correction of another
filing does not count. When the data holds no correction of it at all, the filing is
hidden and listed in the report under `superseded_unresolved`, as ingest's `is_latest`
treats 정 as replaced. A filing without 정 follows the chain rule alone. Excluded filings
and error facts are counted in the report, never exported.

Known limitation: an unresolved 정 filing is hidden at every `--as-of`, including one
earlier than the correction DART filed. For such a date the build shows neither version,
although the 정 filing was the current one then. It applies to corrections whose body
names no first filing date, or names one that matches no filing.

SEC 8-K facts (`items`, `report_date`) are checked against the pinned
`sec/submissions/CIK<cik10>.json` with the same parser and fact builder the ingest uses.

Annual filings (`app.build.model.ANNUAL_SCOPE`):

- only those filed on or before `--as-of` count;
- per company and fiscal year, only the newest version is kept, with `is_corrected = 1`
  when it replaced an earlier version or its title marks a correction;
- a kept version is exported only when it is the source of an exported figure;
- each company's latest exported annual filing needs approved summaries in both
  languages and all four sections; older annual filings need none;
- every exported event filing needs an approved summary in both languages.
