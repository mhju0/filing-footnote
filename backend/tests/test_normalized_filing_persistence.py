"""PostgreSQL behavior tests for the public Normalized Filing persistence seam."""

import asyncio
import datetime
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.models import FilingChunk as ChunkRow
from app.filings.model import (
    CompanyIdentity,
    FilingChunk,
    FilingChunkLocation,
    FilingIdentity,
    NormalizedFiling,
    RegulatedCompany,
    RegulatorySource,
)
from app.filings.persistence import load_normalized_filing, persist_normalized_filing
from app.financials.model import FinancialFact, ReportingPeriod
from app.financials.vocabulary import PeriodKind, ReportedMetric

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError(
        "refusing to drop tables: TEST_DATABASE_URL must name an isolated *_test database"
    )
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL persistence tests",
)


@asynccontextmanager
async def _database():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text((Path(__file__).parents[1] / "db/init.sql").read_text()))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _snapshot(*, include_eps: bool, include_second_chunk: bool) -> NormalizedFiling:
    period = ReportingPeriod(
        label="2025-annual",
        kind=PeriodKind.duration,
        start_date=datetime.date(2025, 1, 1),
        end_date=datetime.date(2025, 12, 31),
    )
    facts = [
        FinancialFact(
            metric=ReportedMetric.revenue,
            period=period,
            value=Decimal("1000000"),
            unit="KRW",
            currency="KRW",
        )
    ]
    if include_eps:
        facts.append(
            FinancialFact(
                metric=ReportedMetric.eps,
                period=period,
                value=Decimal("12.34"),
                unit="KRW_PER_SHARE",
                currency="KRW",
            )
        )
    chunks = [
        FilingChunk(
            0,
            "Current evidence",
            FilingChunkLocation(section_title="Business"),
        )
    ]
    if include_second_chunk:
        chunks.append(
            FilingChunk(
                1,
                "Stale evidence",
                FilingChunkLocation(section_title="Risk"),
            )
        )
    return NormalizedFiling(
        company=RegulatedCompany(
            identity=CompanyIdentity(RegulatorySource.dart, "00126380"),
            name="Samsung Electronics",
            ticker="005930",
            market="KOSPI",
        ),
        identity=FilingIdentity(RegulatorySource.dart, "20260312000736"),
        filing_type="business_report",
        title="Business Report (2025.12)",
        reporting_period=period,
        financial_facts=tuple(facts),
        filing_chunks=tuple(chunks),
        filed_at=datetime.date(2026, 3, 12),
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260312000736",
    )


def test_reingestion_replaces_the_complete_authoritative_snapshot() -> None:
    async def run() -> None:
        async with _database() as factory:
            async with factory() as session:
                first_snapshot = _snapshot(include_eps=True, include_second_chunk=True)
                first_snapshot = replace(
                    first_snapshot,
                    company=replace(
                        first_snapshot.company,
                        name_en="Samsung Electronics Co., Ltd.",
                    ),
                )
                first = await persist_normalized_filing(
                    session,
                    first_snapshot,
                )
                second = await persist_normalized_filing(
                    session,
                    _snapshot(include_eps=False, include_second_chunk=False),
                )
                loaded = await load_normalized_filing(
                    session,
                    FilingIdentity(RegulatorySource.dart, "20260312000736"),
                )

            assert first.filing_id == second.filing_id
            assert loaded is not None
            assert loaded.company.name_en == "Samsung Electronics Co., Ltd."
            assert [fact.metric for fact in loaded.financial_facts] == [ReportedMetric.revenue]
            assert [chunk.content for chunk in loaded.filing_chunks] == ["Current evidence"]

    asyncio.run(run())


def test_chunk_part_title_is_stored_in_meta_only_when_recorded() -> None:
    async def run() -> None:
        async with _database() as factory:
            async with factory() as session:
                base = _snapshot(include_eps=False, include_second_chunk=False)
                chunks = (
                    FilingChunk(
                        0,
                        "child text",
                        FilingChunkLocation(section_title="2. 개요", part_title="IV. 경영진단"),
                    ),
                    FilingChunk(1, "no part", FilingChunkLocation(section_title="Item 1.")),
                )
                await persist_normalized_filing(session, replace(base, filing_chunks=chunks))
                loaded = await load_normalized_filing(session, base.identity)
                metas = (
                    await session.execute(select(ChunkRow.meta).order_by(ChunkRow.chunk_index))
                ).scalars().all()

            assert loaded is not None
            assert [c.location.part_title for c in loaded.filing_chunks] == ["IV. 경영진단", None]
            assert metas[0]["part_title"] == "IV. 경영진단"
            assert "part_title" not in metas[1]

    asyncio.run(run())


def test_failed_replacement_rolls_back_to_the_previous_complete_snapshot() -> None:
    async def run() -> None:
        async with _database() as factory:
            baseline = _snapshot(include_eps=True, include_second_chunk=True)
            oversized_fact = replace(
                baseline.financial_facts[0],
                value=Decimal("1000000000000000000000000000000"),
            )
            invalid_replacement = replace(
                baseline,
                financial_facts=(oversized_fact,),
                filing_chunks=(FilingChunk(0, "Would replace evidence"),),
            )

            async with factory() as session:
                await persist_normalized_filing(session, baseline)
                with pytest.raises(DataError):
                    await persist_normalized_filing(session, invalid_replacement)
                loaded = await load_normalized_filing(session, baseline.identity)

            assert loaded is not None
            assert {fact.metric for fact in loaded.financial_facts} == {
                ReportedMetric.revenue,
                ReportedMetric.eps,
            }
            assert [chunk.content for chunk in loaded.filing_chunks] == [
                "Current evidence",
                "Stale evidence",
            ]

    asyncio.run(run())


def test_two_filings_can_report_the_same_period_without_reassigning_provenance() -> None:
    async def run() -> None:
        async with _database() as factory:
            first = _snapshot(include_eps=False, include_second_chunk=False)
            second = replace(
                first,
                identity=FilingIdentity(RegulatorySource.dart, "20260401000001"),
                title="Corrected Business Report (2025.12)",
                financial_facts=(replace(first.financial_facts[0], value=Decimal("2000000")),),
                filing_chunks=(FilingChunk(0, "Corrected evidence"),),
            )

            async with factory() as session:
                first_result = await persist_normalized_filing(session, first)
                second_result = await persist_normalized_filing(session, second)
                loaded_first = await load_normalized_filing(session, first.identity)
                loaded_second = await load_normalized_filing(session, second.identity)

            assert first_result.filing_id != second_result.filing_id
            assert loaded_first is not None and loaded_second is not None
            assert loaded_first.financial_facts[0].value == Decimal("1000000.0000")
            assert loaded_second.financial_facts[0].value == Decimal("2000000.0000")

    asyncio.run(run())
