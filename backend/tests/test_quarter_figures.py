"""Quarter figures (I11), offline: DART and SEC mapping, selection, export and verification.

The fixtures are synthetic (``fixtures/build/pinned``): Samsung Electronics' 3분기보고서, whose
operating income a year earlier is a loss, and an Apple 10-Q with a nine-month entry beside
its three-month ones.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from app.build import export
from app.build.export import BuildOptions, build_bundle, write_bundle
from app.build.model import BuildError, BuildInput
from app.build.verify import VerifyError, check_bundle, dart_quarter_period
from app.clients.dart import DartClient, _filing_item_from_row
from app.clients.sec import SecCompanyMatch, SecFilingItem, parse_quarter_facts
from app.filings.persistence import _legacy_fiscal_fields
from app.financials.model import ReportingPeriod
from app.financials.vocabulary import PeriodKind
from app.ingest.__main__ import select_latest_quarter
from app.ingest.dart import dart_quarter_facts, period_descriptor
from app.ingest.sec_ingest import SecIngestError, build_sec_quarter_filing
from tests.build_seed import (
    APPLE_QUARTER,
    AS_OF,
    PINNED_BUILD,
    PINNED_DIRS,
    SAMSUNG_QUARTER,
    fixture_build_input,
)

DART_Q3 = PINNED_BUILD / "dart" / "fnlttSinglAcntAll" / "00126380_2026_11014_CFS.json"
SEC_FACTS = PINNED_BUILD / "sec" / "companyfacts" / "CIK0000320193.json"
SAMSUNG = "dart:00126380"
APPLE = "sec:0000320193"


def _dart_items(rows: list[dict] | None = None):
    payload = json.loads(DART_Q3.read_text())
    if rows is not None:
        payload["list"] = rows
    return DartClient._parse_financials_payload(payload)


def _facts_by_label(facts) -> dict[tuple[str, str], Decimal]:
    return {(f.metric.value, f.period.label): Decimal(f.value) for f in facts}


# -- DART ----------------------------------------------------------------------------------------


def test_dart_quarter_reads_the_quarter_and_the_same_quarter_a_year_earlier() -> None:
    facts = dart_quarter_facts(_dart_items(), period_descriptor("2026", "11014"))
    values = _facts_by_label(facts)
    assert values[("revenue", "2026-Q3")] == Decimal("86061747000000")
    assert values[("revenue", "2025-Q3")] == Decimal("79098718000000")
    assert values[("net_income_attributable", "2026-Q3")] == Decimal("12006461000000")
    assert values[("net_income_attributable", "2025-Q3")] == Decimal("9780000000000")
    # The cash-flow row states the year to date (30 trillion); the income statement wins.
    assert values[("net_income", "2026-Q3")] == Decimal("12225747000000")
    assert all(f.period.start_date is None and f.period.kind is PeriodKind.duration for f in facts)


def test_dart_quarter_keeps_a_loss_a_year_earlier_exactly() -> None:
    """The base at or below zero case: the stored value is the loss as filed, never guessed."""
    values = _facts_by_label(dart_quarter_facts(_dart_items(), period_descriptor("2026", "11014")))
    assert values[("operating_income", "2025-Q3")] == Decimal("-1200000000000")


def test_dart_quarter_refuses_a_period_name_that_is_not_the_report_codes() -> None:
    rows = json.loads(DART_Q3.read_text())["list"]
    rows[0] = {**rows[0], "thstrm_nm": "제 58 기 반기"}
    with pytest.raises(ValueError, match="3분기"):
        dart_quarter_facts(_dart_items(rows), period_descriptor("2026", "11014"))


def test_dart_half_year_report_gives_the_second_quarter() -> None:
    rows = [
        {**row, "reprt_code": "11012", "thstrm_nm": "제 58 기 반기"}
        for row in json.loads(DART_Q3.read_text())["list"]
    ]
    values = _facts_by_label(dart_quarter_facts(_dart_items(rows), period_descriptor("2026", "11012")))
    assert values[("revenue", "2026-Q2")] == Decimal("86061747000000")
    assert values[("revenue", "2025-Q2")] == Decimal("79098718000000")
    assert _legacy_fiscal_fields(ReportingPeriod("2026-Q2", PeriodKind.duration)) == (2026, 2)


def test_dart_quarter_leaves_out_a_row_that_does_not_state_the_year_to_date() -> None:
    """After the first quarter, a row without thstrm_add_amount does not show whether its
    thstrm_amount is the quarter or the year to date."""
    rows = json.loads(DART_Q3.read_text())["list"]
    rows = [{k: v for k, v in r.items() if k != "thstrm_add_amount"}
            if r["account_id"] == "ifrs-full_Revenue" else r for r in rows]  # fmt: skip
    values = _facts_by_label(dart_quarter_facts(_dart_items(rows), period_descriptor("2026", "11014")))
    assert not any(metric == "revenue" for metric, _ in values)
    assert ("operating_income", "2026-Q3") in values


def test_dart_quarter_leaves_out_a_quarter_equal_to_the_year_to_date() -> None:
    """After the first quarter, a quarter equal to its year to date is one amount filed in
    both columns: the row is left out. A year-earlier quarter equal to that year's year to
    date is not read, and the row's own quarter still is."""
    rows = json.loads(DART_Q3.read_text())["list"]
    for row in rows:
        if row["account_id"] == "ifrs-full_Revenue":
            row["thstrm_amount"] = row["thstrm_add_amount"]
        if row["account_id"] == "dart_OperatingIncomeLoss":
            row["frmtrm_q_amount"] = row["frmtrm_add_amount"]
    values = _facts_by_label(dart_quarter_facts(_dart_items(rows), period_descriptor("2026", "11014")))
    assert not any(metric == "revenue" for metric, _ in values)
    assert values[("operating_income", "2026-Q3")] == Decimal("12166062000000")
    assert ("operating_income", "2025-Q3") not in values
    assert values[("net_income_attributable", "2025-Q3")] == Decimal("9780000000000")


