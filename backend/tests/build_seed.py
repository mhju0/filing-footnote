"""Fixture-seeded build data for the M8 export tests (no network).

The annual filings go through the real DART and SEC adapters from the pinned responses in
``fixtures/build/pinned``; the event filings go through the M3 event ingest with the saved
Samsung Electronics (005930) fixtures, and Apple's 8-K filings go through the M4 SEC event
ingest with the saved AAPL fixtures. :func:`fixture_build_input` returns the same data
without a database; :func:`seed` writes it into a ``*_test`` database.

    python -m tests.build_seed create   # prints the URL of a new seeded *_test database
    python -m tests.build_seed drop URL
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.build.model import (
    AnnualFilingRow,
    BuildInput,
    ChunkRow,
    CompanyRow,
    EventFactRow,
    FinancialRow,
)
from app.build.source import event_rows
from app.clients.dart import DartClient, _filing_item_from_row
from app.clients.sec import SecCompanyMatch, SecFilingItem, parse_companyfacts_payload
from app.db.models import Base
from app.filings.model import NormalizedFiling
from app.filings.persistence import persist_normalized_filing
from app.ingest.chunking import Chunk
from app.ingest.dart import build_dart_normalized_filing, filing_type_for, period_descriptor
from app.ingest.events import collect_dart_events, persist_events, window_bounds
from app.ingest.sec_events import collect_sec_events
from app.ingest.sec_ingest import build_sec_normalized_filing
from tests.event_fakes import DART, FakeDartClient
from tests.sec_fakes import FakeSecClient

BACKEND = Path(__file__).resolve().parents[1]
PINNED_BUILD = Path(__file__).parent / "fixtures" / "build" / "pinned"
PINNED_EVENTS = Path(__file__).parent / "fixtures" / "events"
PINNED_DIRS = (PINNED_BUILD, PINNED_EVENTS)
AS_OF = datetime.date(2026, 11, 17)
EVENT_TICKER = "005930"
APPLE_CIK = "0000320193"
CORRECTION = "20261029800099"
CORRECTION_BODY = DART / "correction" / f"{CORRECTION}.xml"

_DART_ANNUAL = PINNED_BUILD / "dart" / "fnlttSinglAcntAll" / "00126380_2025_11011_CFS.json"
_SEC_FACTS = PINNED_BUILD / "sec" / "companyfacts" / "CIK0000320193.json"
_SEC_ACCESSION = "0000320193-25-000079"
_SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


def _chunk(content: str) -> Chunk:
    return Chunk(chunk_index=0, content=content, section_title="I. 회사의 개요", section_order=0,
                 part_index=0)  # fmt: skip


def annual_filings() -> list[NormalizedFiling]:
    dart_item = _filing_item_from_row(
        {
            "corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930",
            "corp_cls": "Y", "report_nm": "사업보고서 (2025.12)", "rcept_no": "20260310000123",
            "flr_nm": "삼성전자", "rcept_dt": "20260310", "rm": "연",
        }
    )  # fmt: skip
    dart = build_dart_normalized_filing(
        filing_item=dart_item,
        corp_code="00126380",
        name_en="SAMSUNG ELECTRONICS CO,.LTD",
        descriptor=period_descriptor("2025", "11011"),
        filing_type=filing_type_for("11011"),
        financial_items=DartClient._parse_financials_payload(json.loads(_DART_ANNUAL.read_text())),
        chunks=[_chunk("회사의 개요 본문")],
    )
    sec_items = [
        i
        for i in parse_companyfacts_payload(json.loads(_SEC_FACTS.read_text()), with_prior=True)
        if i.accession_number == _SEC_ACCESSION
    ]
    sec = build_sec_normalized_filing(
        company_match=SecCompanyMatch(cik="0000320193", ticker="AAPL", title="Apple Inc."),
        cik10="0000320193",
        filing=SecFilingItem(
            accession_number=_SEC_ACCESSION,
            form="10-K",
            filing_date=datetime.date(2025, 10, 31),
            report_date=datetime.date(2025, 9, 27),
            primary_document="aapl-20250927.htm",
        ),
        fiscal_year=2025,
        document_url=_SEC_URL,
        financial_items=sec_items,
        chunks=[_chunk("Item 1. Business text")],
    )
    return [dart, sec]


def _event_client() -> FakeDartClient:
    # The one saved Samsung correction body: it names the 2026-10-08 filing, so that pair links.
    return FakeDartClient(EVENT_TICKER, documents={CORRECTION: CORRECTION_BODY})


async def _event_batches() -> tuple[list, list]:
    """Samsung's DART events and Apple's 8-K events (with the 8-K/A chain of 2026-04-17),
    one list per source as the ingest persists them."""
    window = window_bounds(AS_OF)
    dart, _ = await collect_dart_events(_event_client(), "00126380", window)
    sec, _ = await collect_sec_events(FakeSecClient("AAPL"), APPLE_CIK, "AAPL", "Apple Inc.",
                                      window)  # fmt: skip
    return dart, sec


async def _event_records() -> list:
    dart, sec = await _event_batches()
    return [*dart, *sec]


def fixture_build_input() -> BuildInput:
    """The seeded data as the exporter's input rows, built without a database."""
    companies: dict[tuple[str, str], CompanyRow] = {}
    filings: list[AnnualFilingRow] = []
    financials: list[FinancialRow] = []
    for filing in annual_filings():
        regulator = filing.identity.source.value.upper()
        company_key = filing.company.identity.source_company_id
        companies[(regulator, company_key)] = CompanyRow(
            regulator, company_key, filing.company.name, filing.company.name_en,
            filing.company.ticker, filing.company.market,
        )  # fmt: skip
        digest = hashlib.sha256()
        for chunk in filing.filing_chunks:
            digest.update(chunk.content.encode() + b"\n")
        filings.append(
            AnnualFilingRow(
                regulator, filing.identity.source_filing_id, company_key, filing.filing_type,
                filing.title, filing.reporting_period.label, filing.filed_at, filing.url,
                digest.hexdigest(),
                tuple(ChunkRow(c.chunk_index, c.location.section_title, c.content)
                      for c in filing.filing_chunks),
            )
        )  # fmt: skip
        for fact in filing.financial_facts:
            financials.append(
                FinancialRow(
                    regulator, filing.identity.source_filing_id, company_key, fact.metric.value,
                    fact.period.label, fact.period.kind.value, int(fact.period.label[:4]),
                    fact.period.start_date, fact.period.end_date, fact.value, fact.unit,
                    fact.currency,
                )
            )  # fmt: skip

    events = event_rows(*event_input())
    return BuildInput(tuple(companies.values()), tuple(filings), tuple(financials), tuple(events))


