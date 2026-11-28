"""Check figures and facts against pinned regulator responses, links, and finished bundles.

Pinned responses are the regulator's JSON bodies saved on disk, looked up under each pinned
directory in order:

- ``dart/fnlttSinglAcntAll/<corp_code>_<bsns_year>_11011_CFS.json`` (annual, consolidated)
- ``dart/fnlttSinglAcntAll/<corp_code>_<bsns_year>_<11013|11012|11014>_CFS.json`` (a
  quarterly or half-year report, for the quarter figures of I11)
- ``sec/companyfacts/CIK<10-digit cik>.json``
- ``dart/structured/<endpoint>_<stock_code>.json`` (event facts, M3 layout)
- ``sec/submissions/CIK<10-digit cik>.json`` (8-K facts: items and event date)
- ``dart/document/<rcept_no>.xml`` (event facts read from a filing's table, D78)

A pinned response is parsed and its row selected by the same code the ingest uses, and the
figure must equal the stored value exactly, as a ``Decimal`` and as its canonical string. Any
missing response or difference is a failure. The export and :func:`check_bundle` call the
same :func:`check_figure` and :func:`check_fact`.

    python -m app.build.verify dist/footnote.sqlite --pinned data/pinned [--release | --preview]

checks a finished file on its own contents, trusting nothing in ``build_meta`` but the
fingerprint it recomputes: every figure and fact against the pinned responses, links (N5),
canonical decimals, column types and the neutrality guard on every summary line. With
``--release`` it also refuses a development build or ``prompt_version`` ``none``, and requires
approved summaries in both languages and every section for each filing that needs them
(:data:`app.build.model.ANNUAL_SCOPE`), and refuses a preview bundle (``build_meta.preview``).
``--preview`` runs every release check except that summary coverage, and refuses a development
build.

A release also reads the faithfulness report of :mod:`app.build.faithfulness` (D97): every
summary line needs a record from the current aligner for that exact line and approval, and
``--faithfulness-policy`` decides which verdicts block. The default, ``unsupported``, blocks
unsupported lines and lines without source text unless the owner accepted them; ``partly``
also blocks partly supported lines, ``warn`` only reports the counts, ``off`` skips the check.

Every check also reads ``summary_sources`` (D101): each row belongs to a line the bundle holds,
in order and in its filing's language. A release requires a supported, partly or template
source row for every summary line the owner did not accept, and, when the report is read,
exactly the rows its current record gives.
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import functools
import json
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.build import faithfulness
from app.build.bundle import BUILD_META_COLUMNS, TABLES, content_sha256
from app.build.model import (
    DECIMAL_VALUE_KINDS,
    THREE_LINE_SECTIONS,
    canonical_decimal,
    require_canonical,
    required_summaries,
)
from app.clients.dart import DartApiError, DartClient
from app.clients.dart_events import (
    load_facts_contract,
    parse_structured_payload,
    read_event_document,
)
from app.clients.dart_tables import parse_table_facts
from app.clients.sec import (
    SecApiError,
    parse_companyfacts_payload,
    parse_quarter_facts,
    parse_submissions_payload,
)
from app.filings.categories import load_contract as load_categories_contract
from app.ingest.dart import _dart_financial_facts, dart_quarter_rows, period_descriptor
from app.ingest.sec_events import sec_facts
from app.llm.neutrality_guard import Source, check_line, check_source_url, check_summary

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PINNED_DIR = BACKEND_DIR / "data" / "pinned"
ALLOWED_HOSTS = frozenset({"dart.fss.or.kr", "www.sec.gov"})
DART_ANNUAL_REPORT_CODE = "11011"
DART_CONSOLIDATED = "CFS"
NO_PROMPT_VERSION = "none"
BASIS = "consolidated"

_DART_TITLE_PERIOD_RE = re.compile(r"\(([0-9]{4})\.([0-9]{2})\)")
_FISCAL_YEAR_LABEL_RE = re.compile(r"FY([0-9]{4})")
_ORIGIN_RE = re.compile(r"opendart:([A-Za-z]+)\.([A-Za-z0-9_]+)")
_DOCUMENT_ORIGIN_RE = re.compile(r"dartdoc:([a-z_]+)\.([a-z0-9_]+)")


class VerifyError(Exception):
    pass


@functools.cache
def _sec_fact_fields() -> frozenset[str]:
    """SEC fact origins: the ``source_field`` values of the contract's ``sec`` block."""
    return frozenset(f["source_field"] for f in load_facts_contract()["sec"]["fields"])


