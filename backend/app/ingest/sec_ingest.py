"""SEC adapter for the source-independent Normalized Filing seam.

The SEC adapter fetches and parses everything before building one complete
:class:`app.filings.model.NormalizedFiling`. The shared ingestion module owns
persistence and filing-scoped indexing after this adapter returns.

Design (mirrors the DART adapter; the differences are all SEC-specific):

1. **Numbers come only from companyfacts.** ``fetch_company_facts`` is the single
   source of figures (never the LLM/document); the facts are filtered to the
   chosen accession's *own-period* rows and its prior-year comparatives before
   they become ``financials`` rows.

2. **USD units, not KRW.** SEC facts use their own unit vocabulary while the
   adapter translates ``SecFinancialItem.value`` directly into canonical
   :class:`~app.financials.model.FinancialFact` objects.

3. **Filing identity stays filing-owned.** SEC provenance resolves through the
   Corporate Filing's accession while Filing Chunks carry only their
   within-filing locations.

The :class:`SecFilingAdapter` interface returns a complete snapshot; database
row construction belongs solely to :mod:`app.filings.persistence`.
"""

import datetime
import logging
from dataclasses import dataclass

from app.clients.sec import (
    QUARTERLY_FORM,
    SecClient,
    SecCompanyMatch,
    SecFilingItem,
    SecFinancialItem,
    _archive_url,
    format_cik,
)
from app.clients.sec_document import extract_10k_prose
from app.filings.model import (
    CompanyIdentity,
    FilingChunk,
    FilingChunkLocation,
    FilingIdentity,
    NormalizedFiling,
    RegulatedCompany,
    RegulatorySource,
)
from app.financials.model import FinancialFact, ReportingPeriod
from app.financials.vocabulary import PeriodKind, ReportedMetric
from app.ingest.chunking import Chunk, chunk_document
from app.ingest.pinned import PinnedStore, sec_companyfacts_path

logger = logging.getLogger(__name__)

# The one SEC form this step ingests (annual report). Mirrors the DART report
# codes: only 10-K is in scope; 10-Q and others are a future extension.
_FORM_10K = "10-K"

# SEC financials.unit / currency vocabulary. Parallels the DART UNIT_KRW /
# UNIT_KRW_PER_SHARE split (the `unit` column distinguishes absolute vs per-share
# so a reader never mistakes an EPS for an absolute amount); `currency` carries
# the ISO code.
UNIT_USD = "USD"  # absolute USD (revenue, operating_income, net_income)
UNIT_USD_PER_SHARE = "USD_PER_SHARE"  # USD per share (eps, eps_diluted)
CURRENCY_USD = "USD"

# Per-share metrics -> UNIT_USD_PER_SHARE; everything else -> UNIT_USD.
_EPS_METRICS = frozenset(
    {ReportedMetric.eps.value, ReportedMetric.eps_diluted.value}
)


class SecIngestError(RuntimeError):
    """Raised when a SEC 10-K cannot be selected/resolved for ingest.

    Distinct from ``SecApiError`` (malformed API response) and
    ``SecDocumentParseError`` (prose extraction failed): this is an
    orchestration-level "no filing to ingest" / "cannot derive a required field"
    signal. Fail-loud -- we never silently ingest a different or partial filing.
    """


# -- pure vocabulary helpers --------------------------------------------------


def sec_period(fiscal_year: int) -> str:
    """Canonical annual ``period`` string for a 10-K (mirrors DART's "<year>-annual").

    A 10-K is always a full-year report, so the period is ``f"{fiscal_year}-annual"``
    -- byte-identical across re-runs, which is what keeps the financials upsert
    idempotent (its UNIQUE includes ``period``). Pure.
    """
    return f"{fiscal_year}-annual"


def sec_unit_for(metric: str) -> str:
    """Return the ``financials.unit`` for a SEC metric (per-share vs absolute USD).

    EPS metrics ->
    ``UNIT_USD_PER_SHARE``, everything else -> ``UNIT_USD``. Pure.
    """
    return UNIT_USD_PER_SHARE if metric in _EPS_METRICS else UNIT_USD


