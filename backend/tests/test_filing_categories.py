"""Filing category contract and classifier, checked against the M1 and M2 fixtures (no network)."""

from __future__ import annotations

import copy
import gzip
import json
import random
from functools import lru_cache
from pathlib import Path

import pytest

from app.filings import categories
from app.filings.categories import (
    Classification,
    classify_dart,
    classify_sec,
    load_contract,
    normalise_dart_name,
    normalise_text,
)

EVENTS = Path(__file__).parent / "fixtures" / "events"
CLASSIFIER = EVENTS / "classifier"


@lru_cache(maxsize=1)
def dart_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for path in sorted((EVENTS / "dart" / "list").glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8"))["list"]:
            rows[str(row["rcept_no"])] = row
    return rows


@lru_cache(maxsize=1)
def dart_bodies() -> dict[str, str]:
    return {
        p.stem: p.read_text(encoding="utf-8")
        for p in (CLASSIFIER / "dart" / "document").glob("*.xml")
    }


@lru_cache(maxsize=1)
def sec_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for path in sorted((EVENTS / "sec" / "submissions_8k").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["rows"]:
            rows[row["accessionNumber"]] = {"ticker": payload["ticker"], **row}
    return rows


@lru_cache(maxsize=1)
def sec_texts() -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[str]] = {}
    for path in (CLASSIFIER / "sec").glob("*.json.gz"):
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        out[payload["accession"]] = [(d["type"], d["text"]) for d in payload["documents"]]
    return out


def classify_dart_row(rcept_no: str) -> Classification:
    row = dart_rows()[rcept_no]
    return classify_dart(row["report_nm"], dart_bodies().get(rcept_no))


def classify_sec_row(accession: str) -> Classification:
    row = sec_rows()[accession]
    return classify_sec(row["form"], row["items"], sec_texts().get(accession))


# -- coverage over every fixture row -----------------------------------------------------------

# Names the owner has not placed in a category or an exclusion. They are excluded as no_rule.
KNOWN_NO_RULE = {
    "매출액또는손익구조30%(대규모법인은15%)이상변경",
    "수시공시의무관련사항(공정공시)",
    "타인에대한채무보증결정",
    "타인에대한담보제공결정",
    "금전대여결정",
    "중대재해발생",
    "생산중단",
    "생산재개(자율공시)",
    "파생상품거래손실발생",
    "투자판단관련주요경영사항",
}


def test_fixture_sizes() -> None:
    assert len(dart_rows()) == 626
    assert len(sec_rows()) == 114
    assert len(sec_texts()) == 76


def test_every_dart_row_is_categorised_or_excluded_with_a_named_reason() -> None:
    contract = load_contract()
    reasons = set(contract["excluded_reasons"])
    categories = {c["key"] for c in contract["categories"]}
    for rcept_no, row in dart_rows().items():
        result = classify_dart_row(rcept_no)
        assert (result.category in categories) != (result.excluded_reason in reasons), row
        assert result.matched_rule


def test_dart_no_rule_names_are_exactly_the_known_leftovers() -> None:
    unexpected = set()
    for rcept_no, row in dart_rows().items():
        if classify_dart_row(rcept_no).excluded_reason == "no_rule":
            key = normalise_dart_name(row["report_nm"])[0]
            if not key.startswith(tuple(KNOWN_NO_RULE)):
                unexpected.add(key)
    assert not unexpected


def test_dart_sample_has_no_needs_body_and_every_plain_earnings_body_is_present() -> None:
    plain = 0
    for rcept_no, row in dart_rows().items():
        result = classify_dart_row(rcept_no)
        assert result.excluded_reason != "needs_body", rcept_no
        if normalise_dart_name(row["report_nm"])[0].startswith("영업(잠정)실적"):
            plain += 1
            assert rcept_no in dart_bodies()
            assert result.matched_rule in ("dart.earnings.monthly", "dart.earnings.period")
    assert plain == 28 == len(dart_bodies())


def test_no_listed_name_is_ever_no_rule() -> None:
    dart = load_contract()["dart"]
    listed = [p for e in dart["exclusions"] + dart["rules"] for p in e["prefixes"]]
    listed += dart["earnings"]["consolidated_prefixes"] + dart["earnings"]["plain_prefixes"]
    for rcept_no, row in dart_rows().items():
        key = normalise_dart_name(row["report_nm"])[0]
        if key.startswith(tuple(listed)):
            assert classify_dart_row(rcept_no).excluded_reason != "no_rule", key


def test_every_sec_row_is_categorised_or_excluded_with_a_named_reason() -> None:
    contract = load_contract()
    reasons = set(contract["excluded_reasons"])
    categories = {c["key"] for c in contract["categories"]}
    for accession in sec_rows():
        result = classify_sec_row(accession)
        assert (result.category in categories) != (result.excluded_reason in reasons), accession
        assert result.excluded_reason not in ("no_rule", "needs_body"), accession


def test_sec_sample_texts_belong_to_body_item_filings() -> None:
    body_items = set(load_contract()["sec"]["body_items"])
    for accession in sec_texts():
        items = {i.strip() for i in sec_rows()[accession]["items"].split(",")}
        assert items & body_items


# -- golden table: real examples ---------------------------------------------------------------

# rcept_no -> (category, subsidiary, is_correction, basis)
DART_GOLDEN = {
    "20261029800087": ("earnings", False, False, "consolidated"),  # Samsung Electronics Q3
    "20261029800099": ("earnings", False, True, "consolidated"),  # [기재정정] of the above
    "20261112800028": ("earnings", False, False, "separate"),  # NAVER plain, 3 months
    "20260206800015": ("earnings", False, False, "separate"),  # NAVER plain, Q4 2025
    "20261102800493": ("unit_sales", False, False, None),  # Kia, October 2026
    "20251201800591": ("unit_sales", False, False, None),  # Kia, November 2025
    "20261102800520": ("unit_sales", False, False, None),  # Hyundai, October 2026
    "20251201800598": ("unit_sales", False, False, None),  # Hyundai, November 2025
    "20260821000616": ("buyback", False, False, None),  # 자기주식취득결정
    "20260826800261": ("buyback", False, False, None),  # 주식소각결정
    "20261026800524": ("buyback", False, True, None),  # [기재정정]주식소각결정
    "20261029800101": ("dividend", False, False, None),
    "20260206800010": ("dividend", False, False, None),
    "20260624000420": ("capital", False, False, None),  # 유상증자결정
    "20260212001501": ("capital", False, False, None),  # 감자결정
    "20260624000423": ("capital", False, False, None),  # 해외증권시장주권등상장결정
    "20260303801345": ("capital", True, False, None),  # 유상증자결정(종속회사의주요경영사항)
    "20261106800553": ("capital", False, False, None),  # 발행결과(자율공시)
    "20261116800009": ("capital", False, False, None),  # 청약결과(자율공시)
    "20261105800618": ("capital", False, False, None),  # 신주발행가액(안내공시)
    "20260428800513": ("capital", False, False, None),  # 자기교환사채만기전취득결정
    "20260128800915": ("deal", False, False, None),  # 타법인주식및출자증권취득결정
    "20261103800043": ("deal", False, False, None),  # 단일판매ㆍ공급계약체결
    "20261002800830": ("deal", False, False, None),  # 단일판매ㆍ공급계약체결(자율공시)
    "20260807800613": ("deal", False, False, None),  # 신규시설투자등
    "20260128800964": ("deal", True, False, None),  # 영업양수결정(종속회사의주요경영사항)
    "20260331803716": ("deal", True, True, None),  # [기재정정]…(자율공시)(종속회사의주요경영사항)
    "20251128800894": ("leadership", False, False, None),
    "20260326802256": ("leadership", False, False, None),
    "20260225801485": ("legal", False, False, None),  # 소송등의판결ㆍ결정
    "20260223801173": ("legal", False, False, None),  # 소송등의제기ㆍ신청(경영권분쟁소송)
}


@pytest.mark.parametrize("rcept_no", sorted(DART_GOLDEN))
def test_dart_golden(rcept_no: str) -> None:
    category, subsidiary, is_correction, basis = DART_GOLDEN[rcept_no]
    result = classify_dart_row(rcept_no)
    assert (result.category, result.subsidiary, result.is_correction, result.basis) == (
        category,
        subsidiary,
        is_correction,
        basis,
    )
    assert result.excluded_reason is None


# accession -> category
SEC_GOLDEN = {
    "0000320193-26-000024": "earnings",  # Apple results
    "0001628280-26-066738": "earnings",  # Tesla Q3 update
    "0001628280-26-003837": "earnings",  # Tesla Q4 update
    "0001628280-26-064366": "unit_sales",  # Tesla Q3 production and deliveries
    "0001628280-26-000016": "unit_sales",  # Tesla Q4 production and deliveries
    "0000909832-26-000134": "buyback",  # Costco: special dividend + repurchase + 5.02
    "0000909832-26-000096": "dividend",
    "0000909832-26-000041": "dividend",
    "0001193125-26-051423": "capital",  # Alphabet notes offering, 8.01
    "0001104659-26-073562": "capital",  # Amazon notes, 8.01
    "0001104659-26-072140": "capital",  # Amazon 1.01 + 2.03: capital outranks deal
    "0001193125-26-257724": "capital",  # Alphabet 1.01 + 7.01 + 8.01 stock offering
    "0001193125-26-259830": "deal",  # Alphabet 1.01 + 3.03 + 5.03
    "0001104659-26-021050": "deal",  # Amazon 1.01 + 7.01 + 8.01 (no keyword rule hit)
    "0001140361-26-035325": "leadership",  # Apple 5.02 (8-K/A)
    "0001193125-26-448357": "leadership",  # Microsoft 5.02
    "0001193125-25-311196": "leadership",  # Microsoft 5.02 + 5.07
    "0001045810-26-000078": "deal",  # NVIDIA, definitive agreement to acquire Hugging Face (8.01)
    "0001104659-26-042880": "deal",  # Amazon, merger agreement to acquire Globalstar (7.01)
    "0001628280-25-056768": "legal",  # Meta derivative-action settlement, 8.01
}


@pytest.mark.parametrize("accession", sorted(SEC_GOLDEN))
def test_sec_golden(accession: str) -> None:
    result = classify_sec_row(accession)
    assert result.category == SEC_GOLDEN[accession]
    assert result.excluded_reason is None
    assert result.basis is None


def test_sec_8ka_is_a_correction() -> None:
    row = sec_rows()["0001140361-26-035325"]  # Apple's only 8-K/A in the window
    assert row["form"] == "8-K/A"
    assert classify_sec_row("0001140361-26-035325").is_correction is True
    assert classify_sec_row("0001140361-26-015711").is_correction is False


def test_sec_matched_rule_names_the_deciding_rule() -> None:
    assert classify_sec_row("0001628280-26-064366").matched_rule == "sec.2.02.deliveries"
    assert classify_sec_row("0001628280-26-066738").matched_rule == "sec.2.02.results"
    assert classify_sec_row("0000909832-26-000134").matched_rule == "sec.kw.buyback"
    assert classify_sec_row("0001104659-26-072140").matched_rule == "sec.item.2.03"


# -- one test per exclusion reason -------------------------------------------------------------

DART_EXCLUDED = {
    "ir_event": "기업설명회(IR)개최(안내공시)",
    "ownership_report": "최대주주등소유주식변동신고서",
    "rumor_response": "풍문또는보도에대한해명(미확정)",
    "market_action": "조회공시요구(풍문또는보도)",
    "forward_looking": "장래사업ㆍ경영계획(공정공시)",
    "shareholder_meeting": "정기주주총회결과",
    "record_date": "현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정",
    "audit_report": "감사보고서제출",
    "governance_report": "기업지배구조보고서공시",
    "sustainability_report": "지속가능경영보고서등관련사항(자율공시)",
    "compliance_program": "공정거래자율준수프로그램운영현황(안내공시)",
    "earnings_notice": "결산실적공시예고(안내공시)",
    "value_up_plan": "기업가치제고계획(자율공시) (2025년 이행현황)",
    "other_management": "기타경영사항(자율공시) (배당기준일 변경 안내)",
    "notice_only": "기타안내사항(안내공시)",
    "no_rule": "중대재해발생",
}

SEC_EXCLUDED = {
    "shareholder_vote": ("5.07,9.01", None),
    "bylaws_change": ("5.03,5.07,9.01", None),
    "exhibits_only": ("9.01", None),
    "listing_notice": ("3.01", None),
    "rights_modification": ("3.03", None),
    "trading_plan": ("8.01", ["Mr. Smith entered into a stock trading plan under Rule 10b5-1."]),
    "no_keyword_match": ("8.01", ["The company posted an investor presentation."]),
    "no_rule": ("4.02", None),
}


@pytest.mark.parametrize("reason", sorted(DART_EXCLUDED))
def test_dart_exclusion_reason(reason: str) -> None:
    result = classify_dart(DART_EXCLUDED[reason])
    assert (result.category, result.excluded_reason) == (None, reason)


def test_dart_exclusion_table_covers_every_exclusion_in_the_contract() -> None:
    contract_reasons = {e["reason"] for e in load_contract()["dart"]["exclusions"]}
    assert contract_reasons <= set(DART_EXCLUDED)


def test_dart_other_exclusion_names_from_the_contract() -> None:
    for name in (
        "주주총회소집결의",
        "임시주주총회결과",
        "주주총회집중일개최사유신고",
        "주주명부폐쇄기간또는기준일설정",
        "조회공시요구(풍문또는보도)에대한답변(미확정)",
        "연결재무제표기준영업실적등에대한전망(공정공시)",
        "임원ㆍ주요주주특정증권등소유상황보고서",
        "기업가치제고계획(자율공시)",
    ):
        assert classify_dart(name).category is None
        assert classify_dart(name).excluded_reason != "no_rule", name


@pytest.mark.parametrize("reason", sorted(SEC_EXCLUDED))
def test_sec_exclusion_reason(reason: str) -> None:
    items, texts = SEC_EXCLUDED[reason]
    result = classify_sec("8-K", items, texts)
    assert (result.category, result.excluded_reason) == (None, reason)


def test_sec_exclusion_table_covers_every_sec_exclusion_in_the_contract() -> None:
    sec = load_contract()["sec"]
    assert set(sec["item_exclusions"].values()) <= set(SEC_EXCLUDED)
    assert {e["reason"] for e in sec["no_keyword_reasons"]} <= set(SEC_EXCLUDED)


def test_real_sec_rows_excluded_with_their_reason() -> None:
    assert classify_sec_row("0001140361-26-006577").excluded_reason == "shareholder_vote"
    assert classify_sec_row("0000104169-26-000111").excluded_reason == "bylaws_change"
    assert classify_sec_row("0000104169-26-000067").excluded_reason == "trading_plan"
    assert classify_sec_row("0001104659-26-041034").excluded_reason == "no_keyword_match"


def test_wmt_10b5_1_trading_plan_notices_stay_excluded() -> None:
    for accession in ("0000104169-25-000238", "0000104169-26-000057", "0000104169-26-000067"):
        result = classify_sec_row(accession)
        assert (result.category, result.excluded_reason) == (None, "trading_plan")
        assert result.matched_rule == "sec.kw.trading_plan"


def test_trading_plan_phrase_does_not_override_a_category() -> None:
    text = "Rule 10b5-1 plan. The Board declared a cash dividend."
    assert classify_sec("8-K", "8.01", [text]).category == "dividend"


def test_keywords_read_only_primary_and_ex99_documents() -> None:
    text = "The Board declared a cash dividend."
    assert classify_sec("8-K", "8.01", [("EX-99.1", text)]).category == "dividend"
    assert classify_sec("8-K", "8.01", [("primary", text)]).category == "dividend"
    for doc_type in ("EX-1.1", "EX-4.1", "EX-5.1", "EX-10.1", "EX-101.INS"):
        result = classify_sec("8-K", "8.01", [("primary", "Other events."), (doc_type, text)])
        assert result.excluded_reason == "no_keyword_match", doc_type
    only_ex4 = classify_sec("8-K", "8.01", [("EX-4.1", text)])
    assert only_ex4.excluded_reason == "needs_body"


def test_deal_keywords_are_narrow() -> None:
    assert classify_sec("8-K", "8.01", ["NVIDIA agreed to acquire a startup."]).category == "deal"
    assert classify_sec("8-K", "8.01", ["It completed the acquisition of X."]).category == "deal"
    assert classify_sec("8-K", "7.01", ["Accelerated by acquiring Kiva in 2012."]).excluded_reason
    assert classify_sec("8-K", "2.02", ["Revenue grew; agreed to acquire X."]).category == "earnings"


def test_sec_exhibits_only_does_not_hide_a_more_specific_reason() -> None:
    assert classify_sec("8-K", "5.07,9.01").excluded_reason == "shareholder_vote"
    assert classify_sec("8-K", "9.01,3.01").excluded_reason == "listing_notice"


# -- priority ----------------------------------------------------------------------------------


def test_sec_priority_earnings_beats_dividend() -> None:
    text = "Revenue was up. The Board declared a quarterly cash dividend."
    result = classify_sec("8-K", "2.02,8.01,9.01", [text])
    assert result.category == "earnings"


def test_sec_priority_follows_contract_order() -> None:
    order = [c["key"] for c in sorted(load_contract()["categories"], key=lambda c: c["priority"])]
    assert order == [
        "earnings",
        "unit_sales",
        "buyback",
        "dividend",
        "capital",
        "deal",
        "leadership",
        "legal",
    ]
    text = (
        "The Board declared a special dividend and approved a new share repurchase program "
        "and priced an underwritten public offering."
    )
    assert classify_sec("8-K", "8.01", [text]).category == "buyback"
    assert classify_sec("8-K", "8.01,5.02", ["cash dividend"]).category == "dividend"
    assert classify_sec("8-K", "1.01,5.02", None).category == "deal"
    assert classify_sec("8-K", "5.02,1.05", None).category == "leadership"


def test_sec_delivery_report_is_not_earnings_but_a_release_with_revenue_is() -> None:
    delivery = "Q1 Production, Deliveries & Deployments. Our net income will be announced later."
    assert classify_sec("8-K", "2.02", [delivery]).category == "unit_sales"
    both = delivery + " Total revenues were reported."
    assert classify_sec("8-K", "2.02", [both]).category == "earnings"


# -- needs_body --------------------------------------------------------------------------------


def test_needs_body_is_never_guessed() -> None:
    assert classify_dart("영업(잠정)실적(공정공시)").excluded_reason == "needs_body"
    assert classify_dart("영업(잠정)실적(공정공시)", "").excluded_reason == "needs_body"
    assert classify_sec("8-K", "2.02,9.01").excluded_reason == "needs_body"
    assert classify_sec("8-K", "2.02,9.01", []).excluded_reason == "needs_body"
    assert classify_sec("8-K", "8.01", None).excluded_reason == "needs_body"
    assert classify_sec("8-K", "7.01,9.01", [""]).excluded_reason == "needs_body"


def test_body_is_not_required_when_the_name_or_item_decides() -> None:
    assert classify_dart("연결재무제표기준영업(잠정)실적(공정공시)").category == "earnings"
    assert classify_dart("현금ㆍ현물배당결정").category == "dividend"
    assert classify_sec("8-K", "5.02,9.01").category == "leadership"


def _body(period: str) -> str:
    return (
        "<html><style>.x{}</style><body><td>실적기간</td><td>당기실적</td>"
        f"<td>{period}</td><td>전기실적</td></body></html>"
    )


@pytest.mark.parametrize(
    ("period", "category", "basis"),
    [
        ("2026-10-01 ~ 2026-10-31", "unit_sales", None),
        ("2026-02-01 ~ 2026-02-28", "unit_sales", None),
        ("2026-07-01 ~ 2026-09-30", "earnings", "separate"),
        ("2026-01-01 ~ 2026-12-31", "earnings", "separate"),
        ("2026-01-01 ~ 2026-06-30", "earnings", "separate"),
    ],
)
def test_plain_earnings_period_rule(period: str, category: str, basis: str | None) -> None:
    result = classify_dart("영업(잠정)실적(공정공시)", _body(period))
    assert (result.category, result.basis) == (category, basis)


@pytest.mark.parametrize(
    "period",
    [
        "2026-09-01 ~ 2026-10-31",  # two months
        "2026-10-02 ~ 2026-10-31",  # does not start on a first day
        "2026-10-01 ~ 2026-10-30",  # does not end on a month end
        "2026-10-31 ~ 2026-10-01",  # reversed
        "2026-02-30 ~ 2026-03-31",  # impossible date
    ],
)
def test_plain_earnings_unusable_period_is_excluded(period: str) -> None:
    result = classify_dart("영업(잠정)실적(공정공시)", _body(period))
    assert (result.category, result.excluded_reason) == (None, "no_rule")


def test_plain_earnings_without_a_period_is_excluded() -> None:
    result = classify_dart("영업(잠정)실적(공정공시)", "<html>no period here</html>")
    assert result.excluded_reason == "no_rule"


# -- name normalisation ------------------------------------------------------------------------


def test_correction_prefixes_and_padding_are_stripped() -> None:
    result = classify_dart("[기재정정][첨부추가] 자기주식취득결정      ")
    assert (result.category, result.is_correction) == ("buyback", True)
    plain = classify_dart("  자기주식취득결정(자율공시) ")
    assert (plain.category, plain.is_correction) == ("buyback", False)


def test_subsidiary_marker_and_report_wrapper() -> None:
    name = "[기재정정]주요사항보고서(유상증자결정)(종속회사의주요경영사항)"
    result = classify_dart(name)
    assert (result.category, result.subsidiary, result.is_correction) == ("capital", True, True)
    parent = classify_dart("주요사항보고서(유상증자결정)")
    assert (parent.category, parent.subsidiary) == ("capital", False)


def test_unmatched_subsidiary_filing_is_excluded_like_a_parent_one() -> None:
    result = classify_dart("중대재해발생(종속회사의주요경영사항)")
    assert (result.category, result.excluded_reason, result.subsidiary) == (None, "no_rule", True)


def test_unit_sales_and_earnings_keep_subsidiary_false_for_parent_names() -> None:
    assert normalise_dart_name("영업(잠정)실적(공정공시)") == ("영업(잠정)실적(공정공시)", False, False)


# -- contract schema ---------------------------------------------------------------------------


def test_contract_categories() -> None:
    contract = load_contract()
    assert contract["version"] == 1
    categories = contract["categories"]
    keys = [c["key"] for c in categories]
    priorities = [c["priority"] for c in categories]
    assert len(set(keys)) == len(keys) == 8
    assert len(set(priorities)) == len(priorities)
    for c in categories:
        assert c["ko"].strip() and c["en"].strip()
        assert isinstance(c["priority"], int)


def test_contract_rules_reference_known_categories_and_reasons() -> None:
    contract = load_contract()
    keys = {c["key"] for c in contract["categories"]}
    reasons = set(contract["excluded_reasons"])
    dart, sec = contract["dart"], contract["sec"]
    ids = [r["id"] for r in dart["rules"] + dart["exclusions"]]
    ids += [r["id"] for r in sec["keyword_rules"]] + [e["id"] for e in sec["items"].values()]
    ids += [dart["earnings"]["id"], sec["earnings_item"]["earnings_id"]]
    ids += [sec["earnings_item"]["unit_sales_id"]]
    assert len(set(ids)) == len(ids)
    assert {r["category"] for r in dart["rules"]} <= keys
    assert {r["category"] for r in sec["keyword_rules"]} <= keys
    assert {e["category"] for e in sec["items"].values()} <= keys
    assert {e["reason"] for e in dart["exclusions"]} <= reasons
    assert set(sec["item_exclusions"].values()) <= reasons
    assert {"no_rule", "needs_body", "no_keyword_match"} <= reasons


def test_contract_matching_data_is_well_formed() -> None:
    contract = load_contract()
    dart, sec = contract["dart"], contract["sec"]
    prefixes = [p for r in dart["rules"] + dart["exclusions"] for p in r["prefixes"]]
    prefixes += dart["earnings"]["consolidated_prefixes"] + dart["earnings"]["plain_prefixes"]
    assert all(p and not any(ch.isspace() for ch in p) for p in prefixes)
    assert len(set(prefixes)) == len(prefixes)
    phrases = [p for r in sec["keyword_rules"] for p in r["phrases"]]
    phrases += sec["earnings_item"]["unit_sales_phrases"] + sec["earnings_item"]["results_phrases"]
    assert all(p == p.lower() and p.strip() == p for p in phrases)
    items = set(sec["items"]) | set(sec["item_exclusions"])
    assert not items & set(sec["keyword_items"] + [sec["earnings_item"]["item"]])
    assert set(sec["keyword_items"]) | {sec["earnings_item"]["item"]} == set(sec["body_items"])


# SEC rules no real fixture decides. Each has a named synthetic test below.
SYNTHETIC_ONLY_SEC_RULES = {
    "sec.item.1.02": "1.02",
    "sec.item.3.02": "3.02",
    "sec.item.1.05": "1.05",
    "sec.item.2.01": "2.01",
}


def test_every_contract_rule_id_is_decided_by_a_fixture_or_listed_as_synthetic() -> None:
    contract = load_contract()
    used = {classify_dart_row(r).matched_rule for r in dart_rows()}
    used |= {classify_sec_row(a).matched_rule for a in sec_rows()}
    dart = contract["dart"]
    sec = contract["sec"]
    dart_ids = {r["id"] for r in dart["rules"] + dart["exclusions"]}
    sec_ids = {r["id"] for r in sec["keyword_rules"] + sec["no_keyword_reasons"]}
    sec_ids |= {e["id"] for e in sec["items"].values()}
    sec_ids |= {sec["earnings_item"]["earnings_id"], sec["earnings_item"]["unit_sales_id"]}
    assert dart_ids <= used, dart_ids - used
    gap = sec_ids - used
    assert gap == set(SYNTHETIC_ONLY_SEC_RULES), gap ^ set(SYNTHETIC_ONLY_SEC_RULES)


@pytest.mark.parametrize(("rule_id", "item"), sorted(SYNTHETIC_ONLY_SEC_RULES.items()))
def test_synthetic_item_rules(rule_id: str, item: str) -> None:
    entry = load_contract()["sec"]["items"][item]
    assert entry["id"] == rule_id
    result = classify_sec("8-K", f"{item},9.01")
    assert (result.category, result.matched_rule) == (entry["category"], rule_id)


def test_synthetic_item_categories() -> None:
    expected = {"1.02": "deal", "2.01": "deal", "3.02": "capital", "1.05": "legal"}
    for item, category in expected.items():
        assert classify_sec("8-K", item).category == category


def test_classification_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValueError):
        Classification(None, None, False, False, None, "x")
    with pytest.raises(ValueError):
        Classification("deal", "no_rule", False, False, None, "x")