def link_problems(url: str | None) -> list[str]:
    """N5 from the neutrality guard, plus a parsed host check."""
    if not url:
        return ["missing source_url"]
    problems = []
    if check_source_url(url):
        problems.append(f"N5: source_url {url!r} is not DART or SEC EDGAR over https")
    try:
        parts = urlsplit(url)
        host_ok = (
            parts.scheme == "https"
            and parts.hostname in ALLOWED_HOSTS
            and parts.port is None
            and not parts.username
            and not parts.password
        )
    except ValueError:
        host_ok = False
    if not host_ok:
        problems.append(f"source_url {url!r} host is not one of {sorted(ALLOWED_HOSTS)}")
    return problems


def dart_fiscal_period(
    title: str, filing_year: int, fiscal_year: int
) -> tuple[datetime.date, datetime.date]:
    """The twelve months ending on the last day of the month a 사업보고서 title states, e.g.
    '(2025.12)', for ``fiscal_year``. The title year must be the filing's fiscal year."""
    match = _DART_TITLE_PERIOD_RE.search(title)
    if match is None or int(match.group(1)) != filing_year or not 1 <= int(match.group(2)) <= 12:
        raise VerifyError(f"title {title!r} does not state the fiscal year end of {filing_year}")
    month = int(match.group(2))

    def month_end(year: int) -> datetime.date:
        return datetime.date(year, month, calendar.monthrange(year, month)[1])

    return month_end(fiscal_year - 1) + datetime.timedelta(days=1), month_end(fiscal_year)


# Fiscal quarter -> the DART report code of the report that closes with it.
DART_QUARTER_REPORT_CODES = {1: "11013", 2: "11012", 3: "11014"}
_FISCAL_QUARTER_LABEL_RE = re.compile(r"FY([0-9]{4})-Q([1-3])")


def dart_quarter_period(
    title: str, filing_year: int, fiscal_quarter: int, fiscal_year: int
) -> tuple[datetime.date, datetime.date]:
    """The three calendar months ending on the last day of the month a 분기보고서 or
    반기보고서 title states, e.g. '(2026.09)', in ``fiscal_year`` (the filing's year or the year
    before). The title must state the filing's year and the month that closes
    ``fiscal_quarter`` of a fiscal year ending in December; anything else is refused."""
    match = _DART_TITLE_PERIOD_RE.search(title)
    if match is None or int(match.group(1)) != filing_year:
        raise VerifyError(f"title {title!r} does not state a quarter end in {filing_year}")
    month = int(match.group(2))
    if month != fiscal_quarter * 3:
        raise VerifyError(f"title {title!r} does not close fiscal quarter {fiscal_quarter}")
    end = datetime.date(fiscal_year, month, calendar.monthrange(fiscal_year, month)[1])
    return datetime.date(fiscal_year, month - 2, 1), end


@dataclass(frozen=True)
class QuarterRef:
    """One quarter figure as both the export and a finished bundle hold it (I11)."""

    company_id: str
    filing_id: str
    filing_title: str
    filing_year: int  # the quarterly report's own fiscal year
    fiscal_quarter: int  # 1 to 3
    metric: str
    fiscal_year: int  # the filing's year or the year before
    period_start: str
    period_end: str
    value: str


@dataclass(frozen=True)
class FigureCheck:
    regulator_tag: str
    pinned: str  # path relative to its pinned directory


_COMBINED_EPS_LABELS = frozenset({"기본및희석주당이익", "기본및희석주당순이익"})
_COMMON_SHARE_QUALIFIER = "보통주"


def is_combined_eps_label(account_nm: str) -> bool:
    """Whether a DART EPS row's label says it is both basic and diluted EPS (D79): one of
    the combined labels exactly once whitespace is removed, optionally after the
    common-share qualifier 보통주."""
    label = re.sub(r"\s+", "", account_nm or "")
    label = label.removeprefix(_COMMON_SHARE_QUALIFIER)
    return label in _COMBINED_EPS_LABELS


@dataclass(frozen=True)
class FigureRef:
    """One figure as both the export and a finished bundle hold it."""

    company_id: str  # 'dart:<corp_code>' | 'sec:<cik10>'
    filing_id: str  # 'dart:<rcept_no>' | 'sec:<accession>'
    filing_title: str
    filing_year: int  # the annual filing's own fiscal year
    metric: str
    fiscal_year: int
    period_start: str
    period_end: str
    value: str  # canonical decimal


