"""Rows the exporter reads from the build database, the canonical decimal form, and scope rules.

The rows are regulator-neutral so the exporter never sees a PostgreSQL row or ORM object.
Every amount is a ``Decimal``; the bundle stores it as a canonical decimal string.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, Inexact, Rounded

# ASCII digits only: ``\d`` would also accept other scripts' digits.
CANONICAL_DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$")

# M3 fact kind -> section-4 value_kind. The one place this mapping lives.
FACT_VALUE_KINDS: dict[str, str] = {
    "amount": "amount",
    "count": "shares",
    "ratio": "ratio",
    "date": "date",
    "text": "text",
}
DECIMAL_VALUE_KINDS = frozenset({"amount", "shares", "ratio"})

# The summary prompt's version. It is part of the summary cache key (summary_input_sha256), so
# bump it on any change to a prompt, the schema or the source-text layout. It lives here so the
# exporter's default and the summary build read the one value (D72).
PROMPT_VERSION = "m6-2026-11-18-b"
# The event prompt's version, which keys the event ``summary`` section in place of
# PROMPT_VERSION, so a change to the event prompt alone keeps every annual summary (D78).
EVENT_PROMPT_VERSION = "m6-2026-11-19-a"

LANGS = ("ko", "en")
# A quarterly report (I11) is a figures source only and is never summarised.
SUMMARY_SECTIONS = {
    "event": ("summary",),
    "annual": ("one_line", "business", "changes", "risks"),
    "quarterly": (),
}
# Sections written as three lines, checked as one summary by the neutrality guard.
THREE_LINE_SECTIONS = frozenset({"summary"})


def section_prompt_version(section: str, prompt_version: str, event_prompt_version: str) -> str:
    """The prompt version in the cache key of ``section``: the event one for an event section."""
    return event_prompt_version if section in SUMMARY_SECTIONS["event"] else prompt_version


class BuildError(Exception):
    """The build cannot produce a bundle; ``problems`` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = sorted(set(problems))
        super().__init__("; ".join(self.problems))


def canonical_decimal(value: Decimal) -> str:
    """Plain digits, no exponent, no trailing zeros after the point, and no ``-0``.

    Exact or an error: the context holds every digit and traps rounding.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"expected Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"non-finite decimal {value!r}")
    if value.is_zero():
        return "0"
    exact = Context(prec=max(len(value.as_tuple().digits), 1), traps=[Inexact, Rounded])
    normalized = value.normalize(exact)
    if normalized != value:
        raise ValueError(f"decimal {value!r} changed while normalising")
    return require_canonical(format(normalized, "f"))


def require_canonical(text: str) -> str:
    """Return ``text`` if it is a canonical decimal string, else raise ``ValueError``."""
    if not isinstance(text, str) or not CANONICAL_DECIMAL_RE.fullmatch(text) or text == "-0":
        raise ValueError(f"non-canonical decimal {text!r}")
    return text


# -- scope ---------------------------------------------------------------------------------------

ANNUAL_SCOPE = """Annual scope (PRODUCT.md: latest annual results, with earlier years per figure).

- Annual filings are considered only when filed on or before --as-of.
- Per company and period, only the newest version is kept (filed date, then filing id);
  it gets is_corrected=1 when it replaced an earlier version or its title marks a correction.
- An annual filing is exported only when it is the source of an exported figure.
- Each company's latest exported annual filing (period year, filed date, filing id) is the
  one that needs approved summaries; older annual filings need none.
- Every exported event filing needs approved summaries.
"""


def latest_annual_ids(
    annual: Iterable[tuple[str, str, str | None, str]],
) -> set[str]:
    """Each company's latest annual filing from ``(filing_id, company_id, period_label,
    filed_on)`` rows; see :data:`ANNUAL_SCOPE`."""
    best: dict[str, tuple[str, str, str]] = {}
    for filing_id, company_id, period_label, filed_on in annual:
        rank = (period_label or "", filed_on, filing_id)
        if company_id not in best or rank > best[company_id]:
            best[company_id] = rank
    return {rank[2] for rank in best.values()}


def required_summaries(
    filings: Iterable[tuple[str, str, str, str | None, str]],
    annual_sections: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Filing id -> the ``(lang, section)`` pairs that must be approved, from
    ``(filing_id, company_id, kind, period_label, filed_on)`` rows; see :data:`ANNUAL_SCOPE`.

    ``annual_sections`` maps an annual filing id to its sections, from
    :func:`annual_sections`. A filing missing from it needs the sections every report has,
    :func:`mandatory_annual_sections`; a reader without the filing's chunks (the finished
    bundle) can check no more than that."""
    rows = list(filings)
    latest = latest_annual_ids((f, c, p, d) for f, c, k, p, d in rows if k == "annual")
    known = annual_sections or {}
    required = {}
    for filing_id, _, kind, _, _ in rows:
        if kind == "event":
            sections: Sequence[str] = SUMMARY_SECTIONS["event"]
        elif filing_id in latest:
            sections = known.get(filing_id, mandatory_annual_sections(filing_id))
        else:
            continue
        required[filing_id] = tuple((lang, section) for lang in LANGS for section in sections)
    return required