# -- review fixes ------------------------------------------------------------------------------


def test_keyword_rules_read_only_the_lead_of_an_ex99_exhibit() -> None:
    filler = "Remarks about the business. " * 120
    primary = ("8-K", "Item 7.01 Regulation FD. The presentation is furnished as Exhibit 99.1.")
    late_buyback = ("EX-99.1", filler + "We have a share repurchase program.")
    assert classify_sec("8-K", "7.01,9.01", [primary, late_buyback]).excluded_reason == (
        "no_keyword_match"
    )
    late_legal = ("EX-99.1", filler + "Risk factors: we face lawsuits and a class action.")
    assert classify_sec("8-K", "7.01", [primary, late_legal]).excluded_reason == "no_keyword_match"
    lead_buyback = ("EX-99.1", "We announced a share repurchase program. " + filler)
    assert classify_sec("8-K", "7.01", [primary, lead_buyback]).category == "buyback"


def test_primary_document_is_read_in_full() -> None:
    filler = "Other events text. " * 400
    primary = ("8-K", filler + "The Board declared a cash dividend.")
    assert classify_sec("8-K", "8.01", [primary]).category == "dividend"


def test_earnings_rule_reads_full_exhibits() -> None:
    filler = "Production, Deliveries & Deployments. " + "More text. " * 400
    deep_results = ("EX-99.1", filler + "Total revenues were reported.")
    assert classify_sec("8-K", "2.02", [("8-K", "Item 2.02"), deep_results]).category == "earnings"


