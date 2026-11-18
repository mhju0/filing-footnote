"""Facts from DART exchange-filing tables (D77), on saved real documents."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.clients.dart_events import load_facts_contract, read_event_document
from app.clients.dart_tables import parse_table_facts, table_for, table_of_key

FIXTURES = Path(__file__).parent / "fixtures" / "events"
DOCUMENTS = FIXTURES / "dart" / "document"
CLASSIFIER = FIXTURES / "classifier" / "dart" / "document"


def _rows(path: Path) -> list[list[str]]:
    return read_event_document(path.read_bytes()).rows


def _facts(table: str, path: Path) -> dict[str, object]:
    found = {}
    for fact in parse_table_facts(table, _rows(path)):
        assert fact.error is None
        value = fact.value_decimal if fact.value_decimal is not None else (
            fact.value_date if fact.value_date is not None else fact.value_text)  # fmt: skip
        found[fact.key] = (value, fact.unit)
    return found


def test_tables_are_chosen_by_category_and_report_name() -> None:
    results = "연결재무제표기준영업(잠정)실적(공정공시)"
    assert table_for("earnings", results) == "results"
    # 영업(잠정)실적 is results or unit sales; the body-decided category picks the table.
    assert table_for("earnings", "영업(잠정)실적(공정공시)") == "results"
    assert table_for("unit_sales", "영업(잠정)실적(공정공시)") == "units"
    assert table_for("earnings", "매출액또는손익구조30%(대규모법인은15%)이상변경") == "change"
    assert table_for("dividend", "현금ㆍ현물배당결정") == "dividend"
    assert table_for("outlook", "영업실적등에대한전망(공정공시)") == "outlook"
    assert table_for("outlook", "연결재무제표기준영업실적등에대한전망(공정공시)") == "outlook"
    # 장래사업ㆍ경영계획 is prose, not a regular table: the model summarises it.
    assert table_for("outlook", "장래사업ㆍ경영계획(공정공시)") is None
    assert table_for("buyback", "자기주식취득결정") is None
    assert table_for(None, results) is None


def test_contract_document_fields_are_unique_and_state_no_unit() -> None:
    contract = load_facts_contract()
    assert contract["version"] == 2
    keys = [f["key"] for spec in contract["documents"] for f in spec["fields"]]
    endpoint_keys = {f["key"] for spec in contract["endpoints"] for f in spec["fields"]}
    assert len(keys) == len(set(keys)) and not set(keys) & endpoint_keys
    for spec in contract["documents"]:
        for field in spec["fields"]:
            assert field["unit"] is None  # the unit is the one the filing states
            assert field["kind"] in contract["kinds"]
            assert table_of_key(field["key"]) == spec["table"]


def test_hyundai_consolidated_results() -> None:
    facts = _facts("results", DOCUMENTS / "20261029800228.xml")
    assert len(facts) == 29
    assert facts["results_period_start"] == (datetime.date(2026, 7, 1), None)
    assert facts["results_year_ago_end"] == (datetime.date(2025, 9, 30), None)
    assert facts["results_revenue_current"] == (Decimal("45110247"), "백만원")
    assert facts["results_revenue_prior_period"] == (Decimal("49215328"), "백만원")
    assert facts["results_revenue_year_ago"] == (Decimal("46721448"), "백만원")
    assert facts["results_revenue_cumulative"] == (Decimal("140264461"), "백만원")
    assert facts["results_revenue_cumulative_year_ago"] == (Decimal("139415886"), "백만원")
    assert facts["results_operating_income_current"] == (Decimal("2677232"), "백만원")
    assert facts["results_operating_income_year_ago"] == (Decimal("2537266"), "백만원")
    assert facts["results_net_income_attributable_current"] == (Decimal("1704370"), "백만원")
    assert facts["results_net_income_attributable_cumulative_year_ago"] == (
        Decimal("8416950"), "백만원")  # fmt: skip
    for value, _ in facts.values():
        assert not isinstance(value, float)


def test_samsung_corrected_results_keep_decimals_and_skip_dashes() -> None:
    # A correction lists the changed items first; the form's own table is read. Its net income
    # rows are "-", which gives no fact.
    facts = _facts("results", DOCUMENTS / "20261029800099.xml")
    assert facts["results_revenue_current"] == (Decimal("195.25"), "조원")
    assert facts["results_revenue_prior_period"] == (Decimal("171.50"), "조원")
    assert str(facts["results_revenue_prior_period"][0]) == "171.50"
    assert facts["results_operating_income_year_ago"] == (Decimal("12.17"), "조원")
    assert not any(k.startswith(("results_net_income", "results_pretax")) for k in facts)


def test_naver_results_in_hundred_million_won() -> None:
    facts = _facts("results", CLASSIFIER / "20260807800028.xml")
    assert facts["results_revenue_current"][1] == "억원"
    assert "results_net_income_attributable_current" not in facts  # NAVER's form has no row


def test_change_in_revenue_or_profit_structure() -> None:
    facts = _facts("change", DOCUMENTS / "20260129800345.xml")
    assert facts == {
        "change_statement": ("연결", None),
        "change_period_start": (datetime.date(2025, 1, 1), None),
        "change_period_end": (datetime.date(2025, 12, 31), None),
        "change_prior_start": (datetime.date(2024, 1, 1), None),
        "change_prior_end": (datetime.date(2024, 12, 31), None),
        "change_revenue_current": (Decimal("186254472000"), "천원"),
        "change_revenue_prior": (Decimal("175231153000"), "천원"),
        "change_operating_income_current": (Decimal("11467851000"), "천원"),
        "change_operating_income_prior": (Decimal("14239592000"), "천원"),
        "change_pretax_income_current": (Decimal("13841903000"), "천원"),
        "change_pretax_income_prior": (Decimal("17781436000"), "천원"),
        "change_net_income_current": (Decimal("10364775000"), "천원"),
        "change_net_income_prior": (Decimal("13229908000"), "천원"),
    }


def test_unit_sales_hyundai_and_kia() -> None:
    hyundai = _facts("units", CLASSIFIER / "20261102800520.xml")
    assert hyundai["units_total_current"] == (Decimal("329773"), "대")
    assert hyundai["units_total_year_ago"] == (Decimal("352083"), "대")
    assert hyundai["units_total_cumulative"] == (Decimal("3218586"), "대")
    assert hyundai["units_total_cumulative_year_ago"] == (Decimal("3457429"), "대")
    assert hyundai["units_domestic_current"] == (Decimal("49042"), "대")
    assert not any(k.startswith("units_special") for k in hyundai)
    kia = _facts("units", CLASSIFIER / "20261102800493.xml")
    assert kia["units_total_current"] == (Decimal("291219"), "대")
    assert kia["units_total_year_ago"] == (Decimal("264017"), "대")
    assert kia["units_total_cumulative"] == (Decimal("2769954"), "대")
    assert kia["units_special_current"] == (Decimal("904"), "대")
    assert kia["units_period_end"] == (datetime.date(2026, 10, 31), None)


def test_cash_dividend_decisions() -> None:
    hyundai = _facts("dividend", DOCUMENTS / "20261029800269.xml")
    assert hyundai == {
        "dividend_kind": ("분기배당", None),
        "dividend_type": ("현금배당", None),
        "dividend_per_share_common": (Decimal("2500"), "원"),
        "dividend_per_share_preferred": (Decimal("2500"), "원"),
        "dividend_yield_common": (Decimal("0.8"), "%"),
        "dividend_yield_preferred": (Decimal("1.6"), "%"),
        "dividend_total": (Decimal("656885882500"), "원"),
        "dividend_record_date": (datetime.date(2026, 11, 30), None),
        "dividend_payment_date": (datetime.date(2026, 12, 30), None),
        "dividend_decision_date": (datetime.date(2026, 10, 29), None),
    }
    # SK hynix states no payment date ("-") and no other share class.
    hynix = _facts("dividend", DOCUMENTS / "20261028800045.xml")
    assert hynix["dividend_yield_common"] == (Decimal("1.56"), "%")
    assert "dividend_payment_date" not in hynix
    assert "dividend_per_share_preferred" not in hynix
    # A correction's table of changed items is skipped; the form after it is read.
    corrected = _facts("dividend", DOCUMENTS / "20260331802678.xml")
    assert corrected["dividend_kind"] == ("결산배당", None)
    assert corrected["dividend_total"] == (Decimal("153681050950"), "원")


def test_outlook_keeps_the_before_and_after_of_a_correction() -> None:
    hyundai = _facts("outlook", DOCUMENTS / "20261029800240.xml")
    assert hyundai["outlook_year_y1"] == ("2026", None)
    assert hyundai["outlook_item1_label"] == ("2026년 판매목표(대수)", None)
    assert hyundai["outlook_item1_y1"] == (Decimal("4000000"), "대수")
    assert hyundai["outlook_item2_label"] == ("2026년 판매목표(대수)-국내", None)
    assert hyundai["outlook_change1_before"] == (Decimal("4158300"), "대수")
    assert hyundai["outlook_change1_after"] == (Decimal("4000000"), "대수")
    assert hyundai["outlook_change3_before"] == (Decimal("3458300"), "대수")
    biologics = _facts("outlook", DOCUMENTS / "20261021800395.xml")
    assert biologics["outlook_revenue_y1"] == (Decimal("54684"), "억원")
    assert biologics["outlook_change1_before"] == (Decimal("53200"), "억원")
    assert biologics["outlook_change1_after"] == (Decimal("54684"), "억원")
    assert biologics["outlook_start_y1"] == (datetime.date(2026, 1, 1), None)


def test_outlook_stops_before_the_comparison_with_results() -> None:
    # The form's later table compares the earlier outlook with results (전망 | 실적 | 오차율);
    # none of it is stored.
    rows = _rows(DOCUMENTS / "20261029800240.xml")
    assert any("오차율" in "".join(row) for row in rows)
    keys = {f.key for f in parse_table_facts("outlook", rows)}
    assert all(k.startswith("outlook_") for k in keys)
    assert len(keys) == 16


def test_an_unparseable_table_gives_no_facts() -> None:
    rows = _rows(DOCUMENTS / "20261029800228.xml")
    broken = [[cell.replace("45,110,247", "45,11O,247") for cell in row] for row in rows]
    assert parse_table_facts("results", rows)
    assert parse_table_facts("results", broken) == []
    # Another form's rows are not this table.
    assert parse_table_facts("results", _rows(DOCUMENTS / "20261029800269.xml")) == []
    assert parse_table_facts("dividend", rows) == []
    # 장래사업ㆍ경영계획 is prose with no outlook table.
    assert parse_table_facts("outlook", _rows(DOCUMENTS / "20261029800102.xml")) == []


def test_an_unknown_results_row_gives_no_facts() -> None:
    rows = _rows(DOCUMENTS / "20261029800228.xml")
    renamed = [["새항목", *row[1:]] if row and row[0].strip() == "영업이익" else row for row in rows]
    assert parse_table_facts("results", renamed) == []


def test_the_korean_minus_sign_is_negative() -> None:
    rows = _rows(DOCUMENTS / "20260129800345.xml")
    marked = [[("△" + c if c.strip() == "14,239,592,000" else c) for c in row] for row in rows]
    facts = {f.key: f for f in parse_table_facts("change", marked)}
    assert facts["change_operating_income_prior"].value_decimal == Decimal("-14239592000")


def test_an_unknown_table_is_an_error() -> None:
    with pytest.raises(KeyError):
        parse_table_facts("nope", [])