def test_dart_first_quarter_may_equal_its_year_to_date() -> None:
    rows = [
        row | {"reprt_code": "11013", "thstrm_nm": "제 58 기 1분기",
               "thstrm_add_amount": row.get("thstrm_amount")}
        for row in json.loads(DART_Q3.read_text())["list"]
    ]  # fmt: skip
    values = _facts_by_label(dart_quarter_facts(_dart_items(rows), period_descriptor("2026", "11013")))
    assert values[("revenue", "2026-Q1")] == Decimal("86061747000000")


def test_dart_first_quarter_needs_no_year_to_date() -> None:
    rows = [
        {k: v for k, v in row.items() if k != "thstrm_add_amount"}
        | {"reprt_code": "11013", "thstrm_nm": "제 58 기 1분기"}
        for row in json.loads(DART_Q3.read_text())["list"]
    ]
    values = _facts_by_label(dart_quarter_facts(_dart_items(rows), period_descriptor("2026", "11013")))
    assert values[("revenue", "2026-Q1")] == Decimal("86061747000000")


def _listed(report_nm: str, rcept_no: str, rcept_dt: str):
    return _filing_item_from_row(
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930",
         "corp_cls": "Y", "report_nm": report_nm, "rcept_no": rcept_no, "flr_nm": "삼성전자",
         "rcept_dt": rcept_dt, "rm": ""}
    )  # fmt: skip


def test_select_latest_quarter_picks_the_newest_quarter_and_its_report_code() -> None:
    page = [
        _listed("사업보고서 (2025.12)", "20260310000123", "20260310"),
        _listed("분기보고서 (2026.03)", "20260515000001", "20260515"),
        _listed("반기보고서 (2026.06)", "20260814000001", "20260814"),
        _listed("분기보고서 (2026.09)", "20261116000111", "20261116"),
    ]
    item, year, code = select_latest_quarter(page)
    assert (item.rcept_no, year, code) == ("20261116000111", "2026", "11014")
    item, year, code = select_latest_quarter(page[:3])
    assert (item.rcept_no, year, code) == ("20260814000001", "2026", "11012")