def test_text_normalisation() -> None:
    assert classify_sec("8-K", "2.02", ["Q1 Production & Deliveries"]).category == "unit_sales"
    assert classify_sec("8-K", "8.01", ["Rule 10b5\u20111 plan"]).excluded_reason == "trading_plan"
    for dash in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212":
        assert normalise_text(f"10b5{dash}1") == "10b5-1"
    assert classify_sec("8-K", "8.01", ["<b>cash</b>&nbsp;dividend"]).category == "dividend"
    assert classify_sec("8-K", "8.01", ["CASH\n\tDividend"]).category == "dividend"
    assert normalise_text("<DOCUMENT><TYPE>EX-99.1<TEXT>Hello &amp; bye") == "hello and bye"
    assert normalise_text("a < b and c > d") == "a < b and c > d"


def test_primary_document_type_may_equal_the_form() -> None:
    text = "The Board declared a cash dividend."
    assert classify_sec("8-K", "8.01", [("8-K", text)]).category == "dividend"
    assert classify_sec("8-K/A", "8.01", [("8-K/A", text)]).category == "dividend"
    assert classify_sec(" 8-k/a ", "8.01", [("8-K/A", text)]).category == "dividend"
    assert classify_sec("8-K", "8.01", [("8-K/A", text)]).excluded_reason == "needs_body"
    assert classify_sec(" 8-K/A ", "5.02").is_correction is True