class PinnedResponses:
    def __init__(self, directories: Sequence[Path]) -> None:
        self.directories = [Path(d) for d in directories]
        self._cache: dict[str, Any] = {}

    def load(self, relative: str) -> Any:
        if relative not in self._cache:
            for directory in self.directories:
                path = directory / relative
                if path.is_file():
                    # Numbers keep their text: no binary floating point on the way in.
                    self._cache[relative] = json.loads(
                        path.read_text(encoding="utf-8"), parse_float=str
                    )
                    break
            else:
                raise VerifyError(f"no pinned response {relative}")
        return self._cache[relative]

    def load_bytes(self, relative: str) -> bytes:
        for directory in self.directories:
            path = directory / relative
            if path.is_file():
                return path.read_bytes()
        raise VerifyError(f"no pinned response {relative}")

    def dart_annual(
        self,
        *,
        corp_code: str,
        rcept_no: str,
        bsns_year: int,
        metric: str,
        fiscal_year: int,
        expected: Decimal,
    ) -> FigureCheck:
        relative = (
            f"dart/fnlttSinglAcntAll/{corp_code}_{bsns_year}_"
            f"{DART_ANNUAL_REPORT_CODE}_{DART_CONSOLIDATED}.json"
        )
        try:
            items = DartClient._parse_financials_payload(self.load(relative))
        except DartApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        others = sorted({i.rcept_no for i in items if i.rcept_no != rcept_no})
        if others:
            raise VerifyError(f"{relative}: rows belong to {others}, not {rcept_no}")
        # The ingest's own row selection, so verify reads the value ingest stored.
        facts = _dart_financial_facts(
            items, period_descriptor(str(bsns_year), DART_ANNUAL_REPORT_CODE)
        )
        label = f"{fiscal_year}-annual"
        fact = next(
            (f for f in facts if f.metric.value == metric and f.period.label == label), None
        )
        if fact is None:
            raise VerifyError(f"{relative}: no {metric} {label} row")
        _require_equal(relative, metric, fact.value, expected)
        comparative = fiscal_year != bsns_year
        tag = next(
            i.account_id
            for i in items
            if i.metric == metric
            and i.thstrm_amount is not None
            and (not comparative or i.frmtrm_amount is not None)
        )
        return FigureCheck(tag, relative)

    def dart_quarter(
        self,
        *,
        corp_code: str,
        rcept_no: str,
        bsns_year: int,
        fiscal_quarter: int,
        metric: str,
        fiscal_year: int,
        expected: Decimal,
    ) -> FigureCheck:
        reprt_code = DART_QUARTER_REPORT_CODES[fiscal_quarter]
        relative = (
            f"dart/fnlttSinglAcntAll/{corp_code}_{bsns_year}_{reprt_code}_{DART_CONSOLIDATED}.json"
        )
        try:
            items = DartClient._parse_financials_payload(self.load(relative))
        except DartApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        others = sorted({i.rcept_no for i in items if i.rcept_no != rcept_no})
        if others:
            raise VerifyError(f"{relative}: rows belong to {others}, not {rcept_no}")
        try:
            rows = dart_quarter_rows(items, period_descriptor(str(bsns_year), reprt_code))
        except ValueError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        label = f"{fiscal_year}-Q{fiscal_quarter}"
        found = next(
            ((item, fact) for item, fact in rows
             if fact.metric.value == metric and fact.period.label == label),
            None,
        )  # fmt: skip
        if found is None:
            raise VerifyError(f"{relative}: no {metric} {label} row")
        item, fact = found
        _require_equal(relative, metric, fact.value, expected)
        return FigureCheck(item.account_id, relative)

    def sec_quarter(
        self,
        *,
        cik10: str,
        accession: str,
        metric: str,
        fiscal_year: int,
        period_start: datetime.date,
        period_end: datetime.date,
        expected: Decimal,
    ) -> FigureCheck:
        relative = f"sec/companyfacts/CIK{cik10}.json"
        try:
            items = parse_quarter_facts(self.load(relative), accession)
        except SecApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        item = next(
            (i for i in items if i.metric == metric and i.fiscal_year == fiscal_year), None
        )
        if item is None:
            raise VerifyError(f"{relative}: no {metric} quarter fact for {accession} {fiscal_year}")
        if (item.period_start, item.period_end) != (period_start, period_end):
            raise VerifyError(
                f"{relative}: {metric} {accession} covers "
                f"{item.period_start}..{item.period_end}, not {period_start}..{period_end}"
            )
        _require_equal(relative, metric, Decimal(item.value), expected)
        return FigureCheck(item.tag, relative)

    def dart_combined_diluted_eps(
        self, *, corp_code: str, rcept_no: str, bsns_year: int
    ) -> tuple[Decimal, FigureCheck] | None:
        """The report's own-year diluted EPS when it states none on its own but labels its
        basic EPS row as basic and diluted (D79), else ``None``. Only for checking a later
        comparative; no figure is exported from it."""
        relative = (
            f"dart/fnlttSinglAcntAll/{corp_code}_{bsns_year}_"
            f"{DART_ANNUAL_REPORT_CODE}_{DART_CONSOLIDATED}.json"
        )
        try:
            items = DartClient._parse_financials_payload(self.load(relative))
        except DartApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        others = sorted({i.rcept_no for i in items if i.rcept_no != rcept_no})
        if others:
            raise VerifyError(f"{relative}: rows belong to {others}, not {rcept_no}")
        if any(i.metric == "eps_diluted" and i.thstrm_amount is not None for i in items):
            return None
        combined = [
            i
            for i in items
            if i.metric == "eps" and i.thstrm_amount is not None
            and is_combined_eps_label(i.account_nm)
        ]  # fmt: skip
        values = {Decimal(i.thstrm_amount) for i in combined}
        if len(values) != 1:
            return None
        return values.pop(), FigureCheck(combined[0].account_id, relative)

    def sec_annual(
        self,
        *,
        cik10: str,
        accession: str,
        metric: str,
        period_start: datetime.date,
        period_end: datetime.date,
        expected: Decimal,
    ) -> FigureCheck:
        relative = f"sec/companyfacts/CIK{cik10}.json"
        try:
            # The ingest's own selection: the 10-K's own year and its prior-year comparative.
            items = parse_companyfacts_payload(self.load(relative), with_prior=True)
        except SecApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        found = [i for i in items if i.accession_number == accession and i.metric == metric]
        if not found:
            raise VerifyError(f"{relative}: no {metric} fact for {accession}")
        for item in found:
            if item.fiscal_year == period_end.year:
                if (item.period_start, item.period_end) != (period_start, period_end):
                    raise VerifyError(
                        f"{relative}: {metric} {accession} covers "
                        f"{item.period_start}..{item.period_end}, not {period_start}..{period_end}"
                    )
                _require_equal(relative, metric, Decimal(item.value), expected)
                return FigureCheck(item.tag, relative)
        raise VerifyError(
            f"{relative}: no {metric} fact for {accession} ending in {period_end.year}"
        )

    def dart_event_fact(
        self, *, endpoint: str, stock_code: str, rcept_no: str, key: str, expected: str
    ) -> str:
        relative = f"dart/structured/{endpoint}_{stock_code}.json"
        try:
            result = parse_structured_payload(endpoint, self.load(relative))
        except DartApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        for event in result.events:
            if event.rcept_no != rcept_no:
                continue
            for fact in event.facts:
                if fact.key != key or fact.error:
                    continue
                actual = _fact_text(fact)
                if actual != expected:
                    raise VerifyError(f"{relative}: {rcept_no} {key} is {actual}, not {expected}")
                return relative
        raise VerifyError(f"{relative}: no {key} for {rcept_no}")

    def dart_document_fact(self, *, table: str, rcept_no: str, key: str, expected: str) -> str:
        """Re-read a table fact from the pinned body with the ingest's own parser."""
        relative = f"dart/document/{rcept_no}.xml"
        if relative not in self._cache:
            document = read_event_document(self.load_bytes(relative))
            self._cache[relative] = {
                name: parse_table_facts(name, document.rows) for name in _document_tables()
            }
        for fact in self._cache[relative][table]:
            if fact.key != key:
                continue
            actual = _fact_text(fact)
            if actual != expected:
                raise VerifyError(f"{relative}: {key} is {actual}, not {expected}")
            return relative
        raise VerifyError(f"{relative}: no {key} in its {table} table")

    def sec_event_fact(
        self, *, cik10: str, accession: str, origin: str, key: str, expected: str
    ) -> str:
        relative = f"sec/submissions/CIK{cik10}.json"
        try:
            listed = parse_submissions_payload(self.load(relative))
        except SecApiError as exc:
            raise VerifyError(f"{relative}: {exc}") from exc
        found = [f for f in listed if f.accession_number == accession]
        if len(found) != 1:
            raise VerifyError(f"{relative}: {len(found)} rows for {accession}")
        # The ingest's own fact builder, so verify reads the value ingest stored.
        for fact in sec_facts(found[0]):
            if fact.key != key or fact.source_field != origin:
                continue
            actual = fact.value_date.isoformat() if fact.value_date else str(fact.value_text)
            if actual != expected:
                raise VerifyError(f"{relative}: {accession} {key} is {actual}, not {expected}")
            return relative
        raise VerifyError(f"{relative}: no {key} for {accession}")


