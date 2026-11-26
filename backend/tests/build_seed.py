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

from app.build import faithfulness
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
from app.clients.sec import (
    SecCompanyMatch,
    SecFilingItem,
    parse_companyfacts_payload,
    parse_quarter_facts,
)
from app.db.models import Base
from app.filings.model import NormalizedFiling
from app.filings.persistence import persist_normalized_filing
from app.ingest.chunking import Chunk
from app.ingest.dart import build_dart_normalized_filing, filing_type_for, period_descriptor
from app.ingest.events import collect_dart_events, persist_events, window_bounds
from app.ingest.sec_events import collect_sec_events
from app.ingest.sec_ingest import build_sec_normalized_filing, build_sec_quarter_filing
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

_SEC_FACTS = PINNED_BUILD / "sec" / "companyfacts" / "CIK0000320193.json"
_SEC_ACCESSION = "0000320193-25-000079"
SAMSUNG_PRIOR = "20250310000456"
APPLE_PRIOR = "0000320193-24-000123"
SAMSUNG_QUARTER = "20261116000111"
APPLE_QUARTER = "0000320193-26-000020"


def _chunk(content: str) -> Chunk:
    return Chunk(chunk_index=0, content=content, section_title="I. 회사의 개요", section_order=0,
                 part_index=0)  # fmt: skip


def _dart_annual(year: str, rcept_no: str, rcept_dt: str) -> NormalizedFiling:
    item = _filing_item_from_row(
        {
            "corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930",
            "corp_cls": "Y", "report_nm": f"사업보고서 ({year}.12)", "rcept_no": rcept_no,
            "flr_nm": "삼성전자", "rcept_dt": rcept_dt, "rm": "연",
        }
    )  # fmt: skip
    payload = PINNED_BUILD / "dart" / "fnlttSinglAcntAll" / f"00126380_{year}_11011_CFS.json"
    return build_dart_normalized_filing(
        filing_item=item,
        corp_code="00126380",
        name_en="SAMSUNG ELECTRONICS CO,.LTD",
        descriptor=period_descriptor(year, "11011"),
        filing_type=filing_type_for("11011"),
        financial_items=DartClient._parse_financials_payload(json.loads(payload.read_text())),
        chunks=[_chunk("회사의 개요 본문")],
    )


def _sec_annual(accession: str, filed: datetime.date, report: datetime.date, year: int,
                document: str) -> NormalizedFiling:  # fmt: skip
    sec_items = [
        i
        for i in parse_companyfacts_payload(json.loads(_SEC_FACTS.read_text()), with_prior=True)
        if i.accession_number == accession
    ]
    return build_sec_normalized_filing(
        company_match=SecCompanyMatch(cik="0000320193", ticker="AAPL", title="Apple Inc."),
        cik10="0000320193",
        filing=SecFilingItem(
            accession_number=accession,
            form="10-K",
            filing_date=filed,
            report_date=report,
            primary_document=document,
        ),
        fiscal_year=year,
        document_url=f"https://www.sec.gov/Archives/edgar/data/320193/"
        f"{accession.replace('-', '')}/{document}",
        financial_items=sec_items,
        chunks=[_chunk("Item 1. Business text")],
    )


def annual_filings() -> list[NormalizedFiling]:
    """The latest annual report per company and the one before it, whose own-year values
    the latest report's comparatives repeat (so the prior-year figures are checked)."""
    return [
        _dart_annual("2025", "20260310000123", "20260310"),
        _dart_annual("2024", SAMSUNG_PRIOR, "20250310"),
        _sec_annual(_SEC_ACCESSION, datetime.date(2025, 10, 31), datetime.date(2025, 9, 27),
                    2025, "aapl-20250927.htm"),  # fmt: skip
        _sec_annual(APPLE_PRIOR, datetime.date(2024, 11, 1), datetime.date(2024, 9, 28), 2024,
                    "aapl-20240928.htm"),  # fmt: skip
    ]


def quarterly_filings() -> list[NormalizedFiling]:
    """Each company's latest quarterly report (I11): Samsung's 3분기보고서, whose operating
    income a year earlier is a loss, and Apple's 10-Q, through the real quarter parsers."""
    item = _filing_item_from_row(
        {
            "corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930",
            "corp_cls": "Y", "report_nm": "분기보고서 (2026.09)", "rcept_no": SAMSUNG_QUARTER,
            "flr_nm": "삼성전자", "rcept_dt": "20261116", "rm": "",
        }
    )  # fmt: skip
    payload = PINNED_BUILD / "dart" / "fnlttSinglAcntAll" / "00126380_2026_11014_CFS.json"
    samsung = build_dart_normalized_filing(
        filing_item=item,
        corp_code="00126380",
        name_en="SAMSUNG ELECTRONICS CO,.LTD",
        descriptor=period_descriptor("2026", "11014"),
        filing_type=filing_type_for("11014"),
        financial_items=DartClient._parse_financials_payload(json.loads(payload.read_text())),
        chunks=[],
    )
    apple = build_sec_quarter_filing(
        company_match=SecCompanyMatch(cik="0000320193", ticker="AAPL", title="Apple Inc."),
        cik10="0000320193",
        filing=SecFilingItem(
            accession_number=APPLE_QUARTER,
            form="10-Q",
            filing_date=datetime.date(2026, 7, 31),
            report_date=datetime.date(2026, 6, 27),
            primary_document="aapl-20260627.htm",
        ),
        financial_items=parse_quarter_facts(json.loads(_SEC_FACTS.read_text()), APPLE_QUARTER),
    )
    return [samsung, apple]


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
    for filing in [*annual_filings(), *quarterly_filings()]:
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
        for filing in [*annual_filings(), *quarterly_filings()]:
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


def supported_records(summaries) -> list[dict]:
    """A current, supported record with a one-sentence span for every approved line; the
    sentence and its offsets are made up, in the filing's language."""
    records = []
    for summary in summaries:
        if summary.review_state != "approved":
            continue
        for number, line in enumerate((summary.line1, summary.line2, summary.line3), start=1):
            if line is None:
                continue
            text = ("공시 원문 문장" if summary.filing_id.startswith("dart:")
                    else "A sentence of the filing.")  # fmt: skip
            start = 100 * number
            records.append({
                "filing_id": summary.filing_id, "lang": summary.lang,
                "section": summary.section, "line_no": number,
                "line_sha256": faithfulness.line_sha256(line),
                "input_sha256": summary.input_sha256, "verdict": faithfulness.SUPPORTED,
                "method": "direct", "aligner_version": faithfulness.ALIGNER_VERSION,
                "spans": [{"start": start, "end": start + len(text), "text": text}],
                "reasons": [],
            })  # fmt: skip
    return records
