"""SEC 8-K event-filing ingest, into the same tables as the DART ingest.

    python -m app.ingest events --source sec --ticker AAPL

For one company and the last 12 months it

1. lists the 8-K and 8-K/A filings from the submissions API;
2. classifies each with ``classify_sec``, reading the primary document and EX-99.* exhibits
   only for the filings the contract needs text for (items 2.02, 7.01, 8.01) and for in-scope
   filings (their text is kept for summaries, cut at ``TEXT_STORE_LIMIT``);
3. links each in-scope 8-K/A to its original and marks the newest version of a chain as the one
   to show (older versions are kept);
4. writes item numbers and the event date as facts (D64: nothing is read from the text);
5. upserts ``event_filings`` and ``filing_facts`` through ``persist_events``.

A filing is stored as ``sec:<accession>`` with ``source='sec'``. Excluded filings are stored
with their reason. SEC has no field that names the amended filing, so an 8-K/A is linked only
when exactly one in-scope original of the same company has the same event date and shares an
item with it; otherwise it is stored unlinked with a note and nothing is guessed.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.dart_events import ExtractedFact, load_facts_contract
from app.clients.rate_limit import RequestLimiter, rate_limited_client
from app.clients.sec import SecClient, SecFilingItem, filing_index_url
from app.clients.sec_8k import TEXT_STORE_LIMIT, read_8k, store_text
from app.config import get_settings
from app.db.models import EventFiling, FilingFact
from app.db.session import get_async_engine, get_async_session
from app.filings.categories import Classification, classify_sec
from app.ingest.events import (
    ChainResult,
    EventIngestSummary,
    format_summary,
    persist_events,
    window_bounds,
)

logger = logging.getLogger(__name__)

SEC_FORMS = ["8-K", "8-K/A"]
_DATE_MIN = datetime.date.min
# Item 9.01 (exhibits) appears in most filings, so sharing it says nothing about which event
# an amendment corrects.
_GENERIC_ITEMS = frozenset({"9.01"})


def sec_key(accession: str) -> str:
    return f"sec:{accession}"


def item_set(items: str) -> frozenset[str]:
    return frozenset(i.strip() for i in items.split(",") if i.strip()) - _GENERIC_ITEMS


# -- correction chains (pure) --------------------------------------------------------------------


@dataclass(frozen=True)
class SecChainInput:
    key: str
    cik: str
    filed_at: datetime.date | None
    report_date: datetime.date | None
    items: frozenset[str]  # without the generic 9.01
    is_correction: bool
    in_scope: bool  # has a category; excluded filings are candidates but never linked to


def resolve_sec_chains(entries: list[SecChainInput]) -> dict[str, ChainResult]:
    """Link 8-K/A filings to originals and choose the version of each chain to show.

    Candidates for the original of an 8-K/A are all non-correction filings of the same company
    with the same event date (``reportDate``), filed no later than the amendment, that share an
    item number other than 9.01. Excluded filings and filings stored from before the window
    count as candidates, so a sibling is never picked while the true original is not in scope.
    The amendment is linked only when there is exactly one candidate and it is in scope.
    Otherwise (none, several, an excluded one, no event date) it is ``unlinked`` with a note.
    Amendments the classifier excluded are ``not_resolved_excluded``. Within a chain only the
    newest member by filing date and accession is ``is_latest``; a filing outside any chain is
    latest.
    """
    originals = [e for e in entries if not e.is_correction]
    results: dict[str, ChainResult] = {}
    chains: dict[str, list[SecChainInput]] = {}
    for entry in entries:
        if not entry.is_correction:
            if entry.in_scope:
                chains.setdefault(entry.key, []).append(entry)
            continue
        if not entry.in_scope:
            results[entry.key] = ChainResult(
                "not_resolved_excluded", None, None, "excluded filing; chain not resolved", True
            )
            continue
        link = _link(entry, originals)
        results[entry.key] = link
        if link.original_rcept_no is not None:
            chains.setdefault(link.original_rcept_no, []).append(entry)

    for members in chains.values():
        newest = max(members, key=lambda e: (e.filed_at or _DATE_MIN, e.key))
        for entry in members:
            if entry.is_correction:
                prior = results[entry.key]
                results[entry.key] = ChainResult(
                    prior.correction_link,
                    prior.original_rcept_no,
                    prior.first_filed_at,
                    prior.note,
                    entry is newest,
                )
            else:
                results[entry.key] = ChainResult("none", None, None, None, entry is newest)
    for entry in entries:
        results.setdefault(entry.key, ChainResult("none", None, None, None, True))

    # Orphan chains: unlinked amendments of one company with the same event date that share an
    # item belong together although the original is not available; only the newest is latest.
    unlinked = [
        e
        for e in entries
        if e.is_correction and results[e.key].correction_link == "unlinked" and e.report_date
    ]
    groups: list[list[SecChainInput]] = []
    for entry in sorted(unlinked, key=lambda e: e.key):
        joined = [
            g
            for g in groups
            if any(
                m.cik == entry.cik and m.report_date == entry.report_date and m.items & entry.items
                for m in g
            )
        ]
        merged = [entry] + [m for g in joined for m in g]
        groups = [g for g in groups if g not in joined] + [merged]
    for members in groups:
        newest = max(members, key=lambda e: (e.filed_at or _DATE_MIN, e.key))
        for entry in members:
            prior = results[entry.key]
            results[entry.key] = ChainResult(
                prior.correction_link,
                prior.original_rcept_no,
                prior.first_filed_at,
                prior.note,
                entry is newest,
            )
    return results


def _link(entry: SecChainInput, originals: list[SecChainInput]) -> ChainResult:
    def unlinked(note: str) -> ChainResult:
        return ChainResult("unlinked", None, None, note, True)

    if entry.report_date is None:
        return unlinked("8-K/A has no event date in the submissions data")
    candidates = [
        o
        for o in originals
        if o.cik == entry.cik
        and o.report_date == entry.report_date
        and (o.filed_at or _DATE_MIN) <= (entry.filed_at or _DATE_MIN)
        and o.items & entry.items
    ]
    day = entry.report_date.isoformat()
    if len(candidates) == 1:
        if not candidates[0].in_scope:
            return unlinked(f"the one original 8-K for event date {day} is not in scope")
        return ChainResult("linked", candidates[0].key, candidates[0].filed_at, None, True)
    if not candidates:
        return unlinked(f"no original 8-K for event date {day} with a shared item in the window")
    return unlinked(f"{len(candidates)} original 8-Ks for event date {day} share an item")


# -- one company ---------------------------------------------------------------------------------


@dataclass
class SecEventRecord:
    filing: SecFilingItem
    cik: str
    ticker: str
    company: str
    classification: Classification
    chain: ChainResult | None = None
    # None: stored facts are left alone. Facts come from the submissions data, so they are
    # written for every record whose filing was read this run.
    facts: list[ExtractedFact] | None = None
    errors: list[str] = field(default_factory=list)
    # True when a document this run needed could not be read; stored classification and link
    # then stay as they are instead of being replaced by this run's incomplete answer.
    degraded: bool = False
    body_text: str | None = None
    body_truncated: bool = False

    @property
    def key(self) -> str:
        return sec_key(self.filing.accession_number)

    def to_row(self) -> dict:
        """The ``event_filings`` columns this record sets (a SEC row)."""
        chain = self.chain
        assert chain is not None
        f, cls = self.filing, self.classification
        return {
            "rcept_no": self.key,
            "source": "sec",
            "corp_code": self.cik,
            "stock_code": self.ticker,
            "corp_name": self.company,
            "report_nm": f.form,
            "filed_at": f.filing_date,
            "rm": "",
            "url": filing_index_url(self.cik, f.accession_number),
            "category": cls.category,
            "excluded_reason": cls.excluded_reason,
            "subsidiary": cls.subsidiary,
            "is_correction": cls.is_correction,
            "matched_rule": cls.matched_rule,
            "basis": cls.basis,
            "correction_link": chain.correction_link,
            "original_rcept_no": chain.original_rcept_no,
            "correction_first_filed_at": chain.first_filed_at,
            "correction_note": chain.note,
            "is_latest": chain.is_latest,
            "errors": self.errors,
            "body_text": self.body_text,
            "body_truncated": self.body_truncated,
        }


@dataclass
class SecEventSummary(EventIngestSummary):
    # EX-99.* documents that are PDFs or images, not read.
    skipped_exhibits: list[str] = field(default_factory=list)
    # Filings whose kept text was cut at TEXT_STORE_LIMIT.
    truncated: int = 0
    documents_read: int = 0


# submissions field named in the contract's source_field -> SecFilingItem attribute
_SUBMISSIONS_ATTRIBUTES = {"items": "items", "reportDate": "report_date"}


def sec_facts(filing: SecFilingItem) -> list[ExtractedFact]:
    """Item numbers and event date from the submissions data; nothing comes from the text.

    Keys, kinds and ``source_field`` values come from the ``sec`` block of
    ``contracts/filing-facts.json``. A field the filing does not have gives no fact.
    """
    facts = []
    for spec in load_facts_contract()["sec"]["fields"]:
        value = getattr(filing, _SUBMISSIONS_ATTRIBUTES[spec["source_field"].split(".", 1)[1]])
        if value in (None, ""):
            continue
        if spec["kind"] == "date":
            facts.append(
                ExtractedFact(
                    spec["key"], "date", spec["unit"], spec["source_field"], value.isoformat(),
                    value_date=value,
                )  # fmt: skip
            )
        else:
            facts.append(
                ExtractedFact(
                    spec["key"], spec["kind"], spec["unit"], spec["source_field"], value,
                    value_text=value,
                )  # fmt: skip
            )
    return facts


async def collect_sec_events(
    client: SecClient,
    cik: str,
    ticker: str,
    company: str,
    window: tuple[datetime.date, datetime.date],
    stored: list[SecChainInput] | None = None,
) -> tuple[list[SecEventRecord], SecEventSummary]:
    """``stored`` are earlier-stored non-correction filings of this company (the ones that left
    the window included); they only serve as candidates for an amendment's original."""
    summary = SecEventSummary(cik, window)
    listed, list_problems = await client.list_filings_window(cik, SEC_FORMS, window[0])
    summary.problems.extend(f"list: {p}" for p in list_problems)
    filings: list[SecFilingItem] = []
    for filing in listed:
        if filing.filing_date is None:
            summary.problems.append(f"{filing.accession_number}: no filing date; skipped")
        elif window[0] <= filing.filing_date <= window[1]:
            filings.append(filing)
    filings.sort(key=lambda f: (f.filing_date or _DATE_MIN, f.accession_number))
    summary.listed = len(filings)

    records: list[SecEventRecord] = []
    for filing in filings:
        classification = classify_sec(filing.form, filing.items)
        record = SecEventRecord(filing, cik, ticker, company, classification)
        if classification.excluded_reason == "needs_body" or classification.category:
            documents = await read_8k(client, cik, filing)
            summary.documents_read += len(documents.texts)
            summary.skipped_exhibits.extend(
                f"{filing.accession_number} {s}" for s in documents.skipped
            )
            for failure in documents.failed:
                record.errors.append(failure)
                summary.problems.append(f"document {failure}")
            record.degraded = bool(documents.failed)
            # A category is never decided from partial text: after any failed document a filing
            # that needs its body stays needs_body (excluded), and no partial text is kept.
            if not record.degraded:
                record.classification = classify_sec(filing.form, filing.items, documents.texts)
                record.body_text, record.body_truncated = store_text(documents.texts)
                summary.truncated += record.body_truncated
                if record.classification.excluded_reason == "needs_body":
                    summary.problems.append(
                        f"classification {filing.accession_number}: still needs_body after "
                        "reading it"
                    )
        records.append(record)

    entries = [
        SecChainInput(
            key=r.key,
            cik=cik,
            filed_at=r.filing.filing_date,
            report_date=r.filing.report_date,
            items=item_set(r.filing.items),
            is_correction=r.classification.is_correction,
            in_scope=r.classification.category is not None,
        )
        for r in records
    ]
    listed_keys = {r.key for r in records}
    entries.extend(e for e in stored or [] if e.key not in listed_keys and not e.is_correction)
    chains = resolve_sec_chains(entries)
    for record in records:
        record.chain = chains[record.key]
        # Item numbers and event date come from the listing, so they do not depend on the
        # documents. Excluded filings get them too: a later 8-K/A needs them to find its original.
        record.facts = sec_facts(record.filing)

        category = record.classification.category
        if category is not None:
            summary.by_category[category] += 1
        else:
            summary.excluded[str(record.classification.excluded_reason)] += 1
        link = record.chain.correction_link
        if link == "linked":
            summary.linked += 1
        elif link == "unlinked":
            summary.unlinked += 1
        elif link == "not_resolved_excluded":
            summary.not_resolved_excluded += 1
        summary.facts_written += len(record.facts or [])
    return records, summary


