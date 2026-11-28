"""Export the build database to the bundled SQLite file (build plan section 4, ADR 0006).

    python -m app.build.export --as-of 2026-11-17 --out dist/footnote.sqlite \\
        --pinned data/pinned [--allow-unapproved | --preview]

The build either writes a file whose every figure and fact matched a pinned regulator
response, or exits 1 and leaves no bundle and no report at the output paths. Both files are
written in a fresh temporary directory and moved into place only after both are complete.
A failed build removes outputs an earlier build left at the same paths rather than keep them,
so a file at ``--out`` is always the result of the latest successful run. Next to the file it
writes ``<name>.report.json`` (``footnote.sqlite`` -> ``footnote.report.json``): row counts,
per-figure checks, excluded filings, file SHA-256 and size.

Release is the default: it refuses when a filing that needs summaries lacks approved ones
in both languages and every section (:data:`app.build.model.ANNUAL_SCOPE`), when a summary
line fails the neutrality guard, and when ``--prompt-version`` is ``none``.
``--allow-unapproved`` is for development builds only and is recorded in
``build_meta.allow_unapproved``; ``python -m app.build.verify --release`` refuses such a file.
Summaries not yet approved are never written, because ``review_state`` must be ``approved``.
Glossary entries (``contracts/glossary.json``, D81) follow the same split: a release build
refuses while any entry is unapproved and every build runs the neutrality guard on them; a
development build writes the unapproved entries too, since ``allow_unapproved`` marks the file.

``--preview`` (D90) is for internal TestFlight builds made before every summary is approved. It
relaxes only two release refusals: a filing without approved summaries and a stale approved row
are left out and listed in the report. Everything else stays on: the neutrality guard,
``prompt_version`` ``none``, ``restatement_unchecked`` and the figure checks. Unapproved glossary
entries are omitted, never written, and do not refuse the build. A preview records
``allow_unapproved = 0`` and ``preview = 1`` in ``build_meta``; ``python -m app.build.verify
--release`` refuses it. Only approved summaries are ever written, in every mode.

Source sentences (D101): every exported summary line gets its rows in ``summary_sources``,
copied from the faithfulness report (``--faithfulness``, default
``data/summaries/faithfulness.jsonl``, D97) when its record is from the current aligner for
exactly that line and approval. A supported or partly line ships its span sentences, a template
line one row without an excerpt, and a line the owner accepted
(``data/summaries/faithfulness_accepted.jsonl``) no row. A release refuses a line without a
current record and an unsupported or unsourced line the owner has not accepted. A development
build or a preview leaves such a section out in both languages and lists it in the report, and
ships a line without a record without a source sentence.

Event filings: the version of each correction chain shown is the newest one filed on or
before ``--as-of``; ingest's ``is_latest`` is not used. At most ten events per company are
exported, the newest, and an event without a stored body text is left out
(:func:`event_scope`). Notice filings (D76) go to the ``notices`` table: same window and
correction rule, no body needed, no cap, never summarised. Annual filings follow
:data:`app.build.model.ANNUAL_SCOPE`. The event filings the owner excluded
(``data/summaries/excluded_filings.jsonl``, ``--excluded``, D109) are left out in every mode,
after the cap, and listed with their reason and date in the report and the output. An entry
that names no event filing in the build input refuses the build.

Figures cover two fiscal years per company: the year of its latest annual filing and the
year before (D79). The newest filing that states a figure is its source; a figure whose
value an earlier filing stated differently under the same regulator tag is restated, and
both values are read from their pinned responses. The report lists restated figures,
``tag_changed``, ``restatement_unchecked`` (a release build refuses these), ``mixed_basis``
figures left out so one year has one basis, and each company and metric without both years
(``figure_gaps``).

Output depends only on the database contents and the arguments: ``--as-of`` replaces the
clock, ``--source-revision`` (default ``git rev-parse HEAD``) names the pipeline, rows are
inserted in primary-key order and every collection is sorted before use.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import functools
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.build import faithfulness
from app.build.bundle import (
    BUILD_META_COLUMNS,
    INSERT_ORDER,
    SCHEMA,
    SCHEMA_VERSION,
    TABLES,
    content_sha256,
)
from app.build.glossary import glossary_problems, glossary_rows, load_glossary, release_problems
from app.build.model import (
    DECIMAL_VALUE_KINDS,
    EVENT_PROMPT_VERSION,
    FACT_VALUE_KINDS,
    LANGS,
    PROMPT_VERSION,
    SUMMARY_SECTIONS,
    AnnualFilingRow,
    BuildError,
    BuildInput,
    CompanyRow,
    EventRow,
    FinancialRow,
    annual_sections,
    annual_source_text,
    canonical_decimal,
    event_source_text,
    latest_annual_ids,
    require_canonical,
    required_summaries,
    summary_input_sha256,
)
from app.build.templates import event_summary_key
from app.build.verify import (
    BASIS,
    DEFAULT_PINNED_DIR,
    NO_PROMPT_VERSION,
    FigureRef,
    PinnedResponses,
    QuarterRef,
    VerifyError,
    check_fact,
    check_figure,
    check_quarter_figure,
    cited_source,
    dart_fiscal_period,
    dart_quarter_period,
    link_problems,
    summary_problems,
)
from app.clients.dart_events import load_facts_contract
from app.filings.categories import load_contract as load_categories_contract
from app.financials.vocabulary import ReportedMetric
from app.ingest.events import _superseded_by_rm, window_bounds
from app.llm.neutrality_guard import Source, load_lexicon

BACKEND_DIR = Path(__file__).resolve().parents[2]
FAMILY_GLOSSARY_PATH = BACKEND_DIR.parent / "contracts" / "family-glossary.json"

# (regulator, stored filing_type) -> section-4 form for an annual report.
ANNUAL_FORMS: dict[tuple[str, str], str] = {
    ("DART", "business_report"): "사업보고서",
    ("SEC", "10-K"): "10-K",
}
ANNUAL_CATEGORY = "annual"
# (regulator, stored filing_type) -> form for a quarterly or half-year report (I11).
QUARTERLY_FORMS: dict[tuple[str, str], str] = {
    ("DART", "quarterly_report"): "분기보고서",
    ("DART", "half_year_report"): "반기보고서",
    ("SEC", "10-Q"): "10-Q",
}
QUARTERLY_CATEGORY = "quarterly"
# The quarter report's figures (I11, board 15): revenue, operating income, and net income
# attributable to owners where reported, else net income. The app picks between the last two.
QUARTER_METRICS = ("revenue", "operating_income", "net_income_attributable", "net_income")
# A filing's period label -> fiscal quarter: DART 'YYYY-Q1' / 'YYYY-H1' / 'YYYY-Q3', SEC
# 'YYYY-Q1' to 'YYYY-Q3'.
_QUARTER_PERIOD_RE = re.compile(r"([0-9]{4})-(Q1|H1|Q2|Q3)")
_QUARTER_OF = {"Q1": 1, "H1": 2, "Q2": 2, "Q3": 3}
CURRENCY = {"DART": "KRW", "SEC": "USD"}
REGULATOR_ORDER = {"DART": 0, "SEC": 1}
DEFAULT_LLM_MODEL = "qwen/qwen3.8-27b"  # D68
DEFAULT_PROMPT_VERSION = PROMPT_VERSION
DEFAULT_EVENT_PROMPT_VERSION = EVENT_PROMPT_VERSION

_ANNUAL_PERIOD_RE = re.compile(r"([0-9]{4})-annual")
_REPORTED_METRICS = frozenset(m.value for m in ReportedMetric)


@dataclass(frozen=True)
class BuildOptions:
    as_of: datetime.date
    source_revision: str
    allow_unapproved: bool = False
    # A preview leaves out filings without approved summaries instead of refusing (D90).
    preview: bool = False
    llm_model: str = DEFAULT_LLM_MODEL
    prompt_version: str = DEFAULT_PROMPT_VERSION
    # Keys event summaries; prompt_version keys annual ones (D78).
    event_prompt_version: str = DEFAULT_EVENT_PROMPT_VERSION


@dataclass
class Bundle:
    rows: dict[str, list[tuple]]
    meta: dict[str, Any]
    report: dict[str, Any]


@dataclass
class _Candidate:
    row: FinancialRow
    company_id: str
    filing_id: str
    filed_on: datetime.date
    period_start: datetime.date
    period_end: datetime.date


@dataclass(frozen=True)
class _Annual:
    filing: AnnualFilingRow
    company_id: str
    year: int
    is_corrected: bool


@dataclass
class _Build:
    data: BuildInput
    options: BuildOptions
    pinned: PinnedResponses
    problems: list[str] = field(default_factory=list)
    annual: dict[str, _Annual] = field(default_factory=dict)  # kept versions, by filing id
    filings: dict[str, tuple] = field(default_factory=dict)
    filing_kinds: dict[str, str] = field(default_factory=dict)
    filing_company: dict[str, str] = field(default_factory=dict)
    events: dict[str, EventRow] = field(default_factory=dict)  # exported, by filing id
    notices: dict[str, tuple] = field(default_factory=dict)  # notices rows, by filing id
    notice_company: dict[str, str] = field(default_factory=dict)
    facts: list[tuple] = field(default_factory=list)
    figures: list[tuple] = field(default_factory=list)
    quarter_figures: list[tuple] = field(default_factory=list)
    sources: list[tuple] = field(default_factory=list)  # summary_sources rows
    faithfulness: faithfulness.RecordIndex = field(default_factory=faithfulness.RecordIndex)
    report: dict[str, Any] = field(default_factory=dict)


def _filing_id(regulator: str, key: str) -> str:
    return f"{regulator.lower()}:{key}"


def _company_id(regulator: str, key: str) -> str:
    return f"{regulator.lower()}:{key}"


def build_bundle(
    data: BuildInput,
    options: BuildOptions,
    pinned_dirs: Sequence[Path],
    sources: faithfulness.RecordIndex | None = None,
) -> Bundle:
    """Select, convert and verify every row; raise :class:`BuildError` on any problem.
    ``sources`` holds the faithfulness records the summary lines' source sentences come from;
    none means no line has one, which only a development build or a preview accepts."""
    build = _Build(data, options, PinnedResponses(pinned_dirs))
    if sources is not None:
        build.faithfulness = sources
    companies = {(c.regulator, c.key): c for c in data.companies}
    _annual_versions(build, companies)
    _event_filings(build, companies)
    _figures(build)
    _annual_filings(build)
    _quarters(build, companies)
    company_rows = _companies(build, companies)
    summary_rows = _summaries(build, company_rows)
    if not options.allow_unapproved and options.prompt_version == NO_PROMPT_VERSION:
        build.problems.append(f"release build refused: --prompt-version is {NO_PROMPT_VERSION!r}")
    if not options.allow_unapproved and options.event_prompt_version == NO_PROMPT_VERSION:
        build.problems.append(
            f"release build refused: --event-prompt-version is {NO_PROMPT_VERSION!r}"
        )
    glossary = load_glossary()
    build.problems.extend(glossary_problems(glossary))
    if not options.allow_unapproved and not options.preview:
        build.problems.extend(release_problems(glossary))
    if build.problems:
        raise BuildError(build.problems)

    rows = {
        "companies": company_rows,
        "filings": list(build.filings.values()),
        "notices": list(build.notices.values()),
        "filing_summaries": summary_rows,
        "summary_sources": build.sources,
        "filing_facts": build.facts,
        "figures": build.figures,
        "quarter_figures": build.quarter_figures,
        "glossary": glossary_rows(glossary, allow_unapproved=options.allow_unapproved),
    }
    # Insert order is primary-key order; the loops above build rows in other orders.
    for table, table_rows in rows.items():
        columns, key = TABLES[table]
        index = [columns.index(k) for k in key]
        table_rows.sort(key=lambda r, index=index: tuple(r[i] for i in index))
    meta = {
        "schema_version": SCHEMA_VERSION,
        "data_as_of": options.as_of.isoformat(),
        "source_revision": options.source_revision,
        "llm_model": options.llm_model,
        "prompt_version": options.prompt_version,
        "allow_unapproved": int(options.allow_unapproved),
        "preview": int(options.preview),
        "aligner_version": faithfulness.ALIGNER_VERSION,
    }
    build.report["row_counts"] = {table: len(rows[table]) for table in sorted(rows)}
    return Bundle(rows, meta, build.report)


# -- annual filings (ANNUAL_SCOPE) ---------------------------------------------------------------


def _annual_versions(build: _Build, companies: dict[tuple[str, str], CompanyRow]) -> None:
    """Annual filings filed on or before --as-of, newest version per company and period."""
    prefix_re = re.compile(load_categories_contract()["dart"]["correction_prefix_pattern"])
    skipped: Counter[str] = Counter()
    versions: dict[tuple[str, int], list[tuple[AnnualFilingRow, str]]] = defaultdict(list)
    for filing in sorted(build.data.annual_filings, key=lambda f: (f.regulator, f.filing_key)):
        fid = _filing_id(filing.regulator, filing.filing_key)
        if (filing.regulator, filing.filing_type) not in ANNUAL_FORMS:
            if (filing.regulator, filing.filing_type) not in QUARTERLY_FORMS:
                skipped[f"filing_type:{filing.filing_type}"] += 1
            continue
        match = _ANNUAL_PERIOD_RE.fullmatch(filing.period or "")
        if match is None:
            build.problems.append(f"{fid}: annual period {filing.period!r} is not 'YYYY-annual'")
            continue
        if filing.filed_on is None:
            build.problems.append(f"{fid}: no filing date")
            continue
        if filing.filed_on > build.options.as_of:
            skipped["filed_after_as_of"] += 1
            continue
        if (filing.regulator, filing.company_key) not in companies:
            build.problems.append(f"{fid}: no company row for {filing.company_key}")
            continue
        company_id = _company_id(filing.regulator, filing.company_key)
        versions[(company_id, int(match.group(1)))].append((filing, fid))

    replaced = []
    for (company_id, year), members in sorted(versions.items()):
        filing, fid = max(members, key=lambda m: (m[0].filed_on, m[1]))
        replaced += sorted(other for _, other in members if other != fid)
        corrected = len(members) > 1 or bool(prefix_re.match(filing.title))
        build.annual[fid] = _Annual(filing, company_id, year, corrected)
    build.report["annual_filings_not_exported"] = dict(sorted(skipped.items()))
    build.report["annual_versions_replaced"] = {"count": len(replaced), "ids": replaced}


def _annual_filings(build: _Build) -> None:
    """Export the kept annual versions that are the source of an exported figure."""
    contract = load_categories_contract()
    if ANNUAL_CATEGORY not in {c["key"] for c in contract.get("non_event_categories", [])}:
        build.problems.append(f"category {ANNUAL_CATEGORY!r} is not in the categories contract")
    sources = {figure[2] for figure in build.figures}
    unused = []
    for fid, annual in sorted(build.annual.items()):
        if fid not in sources:
            unused.append(fid)
            continue
        filing = annual.filing
        build.problems.extend(f"{fid}: {p}" for p in link_problems(filing.url))
        build.filings[fid] = (
            fid, annual.company_id, "annual", ANNUAL_CATEGORY,
            ANNUAL_FORMS[(filing.regulator, filing.filing_type)], None, filing.title,
            filing.filed_on.isoformat(), f"FY{annual.year}", filing.url or "",
            int(annual.is_corrected), filing.source_text_sha256,
        )  # fmt: skip
        build.filing_kinds[fid] = "annual"
        build.filing_company[fid] = annual.company_id
    build.report["annual_filings_without_figures"] = {"count": len(unused), "ids": unused}


# -- quarterly filings (I11) ---------------------------------------------------------------------


def _quarters(build: _Build, companies: dict[tuple[str, str], CompanyRow]) -> None:
    """Each company's latest quarterly report filed on or before --as-of, with its
    three-month figures and the same three months a year earlier, each checked against the
    pinned response. Only a company that already has an exported event or annual filing gets
    one. A figure missing for either quarter is listed in the report's ``quarter_gaps``; a
    report with no figure for its own quarter is not exported and is listed in
    ``quarterly_filings_without_figures``."""
    contract = load_categories_contract()
    if QUARTERLY_CATEGORY not in {c["key"] for c in contract.get("non_event_categories", [])}:
        build.problems.append(f"category {QUARTERLY_CATEGORY!r} is not in the categories contract")
    prefix_re = re.compile(contract["dart"]["correction_prefix_pattern"])
    exported_companies = {build.filing_company[fid] for fid in build.filings}
    latest: dict[str, tuple[tuple, AnnualFilingRow, str, int, int]] = {}
    versions: Counter[tuple[str, int, int]] = Counter()
    for filing in sorted(build.data.annual_filings, key=lambda f: (f.regulator, f.filing_key)):
        if (filing.regulator, filing.filing_type) not in QUARTERLY_FORMS:
            continue
        fid = _filing_id(filing.regulator, filing.filing_key)
        match = _QUARTER_PERIOD_RE.fullmatch(filing.period or "")
        if match is None:
            build.problems.append(f"{fid}: quarterly period {filing.period!r} is not 'YYYY-Qn'")
            continue
        if filing.filed_on is None or filing.filed_on > build.options.as_of:
            continue
        company_id = _company_id(filing.regulator, filing.company_key)
        if company_id not in exported_companies:
            continue
        year, quarter = int(match.group(1)), _QUARTER_OF[match.group(2)]
        versions[(company_id, year, quarter)] += 1
        rank = (year, quarter, filing.filed_on, fid)
        if company_id not in latest or rank > latest[company_id][0]:
            latest[company_id] = (rank, filing, fid, year, quarter)

    rows = defaultdict(list)
    for row in build.data.financials:
        rows[_filing_id(row.regulator, row.filing_key)].append(row)
    gaps: list[str] = []
    checks = 0
    without_figures: list[str] = []
    for company_id, (_, filing, fid, year, quarter) in sorted(latest.items()):
        figures = []
        for metric in QUARTER_METRICS:
            for fiscal_year in (year, year - 1):
                label = f"{fiscal_year}-Q{quarter}"
                found = [r for r in rows[fid] if r.metric == metric and r.period == label]
                if not found:
                    gaps.append(f"{fid} {metric} {label}")
                    continue
                figure = _quarter_figure(build, filing, fid, company_id, quarter, year, found[0])
                if figure is not None:
                    figures.append(figure)
                    checks += 1
        if not any(f[4] == year for f in figures):
            without_figures.append(fid)
            continue
        build.problems.extend(f"{fid}: {p}" for p in link_problems(filing.url))
        corrected = versions[(company_id, year, quarter)] > 1 or bool(prefix_re.match(filing.title))
        build.filings[fid] = (
            fid, company_id, "quarterly", QUARTERLY_CATEGORY,
            QUARTERLY_FORMS[(filing.regulator, filing.filing_type)], None, filing.title,
            filing.filed_on.isoformat(), f"FY{year}-Q{quarter}", filing.url or "",
            int(corrected), filing.source_text_sha256,
        )  # fmt: skip
        build.filing_kinds[fid] = "quarterly"
        build.filing_company[fid] = company_id
        build.quarter_figures.extend(figures)
    build.report["quarter_checks"] = checks
    exported = sorted(fid for fid, kind in build.filing_kinds.items() if kind == "quarterly")
    build.report["quarter_gaps"] = {"count": len(gaps), "ids": sorted(gaps)}
    build.report["quarterly_filings_without_figures"] = {
        "count": len(without_figures), "ids": without_figures,
    }
    build.report["quarterly_filings"] = {"count": len(exported), "ids": exported}


def _quarter_figure(
    build: _Build,
    filing: AnnualFilingRow,
    fid: str,
    company_id: str,
    quarter: int,
    year: int,
    row: FinancialRow,
) -> tuple | None:
    label = f"{fid} {row.metric} {row.period}"
    if row.period_kind != "duration":
        build.problems.append(f"{label}: not a duration figure")
        return None
    if row.regulator == "DART":
        try:
            start, end = dart_quarter_period(filing.title, year, quarter, row.fiscal_year)
        except VerifyError as exc:
            build.problems.append(f"{label}: {exc}")
            return None
    else:
        if row.period_start is None or row.period_end is None:
            build.problems.append(f"{label}: SEC figure without its own period dates")
            return None
        start, end = row.period_start, row.period_end
    value = canonical_decimal(row.value)
    try:
        check = check_quarter_figure(
            build.pinned,
            QuarterRef(
                company_id=company_id, filing_id=fid, filing_title=filing.title,
                filing_year=year, fiscal_quarter=quarter, metric=row.metric,
                fiscal_year=row.fiscal_year, period_start=start.isoformat(),
                period_end=end.isoformat(), value=value,
            ),
        )  # fmt: skip
    except VerifyError as exc:
        build.problems.append(f"{label}: {exc}")
        return None
    return (
        f"{company_id}|{row.metric}|{end.isoformat()}|{BASIS}", company_id, fid, row.metric,
        row.fiscal_year, quarter, start.isoformat(), end.isoformat(), value, row.unit,
        row.currency, BASIS, check.regulator_tag,
    )  # fmt: skip


# -- event filings -------------------------------------------------------------------------------


def _event_source_sha256(event: EventRow) -> str:
    """The SHA-256 of the stored body text and the facts when a body is stored (SEC 8-K text).

    A DART row stores no body, so its hash is a placeholder over the regulator's list row and
    the fact fields.
    """
    facts = sorted([f.key, f.source_field, f.raw] for f in event.facts)
    if event.body_text is not None:
        payload: dict[str, Any] = {"body_text": event.body_text, "facts": facts}
    else:
        payload = {
            "regulator": event.regulator,
            "filing_key": event.filing_key,
            "company_key": event.company_key,
            "report_nm": event.report_nm,
            "filed_on": event.filed_on.isoformat() if event.filed_on else None,
            "rm": event.rm,
            "sec_items": event.sec_items,
            "facts": facts,
        }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shown_versions(events: list[EventRow], as_of: datetime.date) -> tuple[set[str], set[str]]:
    """Filing keys of the version each correction chain shows as of ``as_of``, and the keys
    of filings marked 정 that are hidden because no correction of theirs can be resolved.

    Chains are the ingest's (see :func:`app.build.source.event_rows`). The shown version is
    the newest chain member filed on or before ``as_of``. DART's rm 정 marks a filing a later
    correction replaced. Such a filing is shown only when a correction of it can be resolved
    and that correction was filed after ``as_of``. A correction of it has the same target
    (company, base report name, subsidiary flag and first filing date): one linked into its
    chain, or an orphan whose stated first filing date is the filing's. A same-name correction
    of a different filing never counts. With no such correction in the data, at any date, the
    filing is hidden as unresolved, as ingest's ``is_latest`` hides it.
    """
    listed = [e for e in events if e.filed_on is not None and e.excluded_reason is None]
    chains: dict[str, list[EventRow]] = defaultdict(list)
    for event in listed:
        if event.filed_on <= as_of:
            chains[event.chain_key].append(event)
    shown, unresolved = set(), set()
    for members in chains.values():
        newest = max(members, key=lambda e: (e.filed_on, e.filing_key))
        if _superseded_by_rm(newest.rm):
            replacing = [
                other
                for other in listed
                if other.is_correction
                and newest.target_key is not None
                and other.target_key == newest.target_key
                and (other.filed_on, other.filing_key) > (newest.filed_on, newest.filing_key)
            ]
            if not replacing:
                unresolved.add(newest.filing_key)
                continue
            if any(other.filed_on <= as_of for other in replacing):
                continue
        shown.add(newest.filing_key)
    return shown, unresolved


EVENT_CAP = 10  # the latest events kept per company (D72; ten since D76)


def notice_categories() -> frozenset[str]:
    """Category keys exported as notices, not as summarised events (D76)."""
    return frozenset(c["key"] for c in load_categories_contract()["notice_categories"])


@dataclass
class EventScope:
    """The event filings a build exports, and why every other one is not."""

    exported: list[EventRow]  # in (regulator, filing_key) order
    window: tuple[datetime.date, datetime.date]
    notices: list[EventRow] = field(default_factory=list)  # in (regulator, filing_key) order
    undated: list[str] = field(default_factory=list)
    outside_window: int = 0
    excluded: list[dict[str, str]] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    superseded_unresolved: list[str] = field(default_factory=list)
    without_body: list[str] = field(default_factory=list)
    capped: dict[str, list[str]] = field(default_factory=dict)  # company id -> dropped ids


def event_scope(data: BuildInput, as_of: datetime.date) -> EventScope:
    """The one rule for which events a build exports and summarises (D72, D76).

    Filed inside the 12-month window, not excluded, the shown version of its correction chain
    (:func:`_shown_versions`), with a stored body text (an event without one can never get a
    summary and does not count toward the cap), and at most :data:`EVENT_CAP` per company:
    the newest by ``filed_on``, ties broken by ``filing_key`` descending. A filing in a notice
    category that passes the window and version rules goes to ``notices`` instead: it needs no
    body, is never capped and never summarised.
    """
    start, end = window_bounds(as_of)
    scope = EventScope([], (start, end))
    events = sorted(data.events, key=lambda e: (e.regulator, e.filing_key))
    shown, unresolved = _shown_versions(events, as_of)
    notices = notice_categories()
    per_company: dict[tuple[str, str], list[EventRow]] = defaultdict(list)
    for event in events:
        fid = _filing_id(event.regulator, event.filing_key)
        if event.filed_on is None:
            scope.undated.append(fid)
            continue
        if not start <= event.filed_on <= end:
            scope.outside_window += 1
            continue
        if event.excluded_reason is not None:
            scope.excluded.append({"id": fid, "reason": event.excluded_reason})
            continue
        if event.filing_key in unresolved:
            scope.superseded_unresolved.append(fid)
            continue
        if event.filing_key not in shown:
            scope.superseded.append(fid)
            continue
        if event.category in notices:
            scope.notices.append(event)
            continue
        if event_source_text(event) is None:
            scope.without_body.append(fid)
            continue
        per_company[(event.regulator, event.company_key)].append(event)
    kept: set[tuple[str, str]] = set()
    for (regulator, company_key), members in per_company.items():
        newest = sorted(members, key=lambda e: (e.filed_on, e.filing_key), reverse=True)
        kept.update((e.regulator, e.filing_key) for e in newest[:EVENT_CAP])
        if len(newest) > EVENT_CAP:
            scope.capped[_company_id(regulator, company_key)] = [
                _filing_id(e.regulator, e.filing_key) for e in newest[EVENT_CAP:]
            ]
    scope.exported = [e for e in events if (e.regulator, e.filing_key) in kept]
    return scope


def _event_filings(build: _Build, companies: dict[tuple[str, str], CompanyRow]) -> None:
    categories_contract = load_categories_contract()
    categories = {c["key"] for c in categories_contract["categories"]}
    reasons = set(categories_contract["excluded_reasons"])
    prefix_re = re.compile(categories_contract["dart"]["correction_prefix_pattern"])

    def form(event: EventRow) -> str:
        if event.regulator == "SEC":
            return event.report_nm  # 8-K or 8-K/A
        return " ".join(prefix_re.sub("", event.report_nm).split())

    scope = event_scope(build.data, build.options.as_of)
    _owner_excluded(build, scope)
    build.problems.extend(f"{fid}: no filing date" for fid in scope.undated)
    for item in scope.excluded:
        if item["reason"] not in reasons:
            build.problems.append(f"{item['id']}: unknown excluded reason {item['reason']!r}")

    fact_errors: list[dict[str, str]] = []
    fact_checks: list[dict[str, str]] = []
    for event in scope.exported:
        fid = _filing_id(event.regulator, event.filing_key)
        if event.category not in categories:
            build.problems.append(f"{fid}: unknown category {event.category!r}")
            continue
        if (event.regulator, event.company_key) not in companies:
            build.problems.append(f"{fid}: no company row for {event.company_key}")
            continue
        build.problems.extend(f"{fid}: {p}" for p in link_problems(event.url))
        company_id = _company_id(event.regulator, event.company_key)
        build.filings[fid] = (
            fid, company_id, "event", event.category, form(event),
            event.sec_items, event.report_nm, event.filed_on.isoformat(), None, event.url or "",
            int(event.is_correction), _event_source_sha256(event),
        )  # fmt: skip
        build.filing_kinds[fid] = "event"
        build.filing_company[fid] = company_id
        build.events[fid] = event
        _event_facts(build, fid, company_id, event, fact_errors, fact_checks)

    for event in scope.notices:
        fid = _filing_id(event.regulator, event.filing_key)
        if (event.regulator, event.company_key) not in companies:
            build.problems.append(f"{fid}: no company row for {event.company_key}")
            continue
        build.problems.extend(f"{fid}: {p}" for p in link_problems(event.url))
        company_id = _company_id(event.regulator, event.company_key)
        build.notices[fid] = (
            fid, company_id, event.category, event.report_nm, event.filed_on.isoformat(),
            event.url or "", int(event.is_correction),
        )  # fmt: skip
        build.notice_company[fid] = company_id

    by_reason = Counter(e["reason"] for e in scope.excluded)
    build.report["excluded_filings"] = {
        "count": len(scope.excluded),
        "by_reason": dict(sorted(by_reason.items())),
        "filings": scope.excluded,
    }
    build.report["superseded_filings"] = {
        "count": len(scope.superseded),
        "ids": scope.superseded,
    }
    build.report["superseded_unresolved"] = {
        "count": len(scope.superseded_unresolved),
        "ids": scope.superseded_unresolved,
    }
    build.report["event_filings_outside_window"] = {
        "window": [scope.window[0].isoformat(), scope.window[1].isoformat()],
        "count": scope.outside_window,
    }
    build.report["event_filings_without_body"] = {
        "count": len(scope.without_body),
        "ids": scope.without_body,
    }
    build.report["event_filings_over_cap"] = {
        "cap": EVENT_CAP,
        "count": sum(len(ids) for ids in scope.capped.values()),
        "by_company": {cid: len(ids) for cid, ids in sorted(scope.capped.items())},
        "ids": sorted(i for ids in scope.capped.values() for i in ids),
    }
    build.report["notices"] = {
        "count": len(build.notices),
        "by_company": dict(sorted(Counter(build.notice_company.values()).items())),
        "by_category": dict(sorted(Counter(row[2] for row in build.notices.values()).items())),
    }
    build.report["fact_errors"] = {"count": len(fact_errors), "facts": fact_errors}
    build.report["fact_checks"] = fact_checks


def _owner_excluded(build: _Build, scope: EventScope) -> None:
    """Leave out the event filings the owner excluded (D109), in every mode, and say why.

    Applied after :func:`event_scope`, cap included, so leaving one out never brings another
    filing into the bundle. An id that is not an event filing in the build input refuses the
    build, so a typo cannot pass for an exclusion."""
    events = {_filing_id(e.regulator, e.filing_key) for e in build.data.events}
    excluded = {e.filing_id: e for e in build.data.excluded}
    build.problems.extend(
        f"{fid}: listed as owner-excluded but not an event filing in the build input"
        for fid in sorted(set(excluded) - events)
    )
    shown = {_filing_id(e.regulator, e.filing_key) for e in (*scope.exported, *scope.notices)}
    scope.exported = [e for e in scope.exported
                      if _filing_id(e.regulator, e.filing_key) not in excluded]  # fmt: skip
    scope.notices = [e for e in scope.notices
                     if _filing_id(e.regulator, e.filing_key) not in excluded]  # fmt: skip
    build.report["owner_excluded_filings"] = {
        "count": len(excluded),
        "filings": [
            {"id": fid, "decided_on": e.decided_on.isoformat(), "reason": e.reason,
             "in_scope": fid in shown}
            for fid, e in sorted(excluded.items())
        ],
    }  # fmt: skip


@functools.cache
def _facts_index() -> dict[tuple[str, str, str], tuple[str, int]]:
    """(regulator, fact key, source field) -> (origin, order in the contract).

    A DART origin is ``opendart:<endpoint>.<field>``, or ``dartdoc:<table>.<key>`` for a fact
    read from a filing's table; a SEC origin is the contract's ``sec:submissions.<field>`` as
    it stands.
    """
    contract = load_facts_contract()
    index = {}
    for spec in contract["endpoints"]:
        for order, item in enumerate(spec["fields"]):
            origin = f"opendart:{spec['endpoint']}.{item['source_field']}"
            index[("DART", item["key"], item["source_field"])] = (origin, order)
    for spec in contract["documents"]:
        for order, item in enumerate(spec["fields"]):
            origin = f"dartdoc:{spec['table']}.{item['key']}"
            index[("DART", item["key"], item["source_field"])] = (origin, order)
    for order, item in enumerate(contract["sec"]["fields"]):
        index[("SEC", item["key"], item["source_field"])] = (item["source_field"], order)
    return index


def _event_facts(
    build: _Build,
    fid: str,
    company_id: str,
    event: EventRow,
    fact_errors: list[dict[str, str]],
    fact_checks: list[dict[str, str]],
) -> None:
    index = _facts_index()
    usable = []
    for fact in event.facts:
        if fact.error is not None:
            fact_errors.append({"filing_id": fid, "fact_key": fact.key, "error": fact.error})
            continue
        located = index.get((event.regulator, fact.key, fact.source_field))
        if located is None:
            build.problems.append(f"{fid}: fact {fact.key}/{fact.source_field} not in contract")
            continue
        usable.append((located[1], located[0], fact))
    for position, (_, origin, fact) in enumerate(sorted(usable, key=lambda u: u[0]), start=1):
        value_kind = FACT_VALUE_KINDS.get(fact.kind)
        if value_kind is None:
            build.problems.append(f"{fid}: fact {fact.key} has unknown kind {fact.kind!r}")
            continue
        if value_kind in DECIMAL_VALUE_KINDS and fact.value_decimal is not None:
            value_text = canonical_decimal(fact.value_decimal)
        elif value_kind == "date" and fact.value_date is not None:
            value_text = fact.value_date.isoformat()
        elif value_kind == "text" and fact.value_text is not None:
            value_text = fact.value_text
        else:
            build.problems.append(f"{fid}: fact {fact.key} has no {fact.kind} value")
            continue
        try:
            pinned = check_fact(
                build.pinned,
                filing_id=fid,
                company_id=company_id,
                stock_code=event.stock_code,
                origin=origin,
                fact_key=fact.key,
                value_text=value_text,
            )
        except VerifyError as exc:
            build.problems.append(f"{fid}: fact {fact.key}: {exc}")
            continue
        build.facts.append((fid, position, fact.key, value_kind, value_text, fact.unit, origin))
        fact_checks.append(
            {"filing_id": fid, "fact_key": fact.key, "pinned": pinned, "result": "match"}
        )


# -- figures -------------------------------------------------------------------------------------


def _figure_candidate(build: _Build, row: FinancialRow) -> _Candidate | None:
    fid = _filing_id(row.regulator, row.filing_key)
    annual = build.annual.get(fid)
    if annual is None:
        return None
    label = f"{fid} {row.metric} {row.period}"
    if row.metric not in _REPORTED_METRICS:
        build.problems.append(f"{label}: metric not in the financial vocabulary")
        return None
    match = _ANNUAL_PERIOD_RE.fullmatch(row.period)
    if match is None or row.period_kind != "duration" or int(match.group(1)) != row.fiscal_year:
        build.problems.append(f"{label}: not an annual duration figure")
        return None
    if row.fiscal_year not in (annual.year, annual.year - 1):
        build.problems.append(f"{label}: not the filing's year or the year before")
        return None
    if row.regulator == "DART":
        try:
            start, end = dart_fiscal_period(annual.filing.title, annual.year, row.fiscal_year)
        except VerifyError as exc:
            build.problems.append(f"{label}: {exc}")
            return None
    else:
        # A 10-K's own year or its prior-year comparative, each with its own period dates.
        if (
            row.period_start is None
            or row.period_end is None
            or row.period_end.year != row.fiscal_year
        ):
            build.problems.append(f"{label}: SEC figure without its own period dates")
            return None
        start, end = row.period_start, row.period_end
    return _Candidate(
        row=row,
        company_id=annual.company_id,
        filing_id=fid,
        filed_on=annual.filing.filed_on,
        period_start=start,
        period_end=end,
    )


def _latest_years(build: _Build) -> dict[str, int]:
    """Per company, the fiscal year of its latest kept annual filing."""
    latest: dict[str, int] = {}
    for annual in build.annual.values():
        latest[annual.company_id] = max(latest.get(annual.company_id, annual.year), annual.year)
    return latest


def _figure_choices(
    build: _Build,
) -> list[tuple[tuple[str, str, str], _Candidate, list[_Candidate], bool]]:
    """Per (company, metric, period end): the candidate that wins, the earlier candidates
    that stated a different value, and whether the year's own annual report states it
    (else a comparative's value has nothing to be checked against). No pinned response is
    read here.

    Two fiscal years per company (D79): the year of its latest annual filing and the year
    before. An older annual filing still counts: its own-year value is the original that a
    later comparative restates, and it is the source when the latest filing does not
    state that year."""
    latest = _latest_years(build)
    groups: dict[tuple[str, str, str], list[_Candidate]] = defaultdict(list)
    outside = 0
    for row in build.data.financials:
        candidate = _figure_candidate(build, row)
        if candidate is None:
            continue
        if row.fiscal_year < latest[candidate.company_id] - 1:
            outside += 1
            continue
        key = (candidate.company_id, row.metric, candidate.period_end.isoformat())
        groups[key].append(candidate)
    build.report["figures_older_than_two_years"] = outside
    choices = []
    for key, candidates in sorted(groups.items()):
        # The newest filing that states the figure wins (filed date, then filing id); an
        # earlier, different value makes it a restated figure.
        chosen = max(candidates, key=lambda c: (c.filed_on, c.filing_id))
        originals = sorted(
            (c for c in candidates if c.row.value != chosen.row.value),
            key=lambda c: (c.filed_on, c.filing_id),
        )
        own_report = any(build.annual[c.filing_id].year == c.row.fiscal_year for c in candidates)
        choices.append((key, chosen, originals, own_report))
    return choices


def annual_summary_filings(data: BuildInput, as_of: datetime.date) -> set[str]:
    """The annual filings that need summaries: each company's latest kept annual version
    that is the source of a figure, chosen by the exporter's own rules (ANNUAL_SCOPE).

    The pinned responses are not read. A figure that fails its pinned check fails a release
    build, so a release exports exactly these filings as figure sources."""
    build = _Build(data, BuildOptions(as_of, "summaries", allow_unapproved=True),
                   PinnedResponses([]))  # fmt: skip
    _annual_versions(build, {(c.regulator, c.key): c for c in data.companies})
    sources = {chosen.filing_id for _, chosen, _, _ in _figure_choices(build)}
    return latest_annual_ids(
        (fid, annual.company_id, f"FY{annual.year}", annual.filing.filed_on.isoformat())
        for fid, annual in build.annual.items()
        if fid in sources
    )


def _check_candidate(build: _Build, candidate: _Candidate):
    """Re-read one candidate's value from its own filing's pinned response."""
    annual = build.annual[candidate.filing_id]
    return check_figure(
        build.pinned,
        FigureRef(
            company_id=candidate.company_id,
            filing_id=candidate.filing_id,
            filing_title=annual.filing.title,
            filing_year=annual.year,
            metric=candidate.row.metric,
            fiscal_year=candidate.row.fiscal_year,
            period_start=candidate.period_start.isoformat(),
            period_end=candidate.period_end.isoformat(),
            value=canonical_decimal(candidate.row.value),
        ),
    )


def _combined_eps_original(build: _Build, chosen: _Candidate) -> dict[str, Any] | None:
    """For a DART diluted EPS comparative: the value the year's own report states as one
    basic-and-diluted EPS line, read from its pinned response (D79). It is used only to
    check the comparative; no figure is exported from it."""
    if chosen.row.regulator != "DART":
        return None
    own = [
        (fid, annual)
        for fid, annual in sorted(build.annual.items())
        if annual.company_id == chosen.company_id and annual.year == chosen.row.fiscal_year
    ]
    if not own:
        return None
    fid, annual = own[0]
    found = build.pinned.dart_combined_diluted_eps(
        corp_code=annual.filing.company_key, rcept_no=annual.filing.filing_key,
        bsns_year=annual.year,
    )  # fmt: skip
    if found is None:
        return None
    value, check = found
    return {"filing_id": fid, "value": canonical_decimal(value),
            "regulator_tag": check.regulator_tag, "pinned": check.pinned,
            "combined_basic_and_diluted": True}  # fmt: skip


def _report_list(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(entries), "figures": entries}


def _figures(build: _Build) -> None:
    """Check every chosen figure and its earlier values against the pinned responses, then
    keep one basis per company and fiscal year (D79).

    An earlier value under the same regulator tag makes the figure restated; under another
    tag it is reported as ``tag_changed`` and the figure is not restated. A prior-year
    figure that the year's own report does not state is ``restatement_unchecked``, which
    fails a release build. When a company's year has a restated figure, that year's figures
    that come only from an earlier report are ``mixed_basis`` and are not exported."""
    restated: list[dict[str, Any]] = []
    tag_changed: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []
    combined_checks: list[dict[str, Any]] = []
    kept: list[tuple[str, _Candidate, Any, bool]] = []
    for (company_id, metric, period_end), chosen, originals, own_report in _figure_choices(build):
        figure_id = f"{company_id}|{metric}|{period_end}|{BASIS}"
        value = canonical_decimal(chosen.row.value)
        try:
            check = _check_candidate(build, chosen)
            # An earlier value is read from its own pinned response too.
            original_checks = [(c, _check_candidate(build, c)) for c in originals]
        except VerifyError as exc:
            build.problems.append(f"{figure_id}: {exc}")
            continue
        entry = {"id": figure_id, "value": value, "filing_id": chosen.filing_id,
                 "regulator_tag": check.regulator_tag}  # fmt: skip
        same_tag, other_tag = [], []
        for c, oc in original_checks:
            (same_tag if oc.regulator_tag == check.regulator_tag else other_tag).append(
                {
                    "filing_id": c.filing_id,
                    "value": canonical_decimal(c.row.value),
                    "regulator_tag": oc.regulator_tag,
                    "pinned": oc.pinned,
                }  # fmt: skip
            )
        lookup_problem = None
        if not own_report and metric == ReportedMetric.eps_diluted.value:
            try:
                combined = _combined_eps_original(build, chosen)
            except VerifyError as exc:
                # Without a readable response the figure stays unchecked, with the reason.
                combined, lookup_problem = None, str(exc)
            if combined is not None:
                own_report = True
                combined_checks.append({**entry, "original": combined})
                if combined["value"] != value:
                    same_tag.append(combined)
        if same_tag:
            restated.append({**entry, "originals": same_tag})
        if other_tag:
            tag_changed.append({**entry, "originals": other_tag})
        if not own_report:
            unchecked.append({**entry, "fiscal_year": chosen.row.fiscal_year,
                              **({"combined_eps_lookup": lookup_problem}
                                 if lookup_problem else {})})  # fmt: skip
            if not build.options.allow_unapproved:
                build.problems.append(
                    f"{figure_id}: release build refused: no annual report for its own year "
                    "to check a restatement against (restatement_unchecked)"
                )
        kept.append((figure_id, chosen, check, bool(same_tag)))

    restating: dict[tuple[str, int], set[str]] = defaultdict(set)
    for _, chosen, _, is_restated in kept:
        if is_restated:
            restating[(chosen.company_id, chosen.row.fiscal_year)].add(chosen.filing_id)
    checks: list[dict[str, Any]] = []
    mixed: list[dict[str, Any]] = []
    excluded: set[tuple[str, str, int]] = set()
    for figure_id, chosen, check, is_restated in kept:
        row = chosen.row
        value = canonical_decimal(row.value)
        restaters = restating.get((chosen.company_id, row.fiscal_year), set())
        if restaters and chosen.filing_id not in restaters:
            excluded.add((chosen.company_id, row.metric, row.fiscal_year))
            mixed.append({"id": figure_id, "value": value, "filing_id": chosen.filing_id,
                          "fiscal_year": row.fiscal_year,
                          "restated_by": sorted(restaters)})  # fmt: skip
            continue
        build.figures.append(
            (figure_id, chosen.company_id, chosen.filing_id, row.metric, row.fiscal_year,
             chosen.period_start.isoformat(), chosen.period_end.isoformat(), value, row.unit,
             row.currency, BASIS, int(is_restated), check.regulator_tag)
        )  # fmt: skip
        checks.append(
            {
                "id": figure_id,
                "value": value,
                "regulator_tag": check.regulator_tag,
                "pinned": check.pinned,
                "is_restated": is_restated,
                "result": "match",
            }
        )
    build.report["figure_checks"] = checks
    build.report["restated_figures"] = _report_list(restated)
    build.report["tag_changed"] = _report_list(tag_changed)
    build.report["restatement_unchecked"] = _report_list(unchecked)
    build.report["combined_eps_checks"] = _report_list(combined_checks)
    build.report["mixed_basis"] = _report_list(mixed)
    build.report["figure_gaps"] = _figure_gaps(build, excluded)


def _figure_gaps(build: _Build, excluded: set[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """Each company and reported metric without a figure for both of its two fiscal years.
    The reason is ``not_stated`` (the ingested filings do not state it) or ``mixed_basis``
    (stated only by an earlier report for a year with restated figures, so not exported)."""
    present: dict[tuple[str, str], set[int]] = defaultdict(set)
    for figure in build.figures:
        present[(figure[1], figure[3])].add(figure[4])
    gaps = []
    for company_id, year in sorted(_latest_years(build).items()):
        for metric in ReportedMetric:
            missing = [y for y in (year - 1, year) if y not in present[(company_id, metric.value)]]
            left_out = [y for y in missing if (company_id, metric.value, y) in excluded]
            for reason, years in (
                ("not_stated", [y for y in missing if y not in left_out]),
                ("mixed_basis", left_out),
            ):
                if years:
                    gaps.append({"company_id": company_id, "metric": metric.value,
                                 "missing_years": years, "reason": reason})  # fmt: skip
    return gaps


# -- companies and summaries ---------------------------------------------------------------------


def _korean_names() -> dict[str, str]:
    glossary = json.loads(FAMILY_GLOSSARY_PATH.read_text(encoding="utf-8"))
    return {ticker: names[0] for ticker, names in glossary["companies"].items()}


def _companies(build: _Build, companies: dict[tuple[str, str], CompanyRow]) -> list[tuple]:
    used = set(build.filing_company.values()) | set(build.notice_company.values())
    year_end: dict[str, str] = {}
    for figure in sorted(build.figures, key=lambda f: f[6]):
        year_end[figure[1]] = figure[6][5:]  # MM-DD of the latest period end
    korean = _korean_names()
    selected = [c for c in companies.values() if _company_id(c.regulator, c.key) in used]
    selected.sort(key=lambda c: (REGULATOR_ORDER[c.regulator], c.ticker or "", c.key))
    rows = []
    for order, company in enumerate(selected, start=1):
        cid = _company_id(company.regulator, company.key)
        if not company.ticker:
            build.problems.append(f"{cid}: no ticker")
        if cid not in year_end:
            build.problems.append(f"{cid}: no annual figure states its fiscal year end")
        if company.regulator == "DART":
            name_ko, name_en = company.name, company.name_en
        else:
            name_en = company.name_en or company.name
            name_ko = korean.get(company.ticker or "", name_en)
        if not name_en:
            build.problems.append(f"{cid}: no English name")
        rows.append(
            (cid, company.regulator, company.ticker or "", name_ko, name_en or "",
             company.market, CURRENCY[company.regulator], year_end.get(cid, ""), order)
        )  # fmt: skip
    return rows


def current_input_sha256(build: _Build, filing_id: str, section: str) -> str | None:
    """The key a summary of this filing and section has now (the summary build's cache key,
    :func:`app.build.model.summary_input_sha256`, or the template's for a templated event,
    :func:`app.build.templates.event_summary_key`), or None when there is no source text."""
    if build.filing_kinds[filing_id] == "event":
        event = build.events[filing_id]
        return event_summary_key(event, event_source_text(event), build.options.llm_model,
                                 build.options.event_prompt_version,
                                 load_lexicon().version)  # fmt: skip
    source = annual_source_text(build.annual[filing_id].filing, section)
    if source is None:
        return None
    return summary_input_sha256(source, build.options.llm_model, section,
                                build.options.prompt_version, load_lexicon().version)  # fmt: skip


def guard_source(build: _Build, filing_id: str, section: str) -> Source | None:
    """The title and source text the summary build guarded this filing and section with
    (D111), or None when there is no source text."""
    if build.filing_kinds[filing_id] == "event":
        event = build.events[filing_id]
        text = event_source_text(event)
        return None if text is None else Source(event.report_nm, text)
    filing = build.annual[filing_id].filing
    text = annual_source_text(filing, section)
    return None if text is None else Source(filing.title, text)


def _summaries(build: _Build, company_rows: list[tuple]) -> list[tuple]:
    names = {row[0]: [row[3], row[4]] for row in company_rows}
    rows = []
    approved: set[tuple[str, str, str]] = set()
    not_approved = 0
    stale: list[str] = []
    for summary in sorted(
        build.data.summaries, key=lambda s: (s.filing_id, s.lang, s.section, s.review_state)
    ):
        kind = build.filing_kinds.get(summary.filing_id)
        if kind is None:
            continue
        if summary.lang not in LANGS or summary.section not in SUMMARY_SECTIONS[kind]:
            build.problems.append(
                f"{summary.filing_id}: summary {summary.lang}/{summary.section} not allowed"
            )
            continue
        if summary.review_state != "approved":
            not_approved += 1
            continue
        key = (summary.filing_id, summary.lang, summary.section)
        if summary.input_sha256 != current_input_sha256(build, summary.filing_id,
                                                        summary.section):  # fmt: skip
            # Approved for other source text, prompt, model or word lists: never shipped.
            stale.append(f"{summary.filing_id} {summary.lang}/{summary.section}")
            continue
        if key in approved:
            build.problems.append(f"{summary.filing_id}: duplicate summary {key[1]}/{key[2]}")
            continue
        approved.add(key)
        lines = (summary.line1, summary.line2, summary.line3)
        build.problems += summary_problems(
            summary.filing_id, summary.lang, summary.section, lines,
            names.get(build.filing_company[summary.filing_id], []),
            guard_source(build, summary.filing_id, summary.section),
        )  # fmt: skip
        rows.append(
            (summary.filing_id, summary.lang, summary.section, *lines, "approved",
             summary.input_sha256)
        )  # fmt: skip
    rows = _summary_sources(build, rows, approved)
    # The bundle keeps only the title and cited excerpts, and verify guards with those (D111):
    # check them here too, so the export refuses what verify would.
    excerpts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for source_row in build.sources:
        if source_row[6]:
            excerpts[(source_row[0], source_row[2])].append(source_row[6])
    reported = set(build.problems)
    for row in rows:
        filing_id, lang, section = row[:3]
        cited = cited_source(build.filings[filing_id][6], excerpts[(filing_id, section)])
        for problem in summary_problems(
            filing_id, lang, section, row[3:6],
            names.get(build.filing_company[filing_id], []), cited,
        ):  # fmt: skip
            if problem not in reported:
                reported.add(problem)
                build.problems.append(problem)
    required = required_summaries(
        ((fid, row[1], row[2], row[8], row[7]) for fid, row in build.filings.items()),
        {
            fid: annual_sections(annual.filing.regulator, annual.filing.chunks)
            for fid, annual in build.annual.items()
        },
    )
    relaxed = build.options.allow_unapproved or build.options.preview
    if stale and not relaxed:
        build.problems.append(
            f"release build refused: {len(stale)} approved summaries do not match the current "
            f"source text, prompt version, model or word lists ({', '.join(stale)})"
        )
    missing = sorted(
        fid
        for fid, pairs in required.items()
        if any((fid, lang, section) not in approved for lang, section in pairs)
    )
    if missing and not relaxed:
        shown = ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else "")
        build.problems.append(
            f"release build refused: {len(missing)} exported filings lack approved summaries "
            f"({shown}); use --allow-unapproved for a development build"
        )
    build.report["summaries"] = {
        "approved_rows": len(rows),
        "not_approved_rows_skipped": not_approved,
        "stale_approved_rows_skipped": stale,
        "filings_needing_summaries": len(required),
        "filings_without_approved_summaries": missing,
    }
    return rows


def _summary_sources(
    build: _Build, rows: list[tuple], approved: set[tuple[str, str, str]]
) -> list[tuple]:
    """Fill ``build.sources`` for the summary rows that ship and return those rows (D101).

    A release refuses a line without a current record, and an unsupported or unsourced line the
    owner did not accept. A development build or a preview leaves such a section out in both
    languages; a line without a record ships there without a source sentence."""
    index = build.faithfulness
    release = not (build.options.allow_unapproved or build.options.preview)
    if release and index.missing is not None:
        build.problems.append(
            f"release build refused: no faithfulness report at {index.missing}; run "
            "make faithfulness AS_OF=<the summary run's --as-of>"
        )
    sources: dict[tuple[str, str, str], list[tuple]] = {}
    withheld: set[tuple[str, str]] = set()
    unchecked: list[str] = []
    accepted = 0
    for row in rows:
        filing_id, lang, section = row[:3]
        excerpt_lang = faithfulness.SOURCE_LANG[filing_id.split(":")[0].upper()]
        found: list[tuple] = []
        for number, line in enumerate((r for r in row[3:6] if r is not None), start=1):
            key = (filing_id, lang, section, number)
            where = f"{filing_id} {lang}/{section} line {number}"
            if index.accepted(key, line, row[7]):
                accepted += 1
                continue
            record = index.current(key, line, row[7])
            if record is None:
                unchecked.append(where)
                continue
            line_rows = faithfulness.source_rows(key, record, excerpt_lang)
            if not line_rows:
                withheld.add((filing_id, section))
                if release:
                    build.problems.append(
                        f"release build refused: {where} is {record['verdict']} with no source "
                        "sentence; unsupported lines never ship unless the owner accepts them"
                    )
            found += line_rows
        sources[(filing_id, lang, section)] = found
    if release and index.missing is None and unchecked:
        shown = ", ".join(unchecked[:10]) + (" ..." if len(unchecked) > 10 else "")
        build.problems.append(
            f"release build refused: {len(unchecked)} summary lines have no faithfulness record "
            f"from {faithfulness.ALIGNER_VERSION} for their text and approval; rerun make "
            f"faithfulness ({shown})"
        )
    kept = []
    for row in rows:
        if (row[0], row[2]) in withheld:
            approved.discard(row[:3])
            continue
        kept.append(row)
        build.sources += sources[row[:3]]
    build.report["summary_sources"] = {
        "aligner_version": faithfulness.ALIGNER_VERSION,
        "rows": len(build.sources),
        "lines_accepted_without_source": accepted,
        "lines_without_record": unchecked,
        "sections_withheld": sorted(f"{fid} {section}" for fid, section in withheld),
    }
    return kept


# -- writing -------------------------------------------------------------------------------------


def report_path_for(out: Path) -> Path:
    return out.with_name(f"{out.stem}.report.json")


def _check_decimals(rows: dict[str, list[tuple]]) -> None:
    """Every stored decimal is canonical; anything else stops the write."""
    problems = []
    for table in ("figures", "quarter_figures"):
        value = TABLES[table][0].index("value")
        for row in rows[table]:
            try:
                require_canonical(row[value])
            except ValueError as exc:
                problems.append(f"{row[0]}: {exc}")
    columns = TABLES["filing_facts"][0]
    kind, text = columns.index("value_kind"), columns.index("value_text")
    for row in rows["filing_facts"]:
        if row[kind] in DECIMAL_VALUE_KINDS:
            try:
                require_canonical(row[text])
            except ValueError as exc:
                problems.append(f"{row[0]}#{row[1]}: {exc}")
    if problems:
        raise BuildError(problems)


def remove_outputs(out: Path, report_path: Path) -> None:
    """A failed build leaves no bundle or report at the output paths, not even an old one."""
    for path in (out, report_path):
        path.unlink(missing_ok=True)


def _write_sqlite(bundle: Bundle, path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        for table in INSERT_ORDER:
            columns = TABLES[table][0]
            marks = ", ".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})",
                bundle.rows[table],
            )
        meta = {
            **bundle.meta,
            "content_sha256": content_sha256(connection, bundle.meta["aligner_version"]),
        }
        connection.execute(
            f"INSERT INTO build_meta ({', '.join(BUILD_META_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in BUILD_META_COLUMNS)})",
            [meta[c] for c in BUILD_META_COLUMNS],
        )
        connection.commit()
    finally:
        connection.close()
    return meta


def write_bundle(bundle: Bundle, out: Path, report_path: Path | None = None) -> dict[str, Any]:
    """Write the file and its report together; on any failure leave neither behind.

    Both files are completed in a fresh directory beside ``out``, then moved into place: the
    old report goes first, so no moment pairs a new bundle with an old report.
    """
    report_path = report_path or report_path_for(out)
    try:
        _check_decimals(bundle.rows)
        out.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
        try:
            staged, staged_report = staging / "bundle.sqlite", staging / "report.json"
            meta = _write_sqlite(bundle, staged)
            data = staged.read_bytes()
            report = {
                **bundle.report,
                "build_meta": meta,
                "mode": (
                    "development"
                    if meta["allow_unapproved"]
                    else "preview" if meta["preview"] else "release"
                ),
                "file": {
                    "name": out.name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                },
            }
            staged_report.write_text(
                json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report_path.unlink(missing_ok=True)
            os.replace(staged, out)
            os.replace(staged_report, report_path)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        remove_outputs(out, report_path)
        raise
    return report


# -- command line --------------------------------------------------------------------------------


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=BACKEND_DIR, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.build.export",
        description="Export the bundled SQLite file and verify every figure in it.",
    )
    parser.add_argument("--as-of", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", type=Path, help="default: <out stem>.report.json")
    parser.add_argument("--database-url", help="default: DATABASE_URL from the settings")
    parser.add_argument(
        "--pinned",
        type=Path,
        action="append",
        help=f"directory of pinned regulator responses, repeatable (default {DEFAULT_PINNED_DIR})",
    )
    parser.add_argument("--source-revision", help="default: git rev-parse HEAD")
    parser.add_argument(
        "--approved",
        type=Path,
        help="file of approved summaries (default backend/data/summaries/approved.jsonl)",
    )
    parser.add_argument(
        "--excluded",
        type=Path,
        help="the owner's excluded filings (default backend/data/summaries/excluded_filings.jsonl, "
        "D109)",
    )
    parser.add_argument(
        "--faithfulness",
        type=Path,
        default=faithfulness.REPORT_PATH,
        help="faithfulness report the source sentences come from (default "
        "data/summaries/faithfulness.jsonl, D97, D101)",
    )
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument(
        "--prompt-version",
        default=DEFAULT_PROMPT_VERSION,
        help=f"the annual summaries' prompt version; a release refuses {NO_PROMPT_VERSION!r}",
    )
    parser.add_argument(
        "--event-prompt-version",
        default=DEFAULT_EVENT_PROMPT_VERSION,
        help=f"the event summaries' prompt version; a release refuses {NO_PROMPT_VERSION!r}",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="development build: export filings without approved summaries",
    )
    mode.add_argument(
        "--preview",
        action="store_true",
        help="preview build: leave out filings without approved summaries, keep every other check",
    )
    mode.add_argument("--release", action="store_true", help="release build (the default)")
    return parser


def _load_from_database(args: argparse.Namespace) -> BuildInput:
    from app.build.source import load_build_input
    from app.config import get_settings

    return asyncio.run(
        load_build_input(
            args.database_url or get_settings().database_url, args.approved, args.excluded
        )
    )


def run(
    argv: Sequence[str] | None = None,
    load: Callable[[argparse.Namespace], BuildInput] = _load_from_database,
) -> int:
    args = _parser().parse_args(argv)
    report_path = args.report or report_path_for(args.out)
    try:
        try:
            revision = args.source_revision or _git_revision()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BuildError([f"cannot read the git revision: {exc}"]) from exc
        options = BuildOptions(
            as_of=args.as_of,
            source_revision=revision,
            allow_unapproved=args.allow_unapproved,
            preview=args.preview,
            llm_model=args.llm_model,
            prompt_version=args.prompt_version,
            event_prompt_version=args.event_prompt_version,
        )
        bundle = build_bundle(load(args), options, args.pinned or [DEFAULT_PINNED_DIR],
                              faithfulness.load_index(args.faithfulness))  # fmt: skip
        report = write_bundle(bundle, args.out, report_path)
    except BuildError as exc:
        remove_outputs(args.out, report_path)
        for problem in exc.problems:
            print(f"FAIL {problem}", file=sys.stderr)
        print(
            f"build failed: {len(exc.problems)} problem(s); no bundle or report left at the "
            "output paths",
            file=sys.stderr,
        )
        return 1
    except BaseException:
        remove_outputs(args.out, report_path)
        raise
    counts = " ".join(f"{t}={n}" for t, n in report["row_counts"].items())
    print(f"content_sha256={report['build_meta']['content_sha256']}")
    print(f"file={args.out} size_bytes={report['file']['size_bytes']}")
    print(f"rows: {counts}")
    print(
        f"excluded={report['excluded_filings']['count']} "
        f"superseded={report['superseded_filings']['count']} "
        f"superseded_unresolved={report['superseded_unresolved']['count']} "
        f"fact_errors={report['fact_errors']['count']} mode={report['mode']}"
    )
    for item in report["owner_excluded_filings"]["filings"]:
        state = "left out" if item["in_scope"] else "not in scope at --as-of"
        print(f"owner-excluded {item['id']} ({state}; decided {item['decided_on']}): "
              f"{item['reason']}")  # fmt: skip
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