# -- annual sections by heading (D64) ------------------------------------------------------------


@dataclass(frozen=True)
class ChunkRow:
    """One stored filing chunk: its document-wide index, heading and text."""

    chunk_index: int
    section_title: str | None
    content: str
    part_title: str | None = None  # enclosing top-level part; None in chunks stored before it


@dataclass(frozen=True)
class HeadingRule:
    include: re.Pattern[str]
    exclude: re.Pattern[str] | None = None

    def matches(self, title: str | None) -> bool:
        if not title or not self.include.search(title):
            return False
        return self.exclude is None or not self.exclude.search(title)


# Matched against filing_chunks.meta.section_title. DART headings are searched anywhere in
# the title ("1. 사업의 개요"); SEC titles are the canonical ones app.clients.sec_document writes
# ("Item 1. Business"). one_line is written from the business chunks.
SECTION_HEADINGS: dict[str, dict[str, HeadingRule]] = {
    "DART": {
        "business": HeadingRule(re.compile(r"사업의\s*개요|주요\s*제품|사업의\s*내용")),
        "changes": HeadingRule(re.compile(r"경영진단|분석의견")),
        # Business and investment risks only; 위험관리 및 파생거래 is hedging and market-risk
        # management, not a list of risks to the business.
        "risks": HeadingRule(
            re.compile(r"투자\s*위험|위험\s*요소|위험\s*요인|사업\s*위험|사업의\s*위험"),
            re.compile(r"위험\s*관리|파생"),
        ),
    },
    "SEC": {
        "business": HeadingRule(re.compile(r"^\s*Item\s*1\.\s*Business", re.IGNORECASE)),
        "changes": HeadingRule(re.compile(r"^\s*Item\s*7\.\s*Management", re.IGNORECASE)),
        "risks": HeadingRule(re.compile(r"^\s*Item\s*1A\.\s*Risk", re.IGNORECASE)),
    },
}
SECTION_SOURCE = {"one_line": "business", "business": "business", "changes": "changes",
                  "risks": "risks"}  # fmt: skip
# A DART top-level part ("II. 사업의 내용", "IV. 이사의 경영진단 및 분석의견"): chunks up to the
# next top-level heading belong to it. SEC items have no parts.
TOP_LEVEL_HEADING: dict[str, re.Pattern[str] | None] = {
    "DART": re.compile(r"^\s*(?:[IVXL]+|[\u2160-\u216B])\s*\."),
    "SEC": None,
}
# Sections a report may lack: a DART report without a risk heading, or a 10-K whose Item 1A
# ingest omitted (missing or too short), has no risks section.
OPTIONAL_SECTIONS: dict[str, frozenset[str]] = {
    "DART": frozenset({"risks"}),
    "SEC": frozenset({"risks"}),
}
_REGULATOR_PREFIX = {"dart": "DART", "sec": "SEC"}


def section_chunks(regulator: str, section: str, chunks: Sequence[ChunkRow]) -> list[ChunkRow]:
    """The chunks a section is written from, in chunk order.

    A chunk belongs when its own heading matches, or when it follows a matching top-level
    heading before the next top-level heading. A chunk also belongs when its stored
    ``part_title`` matches, which finds the children of a top-level part with no text of its
    own (ingest stores no chunk for that heading). A top-level ``part_title`` also ends the
    previous part, so a section stops at the next part even when that part has no chunk of
    its own. Chunks stored without ``part_title`` rely on the chunk-order rule alone.
    """
    rule = SECTION_HEADINGS[regulator][SECTION_SOURCE[section]]
    top = TOP_LEVEL_HEADING[regulator]
    picked, inside = [], False
    for chunk in sorted(chunks, key=lambda c: c.chunk_index):
        title = chunk.section_title
        part = chunk.part_title
        if top is not None and part and top.search(part):
            inside = rule.matches(part)
        if top is not None and title and top.search(title):
            inside = rule.matches(title)
        if inside or rule.matches(title) or rule.matches(part):
            picked.append(chunk)
    return picked