async def load_stored_originals(
    session_factory: Callable[[], AsyncSession], cik: str
) -> list[SecChainInput]:
    """Stored non-correction SEC filings of ``cik`` with their item numbers and event dates."""
    spec_keys = {f["source_field"]: f["key"] for f in load_facts_contract()["sec"]["fields"]}
    items_key = spec_keys["sec:submissions.items"]
    date_key = spec_keys["sec:submissions.reportDate"]
    async with session_factory() as session:
        filings = (
            await session.execute(
                select(
                    EventFiling.id,
                    EventFiling.rcept_no,
                    EventFiling.filed_at,
                    EventFiling.category,
                ).where(
                    EventFiling.source == "sec",
                    EventFiling.corp_code == cik,
                    EventFiling.is_correction.is_(False),
                )
            )
        ).all()
        facts = (
            await session.execute(
                select(
                    FilingFact.event_filing_id,
                    FilingFact.key,
                    FilingFact.value_text,
                    FilingFact.value_date,
                ).where(
                    FilingFact.event_filing_id.in_([f.id for f in filings]),
                    FilingFact.key.in_([items_key, date_key]),
                )
            )
        ).all()
    by_filing: dict = {}
    for filing_id, key, value_text, value_date in facts:
        by_filing.setdefault(filing_id, {})[key] = value_text if key == items_key else value_date
    return [
        SecChainInput(
            key=f.rcept_no,
            cik=cik,
            filed_at=f.filed_at,
            report_date=by_filing.get(f.id, {}).get(date_key),
            items=item_set(by_filing.get(f.id, {}).get(items_key) or ""),
            is_correction=False,
            in_scope=f.category is not None,
        )
        for f in filings
    ]