def _fact_text(fact: Any) -> str:
    if fact.value_decimal is not None:
        return canonical_decimal(fact.value_decimal)
    if fact.value_date is not None:
        return fact.value_date.isoformat()
    return str(fact.value_text)


@functools.cache
def _document_tables() -> tuple[str, ...]:
    return tuple(spec["table"] for spec in load_facts_contract()["documents"])


def _require_equal(relative: str, metric: str, actual: Decimal, expected: Decimal) -> None:
    if actual != expected or canonical_decimal(actual) != canonical_decimal(expected):
        raise VerifyError(
            f"{relative}: {metric} is {canonical_decimal(actual)}, "
            f"stored {canonical_decimal(expected)}"
        )


def _split_id(value: str) -> tuple[str, str]:
    regulator, _, key = value.partition(":")
    if regulator not in ("dart", "sec") or not key:
        raise VerifyError(f"id {value!r} is not '<dart|sec>:<key>'")
    return regulator, key


def check_figure(pinned: PinnedResponses, ref: FigureRef) -> FigureCheck:
    """Re-read one figure from its pinned response; raise :class:`VerifyError` on any gap."""
    regulator, company_key = _split_id(ref.company_id)
    filing_regulator, filing_key = _split_id(ref.filing_id)
    if regulator != filing_regulator:
        raise VerifyError(f"company {ref.company_id} and filing {ref.filing_id} differ")
    try:
        expected = Decimal(require_canonical(ref.value))
    except ValueError as exc:
        raise VerifyError(str(exc)) from exc
    if ref.fiscal_year not in (ref.filing_year, ref.filing_year - 1):
        raise VerifyError(f"fiscal year {ref.fiscal_year} is not in filing year {ref.filing_year}")
    try:
        start = datetime.date.fromisoformat(ref.period_start)
        end = datetime.date.fromisoformat(ref.period_end)
    except ValueError as exc:
        raise VerifyError(f"period dates: {exc}") from exc
    if regulator == "dart":
        period = dart_fiscal_period(ref.filing_title, ref.filing_year, ref.fiscal_year)
        if period != (start, end):
            raise VerifyError(f"period {start}..{end} is not the title's {period[0]}..{period[1]}")
        return pinned.dart_annual(
            corp_code=company_key,
            rcept_no=filing_key,
            bsns_year=ref.filing_year,
            metric=ref.metric,
            fiscal_year=ref.fiscal_year,
            expected=expected,
        )
    if end.year != ref.fiscal_year:
        raise VerifyError(f"period end {end} is not in fiscal year {ref.fiscal_year}")
    return pinned.sec_annual(
        cik10=company_key,
        accession=filing_key,
        metric=ref.metric,
        period_start=start,
        period_end=end,
        expected=expected,
    )


