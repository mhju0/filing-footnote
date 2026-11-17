"""DART event data: value parsing, fact extraction, structured fetchers, document text.

Offline. Inputs are the real responses saved in ``tests/fixtures/events/dart`` (M1 and M3).
"""

from __future__ import annotations

import ast
import asyncio
import datetime
import json
import logging
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.clients import dart_events
from app.clients.dart import DartApiError, DartClient
from app.clients.dart_events import (
    EventValueError,
    ExtractedFact,
    endpoint_for_report_key,
    extract_facts,
    fetch_structured_events,
    load_facts_contract,
    parse_correction_target,
    parse_event_count,
    parse_event_date,
    parse_event_decimal,
    parse_structured_payload,
    read_event_document,
)
from app.config import Settings
from tests.event_fakes import DART, FakeDartClient


def structured_rows(endpoint: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted((DART / "structured").glob(f"{endpoint}_*.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8"))["list"])
    return rows


def by_key(facts: list[ExtractedFact]) -> dict[str, ExtractedFact]:
    return {f.key: f for f in facts}


# -- value parsing -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3,572,800,000,000", Decimal("3572800000000")),
        ("1.8", Decimal("1.8")),
        ("0.0", Decimal("0.0")),
        ("100", Decimal("100")),
        ("-5", Decimal("-5")),
        ("1,234.50", Decimal("1234.50")),
        ("-", None),
        ("", None),
        ("  -  ", None),
        (None, None),
    ],
)
def test_parse_event_decimal(raw, expected) -> None:
    result = parse_event_decimal(raw)
    assert result == expected
    if expected is not None:
        assert isinstance(result, Decimal)
        assert str(result) == str(expected)  # exact digits, no float round trip


@pytest.mark.parametrize(
    "raw",
    [
        "1,2,3", "12,34", "1e5", "NaN", "Infinity", "약 100", "1.2.3", "--5", "₩100", "1,000원",
        # Only ASCII digits: full-width and other Unicode digits are not numbers here.
        "１２３", "1,２３４", "١٢٣", "१२३",
        # Comma grouping must be well formed.
        "0,123", "1,23", "1,2345", "01,234", ",123", "1234,567", "1,234,56",
    ],
)  # fmt: skip
def test_parse_event_decimal_rejects_non_numbers(raw) -> None:
    with pytest.raises(EventValueError):
        parse_event_decimal(raw)


@pytest.mark.parametrize("raw", ["２０２６년 01월 30일", "２０２６０８３１", "2026년 ０１월 30일"])
def test_parse_event_date_accepts_ascii_digits_only(raw) -> None:
    with pytest.raises(EventValueError):
        parse_event_date(raw)


def test_decimal_keeps_digits_a_float_would_lose() -> None:
    assert parse_event_decimal("9,007,199,254,740,993") == Decimal("9007199254740993")
    assert parse_event_decimal("0.1") + parse_event_decimal("0.2") == Decimal("0.3")


def test_parse_event_count_needs_a_whole_non_negative_number() -> None:
    assert parse_event_count("22,000,000") == Decimal("22000000")
    assert parse_event_count("-") is None
    for bad in ("1.5", "-3"):
        with pytest.raises(EventValueError):
            parse_event_count(bad)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026년 01월 30일", datetime.date(2026, 1, 30)),
        ("2026년 1월 5일", datetime.date(2026, 1, 5)),
        ("20260831", datetime.date(2026, 8, 31)),
        ("-", None),
        ("", None),
    ],
)
def test_parse_event_date(raw, expected) -> None:
    assert parse_event_date(raw) == expected


@pytest.mark.parametrize("raw", ["2026년 02월 30일", "2026-01-30", "2026.01.30", "내년 1월", "20261301"])
def test_parse_event_date_rejects_other_text(raw) -> None:
    with pytest.raises(EventValueError):
        parse_event_date(raw)


# -- contract ------------------------------------------------------------------------------------


