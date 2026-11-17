"""The bundled SQLite schema (build plan section 4) and its content fingerprint.

``content_sha256`` is the SHA-256 of a canonical dump of every table except ``build_meta``:
tables in name order, rows in primary-key order, one line per row, lines joined by ``\\n``
and encoded as UTF-8. A line is the JSON array ``[table, row]`` where ``row`` maps each
column name to its stored value, serialised with sorted keys, no whitespace and no ASCII
escaping. It reads the stored values back, so it does not depend on SQLite page layout.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE build_meta (
  schema_version   INTEGER NOT NULL,
  data_as_of       TEXT NOT NULL,
  source_revision  TEXT NOT NULL,
  llm_model        TEXT NOT NULL,
  prompt_version   TEXT NOT NULL,
  content_sha256   TEXT NOT NULL,
  allow_unapproved INTEGER NOT NULL CHECK (allow_unapproved IN (0, 1))
) STRICT;

CREATE TABLE companies (
  id          TEXT PRIMARY KEY,
  regulator   TEXT NOT NULL CHECK (regulator IN ('DART','SEC')),
  ticker      TEXT NOT NULL,
  name_ko     TEXT NOT NULL,
  name_en     TEXT NOT NULL,
  market      TEXT,
  currency    TEXT NOT NULL,
  fiscal_year_end TEXT NOT NULL,
  sort_order  INTEGER NOT NULL
) STRICT;

CREATE TABLE filings (
  id            TEXT PRIMARY KEY,
  company_id    TEXT NOT NULL REFERENCES companies(id),
  kind          TEXT NOT NULL CHECK (kind IN ('annual','event')),
  category      TEXT NOT NULL,
  form          TEXT NOT NULL,
  sec_items     TEXT,
  title_original TEXT NOT NULL,
  filed_on      TEXT NOT NULL,
  period_label  TEXT,
  source_url    TEXT NOT NULL,
  is_corrected  INTEGER NOT NULL DEFAULT 0,
  source_text_sha256 TEXT NOT NULL
) STRICT;
CREATE INDEX filings_company_date ON filings(company_id, filed_on DESC);
CREATE INDEX filings_date ON filings(filed_on DESC);

CREATE TABLE filing_summaries (
  filing_id   TEXT NOT NULL REFERENCES filings(id),
  lang        TEXT NOT NULL CHECK (lang IN ('ko','en')),
  section     TEXT NOT NULL,
  line1       TEXT NOT NULL,
  line2       TEXT,
  line3       TEXT,
  review_state TEXT NOT NULL CHECK (review_state = 'approved'),
  input_sha256 TEXT NOT NULL,
  PRIMARY KEY (filing_id, lang, section)
) STRICT;

CREATE TABLE filing_facts (
  filing_id   TEXT NOT NULL REFERENCES filings(id),
  position    INTEGER NOT NULL,
  fact_key    TEXT NOT NULL,
  value_kind  TEXT NOT NULL CHECK (value_kind IN ('amount','shares','ratio','date','text')),
  value_text  TEXT NOT NULL,
  unit        TEXT,
  origin      TEXT NOT NULL,
  PRIMARY KEY (filing_id, position)
) STRICT;

CREATE TABLE figures (
  id            TEXT PRIMARY KEY,
  company_id    TEXT NOT NULL REFERENCES companies(id),
  filing_id     TEXT NOT NULL REFERENCES filings(id),
  metric        TEXT NOT NULL,
  fiscal_year   INTEGER NOT NULL,
  period_start  TEXT NOT NULL,
  period_end    TEXT NOT NULL,
  value         TEXT NOT NULL,
  unit          TEXT NOT NULL,
  currency      TEXT,
  basis         TEXT NOT NULL,
  is_restated   INTEGER NOT NULL DEFAULT 0,
  regulator_tag TEXT NOT NULL
) STRICT;
CREATE UNIQUE INDEX figures_key ON figures(company_id, metric, period_end, basis);

CREATE TABLE glossary (
  term_key TEXT NOT NULL, lang TEXT NOT NULL CHECK (lang IN ('ko','en')),
  term TEXT NOT NULL, plain TEXT NOT NULL, formal TEXT,
  PRIMARY KEY (term_key, lang)
) STRICT;
"""


def _tables_from_schema(schema: str) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Table -> (columns as created, primary key), read from ``schema`` itself."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(schema)
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
            )
        ]
        tables = {}
        for name in names:
            info = connection.execute(f"PRAGMA table_info({name})").fetchall()
            columns = tuple(row[1] for row in info)
            key = tuple(row[1] for row in sorted((r for r in info if r[5]), key=lambda r: r[5]))
            tables[name] = (columns, key)
        return tables
    finally:
        connection.close()


_ALL_TABLES = _tables_from_schema(SCHEMA)
# Fingerprinted tables: everything except build_meta. Column order as created; the primary
# key decides row order in inserts and the fingerprint.
TABLES = {name: spec for name, spec in _ALL_TABLES.items() if name != "build_meta"}

# Tables in insert order, so every foreign key points at a row already written.
INSERT_ORDER = ("companies", "filings", "filing_summaries", "filing_facts", "figures", "glossary")

BUILD_META_COLUMNS = _ALL_TABLES["build_meta"][0]


def canonical_dump_lines(connection: sqlite3.Connection) -> list[str]:
    lines: list[str] = []
    for table in sorted(TABLES):
        columns, key = TABLES[table]
        query = f"SELECT {', '.join(columns)} FROM {table} ORDER BY {', '.join(key)}"
        for values in connection.execute(query):
            row = dict(zip(columns, values, strict=True))
            for name, value in row.items():
                if value is not None and not isinstance(value, (str, int)):
                    raise TypeError(f"{table}.{name} holds {type(value).__name__}")
            lines.append(
                json.dumps([table, row], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            )
    return lines


def content_sha256(connection: sqlite3.Connection) -> str:
    return hashlib.sha256("\n".join(canonical_dump_lines(connection)).encode("utf-8")).hexdigest()