def build_sec_normalized_filing(
    *,
    company_match: SecCompanyMatch | None,
    cik10: str,
    filing: SecFilingItem,
    fiscal_year: int,
    document_url: str,
    financial_items: list[SecFinancialItem],
    chunks: list[Chunk],
) -> NormalizedFiling:
    """Adapt one fetched SEC filing to the public Normalized Filing seam.

    One fact per metric and fiscal year: the filing's own year and, when the items carry
    it, the prior-year comparative."""
    facts: list[FinancialFact] = []
    seen: set[tuple[ReportedMetric, int]] = set()
    for item in financial_items:
        metric = ReportedMetric(item.metric)
        if (metric, item.fiscal_year) in seen:
            continue
        seen.add((metric, item.fiscal_year))
        has_complete_range = item.period_start is not None and item.period_end is not None
        period = ReportingPeriod(
            label=sec_period(item.fiscal_year),
            kind=PeriodKind.duration,
            start_date=item.period_start if has_complete_range else None,
            end_date=item.period_end if has_complete_range else None,
        )
        facts.append(
            FinancialFact(
                metric=metric,
                period=period,
                value=item.value,
                unit=sec_unit_for(metric.value),
                currency=CURRENCY_USD,
            )
        )

    name = company_match.title if company_match and company_match.title else f"CIK {cik10}"
    return NormalizedFiling(
        company=RegulatedCompany(
            identity=CompanyIdentity(RegulatorySource.sec, cik10),
            name=name,
            name_en=name,
            ticker=(company_match.ticker or None) if company_match else None,
        ),
        identity=FilingIdentity(RegulatorySource.sec, filing.accession_number),
        filing_type=filing.form or _FORM_10K,
        title=f"Form {filing.form or _FORM_10K} (FY{fiscal_year})",
        reporting_period=ReportingPeriod(sec_period(fiscal_year), PeriodKind.duration),
        financial_facts=tuple(facts),
        filing_chunks=tuple(
            FilingChunk(
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                location=FilingChunkLocation(
                    section_title=chunk.section_title,
                    section_order=chunk.section_order,
                    part_index=chunk.part_index,
                ),
            )
            for chunk in chunks
        ),
        filed_at=filing.filing_date,
        url=document_url,
    )


# -- pure selection helpers ---------------------------------------------------


def select_target_filing(
    filings: list[SecFilingItem], accession_number: str | None
) -> SecFilingItem:
    """Pick the 10-K to ingest: the requested accession, or the latest filed.

    With ``accession_number`` given, the matching filing is returned, or
    :class:`SecIngestError` is raised if it is absent -- we never silently ingest
    a different filing. With ``None``, the most recently FILED 10-K wins (max
    ``filing_date``; a filing with no parseable date sorts last so a dated filing
    is always preferred). Raises :class:`SecIngestError` on an empty list. Pure.
    """
    if not filings:
        raise SecIngestError("no 10-K filings to select from")
    if accession_number is not None:
        for filing in filings:
            if filing.accession_number == accession_number:
                return filing
        raise SecIngestError(
            f"requested accession {accession_number!r} not found among "
            f"{len(filings)} 10-K filing(s)"
        )
    return max(
        filings,
        key=lambda f: (f.filing_date is not None, f.filing_date or datetime.date.min),
    )


def select_prior_filing(filings: list[SecFilingItem]) -> SecFilingItem:
    """The 10-K filed before the latest one: the source of the values the latest 10-K's
    comparatives may restate. Raises :class:`SecIngestError` when there is none. Pure."""
    dated = sorted(
        (f for f in filings if f.filing_date is not None),
        key=lambda f: (f.filing_date, f.accession_number),
    )
    if len(dated) < 2:
        raise SecIngestError(f"no 10-K before the latest among {len(filings)} 10-K filing(s)")
    return dated[-2]


class SecPriorYearSkipped(SecIngestError):
    """The 10-K before the latest is not the latest's prior fiscal year; nothing is stored."""


def _require_prior_year(
    filings: list[SecFilingItem],
    facts: list[SecFinancialItem],
    prior: SecFilingItem,
    prior_year: int,
) -> None:
    """Raise :class:`SecPriorYearSkipped` unless ``prior`` covers the latest 10-K's fiscal
    year minus one (an amended or late 10-K can sit between them). Pure."""
    latest = select_target_filing(filings, None)
    latest_facts = [f for f in facts if f.accession_number == latest.accession_number]
    latest_year = _filing_fiscal_year(latest, latest_facts)
    if prior_year != latest_year - 1:
        raise SecPriorYearSkipped(
            f"10-K {prior.accession_number} covers FY{prior_year}, not FY{latest_year - 1} "
            f"before the latest 10-K {latest.accession_number} (FY{latest_year})"
        )


def _filing_fiscal_year(filing: SecFilingItem, own_facts: list[SecFinancialItem]) -> int:
    """Derive the filing's fiscal year: the facts' own period, else report_date.year.

    Prefer the ``fiscal_year`` already derived from companyfacts' own-period
    figures (every own-accession annual fact shares the filing's fiscal year);
    fall back to the submissions ``report_date`` year when no mapped facts exist
    (a 10-K with prose but no mapped numbers is still a valid ingest). Raises
    :class:`SecIngestError` if neither is available -- ``financials.period`` and
    the filing title need a year and we never guess one. Pure.
    """
    if own_facts:
        # The own period is the latest; a prior-year comparative is one year earlier.
        return max(fact.fiscal_year for fact in own_facts)
    if filing.report_date is not None:
        return filing.report_date.year
    raise SecIngestError(
        f"cannot derive fiscal year for accession {filing.accession_number!r} "
        "(no own-period facts and no report_date)"
    )