def test_contract_fields_are_well_formed_and_present_in_real_responses() -> None:
    contract = load_facts_contract()
    kinds = set(contract["kinds"])
    assert {s["endpoint"] for s in contract["endpoints"]} >= {"tsstkAqDecsn", "piicDecsn"}
    for spec in contract["endpoints"]:
        keys = [f["key"] for f in spec["fields"]]
        sources = [f["source_field"] for f in spec["fields"]]
        assert len(set(keys)) == len(keys) and len(set(sources)) == len(sources)
        rows = structured_rows(spec["endpoint"])
        assert rows, f"no fixture rows for {spec['endpoint']}"
        seen = set().union(*(r.keys() for r in rows))
        for field in spec["fields"]:
            assert field["kind"] in kinds
            assert field["ko"] and field["en"]
            assert field["source_field"] in seen, field["source_field"]
            assert (field["unit"] is None) == (field["kind"] in ("date", "text"))


def test_report_names_resolve_to_endpoints() -> None:
    assert endpoint_for_report_key("자기주식취득결정") == "tsstkAqDecsn"
    assert endpoint_for_report_key("자기주식처분결정") == "tsstkDpDecsn"
    assert endpoint_for_report_key("유상증자결정") == "piicDecsn"
    assert endpoint_for_report_key("현금ㆍ현물배당결정") is None


# -- fact extraction -----------------------------------------------------------------------------


def test_buyback_acquisition_facts_are_exact_and_skip_absent_values() -> None:
    row = next(r for r in structured_rows("tsstkAqDecsn") if r["rcept_no"] == "20260129000003")
    facts = by_key(extract_facts("tsstkAqDecsn", row))

    assert facts["acquire_shares_common"].value_decimal == Decimal("22000000")
    assert facts["acquire_amount_common"].value_decimal == Decimal("3572800000000")
    assert facts["acquire_amount_common"].unit == "KRW"
    assert facts["acquire_ratio_common"].value_decimal == Decimal("1.8")
    assert facts["acquire_period_start"].value_date == datetime.date(2026, 1, 30)
    assert facts["acquire_period_end"].value_date == datetime.date(2026, 4, 29)
    assert facts["decision_date"].value_date == datetime.date(2026, 1, 28)
    assert facts["acquire_purpose"].value_text == "임직원 주식보상"
    # "-" in the source: no fact, not a zero.
    assert "acquire_shares_other" not in facts
    assert "acquire_amount_other" not in facts
    assert not any(f.error for f in facts.values())
    for fact in facts.values():
        assert not isinstance(fact.value_decimal, float)


def test_rights_issue_facts_from_a_corrected_filing() -> None:
    row = json.loads((DART / "structured" / "piicDecsn_035420.json").read_text())["list"][0]
    facts = by_key(extract_facts("piicDecsn", row))
    assert row["rcept_no"] == "20261103000311"
    assert facts["new_shares_common"].value_decimal == Decimal("6558435")
    assert facts["par_value"].value_decimal == Decimal("100")
    assert facts["shares_before_common"].value_decimal == Decimal("152126544")
    assert facts["use_other"].value_decimal == Decimal("1341199957500")
    assert facts["issue_method"].value_text == "제3자배정증자"
    # Every other use-of-proceeds field is "-".
    assert not {k for k in facts if k.startswith("use_")} - {"use_other"}
    assert "new_shares_other" not in facts


def test_every_real_row_extracts_without_errors_and_with_typed_values() -> None:
    contract_kinds = {
        spec["endpoint"]: {f["key"]: f["kind"] for f in spec["fields"]}
        for spec in load_facts_contract()["endpoints"]
    }
    total = 0
    for endpoint, kinds in contract_kinds.items():
        for row in structured_rows(endpoint):
            for fact in extract_facts(endpoint, row):
                total += 1
                assert fact.error is None, (endpoint, row["rcept_no"], fact)
                assert fact.kind == kinds[fact.key]
                if fact.kind == "date":
                    assert isinstance(fact.value_date, datetime.date)
                elif fact.kind == "text":
                    assert fact.value_text
                else:
                    assert type(fact.value_decimal) is Decimal
    assert total > 100


