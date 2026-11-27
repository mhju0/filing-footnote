"""Read the build database into :class:`app.build.model.BuildInput`. Read-only SELECTs.

Event filings are read through :func:`read_event_rows` alone, which maps the rows with
:func:`event_rows`; a change to the event tables is fixed in those two functions.
"""

from __future__ import annotations

import datetime
import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.build import summaries
from app.build.model import (
    AnnualFilingRow,
    BuildError,
    BuildInput,
    ChunkRow,
    CompanyRow,
    EventFactRow,
    EventRow,
    ExcludedFiling,
    FinancialRow,
    SummaryRow,
)
from app.clients.dart_events import load_facts_contract
from app.clients.sec import format_cik
from app.filings.categories import normalise_dart_name
from app.ingest.sec_events import item_set

_REGULATOR = {"dart": "DART", "sec": "SEC"}
SEC_KEY_PREFIX = "sec:"  # app.ingest.sec_events.sec_key
# The owner's list of event filings left out of every bundle, tracked and reviewed (D109).
EXCLUDED_PATH = summaries.SUMMARIES_DIR / "excluded_filings.jsonl"
_EXCLUDED_FIELDS = frozenset({"filing_id", "decided_on", "reason"})


def _company_key(source: str, dart_corp_code: str | None, sec_cik: str | None) -> str:
    if source == "dart":
        return str(dart_corp_code or "")
    return format_cik(sec_cik) if sec_cik else ""


async def read_companies(connection: AsyncConnection) -> list[CompanyRow]:
    result = await connection.execute(
        text("SELECT source, dart_corp_code, sec_cik, name, name_en, ticker, market FROM companies")
    )
    return [
        CompanyRow(
            regulator=_REGULATOR[row.source],
            key=_company_key(row.source, row.dart_corp_code, row.sec_cik),
            name=row.name,
            name_en=row.name_en,
            ticker=row.ticker,
            market=row.market,
        )
        for row in result
    ]


async def _chunks(connection: AsyncConnection) -> tuple[dict[object, str], dict[object, tuple]]:
    """Per filing: the SHA-256 of its chunk texts in chunk order, and the chunks themselves."""
    digests = defaultdict(hashlib.sha256)
    chunks: dict[object, list[ChunkRow]] = defaultdict(list)
    result = await connection.execute(
        text(
            "SELECT filing_id, chunk_index, content, meta->>'section_title' AS section_title,"
            " meta->>'part_title' AS part_title"
            " FROM filing_chunks ORDER BY filing_id, chunk_index"
        )
    )
    for row in result:
        digest = digests[row.filing_id]
        digest.update(row.content.encode("utf-8"))
        digest.update(b"\n")
        chunks[row.filing_id].append(
            ChunkRow(row.chunk_index, row.section_title, row.content, row.part_title)
        )
    hashes = {filing_id: digest.hexdigest() for filing_id, digest in digests.items()}
    return hashes, {filing_id: tuple(found) for filing_id, found in chunks.items()}


async def read_annual_filings(connection: AsyncConnection) -> list[AnnualFilingRow]:
    hashes, chunks = await _chunks(connection)
    empty = hashlib.sha256(b"").hexdigest()
    result = await connection.execute(
        text(
            "SELECT f.id, f.source, f.rcept_no, f.sec_accession_no, c.dart_corp_code, c.sec_cik,"
            " f.filing_type, f.title, f.period, f.filed_at, f.url"
            " FROM filings f JOIN companies c ON c.id = f.company_id"
        )
    )
    return [
        AnnualFilingRow(
            regulator=_REGULATOR[row.source],
            filing_key=str(row.rcept_no if row.source == "dart" else row.sec_accession_no),
            company_key=_company_key(row.source, row.dart_corp_code, row.sec_cik),
            filing_type=row.filing_type,
            title=row.title,
            period=row.period,
            filed_on=row.filed_at,
            url=row.url,
            source_text_sha256=hashes.get(row.id, empty),
            chunks=chunks.get(row.id, ()),
        )
        for row in result
    ]