def test_exclusion_longest_prefix_wins_whatever_the_list_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = {
        "조회공시요구(풍문또는보도)에대한답변(미확정)": "rumor_response",
        "조회공시요구(풍문또는보도)": "market_action",
    }
    for seed in range(6):
        contract = copy.deepcopy(load_contract())
        random.Random(seed).shuffle(contract["dart"]["exclusions"])
        monkeypatch.setattr(categories, "load_contract", lambda c=contract: c)
        for name, reason in cases.items():
            assert categories.classify_dart(name).excluded_reason == reason, seed
    monkeypatch.undo()
    contract = copy.deepcopy(load_contract())
    contract["dart"]["exclusions"].reverse()
    monkeypatch.setattr(categories, "load_contract", lambda: contract)
    for name, reason in cases.items():
        assert categories.classify_dart(name).excluded_reason == reason


def test_sec_exclusion_reason_does_not_depend_on_item_order() -> None:
    first = classify_sec("8-K", "4.02,5.07")
    second = classify_sec("8-K", "5.07,4.02")
    assert first.excluded_reason == second.excluded_reason == "no_rule"
    assert first.matched_rule == second.matched_rule
    order = load_contract()["sec"]["exclusion_order"]
    for a, b in (("5.03", "5.07"), ("3.01", "5.03"), ("3.03", "3.01"), ("5.07", "9.01")):
        forward = classify_sec("8-K", f"{a},{b}")
        backward = classify_sec("8-K", f"{b},{a}")
        assert forward.excluded_reason == backward.excluded_reason
        assert forward.excluded_reason == min(
            (load_contract()["sec"]["item_exclusions"][a], load_contract()["sec"]["item_exclusions"][b]),
            key=order.index,
        )