def test_select_latest_quarter_takes_the_newest_version_of_a_corrected_report() -> None:
    page = [
        _listed("분기보고서 (2026.09)", "20261116000111", "20261116"),
        _listed("[기재정정]분기보고서 (2026.09)", "20261120000222", "20261120"),
    ]
    assert select_latest_quarter(page)[0].rcept_no == "20261120000222"


def test_select_latest_quarter_refuses_a_page_with_no_quarterly_report() -> None:
    # A 분기보고서 for a month that closes no December-year quarter is not guessed.
    page = [
        _listed("사업보고서 (2025.12)", "20260310000123", "20260310"),
        _listed("분기보고서 (2026.08)", "20261016000001", "20261016"),
    ]
    with pytest.raises(ValueError, match="no quarterly report"):
        select_latest_quarter(page)


# -- SEC -----------------------------------------------------------------------------------------


def _companyfacts() -> dict:
    return json.loads(SEC_FACTS.read_text(), parse_float=str)


def test_sec_quarter_reads_three_months_and_the_same_quarter_a_year_earlier() -> None:
    items = parse_quarter_facts(_companyfacts(), APPLE_QUARTER)
    got = {(i.metric, i.fiscal_year): (i.period_start, i.period_end, i.value) for i in items}
    assert got[("revenue", 2026)] == (
        datetime.date(2026, 3, 29), datetime.date(2026, 6, 27), 95000000000
    )
    # 52/53-week quarters: the prior quarter ends a day later in the calendar.
    assert got[("revenue", 2025)] == (
        datetime.date(2025, 3, 30), datetime.date(2025, 6, 28), 85000000000
    )
    assert got[("net_income_attributable", 2025)][2] == 21000000000
    # The nine-month entry is not a quarter.
    assert all((i.period_end - i.period_start).days < 100 for i in items)
    assert {i.fiscal_period for i in items} == {"Q3"}


def test_sec_quarter_ignores_other_filings_and_annual_entries() -> None:
    assert parse_quarter_facts(_companyfacts(), "0000320193-25-000079") == []


def test_sec_quarter_drops_a_metric_whose_entries_disagree() -> None:
    payload = _companyfacts()
    entries = payload["facts"]["us-gaap"]["OperatingIncomeLoss"]["units"]["USD"]
    own = next(e for e in entries if e["accn"] == APPLE_QUARTER and e["end"] == "2026-06-27"
               and e["start"] == "2026-03-29")  # fmt: skip
    entries.append({**own, "val": 1})
    metrics = {i.metric for i in parse_quarter_facts(payload, APPLE_QUARTER)}
    assert "operating_income" not in metrics and "revenue" in metrics