async def read_financials(connection: AsyncConnection) -> list[FinancialRow]:
    result = await connection.execute(
        text(
            "SELECT f.source, f.rcept_no, f.sec_accession_no, c.dart_corp_code, c.sec_cik,"
            " x.metric, x.period, x.period_kind, x.fiscal_year, x.period_start, x.period_end,"
            " x.value, x.unit, x.currency, x.scale"
            " FROM financials x JOIN filings f ON f.id = x.filing_id"
            " JOIN companies c ON c.id = f.company_id"
        )
    )
    rows = []
    for row in result:
        if row.scale != 1:
            raise ValueError(f"financials row with scale {row.scale} is not supported")
        rows.append(
            FinancialRow(
                regulator=_REGULATOR[row.source],
                filing_key=str(row.rcept_no if row.source == "dart" else row.sec_accession_no),
                company_key=_company_key(row.source, row.dart_corp_code, row.sec_cik),
                metric=row.metric,
                period=row.period,
                period_kind=row.period_kind,
                fiscal_year=row.fiscal_year,
                period_start=row.period_start,
                period_end=row.period_end,
                value=row.value,
                unit=row.unit,
                currency=row.currency,
            )
        )
    return rows


def _bare_key(source: str, key: str) -> str:
    """``sec:<accession>`` -> ``<accession>``; a DART 접수번호 stays as it is."""
    if source != "sec":
        return key
    if not key.startswith(SEC_KEY_PREFIX):
        raise ValueError(f"SEC event row key {key!r} lacks the {SEC_KEY_PREFIX!r} prefix")
    return key.removeprefix(SEC_KEY_PREFIX)