def test_every_exclusion_reason_has_an_order_position() -> None:
    sec = load_contract()["sec"]
    used = set(sec["item_exclusions"].values()) | {e["reason"] for e in sec["no_keyword_reasons"]}
    used |= {"no_rule", "no_keyword_match"}
    assert used == set(sec["exclusion_order"])
    assert len(set(sec["exclusion_order"])) == len(sec["exclusion_order"])


def test_monthly_body_with_financial_results_is_not_unit_sales() -> None:
    with_results = (
        "<td>실적기간</td><td>당기실적</td><td>2026-10-01 ~ 2026-10-31</td>"
        "<td>매출액</td><td>당해실적</td><td>1,234</td><td>-</td>"
    )
    result = classify_dart("영업(잠정)실적(공정공시)", with_results)
    assert (result.category, result.excluded_reason) == (None, "no_rule")
    assert result.matched_rule == "dart.earnings.monthly_with_results"
    absent = _body("2026-10-01 ~ 2026-10-31")
    assert classify_dart("영업(잠정)실적(공정공시)", absent).category == "unit_sales"
    dashes = absent + "<td>매출액</td><td>당해실적</td><td>-</td>"
    assert classify_dart("영업(잠정)실적(공정공시)", dashes).category == "unit_sales"


def test_all_monthly_sales_fixtures_stay_unit_sales() -> None:
    monthly = [
        r
        for r, row in dart_rows().items()
        if row["corp_name"] in ("기아", "현대자동차")
        and normalise_dart_name(row["report_nm"])[0].startswith("영업(잠정)실적")
    ]
    assert len(monthly) == 24
    assert {classify_dart_row(r).category for r in monthly} == {"unit_sales"}


def test_dart_edges() -> None:
    assert classify_dart("영업(잠정)실적(공정공시)", "   \n\t ").excluded_reason == "needs_body"
    result = classify_dart("유상증자결정(자회사의주요경영사항)")
    assert (result.category, result.subsidiary) == ("capital", True)
    both = classify_dart("[기재정정]타법인주식및출자증권취득결정(자율공시)(자회사의주요경영사항)")
    assert (both.category, both.subsidiary, both.is_correction) == ("deal", True, True)
