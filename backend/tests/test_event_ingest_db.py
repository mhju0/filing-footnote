"""Event ingest against PostgreSQL: the CLI path on fixtures, upsert semantics, constraints."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import os
import re
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
        # Reached only when the scenario body passed: the invariant holds in every scenario.
        await assert_one_latest_per_chain(engine)
    finally:
        await engine.dispose()


_CHAIN_KEY_ROWS = """
SELECT e.rcept_no, e.source, e.corp_code, e.report_nm, e.subsidiary, e.correction_link,
       e.original_rcept_no, e.correction_first_filed_at, e.is_latest,
       (SELECT f.value_date FROM filing_facts f
         WHERE f.event_filing_id = e.id AND f.key = 'report_date') AS event_date
FROM event_filings e
"""


async def assert_one_latest_per_chain(engine) -> None:
    """At most one latest per chain key, whatever scenario produced the rows.

    A chain is an original with its linked corrections; unlinked corrections that name the same
    target form an orphan chain (DART: company, base report name, subsidiary flag, stated
    first-filing date; SEC: company and event date); anything else is a chain of one.
    """
    chains: dict[tuple, list[str]] = {}
    for row in await _rows(engine, _CHAIN_KEY_ROWS):
        key, origin, corp, name, subsidiary, link, original, first, latest, event_date = row
        if link == "linked":
            chain = ("chain", original)
        elif link == "unlinked" and origin == "dart" and first is not None:
            base = re.sub(r"^(\[[^\]]*\])+", "", name).strip()
            chain = ("orphan", corp, base, subsidiary, first)
        elif link == "unlinked" and origin == "sec" and event_date is not None:
            chain = ("orphan", corp, event_date)
        else:
            chain = ("single", key)
        chains.setdefault(chain, [])
        if latest:
            chains[chain].append(key)
    crowded = {chain: keys for chain, keys in chains.items() if len(keys) > 1}
    assert not crowded, f"more than one latest in a chain: {crowded}"


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
            assert len(from_init_sql) == 6
            assert from_models == from_init_sql

    run(scenario())


# -- SEC 8-K ingest into the same tables (M4) -----------------------------------------------------


def _sec_rows(engine):
    return _rows(
        engine,
        "SELECT rcept_no, source, category, excluded_reason, is_correction, correction_link, "
        "original_rcept_no, is_latest, body_truncated, errors, stock_code, corp_code, report_nm, "
        "correction_first_filed_at, correction_note FROM event_filings WHERE source = 'sec' "
        "ORDER BY rcept_no",
    )


def test_sec_cli_stores_filings_with_a_failed_exhibit_and_an_amendment(monkeypatch, capsys) -> None:
    from app.ingest import __main__ as cli
    from app.ingest import sec_events
    from tests.test_sec_event_ingest import (
        AMENDMENT,
        BROKEN,
        EARNINGS,
        LEADERSHIP,
        VOTE,
        scenario_client,
    )

    fake = scenario_client()
    monkeypatch.setattr(sec_events, "SecClient", lambda settings, http: fake)
    monkeypatch.setattr(sys, "argv", ["app.ingest", "events", "--source", "sec", "--ticker", "AAPL"])

    async def prepare():
        async with _database() as (_factory, _engine):
            return None

    run(prepare())
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1  # the unreadable exhibit is a problem, as in the DART run
    out = capsys.readouterr().out
    assert f"PROBLEM document {BROKEN} EX-99.1 ex991.htm" in out
    assert "skipped exhibits (not text): 1" in out
    assert f"skipped {EARNINGS} EX-99.2 slides.pdf" in out
    assert "corrections: linked=1 unlinked=0" in out

    async def check():
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            rows = {r[0]: r for r in await _sec_rows(engine)}
            facts = await _rows(
                engine,
                "SELECT e.rcept_no, f.key, f.kind, f.value_text, f.value_date, f.value_decimal, "
                "f.source_field FROM filing_facts f JOIN event_filings e ON e.id = f.event_filing_id "
                "WHERE e.source = 'sec' ORDER BY 1, 2",
            )
            bodies = dict(
                await _rows(
                    engine, "SELECT rcept_no, body_text FROM event_filings WHERE source = 'sec'"
                )
            )
            return rows, facts, bodies
        finally:
            await engine.dispose()

    rows, facts, bodies = run(check())
    assert len(rows) == 5
    by = lambda accession: rows[f"sec:{accession}"]  # noqa: E731
    # columns: key, source, category, excluded_reason, is_correction, link, original, latest,
    #          truncated, errors, ticker, cik, form, first_filed, note
    assert by(EARNINGS)[1:3] == ("sec", "earnings")
    assert (by(EARNINGS)[10], by(EARNINGS)[11], by(EARNINGS)[12]) == ("AAPL", "0000320193", "8-K")
    assert by(LEADERSHIP)[2:9] == ("leadership", None, False, "none", None, False, False)
    assert by(AMENDMENT)[2:9] == (
        "leadership", None, True, "linked", f"sec:{LEADERSHIP}", True, False
    )
    assert by(AMENDMENT)[12:14] == ("8-K/A", datetime.date(2026, 4, 20))
    assert by(VOTE)[2:4] == (None, "shareholder_vote")  # stored with its reason
    assert by(BROKEN)[9] and "EX-99.1 ex991.htm" in by(BROKEN)[9][0]  # error kept on the row
    assert bodies[f"sec:{VOTE}"] is None and bodies[f"sec:{AMENDMENT}"].startswith("[8-K/A]")

    # Facts: items and event date for every listed filing (excluded and degraded ones too, so a
    # later 8-K/A can find its original); never a number.
    keyed = {(r[0], r[1]): r for r in facts}
    assert keyed[(f"sec:{EARNINGS}", "items")][2:5] == ("text", "2.02,9.01", None)
    assert keyed[(f"sec:{EARNINGS}", "report_date")][2:5] == ("date", None, datetime.date(2026, 11, 2))
    assert keyed[(f"sec:{AMENDMENT}", "items")][3] == "5.02"
    assert {r[0] for r in facts} == set(rows)
    assert all(r[5] is None for r in facts) and all(r[6].startswith("sec:submissions.") for r in facts)


def test_sec_rerun_with_an_unreadable_filing_keeps_its_stored_text_and_chain() -> None:
    from app.ingest.sec_events import run_sec_events
    from tests.test_sec_event_ingest import AMENDMENT, LEADERSHIP, scenario_client

    healthy = scenario_client()
    healthy.broken.clear()
    healthy.documents[("0000320193-26-000018", "ex991.htm")] = b"<p>net sales</p>"

    async def scenario():
        async with _database() as (factory, engine):
            first = await run_sec_events(healthy, "AAPL", factory, today=TODAY)
            assert first.ok and first.linked == 1
            probe = (
                "SELECT rcept_no, category, correction_link, original_rcept_no, is_latest, "
                "body_text FROM event_filings WHERE source = 'sec' ORDER BY rcept_no"
            )
            before = await _rows(engine, probe)
            n_facts = (await _rows(engine, "SELECT count(*) FROM filing_facts"))[0][0]
            assert n_facts == 10  # items + event date for each of the five listed filings

            down = scenario_client()
            down.broken = {(AMENDMENT, "ef20081427_8ka.htm"), (LEADERSHIP, "ef20071035_8k.htm")}
            down.documents[("0000320193-26-000018", "ex991.htm")] = b"<p>net sales</p>"
            second = await run_sec_events(down, "AAPL", factory, today=TODAY)
            assert second.ok is False and len(second.problems) == 2

            after = await _rows(engine, probe)
            assert after == before  # stored text, link and latest flags survive an unreadable run
            errors = await _rows(
                engine,
                "SELECT rcept_no, errors FROM event_filings WHERE jsonb_array_length(errors) > 0",
            )
            assert {r[0] for r in errors} == {f"sec:{AMENDMENT}", f"sec:{LEADERSHIP}"}
            assert (await _rows(engine, "SELECT count(*) FROM filing_facts"))[0][0] == n_facts

            # A healthy rerun is idempotent: same rows, no duplicates, errors cleared.
            third = await run_sec_events(healthy, "AAPL", factory, today=TODAY)
            assert third.ok
            assert await _rows(engine, probe) == before
            assert (await _rows(engine, "SELECT count(*) FROM event_filings"))[0][0] == 5
            cleared = "SELECT count(*) FROM event_filings WHERE jsonb_array_length(errors) > 0"
            assert (await _rows(engine, cleared))[0][0] == 0

    run(scenario())


def test_sec_and_dart_rows_share_the_table_and_the_source_column_is_checked() -> None:
    from app.ingest.sec_events import run_sec_events
    from tests.test_sec_event_ingest import scenario_client

    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            dart_before = await _rows(
                engine, "SELECT count(*), min(source), max(source) FROM event_filings"
            )
            assert dart_before[0][1:] == ("dart", "dart")  # the column defaults for DART rows
            healthy = scenario_client()
            healthy.broken.clear()
            await run_sec_events(healthy, "AAPL", factory, today=TODAY)
            counts = await _rows(
                engine, "SELECT source, count(*) FROM event_filings GROUP BY source ORDER BY 1"
            )
            assert counts == [("dart", dart_before[0][0]), ("sec", 5)]
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(text("UPDATE event_filings SET source = 'edgar'"))

    run(scenario())


# -- a degraded member freezes its whole stored chain (reviewer items 1 and 2) -----------------

_CHAIN = (
    "SELECT rcept_no, correction_link, original_rcept_no, is_latest, correction_note "
    "FROM event_filings WHERE source = 'sec' AND category = 'leadership' ORDER BY rcept_no"
)
AMENDMENT_2 = "0001140361-26-099999"


def _chain_client(*, broken=(), accessions=None, extra=False):
    from app.clients.sec import SecFilingItem, parse_submissions_payload
    from tests.sec_fakes import submissions_payload
    from tests.test_sec_event_ingest import AMENDMENT, BROKEN, scenario_client

    client = scenario_client()
    client.broken = set(broken)
    client.documents[(BROKEN, "ex991.htm")] = b"<p>net sales</p>"
    client.documents[(AMENDMENT_2, "am2.htm")] = b"<html><body><p>Second amendment.</p></body></html>"
    client.indexes[AMENDMENT_2] = [("am2.htm", "8-K/A")]
    if accessions is not None:
        client.accessions = set(accessions)
    if extra:
        listed = parse_submissions_payload(submissions_payload("AAPL"), ["8-K/A"])
        base = next(f for f in listed if f.accession_number == AMENDMENT)
        client.extras = [
            SecFilingItem(
                AMENDMENT_2, "8-K/A", base.filing_date + datetime.timedelta(days=30),
                base.report_date, "am2.htm", items=base.items,
            )  # fmt: skip
        ]
    return client


def _one_latest_per_chain(rows) -> None:
    """A chain is an original plus the corrections linked to it; at most one member is latest."""
    chains: dict[str, list[bool]] = {}
    for key, link, original, latest, _ in rows:
        chains.setdefault(original if link == "linked" else key, []).append(latest)
    for flags in chains.values():
        assert sum(flags) <= 1


def test_a_degraded_original_does_not_unlink_its_healthy_stored_correction() -> None:
    from app.ingest.sec_events import run_sec_events
    from tests.test_sec_event_ingest import AMENDMENT, LEADERSHIP

    async def scenario():
        async with _database() as (factory, engine):
            assert (await run_sec_events(_chain_client(), "AAPL", factory, today=TODAY)).ok
            before = await _rows(engine, _CHAIN)
            by = {r[0]: r for r in before}
            assert by[f"sec:{AMENDMENT}"][1:4] == ("linked", f"sec:{LEADERSHIP}", True)
            assert by[f"sec:{LEADERSHIP}"][3] is False

            # Break ONE filing: the original. The amendment is healthy.
            client = _chain_client(broken={(LEADERSHIP, "ef20071035_8k.htm")})
            second = await run_sec_events(client, "AAPL", factory, today=TODAY)
            assert second.ok is False
            assert await _rows(engine, _CHAIN) == before
            _one_latest_per_chain(await _rows(engine, _CHAIN))

    run(scenario())


def test_a_degraded_correction_keeps_the_stored_chain_of_its_healthy_original() -> None:
    from app.ingest.sec_events import run_sec_events
    from tests.test_sec_event_ingest import AMENDMENT

    async def scenario():
        async with _database() as (factory, engine):
            await run_sec_events(_chain_client(), "AAPL", factory, today=TODAY)
            before = await _rows(engine, _CHAIN)
            # Break ONE filing: the amendment.
            client = _chain_client(broken={(AMENDMENT, "ef20081427_8ka.htm")})
            await run_sec_events(client, "AAPL", factory, today=TODAY)
            assert await _rows(engine, _CHAIN) == before

    run(scenario())


def test_a_new_correction_joining_a_frozen_chain_waits_unlinked_until_a_healthy_run() -> None:
    from app.ingest.sec_events import run_sec_events
    from tests.test_sec_event_ingest import AMENDMENT, LEADERSHIP

    async def scenario():
        async with _database() as (factory, engine):
            await run_sec_events(_chain_client(), "AAPL", factory, today=TODAY)
            before = {r[0]: r for r in await _rows(engine, _CHAIN)}

            client = _chain_client(broken={(LEADERSHIP, "ef20071035_8k.htm")}, extra=True)
            summary = await run_sec_events(client, "AAPL", factory, today=TODAY)
            rows = {r[0]: r for r in await _rows(engine, _CHAIN)}
            assert rows[f"sec:{AMENDMENT}"] == before[f"sec:{AMENDMENT}"]  # still linked + latest
            assert rows[f"sec:{LEADERSHIP}"] == before[f"sec:{LEADERSHIP}"]
            waiting = rows[f"sec:{AMENDMENT_2}"]
            assert waiting[1:4] == ("unlinked", None, False)
            assert "could not be read" in waiting[4]
            assert any(f"sec:{AMENDMENT_2}" in p and "not latest" in p for p in summary.problems)
            _one_latest_per_chain(list(rows.values()))

            healed = await run_sec_events(_chain_client(extra=True), "AAPL", factory, today=TODAY)
            assert healed.ok
            rows = {r[0]: r for r in await _rows(engine, _CHAIN)}
            assert rows[f"sec:{AMENDMENT_2}"][1:4] == ("linked", f"sec:{LEADERSHIP}", True)
            assert rows[f"sec:{AMENDMENT}"][3] is False
            _one_latest_per_chain(list(rows.values()))

    run(scenario())


def test_a_healthy_amendment_keeps_its_link_when_the_original_left_the_listing() -> None:
    from app.ingest.sec_events import run_sec_events
    from tests.test_sec_event_ingest import AMENDMENT, LEADERSHIP

    async def scenario():
        async with _database() as (factory, engine):
            await run_sec_events(_chain_client(), "AAPL", factory, today=TODAY)
            before = {r[0]: r for r in await _rows(engine, _CHAIN)}
            kept = {"0000320193-26-000024", AMENDMENT, "0000320193-26-000018", "0001193125-26-447173"}
            await run_sec_events(_chain_client(accessions=kept), "AAPL", factory, today=TODAY)
            rows = {r[0]: r for r in await _rows(engine, _CHAIN)}
            assert rows[f"sec:{AMENDMENT}"] == before[f"sec:{AMENDMENT}"]
            assert rows[f"sec:{LEADERSHIP}"] == before[f"sec:{LEADERSHIP}"]  # stays in the DB

    run(scenario())


_DART_CHAIN = (
    "SELECT rcept_no, correction_link, original_rcept_no, is_latest FROM event_filings "
    "WHERE category = 'capital' AND report_nm LIKE '%유상증자결정%' AND NOT subsidiary "
    "ORDER BY rcept_no"
)
_NAVER_ORIGINAL = "20260727000001"
_NAVER_CORRECTION = "20261103000311"


def _dart_with_broken(rcept_no: str) -> FakeDartClient:
    from app.clients.dart import DartApiError

    return FakeDartClient(
        "035420",
        documents={_NAVER_CORRECTION: BODY},
        broken={rcept_no: DartApiError("document.xml unavailable")},
    )


class _WithoutFiling(FakeDartClient):
    """The listing no longer contains ``dropped``: its filing left the rolling window."""

    dropped = _NAVER_ORIGINAL

    async def list_all_filings(self, *args, **kwargs):
        listing = await super().list_all_filings(*args, **kwargs)
        listing.items[:] = [i for i in listing.items if i.rcept_no != self.dropped]
        return listing


def test_dart_correction_keeps_its_stored_link_when_the_original_left_the_window() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            before = await _rows(engine, _DART_CHAIN)
            assert {r[0]: r[1:] for r in before}[_NAVER_CORRECTION] == (
                "linked", _NAVER_ORIGINAL, True
            )
            client = _WithoutFiling("035420", documents={_NAVER_CORRECTION: BODY})
            await run_dart_events(client, "035420", factory, today=TODAY)
            after = {r[0]: r[1:] for r in await _rows(engine, _DART_CHAIN)}
            assert after[_NAVER_CORRECTION] == ("linked", _NAVER_ORIGINAL, True)
            assert after[_NAVER_ORIGINAL] == {r[0]: r[1:] for r in before}[_NAVER_ORIGINAL]

    run(scenario())


def test_dart_degraded_correction_leaves_the_stored_chain_alone() -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_fake(), "035420", factory, today=TODAY)
            before = await _rows(engine, _DART_CHAIN)
            # Break ONE filing: the correction.
            await run_dart_events(
                _dart_with_broken(_NAVER_CORRECTION), "035420", factory, today=TODAY
            )
            assert await _rows(engine, _DART_CHAIN) == before

    run(scenario())


# -- orphan chains: corrections of one missing original are one chain ---------------------------

_NAVER_C1 = "20261030000001"  # rm 정 in the saved list


class _OrphanedNaver(_WithoutFiling):
    """The original is before the window; C1 and C2 both state its first-filing date."""

    def __init__(self, c1_rm: str) -> None:
        super().__init__("035420", documents={_NAVER_CORRECTION: BODY, _NAVER_C1: BODY})
        self.c1_rm = c1_rm

    async def list_all_filings(self, *args, **kwargs):
        listing = await super().list_all_filings(*args, **kwargs)
        listing.items[:] = [
            dataclasses.replace(i, rm=self.c1_rm) if i.rcept_no == _NAVER_C1 else i
            for i in listing.items
        ]
        return listing


@pytest.mark.parametrize("c1_rm", ["정", ""], ids=["c1_marked_replaced", "c1_not_marked"])
def test_dart_orphan_corrections_of_a_missing_original_have_exactly_one_latest(c1_rm) -> None:
    async def scenario():
        async with _database() as (factory, engine):
            await run_dart_events(_OrphanedNaver(c1_rm), "035420", factory, today=TODAY)
            rows = await _rows(
                engine,
                "SELECT rcept_no, correction_link, original_rcept_no, is_latest, "
                "correction_first_filed_at, correction_note FROM event_filings "
                "WHERE category = 'capital' AND report_nm LIKE '%유상증자결정%' "
                "AND NOT subsidiary ORDER BY rcept_no",
            )
            by = {r[0]: r for r in rows}
            assert _NAVER_ORIGINAL not in by
            for rcept_no in (_NAVER_C1, _NAVER_CORRECTION):
                assert by[rcept_no][1:3] == ("unlinked", None)
                assert by[rcept_no][4] == datetime.date(2026, 7, 27)  # shared first-filing date
                assert "no original filed on 2026-07-27" in by[rcept_no][5]
            assert [r[0] for r in rows if r[3]] == [_NAVER_CORRECTION]
            assert by[_NAVER_C1][3] is False

    run(scenario())


_UNREAD = "20260727800009"  # in scope, not a correction: its category does not need the body


def _text_body(tmp_path, text: str):
    path = tmp_path / "body.xml"
    path.write_text(f"<html><body><p>{text}</p></body></html>", encoding="utf-8")
    return path


_BODIES = (
    "SELECT rcept_no, body_text, body_truncated, category IS NOT NULL FROM event_filings "
    "ORDER BY rcept_no"
)


def test_dart_body_text_is_stored_for_in_scope_rows_only_and_a_failed_refetch_keeps_it(
    tmp_path,
) -> None:
    from app.clients.dart import DartApiError

    async def scenario():
        async with _database() as (factory, engine):
            first = FakeDartClient(
                "035420",
                documents={"20261103000311": BODY, _UNREAD: _text_body(tmp_path, "원문 하나")},
            )
            await run_dart_events(first, "035420", factory, today=TODAY)
            rows = {r[0]: r for r in await _rows(engine, _BODIES)}
            in_scope = [r for r in rows.values() if r[3]]
            assert in_scope and all(r[1] for r in in_scope)  # every in-scope row has text
            assert all(r[1] is None for r in rows.values() if not r[3])  # excluded rows: none
            assert rows[_UNREAD][1] == "원문 하나" and rows[_UNREAD][2] is False
            assert len(rows["20261103000311"][1]) > 1000

            # A re-run whose fetch of that filing fails: the stored text stays, the run fails.
            down = FakeDartClient(
                "035420",
                documents={"20261103000311": BODY},
                broken={_UNREAD: DartApiError("document.xml unavailable")},
            )
            second = await run_dart_events(down, "035420", factory, today=TODAY)
            assert not second.ok
            assert any(p.startswith(f"document {_UNREAD}") for p in second.problems)
            kept = {r[0]: r for r in await _rows(engine, _BODIES)}
            assert kept[_UNREAD][1] == "원문 하나"  # not NULL, not the placeholder
            assert {k: v[1:3] for k, v in kept.items() if k != _UNREAD} == {
                k: v[1:3] for k, v in rows.items() if k != _UNREAD
            }

            # A healthy run replaces it with the new text.
            third = FakeDartClient(
                "035420",
                documents={"20261103000311": BODY, _UNREAD: _text_body(tmp_path, "원문 둘")},
            )
            await run_dart_events(third, "035420", factory, today=TODAY)
            latest = {r[0]: r for r in await _rows(engine, _BODIES)}
            assert latest[_UNREAD][1] == "원문 둘"

    run(scenario())


def test_a_new_row_whose_first_fetch_fails_is_stored_without_text_beside_rows_with_text() -> None:
    from app.clients.dart import DartApiError

    async def scenario():
        async with _database() as (factory, engine):
            down = FakeDartClient(
                "035420",
                documents={"20261103000311": BODY},
                broken={_UNREAD: DartApiError("document.xml unavailable")},
            )
            summary = await run_dart_events(down, "035420", factory, today=TODAY)
            assert not summary.ok
            rows = {r[0]: r for r in await _rows(engine, _BODIES)}
            assert rows[_UNREAD][1] is None
            assert rows["20261103000311"][1]  # same statement set, other rows keep their text

    run(scenario())
