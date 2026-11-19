"""Ingest CLI: one command ingests a company's latest annual filing.

Usage (run from ``backend/`` with the repo venv):

    python -m app.ingest --source dart --ticker 005930
    python -m app.ingest --source sec --ticker MSFT
    python -m app.ingest --source dart --ticker 005930 --quarter   # latest quarter's figures
    python -m app.ingest events --source dart --ticker 005930   # 12 months of event filings

DART and SEC resolve their source-specific identities and build a Normalized
Filing through their adapters. The shared ingestion module then persists and
indexes either source through the same lifecycle.

Selection/matching logic lives in pure functions (``select_latest_annual``,
``match_ticker``) so it is unit-testable without network or DB.
"""

import argparse
import asyncio
import datetime
import logging
import re
import sys

from app.clients.dart import DartClient, FilingItem
from app.clients.sec import SecClient, SecCompanyMatch
from app.config import get_settings
from app.db.session import get_async_engine, get_async_session
from app.filings.categories import load_contract
from app.ingest import ingest_filing
from app.ingest.dart import DartFilingAdapter
from app.ingest.events import main as events_main
from app.ingest.pinned import SAVE_PINNED_HELP, PinnedStore, format_pinned, open_pinned_store
from app.ingest.sec_ingest import SecFilingAdapter, SecPriorYearSkipped, SecQuarterAdapter
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

_ANNUAL_REPRT_CODE = "11011"
# "사업보고서 (2023.12)" -> business year 2023. [Verified] report_nm shape in
# DART annual-report naming convention.
_REPORT_YEAR_RE = re.compile(r"\((\d{4})\.")
# One page of 정기공시 over ~15 months always contains the latest annual report.
_LOOKBACK_DAYS = 450
# --prior reaches one more year back for the report before the latest; a 100-row page of
# 정기공시 over ~27 months still holds every annual report in it.
_PRIOR_EXTRA_DAYS = 366


def select_latest_annual(
    filings: list[FilingItem], *, prior: bool = False
) -> tuple[FilingItem, str]:
    """Pick the newest 사업보고서 from a list.json page and its business year.

    Pure: filters ``report_nm`` starting with "사업보고서" after any correction prefix such
    as "[기재정정]" (D73: DART's statements API returns the newest version's rows), derives
    ``bsns_year`` from the "(YYYY.MM)" suffix, orders by (``bsns_year``, ``rcept_dt``).
    With ``prior`` it picks the newest version of the report for the business year before
    the latest one (the restatement source).
    Raises ``ValueError`` when the page has no parseable annual report.
    """
    prefix_re = re.compile(load_contract()["dart"]["correction_prefix_pattern"])
    candidates: list[tuple[datetime.date, FilingItem, str]] = []
    for item in filings:
        if not prefix_re.sub("", item.report_nm).lstrip().startswith("사업보고서"):
            continue
        match = _REPORT_YEAR_RE.search(item.report_nm)
        if match is None or item.rcept_dt is None:
            continue
        candidates.append((item.rcept_dt, item, match.group(1)))
    if not candidates:
        raise ValueError("no annual report (사업보고서) found in the listing window")
    # The latest business year, then its newest version: a late correction of an older
    # year's report is not the latest report.
    rcept_dt, item, year = max(candidates, key=lambda c: (int(c[2]), c[0]))
    if not prior:
        return item, year
    wanted = str(int(year) - 1)
    earlier = [c for c in candidates if c[2] == wanted]
    if not earlier:
        raise ValueError(f"no annual report (사업보고서) for {wanted} in the listing window")
    rcept_dt, item, year = max(earlier, key=lambda c: c[0])
    return item, year


# A quarterly or half-year report's title month -> (report-name word, reprt_code). The
# month is the end of the quarter the report's statements close with, for a company whose
# fiscal year ends in December; any other month is refused.
_QUARTER_TITLE_MONTHS: dict[str, tuple[str, str]] = {
    "03": ("분기보고서", "11013"),
    "06": ("반기보고서", "11012"),
    "09": ("분기보고서", "11014"),
}
_REPORT_YEAR_MONTH_RE = re.compile(r"\((\d{4})\.(\d{2})\)")


def select_latest_quarter(filings: list[FilingItem]) -> tuple[FilingItem, str, str]:
    """Pick the newest 분기보고서 or 반기보고서 from a list.json page (I11).

    Pure. Returns the item, its business year and its reprt_code, from the "(YYYY.MM)"
    suffix (:data:`_QUARTER_TITLE_MONTHS`); a correction prefix is ignored as in
    :func:`select_latest_annual`. Raises ``ValueError`` when the page has none.
    """
    prefix_re = re.compile(load_contract()["dart"]["correction_prefix_pattern"])
    candidates: list[tuple[str, str, datetime.date, FilingItem, str]] = []
    for item in filings:
        name = prefix_re.sub("", item.report_nm).lstrip()
        match = _REPORT_YEAR_MONTH_RE.search(name)
        if match is None or item.rcept_dt is None:
            continue
        year, month = match.groups()
        kind = _QUARTER_TITLE_MONTHS.get(month)
        if kind is None or not name.startswith(kind[0]):
            continue
        candidates.append((year, month, item.rcept_dt, item, kind[1]))
    if not candidates:
        raise ValueError("no quarterly report (분기보고서 / 반기보고서) in the listing window")
    year, _month, _dt, item, reprt_code = max(candidates, key=lambda c: (c[0], c[1], c[2]))
    return item, year, reprt_code


