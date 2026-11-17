"""Rows the exporter reads from the build database, the canonical decimal form, and scope rules.

The rows are regulator-neutral so the exporter never sees a PostgreSQL row or ORM object.
Every amount is a ``Decimal``; the bundle stores it as a canonical decimal string.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable
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

LANGS = ("ko", "en")
SUMMARY_SECTIONS = {"event": ("summary",), "annual": ("one_line", "business", "changes", "risks")}
# Sections written as three lines, checked as one summary by the neutrality guard.
THREE_LINE_SECTIONS = frozenset({"summary"})


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
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Filing id -> the ``(lang, section)`` pairs that must be approved, from
    ``(filing_id, company_id, kind, period_label, filed_on)`` rows; see :data:`ANNUAL_SCOPE`."""
    rows = list(filings)
    latest = latest_annual_ids((f, c, p, d) for f, c, k, p, d in rows if k == "annual")
    required = {}
    for filing_id, _, kind, _, _ in rows:
        if kind == "event" or filing_id in latest:
            required[filing_id] = tuple(
                (lang, section) for lang in LANGS for section in SUMMARY_SECTIONS[kind]
            )
    return required


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