def annual_sections(regulator: str, chunks: Sequence[ChunkRow]) -> tuple[str, ...]:
    """The annual sections one report needs: every section, except an optional one with no
    chunk under its heading. The exporter and the summary build both call this."""
    return tuple(
        section
        for section in SUMMARY_SECTIONS["annual"]
        if section not in OPTIONAL_SECTIONS[regulator]
        or section_chunks(regulator, section, chunks)
    )


def mandatory_annual_sections(filing_id: str) -> tuple[str, ...]:
    regulator = _REGULATOR_PREFIX[filing_id.split(":", 1)[0]]
    return tuple(s for s in SUMMARY_SECTIONS["annual"] if s not in OPTIONAL_SECTIONS[regulator])


# -- summary source text and cache key -----------------------------------------------------------

# Source text sent per filing and section, in characters; longer text is cut at this point.
# Korean takes two to three times the tokens of English per character, and one request must
# fit Groq's free-tier limit of 7000 input tokens a minute (D69).
MAX_SOURCE_CHARS: dict[str, int] = {"DART": 7000, "SEC": 12000}


def event_source_text(row: EventRow) -> str | None:
    """The text an event summary is written from: the stored body, or None. A filing
    without a body is never summarised from its title alone."""
    body = row.body_text
    if body is None or not body.strip():
        return None
    limit = MAX_SOURCE_CHARS[row.regulator]
    return f"Filing title: {row.report_nm}\n\nFiling text:\n{body.strip()[:limit]}"


def annual_source_text(filing: AnnualFilingRow, section: str) -> str | None:
    picked = section_chunks(filing.regulator, section, filing.chunks)
    if not picked:
        return None
    parts = [f"Report: {filing.title}"]
    parts += [f"[{c.section_title}]\n{c.content.strip()}" for c in picked]
    return "\n\n".join(parts)[: MAX_SOURCE_CHARS[filing.regulator]]


def summary_input_sha256(
    source_text: str, model: str, section: str, prompt_version: str, lexicon_version: int
) -> str:
    """The cache key of a summary and the check the exporter makes on an approved one."""
    payload = json.dumps(
        [source_text, prompt_version, model, section, lexicon_version],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# -- input rows ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CompanyRow:
    regulator: str  # 'DART' | 'SEC'
    key: str  # DART corp_code or 10-digit SEC CIK
    name: str
    name_en: str | None
    ticker: str | None
    market: str | None


@dataclass(frozen=True)
class AnnualFilingRow:
    regulator: str
    filing_key: str  # DART 접수번호 or SEC accession number
    company_key: str
    filing_type: str  # 'business_report' | '10-K' | ...
    title: str
    period: str | None  # '2025-annual'
    filed_on: datetime.date | None
    url: str | None
    source_text_sha256: str  # SHA-256 of the stored filing chunks in chunk order
    chunks: tuple[ChunkRow, ...] = ()


@dataclass(frozen=True)
class FinancialRow:
    regulator: str
    filing_key: str
    company_key: str
    metric: str
    period: str  # '2024-annual'
    period_kind: str
    fiscal_year: int
    period_start: datetime.date | None
    period_end: datetime.date | None
    value: Decimal
    unit: str
    currency: str | None


@dataclass(frozen=True)
class EventFactRow:
    key: str
    kind: str  # M3 kind: amount | count | ratio | date | text
    unit: str | None
    source_field: str
    raw: str
    value_decimal: Decimal | None
    value_date: datetime.date | None
    value_text: str | None
    error: str | None


@dataclass(frozen=True)
class EventRow:
    regulator: str
    filing_key: str
    company_key: str
    stock_code: str | None
    report_nm: str
    filed_on: datetime.date | None
    rm: str
    url: str | None
    category: str | None
    excluded_reason: str | None
    is_correction: bool
    # Set by app.build.source.event_rows from the ingest's links and orphan grouping; the
    # exporter picks the version shown as of --as-of, never from ingest's is_latest.
    chain_key: str
    # DART: the (company, base name, subsidiary flag, first filing date) a filing is a version
    # of; a correction with the same target replaces a filing marked 정. None for SEC.
    target_key: str | None
    sec_items: str | None
    body_text: str | None
    facts: tuple[EventFactRow, ...]


@dataclass(frozen=True)
class SummaryRow:
    filing_id: str  # bundle filing id, e.g. 'dart:20260821000616'
    lang: str
    section: str
    line1: str
    line2: str | None
    line3: str | None
    review_state: str  # only 'approved' rows can ship
    input_sha256: str


@dataclass(frozen=True)
class BuildInput:
    companies: tuple[CompanyRow, ...]
    annual_filings: tuple[AnnualFilingRow, ...]
    financials: tuple[FinancialRow, ...]
    events: tuple[EventRow, ...]
    summaries: tuple[SummaryRow, ...] = ()