def _sec_orphan_chains(
    rows: list[Mapping[str, Any]],
    items: Mapping[str, str],
    report_dates: Mapping[str, datetime.date | None],
) -> dict[str, str]:
    """Row key -> orphan chain key, grouped as ``resolve_sec_chains`` groups them: unlinked
    8-K/As of one CIK with the same event date that share an item other than 9.01 form one
    chain, named after its smallest member key."""
    unlinked = sorted(
        (r for r in rows if r["correction_link"] == "unlinked" and report_dates.get(r["rcept_no"])),
        key=lambda r: r["rcept_no"],
    )

    def joins(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        return (
            a["corp_code"] == b["corp_code"]
            and report_dates[a["rcept_no"]] == report_dates[b["rcept_no"]]
            and bool(
                item_set(items.get(a["rcept_no"], "")) & item_set(items.get(b["rcept_no"], ""))
            )
        )

    groups: list[list[Mapping[str, Any]]] = []
    for row in unlinked:
        joined = [g for g in groups if any(joins(m, row) for m in g)]
        groups = [g for g in groups if g not in joined] + [[row] + [m for g in joined for m in g]]
    return {m["rcept_no"]: min(x["rcept_no"] for x in g) for g in groups for m in g}


def event_rows(
    rows: Sequence[Mapping[str, Any]], facts: Mapping[str, Sequence[EventFactRow]]
) -> list[EventRow]:
    """Exporter rows from ``event_filings`` columns (a database row or an ingest record's
    ``to_row()``) and their facts by row key (``rcept_no``).

    Chains follow the ingest. A linked correction joins its original's chain. Unlinked
    corrections the ingest groups as orphans share a chain: for DART those with the same
    company, base report name, subsidiary flag and ``correction_first_filed_at``; for SEC those
    of one CIK with the same event date and a shared item other than 9.01. Any other filing is
    a chain of its own. A DART row also gets the target it is a version of (company, base name,
    subsidiary flag and first filing date), which the exporter's 정 rule matches on.
    """
    items_key, date_key = (field["key"] for field in load_facts_contract()["sec"]["fields"])
    sec_items: dict[str, str] = {}
    report_dates: dict[str, datetime.date | None] = {}
    for key, found in facts.items():
        for fact in found:
            if fact.key == items_key and fact.value_text is not None:
                sec_items[key] = fact.value_text
            elif fact.key == date_key:
                report_dates[key] = fact.value_date
    sec_orphans = _sec_orphan_chains(
        [r for r in rows if r["source"] == "sec"], sec_items, report_dates
    )

    events = []
    for row in rows:
        source, row_key, link = row["source"], row["rcept_no"], row["correction_link"]
        key = _bare_key(source, row_key)
        target_key = None
        if source == "dart":
            base = normalise_dart_name(row["report_nm"])[0]
            first = row["filed_at"] if link == "none" else row["correction_first_filed_at"]
            if first is not None and (link != "none" or not row["is_correction"]):
                target_key = f"{row['corp_code']}|{base}|{int(row['subsidiary'])}|{first}"
        if link == "linked":
            if not row["original_rcept_no"]:
                raise ValueError(f"{row_key}: linked correction without its original")
            chain_key = _bare_key(source, row["original_rcept_no"])
        elif source == "dart" and link == "unlinked" and target_key is not None:
            chain_key = f"orphan:{target_key}"
        elif row_key in sec_orphans:
            chain_key = f"orphan:{_bare_key(source, sec_orphans[row_key])}"
        else:
            chain_key = key
        events.append(
            EventRow(
                regulator=_REGULATOR[source],
                filing_key=key,
                company_key=row["corp_code"],
                stock_code=row["stock_code"] or None,
                report_nm=row["report_nm"],
                filed_on=row["filed_at"],
                rm=row["rm"],
                url=row["url"],
                category=row["category"],
                excluded_reason=row["excluded_reason"],
                is_correction=row["is_correction"],
                chain_key=chain_key,
                target_key=target_key,
                sec_items=sec_items.get(row_key) if source == "sec" else None,
                body_text=row["body_text"],
                facts=tuple(sorted(facts.get(row_key, ()), key=lambda f: (f.key, f.source_field))),
            )
        )
    return events


async def read_event_rows(connection: AsyncConnection) -> list[EventRow]:
    """The one adapter over ``event_filings`` and ``filing_facts`` (DART and SEC rows).

    Ingest's ``is_latest`` is not read: the exporter picks the version shown as of --as-of from
    the chains :func:`event_rows` builds.
    """
    facts: dict[str, list[EventFactRow]] = defaultdict(list)
    fact_result = await connection.execute(
        text(
            "SELECT e.rcept_no, x.key, x.kind, x.unit, x.source_field, x.raw, x.value_decimal,"
            " x.value_date, x.value_text, x.error"
            " FROM filing_facts x JOIN event_filings e ON e.id = x.event_filing_id"
        )
    )
    for row in fact_result:
        facts[row.rcept_no].append(
            EventFactRow(
                key=row.key,
                kind=row.kind,
                unit=row.unit,
                source_field=row.source_field,
                raw=row.raw,
                value_decimal=row.value_decimal,
                value_date=row.value_date,
                value_text=row.value_text,
                error=row.error,
            )
        )
    result = await connection.execute(
        text(
            "SELECT source, rcept_no, corp_code, stock_code, report_nm, filed_at, rm, url,"
            " category, excluded_reason, subsidiary, is_correction, correction_link,"
            " original_rcept_no, correction_first_filed_at, body_text FROM event_filings"
        )
    )
    return event_rows([dict(row._mapping) for row in result], facts)


def read_summaries(path: Path | None = None) -> list[SummaryRow]:
    """The owner-approved rows of ``approved.jsonl`` (``summaries.APPROVED_PATH`` by default).
    A missing file means no approved summaries, which a development build allows and a release
    refuses."""
    return summaries.read_approved(path or summaries.APPROVED_PATH)


def read_excluded(path: Path | None = None) -> list[ExcludedFiling]:
    """The owner's excluded filings (:data:`EXCLUDED_PATH` by default), one JSON object per line
    with exactly ``filing_id``, ``decided_on`` (an ISO date) and a non-empty ``reason``. A
    missing file means none. Any other line, or an id listed twice, raises :class:`BuildError`.
    """
    path = path or EXCLUDED_PATH
    entries, problems, seen = [], [], set()
    for number, row in enumerate(summaries.read_jsonl(path), start=1):
        where = f"{path.name} entry {number}"
        if not isinstance(row, dict) or set(row) != _EXCLUDED_FIELDS:
            problems.append(f"{where}: needs exactly {sorted(_EXCLUDED_FIELDS)}")
            continue
        filing_id, decided_on, reason = row["filing_id"], row["decided_on"], row["reason"]
        try:
            date = datetime.date.fromisoformat(decided_on)
        except (TypeError, ValueError):
            problems.append(f"{where}: decided_on {decided_on!r} is not an ISO date")
            continue
        if not isinstance(filing_id, str) or not isinstance(reason, str) or not reason.strip():
            problems.append(f"{where}: filing_id and a non-empty reason must be text")
            continue
        if filing_id in seen:
            problems.append(f"{where}: {filing_id} is listed twice")
            continue
        seen.add(filing_id)
        entries.append(ExcludedFiling(filing_id, date, reason))
    if problems:
        raise BuildError(problems)
    return entries


async def load_build_input(
    database_url: str, summaries_path: Path | None = None, excluded_path: Path | None = None
) -> BuildInput:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            return BuildInput(
                companies=tuple(await read_companies(connection)),
                annual_filings=tuple(await read_annual_filings(connection)),
                financials=tuple(await read_financials(connection)),
                events=tuple(await read_event_rows(connection)),
                summaries=tuple(read_summaries(summaries_path)),
                excluded=tuple(read_excluded(excluded_path)),
            )
    finally:
        await engine.dispose()
