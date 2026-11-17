"""Event ingest against PostgreSQL: the CLI path on fixtures, upsert semantics, constraints."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.ingest import events
from app.ingest.events import run_dart_events
from tests.event_fakes import DART, FakeDartClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError(
        "refusing to drop tables: TEST_DATABASE_URL must name an isolated *_test database"
    )
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is required")

BODY = DART / "correction" / "20261103000311.xml"
TODAY = datetime.date(2026, 11, 17)


@asynccontextmanager
async def _database():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text((Path(__file__).parents[1] / "db/init.sql").read_text()))
        yield async_sessionmaker(engine, expire_on_commit=False), engine
    finally:
        await engine.dispose()


def _fake() -> FakeDartClient:
    return FakeDartClient("035420", documents={"20261103000311": BODY})


async def _rows(engine, sql: str, **params):
    async with engine.connect() as connection:
        return (await connection.execute(text(sql), params)).all()


def run(coro):
    return asyncio.run(coro)


def test_ingest_stores_every_filing_chain_and_exact_facts() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            summary = await run_dart_events(_fake(), "035420", factory, today=TODAY)

            total = (await _rows(engine, "SELECT count(*) FROM event_filings"))[0][0]
            assert total == summary.listed

            # Excluded filings are stored with their reason, counted by reason.
            stored = dict(
                await _rows(
                    engine,
                    "SELECT excluded_reason, count(*) FROM event_filings "
                    "WHERE excluded_reason IS NOT NULL GROUP BY 1",
                )
            )
            assert stored == dict(summary.excluded) and stored
            in_scope = (
                await _rows(engine, "SELECT count(*) FROM event_filings WHERE category IS NOT NULL")
            )[0][0]
            assert in_scope == sum(summary.by_category.values())

            chain = {
                r[0]: r[1:]
                for r in await _rows(
                    engine,
                    "SELECT rcept_no, correction_link, original_rcept_no, is_latest, "
                    "correction_note, filed_at FROM event_filings "
                    "WHERE report_nm LIKE '%유상증자결정%'",
                )
            }
            assert chain["20260727000001"][:3] == ("none", None, False)
            assert chain["20261030000001"][0] == "unlinked"
            assert chain["20261030000001"][1] is None and chain["20261030000001"][3]
            assert chain["20261103000311"][:3] == ("linked", "20260727000001", True)
            assert chain["20261103000311"][4] == datetime.date(2026, 11, 3)
            shown = await _rows(
                engine,
                "SELECT rcept_no FROM event_filings WHERE category = 'capital' AND is_latest "
                "AND report_nm LIKE '%유상증자결정%' AND NOT subsidiary",
            )
            assert [r[0] for r in shown] == ["20261103000311"]

            facts = {
                r[0]: r[1:]
                for r in await _rows(
                    engine,
                    "SELECT f.key, f.kind, f.unit, f.value_decimal, f.value_date, f.value_text, "
                    "f.error FROM filing_facts f JOIN event_filings e ON e.id = f.event_filing_id "
                    "WHERE e.rcept_no = '20261103000311'",
                )
            }
            assert facts["new_shares_common"][:3] == ("count", "shares", Decimal("6558435"))
            assert facts["use_other"][2] == Decimal("1341199957500")
            assert isinstance(facts["use_other"][2], Decimal)
            assert facts["issue_method"][4] == "제3자배정증자"
            assert all(v[-1] is None for v in facts.values())
            assert "use_facilities" not in facts  # "-" in the source
            n_facts = (await _rows(engine, "SELECT count(*) FROM filing_facts"))[0][0]
            assert n_facts == summary.facts_written == len(facts)

    run(scenario())


def test_rerun_is_idempotent_and_replaces_facts() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            identity = "SELECT id, rcept_no, created_at FROM event_filings ORDER BY rcept_no"
            computed = (
                "SELECT rcept_no, category, is_latest, correction_link, original_rcept_no "
                "FROM event_filings ORDER BY rcept_no"
            )
            before, before_computed = await _rows(engine, identity), await _rows(engine, computed)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw, "
                        "value_text) SELECT id, 'stale', 'text', 'x', 'x', 'x' FROM event_filings "
                        "WHERE rcept_no = '20261103000311'"
                    )
                )
                await connection.execute(
                    text(
                        "UPDATE event_filings SET is_latest = NOT is_latest, category = 'deal' "
                        "WHERE category IS NOT NULL"
                    )
                )
            await run_dart_events(_fake(), "035420", factory, today=TODAY)

            after = await _rows(engine, identity)
            assert after == before  # same rows (ids, created_at): upserted, not duplicated
            stale = await _rows(engine, "SELECT count(*) FROM filing_facts WHERE key = 'stale'")
            assert stale[0][0] == 0
            # The upsert overwrote every tampered column with the freshly computed value.
            assert await _rows(engine, computed) == before_computed

    run(scenario())


def test_cli_entry_runs_against_the_fake_client_and_test_database(monkeypatch, capsys) -> None:
    from app.ingest import __main__ as cli

    async def no_pause(_seconds: float) -> None:
        return None

    monkeypatch.setattr(events, "DartClient", lambda settings: _fake())
    monkeypatch.setattr(events, "_pause", no_pause)
    monkeypatch.setattr(sys, "argv", ["app.ingest", "events", "--source", "dart", "--ticker", "035420"])

    async def prepare():
        async with _database() as (_factory, engine):
            return None

    run(prepare())
    cli.main()
    out = capsys.readouterr().out
    assert "corrections: linked=1" in out
    assert "PROBLEM" not in out

    async def check():
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            count = (await _rows(engine, "SELECT count(*) FROM event_filings"))[0][0]
            facts = (await _rows(engine, "SELECT count(*) FROM filing_facts"))[0][0]
            return count, facts
        finally:
            await engine.dispose()

    count, facts = run(check())
    listed = {
        row["rcept_no"]
        for kind in ("B", "I")
        for row in json.loads((DART / "list" / f"035420_{kind}.json").read_text())["list"]
    }
    assert count == len(listed) > 50
    assert facts == 5  # the newest 유상증자결정 has five non-"-" fields in the contract


@pytest.mark.parametrize(
    "statement",
    [
        # amount carrying text instead of a decimal
        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw, value_text) "
        "SELECT id, 'k', 'amount', 's', 'r', 'oops' FROM event_filings",
        # an error and a value together
        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw, value_decimal, "
        "error) SELECT id, 'k', 'amount', 's', 'r', 1, 'bad' FROM event_filings",
        # neither value nor error
        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw) "
        "SELECT id, 'k', 'date', 's', 'r' FROM event_filings",
        # unknown kind
        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw, value_text) "
        "SELECT id, 'k', 'float', 's', 'r', 'x' FROM event_filings",
        # duplicate key for one filing
        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw, value_text) "
        "SELECT id, 'new_shares_common', 'text', 's', 'r', 'x' FROM event_filings "
        "WHERE rcept_no = '20261103000311'",
        # both category and excluded_reason
        "UPDATE event_filings SET excluded_reason = 'no_rule' WHERE category IS NOT NULL",
        # a linked correction without its original
        "UPDATE event_filings SET original_rcept_no = NULL WHERE correction_link = 'linked'",
        # an original that claims to be linked
        "UPDATE event_filings SET correction_link = 'linked', original_rcept_no = 'x' "
        "WHERE rcept_no = '20260727000001'",
    ],
)
def test_schema_rejects_inconsistent_rows(statement) -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(text(statement))

    run(scenario())


def test_deleting_a_filing_deletes_its_facts() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM event_filings WHERE rcept_no = '20261103000311'")
                )
            assert (await _rows(engine, "SELECT count(*) FROM filing_facts"))[0][0] == 0

    run(scenario())


# -- a failed run must not destroy what an earlier run stored (reviewer items 1 and 3) -----------


class _StructuredDown(FakeDartClient):
    async def _get(self, endpoint, params):
        self.calls.append(("structured", endpoint))
        payload = {"status": "020", "message": "요청 제한"}
        return type("R", (), {"json": lambda self: payload})()


_FACT_ROWS = "SELECT event_filing_id, key, value_decimal FROM filing_facts ORDER BY 1, 2"
_NAVER_LATEST = (
    "SELECT rcept_no FROM event_filings WHERE is_latest AND category = 'capital' "
    "AND report_nm LIKE '%유상증자결정%' AND NOT subsidiary"
)


def test_a_failed_structured_endpoint_keeps_the_facts_already_stored() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            first = await run_dart_events(_fake(), "035420", factory, today=TODAY)
            stored = await _rows(engine, _FACT_ROWS)
            assert stored and first.ok

            down = _StructuredDown("035420", documents={"20261103000311": BODY})
            second = await run_dart_events(down, "035420", factory, today=TODAY)
            assert second.ok is False
            assert any("piicDecsn" in p and "020" in p for p in second.problems)

            assert await _rows(engine, _FACT_ROWS) == stored  # untouched, not deleted

    run(scenario())


def test_a_successful_endpoint_replaces_facts_and_drops_those_it_no_longer_returns() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            async with engine.begin() as connection:
                # A fact stored on a filing the endpoint does not return any more.
                await connection.execute(
                    text(
                        "INSERT INTO filing_facts (event_filing_id, key, kind, source_field, raw, "
                        "value_text) SELECT id, 'stale', 'text', 'x', 'x', 'x' FROM event_filings "
                        "WHERE rcept_no = '20260727000001'"
                    )
                )
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            stale = await _rows(engine, "SELECT count(*) FROM filing_facts WHERE key = 'stale'")
            assert stale[0][0] == 0

    run(scenario())


def test_a_run_that_cannot_read_bodies_keeps_stored_links_and_classification() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            probe = (
                "SELECT rcept_no, category, excluded_reason, correction_link, original_rcept_no, "
                "is_latest FROM event_filings WHERE rcept_no IN "
                "('20261103000311', '20260727000001', '20260206800015') ORDER BY rcept_no"
            )
            before = await _rows(engine, probe)
            by = {r[0]: r for r in before}
            assert by["20261103000311"][3:5] == ("linked", "20260727000001")
            assert by["20260206800015"][1] == "earnings"  # resolved from its body, not its name
            latest_before = await _rows(engine, _NAVER_LATEST)
            assert [r[0] for r in latest_before] == ["20261103000311"]

            offline = FakeDartClient("035420", missing="fail", use_classifier_documents=False)
            summary = await run_dart_events(offline, "035420", factory, today=TODAY)
            assert summary.ok is False
            assert any(p.startswith("document 20261103000311") for p in summary.problems)

            assert await _rows(engine, probe) == before
            assert await _rows(engine, _NAVER_LATEST) == latest_before  # still exactly one

    run(scenario())


# -- the ORM and init.sql must define the same CHECK constraints (reviewer item 11) -------------

_CHECKS = """
SELECT c.relname, k.conname, pg_get_constraintdef(k.oid)
FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
WHERE k.contype = 'c' AND c.relname IN ('event_filings', 'filing_facts')
  AND c.relnamespace = 'public'::regnamespace
ORDER BY 1, 2
"""


def test_models_and_init_sql_define_the_same_check_constraints() -> None:
    async def scenario():
        async with _database() as (_, engine):
            from_init_sql = [tuple(r) for r in await _rows(engine, _CHECKS)]
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)
            from_models = [tuple(r) for r in await _rows(engine, _CHECKS)]
            assert len(from_init_sql) == 5
            assert from_models == from_init_sql

    run(scenario())
