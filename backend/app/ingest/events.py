"""Event-filing ingest: list a company's DART event filings, classify them, extract facts.

    python -m app.ingest events --source dart --ticker 005930

For one company and the last 12 months it

1. lists the 주요사항보고 (B) and 거래소공시 (I) filings, every page;
2. classifies each with ``classify_dart`` (fetching the body when the contract needs it) and
   fetches the body of every filing in an event category too, keeping its plain text in
   ``body_text``, cut at ``TEXT_STORE_LIMIT`` (the summaries step reads it). Every run
   classifies every listed filing again, so a filing a newer contract brings into scope gets
   its body on the next run. Notices (D76) need no body;
3. links each ``[기재정정]`` filing in an event category to its original and marks the newest
   version of a chain as the one to show (older versions are kept);
4. fetches the structured endpoints named in ``contracts/filing-facts.json`` and extracts facts;
5. upserts ``event_filings`` and ``filing_facts`` in one transaction.

Excluded filings are stored with their ``excluded_reason``; none is dropped. Linking and chain
logic are pure functions (``resolve_chains``) so they are tested without network or database.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from xml.etree.ElementTree import ParseError

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.dart import DartApiError, DartClient, FilingItem
from app.clients.dart_events import (
    CorrectionTarget,
    EventDocument,
    ExtractedFact,
    endpoint_for_report_key,
    fetch_structured_events,
    parse_correction_target,
    read_event_document,
)
from app.clients.sec_8k import TEXT_STORE_LIMIT
from app.config import get_settings
from app.db.models import EventFiling, FilingFact
from app.db.session import get_async_engine, get_async_session
from app.filings.categories import (
    Classification,
    classify_dart,
    is_event_category,
    normalise_dart_name,
)
from app.ingest.pinned import (
    SAVE_PINNED_HELP,
    PinnedStore,
    dart_structured_path,
    format_pinned,
    open_pinned_store,
)
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

# B = 주요사항보고, I = 거래소공시. Sent as pblntf_ty (the detail code is ignored with it).
EVENT_TYPES = ("B", "I")
_DATE_MIN = datetime.date.min


def window_bounds(today: datetime.date) -> tuple[datetime.date, datetime.date]:
    """The 12-month window ending ``today``, both ends inclusive."""
    try:
        same_day_last_year = today.replace(year=today.year - 1)
    except ValueError:  # 29 February
        same_day_last_year = today.replace(year=today.year - 1, day=28)
    return same_day_last_year + datetime.timedelta(days=1), today


# -- correction chains (pure) --------------------------------------------------------------------


@dataclass(frozen=True)
class ChainInput:
    rcept_no: str
    corp_code: str
    base_key: str  # report name without bracket prefix, wrapper or subsidiary marker
    filed_at: datetime.date | None
    rm: str
    is_correction: bool
    in_scope: bool  # has an event category; excluded filings and notices are not chained
    target: CorrectionTarget | None = None
    target_error: str | None = None  # why the body could not be read
    subsidiary: bool = False  # a subsidiary's filing never chains to the parent's


@dataclass(frozen=True)
class ChainResult:
    # 'none' | 'linked' | 'unlinked' | 'not_resolved_excluded'
    correction_link: str
    original_rcept_no: str | None
    first_filed_at: datetime.date | None
    note: str | None
    is_latest: bool


def _superseded_by_rm(rm: str) -> bool:
    # DART's rm column carries 정 on a filing that a later correction replaced.
    return "정" in rm


def resolve_chains(entries: list[ChainInput]) -> dict[str, ChainResult]:
    """Link corrections to originals and choose the version of each chain to show.

    A correction body names the report it corrects and that report's first filing date but not
    the original's 접수번호. The original is the single in-scope, non-correction filing of the
    same company, subsidiary flag and base report name filed on that date. Zero or several
    matches, a name mismatch, an impossible date or an unreadable body leave the correction
    ``unlinked`` with a note; it is never guessed. Corrections the classifier excluded are
    ``not_resolved_excluded``.

    Within a chain (original plus its linked corrections) only the newest member by filing date
    and 접수번호 can be ``is_latest``, and not if its ``rm`` carries 정: DART marks a filing a
    later correction replaced that way, so the newer correction is then an unlinked one that
    holds the flag itself. A filing outside any chain is latest unless its ``rm`` carries 정.
    Unlinked corrections that name the same target form an orphan chain with the same rule.
    """
    originals: dict[tuple[str, str, bool], list[ChainInput]] = {}
    for entry in entries:
        if entry.in_scope and not entry.is_correction:
            key = (entry.corp_code, entry.base_key, entry.subsidiary)
            originals.setdefault(key, []).append(entry)

    results: dict[str, ChainResult] = {}
    chains: dict[str, list[ChainInput]] = {}
    for entry in entries:
        if not entry.is_correction:
            if entry.in_scope:
                chains.setdefault(entry.rcept_no, []).append(entry)
            continue
        if not entry.in_scope:
            results[entry.rcept_no] = ChainResult(
                "not_resolved_excluded",
                None,
                None,
                "excluded filing; chain not resolved",
                not _superseded_by_rm(entry.rm),
            )
            continue
        link = _link(entry, originals)
        results[entry.rcept_no] = link
        if link.original_rcept_no is not None:
            chains.setdefault(link.original_rcept_no, []).append(entry)

    for members in chains.values():
        newest = max(members, key=lambda e: (e.filed_at or _DATE_MIN, e.rcept_no))
        shown = newest if not _superseded_by_rm(newest.rm) else None
        for entry in members:
            if entry.is_correction:
                prior = results[entry.rcept_no]
                results[entry.rcept_no] = ChainResult(
                    prior.correction_link,
                    prior.original_rcept_no,
                    prior.first_filed_at,
                    prior.note,
                    entry is shown,
                )
            else:
                results[entry.rcept_no] = ChainResult("none", None, None, None, entry is shown)

    for entry in entries:
        if entry.rcept_no not in results:
            results[entry.rcept_no] = ChainResult(
                "none", None, None, None, not _superseded_by_rm(entry.rm)
            )

    # Orphan chains: unlinked corrections that name the same target (company, base report name,
    # subsidiary flag and stated first-filing date) belong together although the original is not
    # available. Only the newest can be latest, and not if its rm carries 정.
    orphans: dict[tuple[str, str, bool, datetime.date], list[ChainInput]] = {}
    for entry in entries:
        found = results[entry.rcept_no]
        if found.correction_link == "unlinked" and found.first_filed_at is not None:
            key = (entry.corp_code, entry.base_key, entry.subsidiary, found.first_filed_at)
            orphans.setdefault(key, []).append(entry)
    for members in orphans.values():
        newest = max(members, key=lambda e: (e.filed_at or _DATE_MIN, e.rcept_no))
        shown = newest if not _superseded_by_rm(newest.rm) else None
        for entry in members:
            prior = results[entry.rcept_no]
            results[entry.rcept_no] = ChainResult(
                prior.correction_link,
                prior.original_rcept_no,
                prior.first_filed_at,
                prior.note,
                entry is shown,
            )
    return results


def _link(
    entry: ChainInput, originals: dict[tuple[str, str, bool], list[ChainInput]]
) -> ChainResult:
    def unlinked(note: str, first: datetime.date | None = None) -> ChainResult:
        return ChainResult("unlinked", None, first, note, not _superseded_by_rm(entry.rm))

    if entry.target is None:
        return unlinked(entry.target_error or "correction body has no first-filing date")
    first = entry.target.first_filed
    if first is None:
        return unlinked(entry.target.error or "correction body has no first-filing date")
    if entry.target.name:
        target_key = normalise_dart_name(entry.target.name)[0]
        if target_key != entry.base_key:
            return unlinked(f"correction target {entry.target.name!r} differs from report", first)
    candidates = [
        o
        for o in originals.get((entry.corp_code, entry.base_key, entry.subsidiary), [])
        if o.filed_at == first
    ]
    if len(candidates) == 1:
        return ChainResult("linked", candidates[0].rcept_no, first, None, True)
    if not candidates:
        return unlinked(f"no original filed on {first.isoformat()} in the window", first)
    return unlinked(f"{len(candidates)} originals filed on {first.isoformat()}", first)


# -- one company ---------------------------------------------------------------------------------


@dataclass
class EventRecord:
    item: FilingItem
    classification: Classification
    base_key: str
    chain: ChainResult | None = None
    # None: no structured call succeeded for this filing, so stored facts are left alone.
    facts: list[ExtractedFact] | None = None
    errors: list[str] = field(default_factory=list)
    # True when a body this run needed could not be read; stored classification and link then
    # stay as they are instead of being replaced by this run's incomplete answer.
    degraded: bool = False
    # Plain text of the filing, set only when this run read it. None leaves a stored text alone.
    body_text: str | None = None
    body_truncated: bool = False

    @property
    def key(self) -> str:
        return self.item.rcept_no

    def to_row(self) -> dict:
        """The ``event_filings`` columns this record sets (a DART row)."""
        chain = self.chain
        assert chain is not None
        item, cls = self.item, self.classification
        row = {
            "rcept_no": item.rcept_no,
            "corp_code": item.corp_code,
            "stock_code": item.stock_code or None,
            "corp_name": item.corp_name,
            "report_nm": item.report_nm,
            "filed_at": item.rcept_dt,
            "rm": item.rm,
            "url": item.viewer_url,
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
        }
        if self.body_text is not None:
            row["body_text"] = self.body_text
            row["body_truncated"] = self.body_truncated
        return row


def store_body_text(text: str, limit: int = TEXT_STORE_LIMIT) -> tuple[str, bool]:
    """The text kept for storage and whether it was cut at ``limit`` characters."""
    return (text, False) if len(text) <= limit else (text[:limit], True)


@dataclass
class EventIngestSummary:
    corp_code: str
    window: tuple[datetime.date, datetime.date]
    listed: int = 0
    by_category: Counter[str] = field(default_factory=Counter)  # event categories
    notices: Counter[str] = field(default_factory=Counter)  # notice categories
    excluded: Counter[str] = field(default_factory=Counter)
    linked: int = 0
    unlinked: int = 0
    not_resolved_excluded: int = 0
    facts_written: int = 0
    fact_errors: int = 0
    unmatched_facts: list[str] = field(default_factory=list)
    # Partial list pages, failed endpoints, filings whose body could not be read.
    problems: list[str] = field(default_factory=list)
    # DART only (None: not counted). Document requests made, bodies stored, bodies cut at
    # TEXT_STORE_LIMIT.
    documents_fetched: int | None = None
    bodies_stored: int = 0
    bodies_truncated: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


_DOCUMENT_ERRORS = (DartApiError, httpx.HTTPError, zipfile.BadZipFile, ParseError, ValueError)


async def collect_dart_events(
    client: DartClient,
    corp_code: str,
    window: tuple[datetime.date, datetime.date],
    *,
    request_interval: float = 0.0,
    pinned: PinnedStore | None = None,
    stock_code: str | None = None,
) -> tuple[list[EventRecord], EventIngestSummary]:
    """``pinned`` saves each structured response under ``stock_code`` (the 6-digit code)."""
    bgn, end = (d.strftime("%Y%m%d") for d in window)
    summary = EventIngestSummary(corp_code, window, documents_fetched=0)

    items: dict[str, FilingItem] = {}
    for pblntf_ty in EVENT_TYPES:
        listing = await client.list_all_filings(corp_code, bgn, end, pblntf_ty=pblntf_ty)
        summary.problems.extend(f"list {pblntf_ty}: {e}" for e in listing.page_errors)
        for item in listing.items:
            items[item.rcept_no] = item
        await _pause(request_interval)
    summary.listed = len(items)

    documents: dict[str, EventDocument | str] = {}

    async def document(rcept_no: str) -> EventDocument | str:
        """The parsed body, or an error string. Fetched at most once per filing."""
        if rcept_no not in documents:
            await _pause(request_interval)
            summary.documents_fetched = (summary.documents_fetched or 0) + 1
            try:
                payload = await client.fetch_document(rcept_no)
                documents[rcept_no] = read_event_document(payload.content)
            except _DOCUMENT_ERRORS as exc:
                message = f"document fetch failed: {exc}"
                documents[rcept_no] = message
                summary.problems.append(f"document {rcept_no}: {message}")
        return documents[rcept_no]

    records: list[EventRecord] = []
    for item in sorted(items.values(), key=lambda i: (i.rcept_dt or _DATE_MIN, i.rcept_no)):
        base_key = normalise_dart_name(item.report_nm)[0]
        classification = classify_dart(item.report_nm)
        record = EventRecord(item, classification, base_key)
        if classification.excluded_reason == "needs_body":
            body = await document(item.rcept_no)
            if isinstance(body, str):
                record.errors.append(body)
                record.degraded = True
            else:
                record.classification = classify_dart(item.report_nm, body.text)
                if record.classification.excluded_reason == "needs_body":
                    summary.problems.append(
                        f"classification {item.rcept_no}: still needs_body after reading it"
                    )
        records.append(record)

    # Every filing in an event category keeps its text for the summaries step; excluded ones
    # and notices need none. A failed read leaves body_text unset, so a stored text is kept.
    for record in records:
        if not is_event_category(record.classification.category):
            continue
        body = await document(record.item.rcept_no)
        if isinstance(body, str):
            if body not in record.errors:
                record.errors.append(body)
            continue
        if not body.text:  # nothing was extracted: leave the stored text alone
            continue
        record.body_text, record.body_truncated = store_body_text(body.text, TEXT_STORE_LIMIT)
        summary.bodies_stored += 1
        summary.bodies_truncated += record.body_truncated

    entries: list[ChainInput] = []
    for record in records:
        in_scope = is_event_category(record.classification.category)
        target = None
        target_error = None
        if in_scope and record.classification.is_correction:
            body = await document(record.item.rcept_no)
            if isinstance(body, str):
                target_error = body
                if body not in record.errors:
                    record.errors.append(body)
                record.degraded = True
            else:
                target = parse_correction_target(body.text)
        entries.append(
            ChainInput(
                rcept_no=record.item.rcept_no,
                corp_code=record.item.corp_code,
                base_key=record.base_key,
                filed_at=record.item.rcept_dt,
                rm=record.item.rm,
                is_correction=record.classification.is_correction,
                in_scope=in_scope,
                target=target,
                target_error=target_error,
                subsidiary=record.classification.subsidiary,
            )
        )
    chains = resolve_chains(entries)
    for record in records:
        record.chain = chains[record.item.rcept_no]

    by_rcept = {r.item.rcept_no: r for r in records}
    endpoints = sorted(
        {
            endpoint
            for r in records
            if is_event_category(r.classification.category)
            and (endpoint := endpoint_for_report_key(r.base_key)) is not None
        }
    )
    for endpoint in endpoints:
        await _pause(request_interval)
        save: dict = {}
        if pinned is not None and stock_code:
            save["on_body"] = _structured_sink(
                pinned, dart_structured_path(endpoint, stock_code), summary.problems
            )
        try:
            result = await fetch_structured_events(client, endpoint, corp_code, bgn, end, **save)
        except (DartApiError, httpx.HTTPError, ValueError) as exc:
            # Facts already stored for this endpoint's filings stay untouched.
            summary.problems.append(f"{endpoint}: {exc}")
            continue
        summary.problems.extend(result.errors)
        for record in records:
            if (
                is_event_category(record.classification.category)
                and endpoint_for_report_key(record.base_key) == endpoint
            ):
                record.facts = []  # the call succeeded: what it did not return is not stored
        for event in result.events:
            record = by_rcept.get(event.rcept_no)
            if record is None:
                summary.unmatched_facts.append(f"{endpoint}: {event.rcept_no}")
                continue
            record.facts = event.facts
            for fact in event.facts:
                if fact.error:
                    record.errors.append(f"{fact.key}: {fact.error}")

    for record in records:
        category = record.classification.category
        if is_event_category(category):
            summary.by_category[str(category)] += 1
        elif category is not None:
            summary.notices[category] += 1
        else:
            summary.excluded[str(record.classification.excluded_reason)] += 1
        link = record.chain.correction_link if record.chain else "none"
        if link == "linked":
            summary.linked += 1
        elif link == "unlinked":
            summary.unlinked += 1
        elif link == "not_resolved_excluded":
            summary.not_resolved_excluded += 1
        summary.facts_written += len(record.facts or [])
        summary.fact_errors += sum(1 for f in record.facts or [] if f.error)
    return records, summary


def _structured_sink(
    pinned: PinnedStore, relative: str, problems: list[str]
) -> Callable[[bytes], None]:
    """Stage a structured response. A "no data" answer (status 013) never replaces a file."""

    def on_body(body: bytes) -> None:
        try:
            no_data = str(json.loads(body).get("status", "")).strip() == "013"
        except (ValueError, AttributeError):
            no_data = False
        pinned.sink(relative, problems, only_if_absent=no_data)(body)

    return on_body


async def _pause(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


# -- persistence ---------------------------------------------------------------------------------

# Columns a frozen row may still refresh; classification and chain columns are kept.
_DESCRIPTIVE_COLUMNS = (
    "corp_code", "stock_code", "corp_name", "report_nm", "filed_at", "rm", "url", "errors",
)  # fmt: skip
# Columns that say where a filing sits in a correction chain.
_CHAIN_COLUMNS = frozenset(
    {
        "correction_link",
        "original_rcept_no",
        "correction_first_filed_at",
        "correction_note",
        "is_latest",
    }
)


async def persist_events(
    session_factory: Callable[[], AsyncSession], records: list[EventRecord]
) -> list[str]:
    """Upsert filings by 접수번호 and replace facts, in one transaction; returns problem lines.

    ``records`` are ``EventRecord`` or ``SecEventRecord``: anything with ``key``, ``to_row()``,
    ``chain``, ``degraded`` and ``facts``.

    Chains are never half-recomputed. If any stored member of a chain could not be read this run
    (``degraded``), every stored member of that chain keeps its classification, link and
    ``is_latest``; a new correction that would join that chain is stored unlinked and not
    latest, with a note and a problem line, until a healthy run resolves it. A stored correction
    whose original is no longer in this run's listing (it left the window) keeps its stored
    link instead of being rewritten as unlinked. Facts are replaced for every record whose
    ``facts`` is not ``None``.
    """
    problems: list[str] = []
    if not records:
        return problems
    rows: dict[str, dict] = {record.key: record.to_row() for record in records}

    async with session_factory() as session, session.begin():
        found = await session.execute(
            select(
                EventFiling.rcept_no, EventFiling.correction_link, EventFiling.original_rcept_no
            ).where(EventFiling.rcept_no.in_(list(rows)))
        )
        stored = {key: (link, original) for key, link, original in found.all()}

        def stored_original(key: str) -> str | None:
            link, original = stored.get(key, ("none", None))
            return original if link == "linked" else None

        frozen_roots: set[str] = set()
        for r in records:
            if r.degraded and r.key in stored:
                frozen_roots.add(r.key)
                if original := stored_original(r.key):
                    frozen_roots.add(original)

        def roots(r) -> set[str]:
            members = {r.key}
            if original := stored_original(r.key):
                members.add(original)
            if r.chain and r.chain.original_rcept_no:
                members.add(r.chain.original_rcept_no)
            return members

        frozen = {
            r.key for r in records if r.key in stored and (r.degraded or roots(r) & frozen_roots)
        }
        keep_link: set[str] = set()
        for r in records:
            original = stored_original(r.key)
            if (
                r.key in stored
                and r.key not in frozen
                and original is not None
                and original not in rows
                and r.chain is not None
                and r.chain.correction_link == "unlinked"
            ):
                keep_link.add(r.key)
        for r in records:
            if (
                r.key not in stored
                and r.chain is not None
                and r.chain.original_rcept_no in frozen_roots
            ):
                root = r.chain.original_rcept_no
                rows[r.key].update(
                    correction_link="unlinked",
                    original_rcept_no=None,
                    correction_first_filed_at=None,
                    correction_note=(
                        f"chain of {root} has a member that could not be read this run; "
                        "not resolved"
                    ),
                    is_latest=False,
                )
                problems.append(
                    f"chain {r.key}: joins {root}, which has a member that could not be read; "
                    "stored unlinked and not latest until a healthy run"
                )

        ids: dict[str, int] = {}
        for group, mode in (
            ([v for k, v in rows.items() if k not in frozen and k not in keep_link], "full"),
            ([v for k, v in rows.items() if k in frozen], "frozen"),
            ([v for k, v in rows.items() if k in keep_link], "keep_link"),
        ):
            # One statement per set of columns: a record that read no body text leaves
            # body_text out of its row, so the stored text is kept.
            batches: dict[tuple[str, ...], list[dict]] = {}
            for row in group:
                batches.setdefault(tuple(row), []).append(row)
            for columns, rows_ in batches.items():
                if mode == "frozen":
                    columns = _DESCRIPTIVE_COLUMNS
                elif mode == "keep_link":
                    columns = tuple(c for c in columns if c not in _CHAIN_COLUMNS)
                stmt = pg_insert(EventFiling)
                update_columns = {c: stmt.excluded[c] for c in columns if c != "rcept_no"}
                update_columns["updated_at"] = func.now()
                result = await session.execute(
                    stmt.values(rows_)
                    .on_conflict_do_update(index_elements=["rcept_no"], set_=update_columns)
                    .returning(EventFiling.rcept_no, EventFiling.id)
                )
                ids.update(dict(result.all()))

        refreshed = [r for r in records if r.facts is not None]
        if not refreshed:
            return problems
        await session.execute(
            delete(FilingFact).where(
                FilingFact.event_filing_id.in_([ids[r.key] for r in refreshed])
            )
        )
        fact_rows = [
            {
                "event_filing_id": ids[record.key],
                "key": fact.key,
                "kind": fact.kind,
                "unit": fact.unit,
                "source_field": fact.source_field,
                "raw": fact.raw,
                "value_decimal": fact.value_decimal,
                "value_date": fact.value_date,
                "value_text": fact.value_text,
                "error": fact.error,
            }
            for record in refreshed
            for fact in record.facts or []
        ]
        if fact_rows:
            await session.execute(pg_insert(FilingFact).values(fact_rows))
    return problems


async def run_dart_events(
    client: DartClient,
    ticker: str,
    session_factory: Callable[[], AsyncSession],
    *,
    today: datetime.date | None = None,
    request_interval: float = 0.0,
    pinned: PinnedStore | None = None,
) -> EventIngestSummary:
    corp_code = await client.resolve_corp_code(ticker)
    if corp_code is None:
        raise SystemExit(f"ticker {ticker!r} not found in DART corpCode map")
    window = window_bounds(today or datetime.date.today())
    records, summary = await collect_dart_events(
        client, corp_code, window, request_interval=request_interval, pinned=pinned,
        stock_code=ticker,
    )
    summary.problems.extend(await persist_events(session_factory, records))
    if pinned is not None:  # the rows are committed; only now may the pinned files change
        summary.problems.extend(pinned.commit())
    return summary


def _counts(counter: Counter[str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counter.items())) or "none"


def format_summary(summary: EventIngestSummary) -> str:
    lines = [
        f"corp_code={summary.corp_code} window={summary.window[0]}..{summary.window[1]} "
        f"listed={summary.listed}",
        "in scope: " + _counts(summary.by_category),
        "notices: " + _counts(summary.notices),
        "excluded: " + _counts(summary.excluded),
        f"corrections: linked={summary.linked} unlinked={summary.unlinked} "
        f"not_resolved_excluded={summary.not_resolved_excluded}",
        f"facts: written={summary.facts_written} with_errors={summary.fact_errors}",
    ]
    if summary.documents_fetched is not None:
        lines.append(
            f"documents fetched={summary.documents_fetched} "
            f"bodies stored={summary.bodies_stored} "
            f"cut at {TEXT_STORE_LIMIT} characters={summary.bodies_truncated}"
        )
    if summary.unmatched_facts:
        lines.append(f"facts without a listed filing: {len(summary.unmatched_facts)}")
    lines.extend(f"PROBLEM {p}" for p in summary.problems)
    return "\n".join(lines)


async def _run(ticker: str, pinned: PinnedStore | None = None) -> EventIngestSummary:
    client = DartClient(get_settings())
    try:
        return await run_dart_events(
            client, ticker, get_async_session, request_interval=0.35, pinned=pinned
        )
    finally:
        await client.aclose()
        await get_async_engine().dispose()


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingest events",
        description="Ingest a company's DART event filings for the last 12 months.",
    )
    parser.add_argument("--source", choices=["dart", "sec"], required=True)
    parser.add_argument(
        "--ticker",
        required=True,
        help="DART: 6-digit stock code, e.g. 005930; SEC: symbol, e.g. AAPL",
    )
    parser.add_argument("--save-pinned", metavar="DIR", **SAVE_PINNED_HELP)
    args = parser.parse_args(argv)
    configure_logging()
    pinned = open_pinned_store(args.save_pinned)
    if args.source == "sec":
        from app.ingest.sec_events import format_sec_summary, run_sec_cli  # imports this module

        summary = asyncio.run(run_sec_cli(args.ticker, pinned))
        print(format_sec_summary(summary))
    else:
        summary = asyncio.run(_run(args.ticker, pinned))
        print(format_summary(summary))
    if pinned is not None:
        print(format_pinned(pinned))
    if not summary.ok:
        raise SystemExit(1)