def check_quarter_figure(pinned: PinnedResponses, ref: QuarterRef) -> FigureCheck:
    """Re-read one quarter figure (I11) from its pinned response; raise
    :class:`VerifyError` on any gap."""
    regulator, company_key = _split_id(ref.company_id)
    filing_regulator, filing_key = _split_id(ref.filing_id)
    if regulator != filing_regulator:
        raise VerifyError(f"company {ref.company_id} and filing {ref.filing_id} differ")
    try:
        expected = Decimal(require_canonical(ref.value))
    except ValueError as exc:
        raise VerifyError(str(exc)) from exc
    if ref.fiscal_quarter not in DART_QUARTER_REPORT_CODES:
        raise VerifyError(f"fiscal quarter {ref.fiscal_quarter} is not 1 to 3")
    if ref.fiscal_year not in (ref.filing_year, ref.filing_year - 1):
        raise VerifyError(f"fiscal year {ref.fiscal_year} is not in filing year {ref.filing_year}")
    try:
        start = datetime.date.fromisoformat(ref.period_start)
        end = datetime.date.fromisoformat(ref.period_end)
    except ValueError as exc:
        raise VerifyError(f"period dates: {exc}") from exc
    if regulator == "dart":
        period = dart_quarter_period(
            ref.filing_title, ref.filing_year, ref.fiscal_quarter, ref.fiscal_year
        )
        if period != (start, end):
            raise VerifyError(f"period {start}..{end} is not the title's {period[0]}..{period[1]}")
        return pinned.dart_quarter(
            corp_code=company_key,
            rcept_no=filing_key,
            bsns_year=ref.filing_year,
            fiscal_quarter=ref.fiscal_quarter,
            metric=ref.metric,
            fiscal_year=ref.fiscal_year,
            expected=expected,
        )
    return pinned.sec_quarter(
        cik10=company_key,
        accession=filing_key,
        metric=ref.metric,
        fiscal_year=ref.fiscal_year,
        period_start=start,
        period_end=end,
        expected=expected,
    )