def test_an_unparseable_value_is_an_error_fact_not_a_guess() -> None:
    row = {
        "aqpln_stk_ostk": "약 22,000,000",
        "aqpln_prc_ostk": "3,572,800,000,000",
        "aqexpd_bgd": "곧 시작",
        "aq_dd": "2026년 02월 30일",
        "aq_wtn_div_ostk_rt": 1.8,
    }
    facts = by_key(extract_facts("tsstkAqDecsn", row))
    assert facts["acquire_amount_common"].value_decimal == Decimal("3572800000000")
    for key in ("acquire_shares_common", "acquire_period_start", "decision_date"):
        fact = facts[key]
        assert fact.error and fact.raw == row[fact.source_field]
        assert fact.value_decimal is None and fact.value_date is None and fact.value_text is None
    # A JSON number is not the documented string form; it is reported, not coerced.
    assert "non-string" in (facts["acquire_ratio_common"].error or "")


def test_text_is_whitespace_normalised() -> None:
    row = {"dp_pp": "사외이사 주식 보수 및\n장기성과급 행사에 따른\n주식 보수 지급"}
    fact = by_key(extract_facts("tsstkDpDecsn", row))["dispose_purpose"]
    assert fact.value_text == "사외이사 주식 보수 및 장기성과급 행사에 따른 주식 보수 지급"
    assert fact.raw == row["dp_pp"]


def test_unknown_endpoint_is_refused() -> None:
    with pytest.raises(KeyError):
        extract_facts("noSuchDecsn", {})