def match_ticker(matches: list[SecCompanyMatch], ticker: str) -> SecCompanyMatch:
    """Exact (case-insensitive) ticker match from SEC company search results.

    Pure. Raises ``ValueError`` when the ticker is not present — substring
    hits from ``search_company`` must not silently ingest the wrong company.
    """
    wanted = ticker.upper()
    for m in matches:
        if m.ticker.upper() == wanted:
            return m
    raise ValueError(f"ticker {ticker!r} not found in SEC company_tickers")


async def _run_dart(
    ticker: str,
    pinned: PinnedStore | None = None,
    *,
    prior: bool = False,
    quarter: bool = False,
) -> None:
    client = DartClient(get_settings())
    try:
        corp_code = await client.resolve_corp_code(ticker)
        if corp_code is None:
            raise SystemExit(f"ticker {ticker!r} not found in DART corpCode map")

        today = datetime.date.today()
        lookback = _LOOKBACK_DAYS + (_PRIOR_EXTRA_DAYS if prior else 0)
        bgn = today - datetime.timedelta(days=lookback)
        filings = await client.list_filings(
            corp_code,
            bgn_de=bgn.strftime("%Y%m%d"),
            end_de=today.strftime("%Y%m%d"),
            pblntf_ty="A",  # 정기공시
        )
        if quarter:
            item, bsns_year, reprt_code = select_latest_quarter(filings)
        else:
            item, bsns_year = select_latest_annual(filings, prior=prior)
            reprt_code = _ANNUAL_REPRT_CODE
        logger.info(
            "selected %s (rcept_no=%s, bsns_year=%s)",
            item.report_nm,
            item.rcept_no,
            bsns_year,
        )

        result = await ingest_filing(
            DartFilingAdapter(
                client=client,
                corp_code=corp_code,
                filing_item=item,
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                pinned=pinned,
                figures_only=prior,
                without_document=quarter,
            ),
            get_async_session,
        )
        logger.info(
            "done: company=%s filing=%s financials=%d chunks=%d embeddings=%d",
            result.company_id,
            result.filing_id,
            result.financials_written,
            result.chunks_written,
            result.embeddings_backfilled,
        )
        _commit_pinned(pinned)
    finally:
        await client.aclose()
        await get_async_engine().dispose()


async def _run_sec(
    ticker: str,
    pinned: PinnedStore | None = None,
    *,
    prior: bool = False,
    quarter: bool = False,
) -> None:
    client = SecClient(get_settings())
    try:
        matches = await client.search_company(ticker)
        match = match_ticker(matches, ticker)
        logger.info("selected %s (CIK %s)", match.title, match.cik)

        adapter = (
            SecQuarterAdapter(client=client, cik=match.cik, pinned=pinned)
            if quarter
            else SecFilingAdapter(client=client, cik=match.cik, pinned=pinned, prior=prior)
        )
        try:
            result = await ingest_filing(adapter, get_async_session)
        except SecPriorYearSkipped as exc:
            print(f"skipped: {exc}")
            return
        logger.info(
            "done: company=%s filing=%s financials=%d chunks=%d embeddings=%d",
            result.company_id,
            result.filing_id,
            result.financials_written,
            result.chunks_written,
            result.embeddings_backfilled,
        )
        _commit_pinned(pinned)
    finally:
        await client.aclose()
        await get_async_engine().dispose()


def _commit_pinned(pinned: PinnedStore | None) -> None:
    """Write the staged pinned files once the filing is stored; a problem fails the run."""
    if pinned is None:
        return
    problems = pinned.commit()
    for problem in problems:
        print(f"PROBLEM {problem}")
    if problems:
        raise SystemExit(1)


def main() -> None:
    if sys.argv[1:2] == ["events"]:
        events_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(
        prog="python -m app.ingest",
        description="Ingest a company's latest annual filing (DART 사업보고서 / SEC 10-K).",
    )
    parser.add_argument("--source", choices=["dart", "sec"], required=True)
    parser.add_argument(
        "--ticker",
        required=True,
        help="stock ticker (DART: 6-digit code e.g. 005930; SEC: symbol e.g. MSFT)",
    )
    parser.add_argument("--save-pinned", metavar="DIR", **SAVE_PINNED_HELP)
    parser.add_argument(
        "--prior",
        action="store_true",
        help="ingest the annual report before the latest one (the original values that "
        "the latest report's comparatives may restate)",
    )
    parser.add_argument(
        "--quarter",
        action="store_true",
        help="ingest the figures of the latest quarterly or half-year report (DART "
        "분기/반기보고서, SEC 10-Q) for the quarter report screen; its text is not stored",
    )
    args = parser.parse_args()
    if args.quarter and args.prior:
        parser.error("--quarter and --prior cannot be combined")

    # configure_logging (not bare basicConfig): installs the crtfc_key masking
    # filters so httpx URL logs never leak the DART API key from the CLI path.
    configure_logging()

    pinned = open_pinned_store(args.save_pinned)
    if args.source == "dart":
        asyncio.run(_run_dart(args.ticker, pinned, prior=args.prior, quarter=args.quarter))
    else:
        asyncio.run(_run_sec(args.ticker, pinned, prior=args.prior, quarter=args.quarter))
    if pinned is not None:
        print(format_pinned(pinned))


if __name__ == "__main__":
    main()