def check_fact(
    pinned: PinnedResponses,
    *,
    filing_id: str,
    company_id: str,
    stock_code: str | None,
    origin: str,
    fact_key: str,
    value_text: str,
) -> str:
    """Re-read one event fact from its pinned response; return the response's path.

    A DART fact is found by endpoint, stock code and 접수번호, or, for a table fact
    (``dartdoc:<table>.<key>``), by 접수번호 in the pinned document; a SEC fact by CIK (from
    ``company_id``) and accession.
    """
    regulator, rcept_no = _split_id(filing_id)
    if regulator == "sec":
        if origin not in _sec_fact_fields():
            raise VerifyError(f"origin {origin!r} is not a SEC submissions field")
        company_regulator, cik10 = _split_id(company_id)
        if company_regulator != "sec":
            raise VerifyError(f"SEC filing {filing_id} on non-SEC company {company_id}")
        return pinned.sec_event_fact(
            cik10=cik10, accession=rcept_no, origin=origin, key=fact_key, expected=value_text
        )
    document = _DOCUMENT_ORIGIN_RE.fullmatch(origin)
    if regulator == "dart" and document is not None:
        if document.group(1) not in _document_tables():
            raise VerifyError(f"origin {origin!r} names no filing-facts document table")
        return pinned.dart_document_fact(
            table=document.group(1), rcept_no=rcept_no, key=fact_key, expected=value_text
        )
    match = _ORIGIN_RE.fullmatch(origin)
    if regulator != "dart" or match is None:
        raise VerifyError(f"origin {origin!r} is not an OpenDART structured field")
    if not stock_code:
        raise VerifyError(f"no stock code to find the pinned {match.group(1)} response")
    return pinned.dart_event_fact(
        endpoint=match.group(1),
        stock_code=stock_code,
        rcept_no=rcept_no,
        key=fact_key,
        expected=value_text,
    )


def summary_problems(
    filing_id: str,
    lang: str,
    section: str,
    lines: Sequence[str | None],
    company_names: Sequence[str],
    source: Source | None = None,
) -> list[str]:
    """Neutrality guard on one summary row: a three-line section as one summary, any other
    section line by line. ``source`` opens the D111 allowances (labels, report endings)."""
    present = [line for line in lines if line is not None]
    if section in THREE_LINE_SECTIONS:
        violations = check_summary(present, lang, company_names,  # type: ignore[arg-type]
                                   source=source)  # fmt: skip
    else:
        violations = [
            v
            for number, line in enumerate(present, start=1)
            for v in check_line(line, lang, number, company_names,  # type: ignore[arg-type]
                                source=source)  # fmt: skip
        ]
    return [
        f"{filing_id} summary {lang}/{section}: {v.rule_id} on line {v.line_no} {v.token!r}"
        for v in violations
    ]


# -- finished file -------------------------------------------------------------------------------