def test_no_float_in_the_event_client() -> None:
    tree = ast.parse(Path(dart_events.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "float" not in names
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(tree))


# -- structured endpoints ------------------------------------------------------------------------


def test_parse_structured_payload_statuses() -> None:
    assert parse_structured_payload("piicDecsn", {"status": "013", "message": "무자료"}).events == []
    with pytest.raises(DartApiError, match="020"):
        parse_structured_payload("piicDecsn", {"status": "020", "message": "제한"})
    with pytest.raises(DartApiError):
        parse_structured_payload("piicDecsn", ["not", "an", "object"])


def test_parse_structured_payload_reports_rows_it_cannot_join() -> None:
    payload = {
        "status": "000",
        "list": [{"corp_code": "1", "nstk_ostk_cnt": "5"}, {"rcept_no": "R2", "corp_code": "1"}],
    }
    result = parse_structured_payload("piicDecsn", payload)
    assert [e.rcept_no for e in result.events] == ["R2"]
    assert result.errors == ["piicDecsn: row 0 has no rcept_no"]


def test_fetch_structured_events_uses_the_endpoint_and_returns_facts() -> None:
    client = FakeDartClient("035420")
    result = asyncio.run(
        fetch_structured_events(client, "piicDecsn", "00266961", "20251118", "20261117")
    )
    assert client.calls == [("structured", "piicDecsn.json")]
    assert [e.rcept_no for e in result.events] == ["20261103000311"]
    assert result.errors == []
    assert by_key(result.events[0].facts)["new_shares_common"].value_decimal == Decimal("6558435")


def test_fetch_structured_events_rejects_unknown_endpoint_before_any_request() -> None:
    client = FakeDartClient("035420")
    with pytest.raises(KeyError):
        asyncio.run(fetch_structured_events(client, "noSuchDecsn", "1", "20260101", "20261231"))
    assert client.calls == []


# -- documents -----------------------------------------------------------------------------------


def test_dsd_document_yields_text_and_prose() -> None:
    doc = read_event_document((DART / "document" / "20260821000616.xml").read_bytes())
    assert doc.format == "dsd"
    assert len(doc.prose) == 2
    assert "자기주식 취득 결정" in doc.text
    assert "<" not in doc.text


def test_xforms_document_is_decoded_as_utf8_and_rows_are_read() -> None:
    raw = (DART / "document" / "20261029800101.xml").read_bytes()
    assert b"euc-kr" in raw  # declared euc-kr, bytes are UTF-8
    doc = read_event_document(raw)
    assert doc.format == "xforms"
    assert ["1. 배당구분", "분기배당"] in doc.rows
    assert ["3. 1주당 배당금(원)", "보통주식", "4,601"] in doc.rows
    assert "color:" not in doc.text and "font-family" not in doc.text  # style block dropped


def test_correction_target_from_a_real_correction() -> None:
    doc = read_event_document((DART / "correction" / "20261103000311.xml").read_bytes())
    target = parse_correction_target(doc.text)
    assert target is not None
    assert target.name == "주요사항보고서(유상증자결정)"
    assert target.first_filed == datetime.date(2026, 7, 27)


def test_correction_target_absent_or_unmatched() -> None:
    assert parse_correction_target("주요사항보고서(유상증자결정) 본문") is None
    assert parse_correction_target("") is None


def test_an_impossible_first_filing_date_is_reported_with_the_date() -> None:
    bad = "1. 정정대상 공시서류 : 가 2. 정정대상 공시서류의 최초제출일 : 2026년 13월 40일"
    target = parse_correction_target(bad)
    assert target is not None and target.first_filed is None
    assert target.name == "가"
    assert "2026년 13월 40일" in (target.error or "")

    iso = "정정관련 공시서류 주식소각결정 2. 정정관련 공시서류제출일 2026-02-30 3. 정정사유"
    target = parse_correction_target(iso)
    assert target is not None and target.first_filed is None
    assert "2026-02-30" in (target.error or "")


# I-type (exchange) corrections, saved live read-only bodies: the wording differs from the DSD
# one ("정정관련 공시서류" / "공시서류제출일", no colon) and the date is ISO or Korean.
@pytest.mark.parametrize(
    ("rcept_no", "name", "first_filed"),
    [
        ("20261026800524", "주식소각결정", datetime.date(2026, 8, 19)),
        ("20261102800004", "단일판매ㆍ공급계약체결", datetime.date(2020, 11, 3)),
        ("20261029800099", "연결재무제표기준영업(잠정)실적(공정공시)", datetime.date(2026, 10, 8)),
    ],
)
def test_exchange_correction_target_from_real_bodies(rcept_no, name, first_filed) -> None:
    doc = read_event_document((DART / "correction" / f"{rcept_no}.xml").read_bytes())
    assert doc.format == "xforms"
    target = parse_correction_target(doc.text)
    assert target is not None, doc.text[:300]
    assert target.error is None
    assert (target.name.replace(" ", ""), target.first_filed) == (name, first_filed)


def test_exchange_correction_names_use_the_lists_middle_dot_and_spacing() -> None:
    # The body writes "단일판매·공급계약 체결"; the list and classifier use "단일판매ㆍ공급계약체결".
    text = "정정관련 공시서류 단일판매·공급계약 체결 2. 정정관련 공시서류제출일 2026-08-19 3."
    target = parse_correction_target(text)
    assert target is not None and target.first_filed == datetime.date(2026, 8, 19)
    from app.filings.categories import normalise_dart_name

    assert normalise_dart_name(target.name)[0] == normalise_dart_name("단일판매ㆍ공급계약체결")[0]


# -- crtfc_key never leaks from the structured path (through the real DartClient._get) -----------

_SECRET = "SYNTHETIC_STRUCTURED_KEY_0123456789"


def _structured_call(handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = DartClient(Settings(_env_file=None, dart_api_key=_SECRET), client=transport)
            return await fetch_structured_events(
                client, "piicDecsn", "00266961", "20251118", "20261117"
            )

    return asyncio.run(run())


def test_structured_request_sends_the_key_but_failures_do_not_leak_it(caplog) -> None:
    seen: list[str] = []

    def http_error(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["crtfc_key"])
        return httpx.Response(500, request=request)

    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError) as raised:
        _structured_call(http_error)
    assert seen == [_SECRET]  # the real request carries it
    for text in (str(raised.value), repr(raised.value), str(raised.value.request.url)):
        assert _SECRET not in text
    assert "crtfc_key=%2A%2A%2A" in str(raised.value.request.url)
    assert _SECRET not in caplog.text


def test_structured_transport_failure_does_not_leak_the_key(caplog) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connect failed for {request.url}", request=request)

    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.ConnectError) as raised:
        _structured_call(refuse)
    assert _SECRET not in str(raised.value) and _SECRET not in repr(raised.value)
    assert _SECRET not in str(raised.value.request.url)
    assert _SECRET not in caplog.text


def test_structured_api_error_status_does_not_leak_the_key() -> None:
    def rate_limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "020", "message": "요청 제한"}, request=request)

    with pytest.raises(DartApiError) as raised:
        _structured_call(rate_limited)
    assert "020" in str(raised.value) and _SECRET not in str(raised.value)