async def run_sec_events(
    client: SecClient,
    ticker: str,
    session_factory: Callable[[], AsyncSession],
    *,
    today: datetime.date | None = None,
) -> SecEventSummary:
    matches = await client.search_company(ticker)
    match = next((m for m in matches if m.ticker.upper() == ticker.upper()), None)
    if match is None:
        raise SystemExit(f"ticker {ticker!r} not found in SEC company_tickers")
    window = window_bounds(today or datetime.date.today())
    stored = await load_stored_originals(session_factory, match.cik)
    records, summary = await collect_sec_events(
        client, match.cik, match.ticker, match.title, window, stored
    )
    summary.problems.extend(await persist_events(session_factory, records))
    return summary


def format_sec_summary(summary: SecEventSummary) -> str:
    lines = format_summary(summary).splitlines()
    extra = [
        f"documents read={summary.documents_read}",
        f"text cut at {TEXT_STORE_LIMIT} characters: {summary.truncated} filing(s)",
        f"skipped exhibits (not text): {len(summary.skipped_exhibits)}",
    ]
    extra.extend(f"  skipped {s}" for s in summary.skipped_exhibits)
    # Insert before the PROBLEM lines so they stay last.
    split = next((i for i, line in enumerate(lines) if line.startswith("PROBLEM ")), len(lines))
    return "\n".join(lines[:split] + extra + lines[split:])


async def run_sec_cli(ticker: str) -> SecEventSummary:
    http = rate_limited_client(RequestLimiter())
    client = SecClient(get_settings(), http)
    try:
        return await run_sec_events(client, ticker, get_async_session)
    finally:
        await http.aclose()
        await get_async_engine().dispose()
