"""Migration 0002 must produce the same event tables as db/init.sql, on an existing database."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="isolated TEST_DATABASE_URL required")
ROOT = Path(__file__).parents[1]

_COLUMNS = """
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('event_filings', 'filing_facts')
ORDER BY table_name, column_name
"""
_CONSTRAINTS = """
SELECT c.relname, k.conname, pg_get_constraintdef(k.oid)
FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
WHERE c.relname IN ('event_filings', 'filing_facts') AND c.relnamespace = 'public'::regnamespace
ORDER BY 1, 2
"""
_INDEXES = """
SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('event_filings', 'filing_facts')
ORDER BY 1, 2
"""


def _shape(db) -> dict[str, list]:
    return {q: db.execute(q).fetchall() for q in (_COLUMNS, _CONSTRAINTS, _INDEXES)}


def test_migration_on_the_pre_event_schema_matches_init_sql() -> None:
    url = make_url(URL).set(drivername="postgresql")
    if not (url.database or "").endswith("_test"):
        raise RuntimeError("migration test requires a disposable *_test database")
    migration = (ROOT / "db/migrations/0002_event_filings.sql").read_text()
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as db:
        db.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        db.execute((ROOT / "tests/fixtures/legacy-schema-v02.sql").read_text())
        db.execute((ROOT / "db/migrations/0001_normalized_filing_snapshots.sql").read_text())
        assert db.execute("SELECT to_regclass('event_filings')").fetchone()[0] is None
        db.execute(migration)
        migrated = _shape(db)
        # Running it again on the migrated database changes nothing (IF NOT EXISTS).
        db.execute(migration)
        assert _shape(db) == migrated

        db.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        db.execute((ROOT / "db/init.sql").read_text())
        assert _shape(db) == migrated
    assert len(migrated[_COLUMNS]) > 30