def build_sec_quarter_filing(
    *,
    company_match: SecCompanyMatch | None,
    cik10: str,
    filing: SecFilingItem,
    financial_items: list[SecFinancialItem],
) -> NormalizedFiling:
    """Adapt one 10-Q and its three-month figures (:func:`parse_quarter_facts`) to the
    Normalized Filing seam (I11). The 10-Q's text is not stored: it has no chunks.

    The fiscal year and quarter are the 10-Q's own (``fy``, ``fp``); a 10-Q with no
    three-month figure has none, and :class:`SecIngestError` is raised. Pure."""
    own = [i for i in financial_items if i.fiscal_year == i.filed_fiscal_year]
    if not own:
        raise SecIngestError(f"10-Q {filing.accession_number} states no three-month figure")
    fiscal_year, quarter = own[0].fiscal_year, own[0].fiscal_period
    facts = tuple(
        FinancialFact(
            metric=ReportedMetric(item.metric),
            period=ReportingPeriod(
                label=f"{item.fiscal_year}-{quarter}",
                kind=PeriodKind.duration,
                start_date=item.period_start,
                end_date=item.period_end,
            ),
            value=item.value,
            unit=sec_unit_for(item.metric),
            currency=CURRENCY_USD,
        )
        for item in financial_items
    )
    name = company_match.title if company_match and company_match.title else f"CIK {cik10}"
    return NormalizedFiling(
        company=RegulatedCompany(
            identity=CompanyIdentity(RegulatorySource.sec, cik10),
            name=name,
            name_en=name,
            ticker=(company_match.ticker or None) if company_match else None,
        ),
        identity=FilingIdentity(RegulatorySource.sec, filing.accession_number),
        filing_type=QUARTERLY_FORM,
        title=f"Form {QUARTERLY_FORM} (FY{fiscal_year} {quarter})",
        reporting_period=ReportingPeriod(f"{fiscal_year}-{quarter}", PeriodKind.duration),
        financial_facts=facts,
        filing_chunks=(),
        filed_at=filing.filing_date,
        url=_archive_url(cik10, filing.accession_number, filing.primary_document),
    )


# -- impure adapter fetch -----------------------------------------------------


@dataclass(frozen=True)
class SecQuarterAdapter:
    """Fetch and normalize a company's latest 10-Q, figures only (I11)."""

    client: SecClient
    cik: str | int
    pinned: PinnedStore | None = None

    async def fetch(self) -> NormalizedFiling:
        cik10 = format_cik(self.cik)
        company_match = await self.client.resolve_company_by_cik(self.cik)
        filings = await self.client.list_filings(self.cik, filing_types=[QUARTERLY_FORM])
        if not filings:
            raise SecIngestError(f"no 10-Q filings for CIK {cik10}")
        target = select_target_filing(filings, None)
        save: dict = {}
        if self.pinned is not None:
            save["on_body"] = self.pinned.sink(sec_companyfacts_path(cik10))
        items = await self.client.fetch_quarter_facts(
            self.cik, target.accession_number, **save
        )
        normalized = build_sec_quarter_filing(
            company_match=company_match, cik10=cik10, filing=target, financial_items=items
        )
        logger.info(
            "normalized SEC 10-Q filing=%s financials=%d period=%s",
            target.accession_number,
            len(normalized.financial_facts),
            normalized.reporting_period.label,
        )
        return normalized


@dataclass(frozen=True)
class SecFilingAdapter:
    """Fetch and normalize one selected or latest SEC 10-K."""

    client: SecClient
    cik: str | int
    accession_number: str | None = None
    pinned: PinnedStore | None = None
    # The 10-K before the latest one (the restatement source), instead of the latest.
    prior: bool = False

    async def fetch(self) -> NormalizedFiling:
        """Return a complete snapshot without opening a database session."""
        cik10 = format_cik(self.cik)
        company_match = await self.client.resolve_company_by_cik(self.cik)
        filings = await self.client.list_filings(
            self.cik, filing_types=[_FORM_10K]
        )
        if self.prior:
            target = select_prior_filing(filings)
        else:
            target = select_target_filing(filings, self.accession_number)

        document = await self.client.fetch_document(
            self.cik, target.accession_number, target.primary_document
        )
        sections = extract_10k_prose(document.raw_bytes)
        chunks = chunk_document(sections)

        save: dict = {}
        if self.pinned is not None:
            save["on_body"] = self.pinned.sink(sec_companyfacts_path(cik10))
        facts = await self.client.fetch_company_facts(self.cik, with_prior=True, **save)
        own_facts = [
            fact
            for fact in facts
            if fact.accession_number == target.accession_number
        ]
        fiscal_year = _filing_fiscal_year(target, own_facts)
        if self.prior:
            _require_prior_year(filings, facts, target, fiscal_year)
        normalized = build_sec_normalized_filing(
            company_match=company_match,
            cik10=cik10,
            filing=target,
            fiscal_year=fiscal_year,
            document_url=document.url,
            financial_items=own_facts,
            chunks=chunks,
        )
        logger.info(
            "normalized SEC filing=%s financials=%d chunks=%d fiscal_year=%d",
            target.accession_number,
            len(normalized.financial_facts),
            len(normalized.filing_chunks),
            fiscal_year,
        )
        return normalized