def test_sec_quarter_keeps_a_negative_prior_quarter_exactly() -> None:
    payload = _companyfacts()
    for entry in payload["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]:
        if entry["accn"] == APPLE_QUARTER and entry["end"] == "2025-06-28":
            entry["val"] = -4000000000
    items = parse_quarter_facts(payload, APPLE_QUARTER)
    prior = next(i for i in items if i.metric == "net_income_attributable" and i.fiscal_year == 2025)
    assert prior.value == -4000000000


def _set_quarter_start(payload: dict, tag: str, end: str, days: int) -> None:
    """Give the 10-Q's three-month entry for ``tag`` ending on ``end`` a length of ``days``,
    counting both ends. The nine-month entry (starting 2025-09-28) is left alone."""
    for entry in payload["facts"]["us-gaap"][tag]["units"]["USD"]:
        if entry["accn"] == APPLE_QUARTER and entry["end"] == end and entry["start"] != "2025-09-28":
            last = datetime.date.fromisoformat(end)
            entry["start"] = (last - datetime.timedelta(days=days - 1)).isoformat()


def test_sec_quarter_accepts_twelve_and_fourteen_week_quarters() -> None:
    """A quarter is 12 to 14 weeks counting both ends (84 to 98 days), as in
    FootnoteKit's QuarterComparison: Costco's 12-week quarters are 84 days."""
    for days in (84, 98):
        payload = _companyfacts()
        tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
        _set_quarter_start(payload, tag, "2026-06-27", days)
        _set_quarter_start(payload, tag, "2025-06-28", days)
        got = {(i.metric, i.fiscal_year): i for i in parse_quarter_facts(payload, APPLE_QUARTER)}
        own, prior = got[("revenue", 2026)], got[("revenue", 2025)]
        assert (own.period_end - own.period_start).days + 1 == days
        assert (prior.period_end - prior.period_start).days + 1 == days


def test_sec_quarter_refuses_a_quarter_shorter_than_twelve_weeks() -> None:
    """83 days is not a quarter. The same quarter a year earlier is then not taken for the
    own quarter: the own quarter must end on the 10-Q's latest date."""
    payload = _companyfacts()
    _set_quarter_start(payload, "RevenueFromContractWithCustomerExcludingAssessedTax", "2026-06-27", 83)
    items = parse_quarter_facts(payload, APPLE_QUARTER)
    assert not any(i.metric == "revenue" for i in items)
    assert any(i.metric == "operating_income" and i.fiscal_year == 2026 for i in items)


def test_sec_quarter_tries_the_next_tag_when_the_first_gives_no_quarter() -> None:
    payload = _companyfacts()
    entries = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    payload["facts"]["us-gaap"]["Revenues"] = {
        "units": {"USD": [{**e, "start": "2026-01-01"} for e in entries if e["end"] == "2026-06-27"]}
    }
    got = {(i.metric, i.fiscal_year): i for i in parse_quarter_facts(payload, APPLE_QUARTER)}
    assert got[("revenue", 2026)].tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert got[("revenue", 2026)].value == 95000000000


def _ten_q() -> SecFilingItem:
    return SecFilingItem(
        accession_number=APPLE_QUARTER, form="10-Q", filing_date=datetime.date(2026, 7, 31),
        report_date=datetime.date(2026, 6, 27), primary_document="aapl-20260627.htm",
    )  # fmt: skip


def test_sec_quarter_filing_names_its_fiscal_quarter() -> None:
    filing = build_sec_quarter_filing(
        company_match=SecCompanyMatch(cik="0000320193", ticker="AAPL", title="Apple Inc."),
        cik10="0000320193",
        filing=_ten_q(),
        financial_items=parse_quarter_facts(_companyfacts(), APPLE_QUARTER),
    )
    assert filing.filing_type == "10-Q"
    assert filing.title == "Form 10-Q (FY2026 Q3)"
    assert filing.reporting_period.label == "2026-Q3"
    assert filing.filing_chunks == ()
    assert filing.url.endswith("/320193/000032019326000020/aapl-20260627.htm")
    labels = {(f.metric.value, f.period.label) for f in filing.financial_facts}
    assert ("revenue", "2025-Q3") in labels and ("revenue", "2026-Q3") in labels


def test_sec_quarter_filing_without_a_quarter_figure_is_refused() -> None:
    with pytest.raises(SecIngestError):
        build_sec_quarter_filing(
            company_match=None, cik10="0000320193", filing=_ten_q(), financial_items=[]
        )


# -- export and verification ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def data() -> BuildInput:
    return fixture_build_input()


def _options() -> BuildOptions:
    return BuildOptions(AS_OF, "test", allow_unapproved=True)


def _quarter_rows(data: BuildInput) -> dict[str, tuple]:
    return {row[0]: row for row in build_bundle(data, _options(), PINNED_DIRS).rows["quarter_figures"]}


def test_export_writes_each_quarter_and_the_same_quarter_a_year_earlier(data) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    filings = {row[0]: row for row in bundle.rows["filings"]}
    samsung = filings[f"dart:{SAMSUNG_QUARTER}"]
    assert samsung[2:5] == ("quarterly", "quarterly", "분기보고서")
    assert samsung[8] == "FY2026-Q3"
    assert filings[f"sec:{APPLE_QUARTER}"][2:5] == ("quarterly", "quarterly", "10-Q")
    rows = _quarter_rows(data)
    revenue = rows[f"{SAMSUNG}|revenue|2026-09-30|consolidated"]
    # DART states no dates: the three months ending with the title's month.
    assert revenue[4:10] == (2026, 3, "2026-07-01", "2026-09-30", "86061747000000", "KRW")
    assert revenue[12] == "ifrs-full_Revenue"
    prior = rows[f"{SAMSUNG}|revenue|2025-09-30|consolidated"]
    assert prior[4:9] == (2025, 3, "2025-07-01", "2025-09-30", "79098718000000")
    loss = rows[f"{SAMSUNG}|operating_income|2025-09-30|consolidated"]
    assert loss[8] == "-1200000000000"
    apple = rows[f"{APPLE}|revenue|2026-06-27|consolidated"]
    assert apple[4:9] == (2026, 3, "2026-03-29", "2026-06-27", "95000000000")
    assert bundle.report["quarter_checks"] == len(rows)
    # Apple reports no separate net income (ProfitLoss): the gap is listed, not filled.
    assert f"sec:{APPLE_QUARTER} net_income 2026-Q3" in bundle.report["quarter_gaps"]["ids"]


def test_export_needs_no_summary_for_a_quarterly_filing(data) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    needing = set(bundle.report["summaries"]["filings_without_approved_summaries"])
    assert f"dart:{SAMSUNG_QUARTER}" not in needing


def test_export_refuses_a_quarter_figure_that_differs_from_the_pinned_response(data) -> None:
    changed = tuple(
        dataclasses.replace(r, value=r.value + 1)
        if r.filing_key == SAMSUNG_QUARTER and r.metric == "revenue" and r.period == "2026-Q3"
        else r
        for r in data.financials
    )
    with pytest.raises(BuildError) as refused:
        build_bundle(dataclasses.replace(data, financials=changed), _options(), PINNED_DIRS)
    assert any(SAMSUNG_QUARTER in p and "revenue" in p for p in refused.value.problems)


def test_export_leaves_out_a_quarterly_report_filed_after_as_of(data) -> None:
    later = dataclasses.replace(_options(), as_of=datetime.date(2026, 11, 15))
    rows = build_bundle(data, later, PINNED_DIRS).rows
    assert f"dart:{SAMSUNG_QUARTER}" not in {r[0] for r in rows["filings"]}
    assert not any(r[1] == SAMSUNG for r in rows["quarter_figures"])


def test_dart_quarter_period_refuses_a_title_month_of_another_quarter() -> None:
    assert dart_quarter_period("분기보고서 (2026.09)", 2026, 3, 2025) == (
        datetime.date(2025, 7, 1), datetime.date(2025, 9, 30)
    )
    with pytest.raises(VerifyError):
        dart_quarter_period("분기보고서 (2026.09)", 2026, 2, 2026)
    with pytest.raises(VerifyError):
        dart_quarter_period("분기보고서 (2025.09)", 2026, 3, 2026)


def _written(data: BuildInput, tmp_path: Path) -> Path:
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), out)
    return out