def _select(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns, key = TABLES[table]
    query = f"SELECT {', '.join(columns)} FROM {table} ORDER BY {', '.join(key)}"
    return [dict(zip(columns, row, strict=True)) for row in connection.execute(query)]


def check_bundle(
    path: Path,
    *,
    release: bool,
    pinned_dirs: Sequence[Path],
    preview: bool = False,
    faithfulness_gate: faithfulness.ReleaseGate | None = None,
) -> list[str]:
    """Problems with a finished bundle; an empty list means it passes. With ``release`` and a
    ``faithfulness_gate``, every summary line is also held to that gate (D97)."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta_rows = connection.execute(
            f"SELECT {', '.join(BUILD_META_COLUMNS)} FROM build_meta"
        ).fetchall()
        if len(meta_rows) != 1:
            return [f"build_meta has {len(meta_rows)} rows"]
        meta = dict(zip(BUILD_META_COLUMNS, meta_rows[0], strict=True))
        problems = []
        if content_sha256(connection, meta["aligner_version"]) != meta["content_sha256"]:
            problems.append("content_sha256 does not match the file's contents")
        for table, column, declared in _declared_types(connection):
            if declared.upper() not in ("TEXT", "INTEGER"):
                problems.append(f"{table}.{column} is declared {declared}")
        companies = {row["id"]: row for row in _select(connection, "companies")}
        filings = {row["id"]: row for row in _select(connection, "filings")}
        notices = _select(connection, "notices")
        figures = _select(connection, "figures")
        quarter_figures = _select(connection, "quarter_figures")
        facts = _select(connection, "filing_facts")
        summaries = _select(connection, "filing_summaries")
        sources = _select(connection, "summary_sources")
    finally:
        connection.close()

    if (release or preview) and meta["allow_unapproved"] != 0:
        problems.append(
            f"built with --allow-unapproved; a {'release' if release else 'preview'} refuses it"
        )
    if release and meta["preview"] != 0:
        problems.append("a preview bundle; a release refuses it")
    if (release or preview) and meta["prompt_version"] == NO_PROMPT_VERSION:
        problems.append(f"prompt_version is {NO_PROMPT_VERSION!r}; a release refuses it")
    for filing in filings.values():
        problems.extend(f"{filing['id']}: {p}" for p in link_problems(filing["source_url"]))
    problems += _notice_problems(notices, filings)

    pinned = PinnedResponses(pinned_dirs)
    problems += _figure_problems(pinned, figures, filings)
    problems += _quarter_problems(pinned, quarter_figures, filings)
    problems += _fact_problems(pinned, facts, filings, companies)

    # The bundle holds no source text, only each line's cited excerpts: a D111 label passes
    # here only when the title or an excerpt of the same filing and section holds it.
    excerpts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in sources:
        if row["excerpt"]:
            excerpts[(row["filing_id"], row["section"])].append(row["excerpt"])
    for summary in summaries:
        filing = filings.get(summary["filing_id"])
        company = companies.get(filing["company_id"]) if filing else None
        names = [company["name_ko"], company["name_en"]] if company else []
        cited = None
        if filing:
            texts = excerpts[(summary["filing_id"], summary["section"])]
            cited = Source(filing["title_original"],
                           "\n".join([filing["title_original"], *texts]))  # fmt: skip
        problems += summary_problems(
            summary["filing_id"], summary["lang"], summary["section"],
            (summary["line1"], summary["line2"], summary["line3"]), names, cited,
        )  # fmt: skip
    if release:
        present = {(s["filing_id"], s["lang"], s["section"]) for s in summaries}
        required = required_summaries(
            (f["id"], f["company_id"], f["kind"], f["period_label"], f["filed_on"])
            for f in filings.values()
        )
        for filing_id, pairs in sorted(required.items()):
            missing = [f"{lang}/{section}" for lang, section in pairs
                       if (filing_id, lang, section) not in present]  # fmt: skip
            if missing:
                problems.append(f"{filing_id}: no approved summary {', '.join(missing)}")
        if faithfulness_gate is not None:
            problems += faithfulness_gate.problems(summaries)
    if meta["aligner_version"] != faithfulness.ALIGNER_VERSION:
        problems.append(f"aligner_version {meta['aligner_version']!r} is not "
                        f"{faithfulness.ALIGNER_VERSION!r}")  # fmt: skip
    gate = faithfulness_gate
    index = gate.index if gate is not None else None
    # The rows are compared with the report only when the gate reads it and its verdicts block.
    compare = gate is not None and gate.policy in ("unsupported", "partly") and gate.missing is None
    regulators = {
        fid: companies[f["company_id"]]["regulator"]
        for fid, f in filings.items() if f["company_id"] in companies
    }  # fmt: skip
    problems += faithfulness.bundle_source_problems(
        summaries, sources, regulators, release=release, index=index, compare=compare
    )
    return problems


def _notice_problems(
    notices: list[dict[str, Any]], filings: dict[str, dict[str, Any]]
) -> list[str]:
    """Notices (D76) carry a notice category and a link, and are never also a filing row."""
    contract = load_categories_contract()
    notice_keys = {c["key"] for c in contract["notice_categories"]}
    problems = []
    for notice in notices:
        nid = notice["id"]
        if notice["category"] not in notice_keys:
            problems.append(f"{nid}: {notice['category']!r} is not a notice category")
        if nid in filings:
            problems.append(f"{nid}: exported both as a filing and as a notice")
        problems.extend(f"{nid}: {p}" for p in link_problems(notice["source_url"]))
    for filing in filings.values():
        if filing["kind"] == "event" and filing["category"] in notice_keys:
            problems.append(f"{filing['id']}: notice category {filing['category']!r} as an event")
    return problems


def _figure_problems(
    pinned: PinnedResponses, figures: list[dict[str, Any]], filings: dict[str, dict[str, Any]]
) -> list[str]:
    problems = []
    for figure in figures:
        fid = figure["id"]
        expected_id = "|".join(
            (figure["company_id"], figure["metric"], figure["period_end"], figure["basis"])
        )
        if fid != expected_id or figure["basis"] != BASIS:
            problems.append(f"{fid}: id or basis does not match its columns")
        filing = filings.get(figure["filing_id"])
        label = _FISCAL_YEAR_LABEL_RE.fullmatch((filing or {}).get("period_label") or "")
        if filing is None or filing["kind"] != "annual" or label is None:
            problems.append(f"{fid}: source {figure['filing_id']} is not an exported annual filing")
            continue
        if filing["company_id"] != figure["company_id"]:
            problems.append(f"{fid}: source filing belongs to {filing['company_id']}")
            continue
        try:
            check = check_figure(
                pinned,
                FigureRef(
                    company_id=figure["company_id"],
                    filing_id=figure["filing_id"],
                    filing_title=filing["title_original"],
                    filing_year=int(label.group(1)),
                    metric=figure["metric"],
                    fiscal_year=figure["fiscal_year"],
                    period_start=figure["period_start"],
                    period_end=figure["period_end"],
                    value=figure["value"],
                ),
            )
        except VerifyError as exc:
            problems.append(f"{fid}: {exc}")
            continue
        if check.regulator_tag != figure["regulator_tag"]:
            problems.append(
                f"{fid}: regulator_tag {figure['regulator_tag']!r}, pinned {check.regulator_tag!r}"
            )
    return problems


def _quarter_problems(
    pinned: PinnedResponses, figures: list[dict[str, Any]], filings: dict[str, dict[str, Any]]
) -> list[str]:
    """Each quarter figure (I11) comes from an exported quarterly filing of its company, is
    that filing's quarter or the same quarter a year earlier, and matches its pinned value."""
    problems = []
    for figure in figures:
        fid = figure["id"]
        expected_id = "|".join(
            (figure["company_id"], figure["metric"], figure["period_end"], figure["basis"])
        )
        if fid != expected_id or figure["basis"] != BASIS:
            problems.append(f"{fid}: id or basis does not match its columns")
        filing = filings.get(figure["filing_id"])
        label = _FISCAL_QUARTER_LABEL_RE.fullmatch((filing or {}).get("period_label") or "")
        if filing is None or filing["kind"] != "quarterly" or label is None:
            problems.append(f"{fid}: source {figure['filing_id']} is not a quarterly filing")
            continue
        if filing["company_id"] != figure["company_id"]:
            problems.append(f"{fid}: source filing belongs to {filing['company_id']}")
            continue
        if int(label.group(2)) != figure["fiscal_quarter"]:
            problems.append(f"{fid}: fiscal quarter is not the filing's {label.group(0)}")
            continue
        try:
            check = check_quarter_figure(
                pinned,
                QuarterRef(
                    company_id=figure["company_id"],
                    filing_id=figure["filing_id"],
                    filing_title=filing["title_original"],
                    filing_year=int(label.group(1)),
                    fiscal_quarter=figure["fiscal_quarter"],
                    metric=figure["metric"],
                    fiscal_year=figure["fiscal_year"],
                    period_start=figure["period_start"],
                    period_end=figure["period_end"],
                    value=figure["value"],
                ),
            )
        except VerifyError as exc:
            problems.append(f"{fid}: {exc}")
            continue
        if check.regulator_tag != figure["regulator_tag"]:
            problems.append(
                f"{fid}: regulator_tag {figure['regulator_tag']!r}, pinned {check.regulator_tag!r}"
            )
    return problems


def _fact_problems(
    pinned: PinnedResponses,
    facts: list[dict[str, Any]],
    filings: dict[str, dict[str, Any]],
    companies: dict[str, dict[str, Any]],
) -> list[str]:
    problems = []
    for fact in facts:
        label = f"{fact['filing_id']}#{fact['position']} {fact['fact_key']}"
        if fact["value_kind"] in DECIMAL_VALUE_KINDS:
            try:
                require_canonical(fact["value_text"])
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
                continue
        filing = filings.get(fact["filing_id"])
        if filing is None or filing["kind"] != "event":
            problems.append(f"{label}: not on an exported event filing")
            continue
        company = companies.get(filing["company_id"]) or {}
        try:
            check_fact(
                pinned,
                filing_id=fact["filing_id"],
                company_id=filing["company_id"],
                stock_code=company.get("ticker"),
                origin=fact["origin"],
                fact_key=fact["fact_key"],
                value_text=fact["value_text"],
            )
        except VerifyError as exc:
            problems.append(f"{label}: {exc}")
    return problems


def _declared_types(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    tables = [
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    return [
        (table, info[1], info[2])
        for table in tables
        for info in connection.execute(f"PRAGMA table_info({table})")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.build.verify")
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--pinned",
        type=Path,
        action="append",
        help=f"directory of pinned regulator responses, repeatable (default {DEFAULT_PINNED_DIR})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--release", action="store_true", help="refuse a development or preview build"
    )
    mode.add_argument(
        "--preview",
        action="store_true",
        help="every release check except summary coverage; refuse a development build",
    )
    parser.add_argument(
        "--faithfulness",
        type=Path,
        default=faithfulness.REPORT_PATH,
        help="faithfulness report read by --release (default: data/summaries/faithfulness.jsonl)",
    )
    parser.add_argument(
        "--faithfulness-policy",
        choices=sorted(faithfulness.POLICIES),
        default=faithfulness.DEFAULT_POLICY,
        help=f"verdicts that block a release (default {faithfulness.DEFAULT_POLICY}, D97)",
    )
    args = parser.parse_args(argv)
    gate = None
    if args.release:
        gate = faithfulness.load_gate(args.faithfulness_policy, args.faithfulness)
    problems = check_bundle(
        args.bundle,
        release=args.release,
        preview=args.preview,
        pinned_dirs=args.pinned or [DEFAULT_PINNED_DIR],
        faithfulness_gate=gate,
    )
    for note in gate.notes if gate else ():
        print(note)
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"OK {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
