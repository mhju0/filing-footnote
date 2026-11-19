"""DART adapter for the source-independent Normalized Filing seam.

External fetches and DART parsing complete before this module builds a
:class:`app.filings.model.NormalizedFiling`. The shared ingestion module owns
persistence and filing-scoped indexing after this adapter returns.

The :class:`DartFilingAdapter` interface returns a complete snapshot; database
row construction belongs solely to :mod:`app.filings.persistence`.
"""

import logging
from dataclasses import dataclass
from xml.etree.ElementTree import ParseError

import httpx

from app.clients.dart import (
    DartApiError,
    DartClient,
    FilingItem,
    FinancialItem,
    decode_dart_bytes,
    detect_document_format,
    extract_dsd_prose,
)
from app.filings.model import (
    CompanyIdentity,
    FilingChunkLocation,
    FilingIdentity,
    NormalizedFiling,
    RegulatedCompany,
    RegulatorySource,
)
from app.filings.model import (
    FilingChunk as NormalizedChunk,
)
from app.financials.model import FinancialFact, ReportingPeriod
from app.financials.vocabulary import PeriodKind, ReportedMetric
from app.ingest.chunking import Chunk, chunk_document
from app.ingest.pinned import PinnedStore, dart_annual_path

logger = logging.getLogger(__name__)

# -- DART financial vocabulary -----------------------------------------------

# Default currency for KRW-denominated DART numbers when a row omits `currency`
# (domestic filings report in won).
DEFAULT_CURRENCY = "KRW"

# financials.unit vocabulary. DART amounts are ABSOLUTE KRW (원) with no scaling
# (docs §3); EPS rows are per-share KRW (원/주). unit distinguishes the two so a
# reader never mistakes an EPS for an absolute amount.
UNIT_KRW = "KRW"  # absolute won (revenue, operating_income, net_income, ...)
UNIT_KRW_PER_SHARE = "KRW_PER_SHARE"  # won per share (eps, eps_diluted)

# Per-share metrics -> UNIT_KRW_PER_SHARE; everything else -> UNIT_KRW.
_EPS_METRICS = frozenset(
    {ReportedMetric.eps.value, ReportedMetric.eps_diluted.value}
)

# reprt_code (docs §3) -> (period suffix, fiscal_quarter, filing_type). The
# `period` string is the canonical, re-run-stable identity used by the financials
# UNIQUE constraint: `f"{fiscal_year}-{suffix}"` (e.g. "2023-annual", "2023-Q1").
# fiscal_quarter marks the as-of quarter (annual = None; 반기 = 2 i.e. end of H1).
_REPORT_CODES: dict[str, tuple[str, int | None, str]] = {
    "11011": ("annual", None, "business_report"),  # 사업보고서 (full year)
    "11012": ("H1", 2, "half_year_report"),  # 반기보고서 (H1, as-of Q2)
    "11013": ("Q1", 1, "quarterly_report"),  # 1분기보고서
    "11014": ("Q3", 3, "quarterly_report"),  # 3분기보고서
}

# corp_cls (법인구분, docs §2) -> human market label for companies.market.
_CORP_CLS_TO_MARKET: dict[str, str] = {
    "Y": "KOSPI",  # 유가증권시장
    "K": "KOSDAQ",
    "N": "KONEX",
    "E": "ETC",  # 기타법인
}


@dataclass(frozen=True)
class PeriodDescriptor:
    """The canonical (period, fiscal_year, fiscal_quarter) for one report.

    Derived purely from (``bsns_year``, ``reprt_code``); identical across re-runs,
    which is what makes the financials upsert idempotent.
    """

    period: str
    fiscal_year: int
    fiscal_quarter: int | None


# -- pure vocabulary helpers --------------------------------------------------