def test_check_bundle_rereads_every_quarter_figure(data, tmp_path) -> None:
    out = _written(data, tmp_path)
    assert check_bundle(out, release=False, pinned_dirs=PINNED_DIRS) == []
    with sqlite3.connect(out) as connection:
        connection.execute(
            "UPDATE quarter_figures SET value = '1' WHERE metric = 'revenue' AND fiscal_year = 2026"
        )
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert f"{SAMSUNG}|revenue|2026-09-30|consolidated: " in "\n".join(problems)
    assert any(p.endswith("revenue is 86061747000000, stored 1") for p in problems)
    assert any(p.endswith("revenue is 95000000000, stored 1") for p in problems)


def test_check_bundle_refuses_a_quarter_figure_from_an_annual_filing(data, tmp_path) -> None:
    out = _written(data, tmp_path)
    with sqlite3.connect(out) as connection:
        annual = connection.execute(
            f"SELECT id FROM filings WHERE kind = 'annual' AND company_id = '{SAMSUNG}' LIMIT 1"
        ).fetchone()[0]
        connection.execute(f"UPDATE quarter_figures SET filing_id = '{annual}'")
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert any("is not a quarterly filing" in p for p in problems)


def test_quarter_metrics_are_in_the_vocabulary() -> None:
    vocabulary = json.loads(
        (Path(export.BACKEND_DIR).parent / "contracts" / "financial-vocabulary.json").read_text()
    )
    assert set(export.QUARTER_METRICS) <= set(vocabulary["reported_metrics"])
