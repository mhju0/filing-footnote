"""Facts from DART exchange-filing tables (D78), on saved real documents."""

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


# -- columns are found by their header text, not their position ----------------------------------

KIA_UNITS = CLASSIFIER / "20261102800493.xml"


def _swap(row: list[str], a: int, b: int) -> list[str]:
    row = list(row)
    row[a], row[b] = row[b], row[a]
    return row


def _units_rows(swap: tuple[int, int] | None = None, rename: tuple[str, str] | None = None):
    """Kia's sales rows, with two columns of every row of both tables swapped, or a heading
    renamed in both headers."""
    out, in_table = [], False
    for row in _rows(KIA_UNITS):
        first = "".join(row[0].split()) if row else ""
        if first.startswith("구분") and "단위" in first:
            in_table = True
            if rename:
                row = [c.replace(*rename) for c in row]
        elif not first.startswith("판매대수") and first not in ("합계", "계", "총계"):
            in_table = False
        if in_table and swap:
            row = _swap(row, *swap)
        out.append(row)
    return out


def test_unit_sales_columns_are_found_by_heading() -> None:
    # 당기 (column 1) and 전년동기 (column 5) swapped in both tables: the same values.
    facts = {f.key: f.value_decimal for f in parse_table_facts("units", _units_rows((1, 5)))}
    assert facts["units_total_current"] == Decimal("291219")
    assert facts["units_total_year_ago"] == Decimal("264017")
    assert facts["units_total_cumulative"] == Decimal("2769954")
    original = {f.key: f.value_decimal for f in parse_table_facts("units", _rows(KIA_UNITS))}
    assert facts == original


@pytest.mark.parametrize(
    "rename",
    [("전년동기실적", "비교실적"), ("전년동기누적 (", "비교누적 ("), ("전기실적", "당기실적")],
    ids=["missing year-ago", "missing cumulative year-ago", "repeated current"],
)
def test_a_missing_or_repeated_sales_heading_gives_no_facts(rename) -> None:
    assert parse_table_facts("units", _units_rows(rename=rename)) == []


HYUNDAI_RESULTS = DOCUMENTS / "20261029800228.xml"


def _results_rows(edit) -> list[list[str]]:
    """Hyundai's results rows with ``edit(row, kind)`` applied to the table's rows; kind is
    top, sub, current (당해실적, two label cells) or cumulative (누계실적, one)."""
    rows = _rows(HYUNDAI_RESULTS)
    top = next(i for i, r in enumerate(rows) if r[0].strip() == "구분" and "당기실적" in r)
    out = []
    for index, row in enumerate(rows):
        if index == top:
            row = edit(row, "top")
        elif index == top + 1:
            row = edit(row, "sub")
        elif len(row) > 1 and row[1].strip() == "당해실적":
            row = edit(row, "current")
        elif row and row[0].strip() == "누계실적":
            row = edit(row, "cumulative")
        out.append(row)
    return out


def _values(rows) -> dict[str, object]:
    return {f.key: f.value_decimal for f in parse_table_facts("results", rows)}


def test_results_columns_are_found_by_heading() -> None:
    # 당기실적 and 전년동기실적 swapped: top-row cells 1 and 4, data columns 0 and 4.
    offset = {"sub": 0, "current": 2, "cumulative": 1}

    def swap(row, kind):
        if kind == "top":
            return _swap(row, 1, 4)
        return _swap(row, offset[kind], offset[kind] + 4)

    swapped = _values(_results_rows(swap))
    assert swapped["results_revenue_current"] == Decimal("45110247")
    assert swapped["results_revenue_year_ago"] == Decimal("46721448")
    assert swapped["results_revenue_cumulative_year_ago"] == Decimal("139415886")
    assert swapped == _values(_rows(HYUNDAI_RESULTS))


def test_results_without_the_turnaround_columns_read_the_same_values() -> None:
    # No 흑자적자전환여부 column under either 대비 heading (data columns 3 and 6).
    offset = {"sub": 0, "current": 2, "cumulative": 1}

    def drop(row, kind):
        if kind == "top":
            return row
        base = offset[kind]
        return [c for i, c in enumerate(row) if i not in (base + 3, base + 6)]

    dropped = _values(_results_rows(drop))
    assert dropped["results_operating_income_year_ago"] == Decimal("2537266")
    assert dropped == _values(_rows(HYUNDAI_RESULTS))