def event_input() -> tuple[list[dict], dict[str, list[EventFactRow]]]:
    """The ``event_filings`` rows the ingest writes and their facts by row key, for
    :func:`app.build.source.event_rows`."""
    rows, facts = [], {}
    for record in asyncio.run(_event_records()):
        # The database fills source (default 'dart') for a DART row. Every fixture event gets a
        # stored body (a placeholder when it has none): the exporter leaves out an event
        # without one (D72).
        row = {"source": "dart", **record.to_row()}
        row["body_text"] = row.get("body_text") or f"본문 {record.key}"
        rows.append(row)
        facts[record.key] = [
            EventFactRow(f.key, f.kind, f.unit, f.source_field, f.raw, f.value_decimal,
                         f.value_date, f.value_text, f.error)
            for f in record.facts or []
        ]  # fmt: skip
    return rows, facts


def _require_test_database(url: str) -> None:
    if not (make_url(url).database or "").endswith("_test"):
        raise SystemExit("refusing: the database name must end with _test")


async def seed(database_url: str) -> None:
    """Replace the schema of a ``*_test`` database and fill it through the ingest code."""
    _require_test_database(database_url)
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text((BACKEND / "db/init.sql").read_text()))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        for filing in annual_filings():
            async with factory() as session:
                await persist_normalized_filing(session, filing)
        for batch in await _event_batches():
            await persist_events(factory, batch)
        # The same placeholder body event_input() gives every event (D72).
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE event_filings SET body_text = '본문 ' || rcept_no WHERE body_text IS NULL")
            )
    finally:
        await engine.dispose()


def _admin_url():
    from app.config import get_settings

    return make_url(get_settings().database_url).set(drivername="postgresql")


def create() -> str:
    admin = _admin_url()
    database = f"filing_footnote_build_{uuid.uuid4().hex}_test"
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    url = admin.set(drivername="postgresql+psycopg", database=database)
    rendered = url.render_as_string(hide_password=False)
    asyncio.run(seed(rendered))
    return rendered


def drop(url: str) -> None:
    _require_test_database(url)
    database = make_url(url).database
    admin = _admin_url()
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "create":
        print(create())
    elif command == "drop" and len(sys.argv) == 3:
        drop(sys.argv[2])
    else:
        raise SystemExit("usage: python -m tests.build_seed create | drop URL")