def period_descriptor(bsns_year: str, reprt_code: str) -> PeriodDescriptor:
    """Map (business year, report code) -> canonical :class:`PeriodDescriptor`.

    Raises ``ValueError`` for an unknown ``reprt_code`` or unparseable
    ``bsns_year`` -- we never guess a period, because a wrong/unstable period
    string would break the idempotent financials UNIQUE. Pure -> unit-tested.
    """
    entry = _REPORT_CODES.get((reprt_code or "").strip())
    if entry is None:
        raise ValueError(f"unknown DART reprt_code {reprt_code!r}; refusing to guess a period")
    suffix, quarter, _filing_type = entry
    try:
        year = int(str(bsns_year).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid bsns_year {bsns_year!r}") from exc
    return PeriodDescriptor(period=f"{year}-{suffix}", fiscal_year=year, fiscal_quarter=quarter)


def filing_type_for(reprt_code: str) -> str:
    """Map a report code to the stable ``filings.filing_type`` label (NOT NULL).

    Raises ``ValueError`` for an unknown code (same no-guessing rule as
    :func:`period_descriptor`). Pure -> unit-tested.
    """
    entry = _REPORT_CODES.get((reprt_code or "").strip())
    if entry is None:
        raise ValueError(f"unknown DART reprt_code {reprt_code!r}")
    return entry[2]


def market_for(corp_cls: str | None) -> str | None:
    """Map a DART ``corp_cls`` to a market label, or ``None`` if unknown/blank."""
    return _CORP_CLS_TO_MARKET.get((corp_cls or "").strip().upper())


def unit_for(metric: str) -> str:
    """Return the ``financials.unit`` for a metric (per-share vs absolute KRW)."""
    return UNIT_KRW_PER_SHARE if metric in _EPS_METRICS else UNIT_KRW


# The period a quarterly or half-year report's statements end with, as its thstrm_nm states it
# ("제 59 기 3분기"). A company whose fiscal year does not end in December names another
# period for the same report code, so a mismatch is refused rather than guessed.
_QUARTER_PERIOD_NAMES: dict[int, str] = {1: "1분기", 2: "반기", 3: "3분기"}
# Income-statement rows. A cash-flow row of the same report states the year to date in
# thstrm_amount, so it is never read as the quarter.
_QUARTER_SJ_DIVS = frozenset({"IS", "CIS"})


def quarter_label(fiscal_year: int, fiscal_quarter: int) -> str:
    """The Reporting Period label of one fiscal quarter's three months: ``2026-Q3``."""
    return f"{fiscal_year}-Q{fiscal_quarter}"


def dart_quarter_facts(
    items: list[FinancialItem], descriptor: PeriodDescriptor
) -> tuple[FinancialFact, ...]:
    """The quarter's three months and the same three months a year earlier, from the
    income-statement rows of a quarterly or half-year report (I11).

    ``thstrm_amount`` is the quarter and ``frmtrm_q_amount`` the same quarter a year earlier.
    After the first quarter a row must also state the year to date (``thstrm_add_amount``),
    or it does not show which of the two ``thstrm_amount`` is, and the row is left out.
    Raises ``ValueError`` when a row names a period other than the report code's.
    """
    quarter = descriptor.fiscal_quarter
    if quarter is None:
        raise ValueError(f"{descriptor.period} is not a quarterly period")
    expected = _QUARTER_PERIOD_NAMES[quarter]
    current_period = ReportingPeriod(
        quarter_label(descriptor.fiscal_year, quarter), PeriodKind.duration
    )
    prior_period = ReportingPeriod(
        quarter_label(descriptor.fiscal_year - 1, quarter), PeriodKind.duration
    )
    facts: list[FinancialFact] = []
    seen: set[tuple[ReportedMetric, str]] = set()
    for item in items:
        if item.metric is None or item.sj_div not in _QUARTER_SJ_DIVS:
            continue
        if not item.thstrm_nm.replace(" ", "").endswith(expected):
            raise ValueError(
                f"{item.rcept_no}: thstrm_nm {item.thstrm_nm!r} is not the {expected} period "
                f"of reprt_code for {descriptor.period}"
            )
        if quarter > 1 and item.thstrm_add_amount is None:
            continue
        metric = ReportedMetric(item.metric)
        for period, value in ((current_period, item.thstrm_amount),
                              (prior_period, item.frmtrm_q_amount)):  # fmt: skip
            if value is None or (metric, period.label) in seen:
                continue
            seen.add((metric, period.label))
            facts.append(
                FinancialFact(
                    metric=metric,
                    period=period,
                    value=value,
                    unit=unit_for(metric.value),
                    currency=item.currency or DEFAULT_CURRENCY,
                )
            )
    return tuple(facts)


def _dart_financial_facts(
    items: list[FinancialItem], descriptor: PeriodDescriptor
) -> tuple[FinancialFact, ...]:
    """Translate DART taxonomy rows into canonical reported Financial Facts."""
    if descriptor.fiscal_quarter is not None:
        return dart_quarter_facts(items, descriptor)
    current_period = ReportingPeriod(descriptor.period, PeriodKind.duration)
    prior_period = ReportingPeriod(f"{descriptor.fiscal_year - 1}-annual", PeriodKind.duration)
    facts: list[FinancialFact] = []
    seen_current: set[ReportedMetric] = set()
    seen_prior: set[ReportedMetric] = set()
    for item in items:
        if item.metric is None or item.thstrm_amount is None:
            continue
        metric = ReportedMetric(item.metric)
        if metric not in seen_current:
            seen_current.add(metric)
            facts.append(
                FinancialFact(
                    metric=metric,
                    period=current_period,
                    value=item.thstrm_amount,
                    unit=unit_for(metric.value),
                    currency=item.currency or DEFAULT_CURRENCY,
                )
            )
        if (
            descriptor.fiscal_quarter is None
            and item.frmtrm_amount is not None
            and metric not in seen_prior
        ):
            seen_prior.add(metric)
            facts.append(
                FinancialFact(
                    metric=metric,
                    period=prior_period,
                    value=item.frmtrm_amount,
                    unit=unit_for(metric.value),
                    currency=item.currency or DEFAULT_CURRENCY,
                )
            )
    return tuple(facts)


def build_dart_normalized_filing(
    *,
    filing_item: FilingItem,
    corp_code: str,
    name_en: str | None,
    descriptor: PeriodDescriptor,
    filing_type: str,
    financial_items: list[FinancialItem],
    chunks: list[Chunk],
) -> NormalizedFiling:
    """Adapt one fetched DART filing to the public Normalized Filing seam."""
    return NormalizedFiling(
        company=RegulatedCompany(
            identity=CompanyIdentity(RegulatorySource.dart, corp_code),
            name=filing_item.corp_name,
            name_en=name_en,
            ticker=filing_item.stock_code or None,
            market=market_for(filing_item.corp_cls),
        ),
        identity=FilingIdentity(RegulatorySource.dart, filing_item.rcept_no),
        filing_type=filing_type,
        title=filing_item.report_nm,
        reporting_period=ReportingPeriod(descriptor.period, PeriodKind.duration),
        financial_facts=_dart_financial_facts(financial_items, descriptor),
        filing_chunks=tuple(
            NormalizedChunk(
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                location=FilingChunkLocation(
                    section_title=chunk.section_title,
                    section_order=chunk.section_order,
                    part_index=chunk.part_index,
                    part_title=chunk.part_title,
                ),
            )
            for chunk in chunks
        ),
        filed_at=filing_item.rcept_dt,
        url=filing_item.viewer_url,
    )


async def _fetch_company_eng_name(dart_client: DartClient, corp_code: str) -> str | None:
    """Best-effort English-name enrichment; never fails the ingest.

    ``name_en`` is enrichment for bilingual search, not the critical path (numbers
    and prose are), so a company.json failure -- bad key, rate limit, network --
    logs and yields ``None`` rather than aborting the filing ingest.
    """
    try:
        return await dart_client.fetch_company_eng_name(corp_code)
    except (DartApiError, httpx.HTTPError) as exc:
        logger.warning(
            "company.json enrichment failed for corp_code=%s: %s; name_en stays NULL",
            corp_code,
            exc,
        )
        return None


@dataclass(frozen=True)
class DartFilingAdapter:
    """Fetch and normalize one already-selected DART Corporate Filing."""

    client: DartClient
    corp_code: str
    filing_item: FilingItem
    bsns_year: str
    reprt_code: str
    fs_div: str = "CFS"
    pinned: PinnedStore | None = None
    # A prior annual report (``--prior``) is only a figures source and is never
    # summarised, so a document whose text cannot be parsed keeps zero chunks.
    figures_only: bool = False
    # A quarterly or half-year report (``--quarter``) is only a figures source for the
    # quarter report screen (I11): its document is not fetched and it has no chunks.
    without_document: bool = False

    async def fetch(self) -> NormalizedFiling:
        """Return a complete snapshot without opening a database session."""
        save: dict = {}
        if self.pinned is not None:
            relative = dart_annual_path(
                self.corp_code, self.bsns_year, self.reprt_code, self.fs_div
            )
            save["on_body"] = self.pinned.sink(relative)
        financial_items = await self.client.fetch_financials(
            self.corp_code, self.bsns_year, self.reprt_code, self.fs_div, **save
        )
        name_en = await _fetch_company_eng_name(self.client, self.corp_code)
        chunks: list[Chunk] = []
        if self.without_document:
            document_format = "not fetched"
        else:
            document_format = await self._document_chunks(chunks)

        normalized = build_dart_normalized_filing(
            filing_item=self.filing_item,
            corp_code=self.corp_code,
            name_en=name_en,
            descriptor=period_descriptor(self.bsns_year, self.reprt_code),
            filing_type=filing_type_for(self.reprt_code),
            financial_items=financial_items,
            chunks=chunks,
        )
        logger.info(
            "normalized DART filing=%s financials=%d chunks=%d format=%s",
            self.filing_item.rcept_no,
            len(normalized.financial_facts),
            len(normalized.filing_chunks),
            document_format,
        )
        return normalized

    async def _document_chunks(self, chunks: list[Chunk]) -> str:
        """Fetch the filing's document and append its chunks; return its format."""
        document = await self.client.fetch_document(self.filing_item.rcept_no)
        text = decode_dart_bytes(document.content)
        document_format = detect_document_format(text)
        if document_format == "dsd":
            try:
                chunks.extend(chunk_document(extract_dsd_prose(text)))
            except ParseError as exc:
                if not self.figures_only:
                    raise
                logger.warning(
                    "DART filing %s text is not parseable (%s); figures only, zero chunks",
                    self.filing_item.rcept_no,
                    exc,
                )
        else:
            logger.warning(
                "DART filing %s format=%s is not parseable; using zero chunks",
                self.filing_item.rcept_no,
                document_format,
            )
        return document_format