@pytest.mark.parametrize(
    "edit",
    [
        lambda row, kind: [c.replace("전기실적", "직전실적") for c in row] if kind == "top" else row,
        lambda row, kind: [c.replace("전기실적", "당기실적") for c in row] if kind == "top" else row,
        lambda row, kind: row[:-1] if kind == "current" else row,
    ],
    ids=["missing prior period", "repeated current", "row shorter than its header"],
)
def test_a_results_header_that_does_not_match_gives_no_facts(edit) -> None:
    assert parse_table_facts("results", _results_rows(edit)) == []


# -- outlook item units --------------------------------------------------------------------------


def test_outlook_rows_take_only_a_known_unit() -> None:
    rows = _rows(DOCUMENTS / "20261021800395.xml")
    at = next(i for i, r in enumerate(rows) if r[0].strip() == "당기순이익") + 1
    extra = [
        ["매출액(연결)", "60,000", "-", "-"],  # a results metric: the table's unit
        ["영업이익률", "12.5", "-", "-"],  # a ratio with no unit stated: not stored
        ["영업이익률(연결)", "12.5", "-", "-"],  # 연결 is not a unit
        ["-국내", "5.0", "-", "-"],  # belongs to the row above, so not stored either
        ["판매목표(대수)", "1,000", "-", "-"],
    ]
    facts = {f.key: f for f in parse_table_facts("outlook", [*rows[:at], *extra, *rows[at:]])}
    labels = {k: f.value_text for k, f in facts.items()
              if k.startswith("outlook_item") and k.endswith("_label")}  # fmt: skip
    assert labels == {"outlook_item1_label": "매출액(연결)", "outlook_item2_label": "판매목표(대수)"}
    assert (facts["outlook_item1_y1"].value_decimal, facts["outlook_item1_y1"].unit) == (
        Decimal("60000"), "억원")  # fmt: skip
    assert (facts["outlook_item2_y1"].value_decimal, facts["outlook_item2_y1"].unit) == (
        Decimal("1000"), "대수")  # fmt: skip


def test_an_outlook_table_in_an_unknown_unit_gives_no_facts() -> None:
    rows = [[c.replace("단위 : 억원", "단위 : 주") for c in r]
            for r in _rows(DOCUMENTS / "20261021800395.xml")]  # fmt: skip
    assert parse_table_facts("outlook", rows) == []


# -- a correction's changed items are not the form -----------------------------------------------


def _facts_of(table: str, rows) -> dict[str, object]:
    return {
        f.key: f.value_decimal if f.value_decimal is not None else f.value_text
        for f in parse_table_facts(table, rows)
    }


def test_a_corrected_change_filing_reads_the_form_not_the_changed_items() -> None:
    block = [["4. 정정사항"], ["정정항목", "정정전", "정정후"],
             ["1. 재무제표의 종류", "별도", "연결"], ["-"]]  # fmt: skip
    facts = _facts_of("change", block + _rows(DOCUMENTS / "20260129800345.xml"))
    assert facts["change_statement"] == "연결"
    assert facts["change_revenue_current"] == Decimal("186254472000")


def test_a_corrected_dividend_keeps_no_stale_value_from_the_changed_items() -> None:
    rows = _rows(DOCUMENTS / "20260331802678.xml")
    header = next(i for i, r in enumerate(rows) if r[:1] == ["정정항목"])
    listed = [["1. 배당구분", "분기배당", "결산배당"],
              ["7. 배당금지급 예정일자", "2026-04-30", "2026-04-20"]]  # fmt: skip
    facts = _facts_of("dividend", [*rows[: header + 1], *listed, *rows[header + 1 :]])
    assert facts["dividend_kind"] == "결산배당"  # the form's cell, not 정정전
    # The form's 지급 예정일자 is "-": no fact, not the value the correction block lists.
    assert "dividend_payment_date" not in facts
    assert facts["dividend_total"] == Decimal("153681050950")
