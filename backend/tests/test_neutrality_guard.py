"""Neutrality guard (rules N1-N9) against fixtures and the lexicon contract."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.neutrality_guard import (
    LEXICON_PATH,
    Source,
    check_line,
    check_source_url,
    check_summary,
    line_warnings,
    summary_warnings,
)

FIXTURES = Path(__file__).parent / "fixtures" / "neutrality"
RULE_IDS = [f"N{n}" for n in range(1, 10)]


def _rows(name: str) -> list[dict[str, Any]]:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _failures(row: dict[str, Any]) -> set[str]:
    names = [row["company"]]
    if "lines" in row:
        violations = check_summary(row["lines"], row["lang"], names)
    else:
        violations = check_line(row["line"], row["lang"], 1, names)
    return {v.rule_id for v in violations}


def _row_id(row: dict[str, Any]) -> str:
    return f"{row['lang']}:{row.get('line') or row['lines'][0]}"


GOOD = _rows("good.jsonl")
BAD = _rows("bad.jsonl")


@pytest.mark.parametrize("row", GOOD, ids=_row_id)
def test_good_fixture_passes(row: dict[str, Any]) -> None:
    assert _failures(row) == set()


@pytest.mark.parametrize("row", BAD, ids=_row_id)
def test_bad_fixture_trips_exactly_its_rules(row: dict[str, Any]) -> None:
    assert _failures(row) == set(row["rules"])


@pytest.mark.parametrize("name", ["good.jsonl", "bad.jsonl"])
@pytest.mark.parametrize("lang", ["ko", "en"])
def test_fixture_volume(name: str, lang: str) -> None:
    rows = [row for row in _rows(name) if row["lang"] == lang]
    assert len(rows) >= 30
    assert all(row["note"] for row in rows)


def test_good_fixtures_mostly_from_real_filings() -> None:
    real = [row for row in GOOD if "synthetic" not in row["note"]]
    assert len(real) * 2 >= len(GOOD)


def test_bad_fixtures_name_known_rules() -> None:
    for row in BAD:
        assert row["rules"] and set(row["rules"]) <= set(RULE_IDS)


@pytest.mark.parametrize(
    "line",
    ["회사는 자기주식 3주를 취득했다고 밝혔어요", "회사는 자기주식 ３주를 취득했다고 밝혔어요",
     "회사는 삼천억원 규모의 계약을 체결했다고 공시했어요"],
)
def test_n1_korean_numbers(line: str) -> None:
    assert {v.rule_id for v in check_line(line, "ko")} == {"N1"}


@pytest.mark.parametrize(
    "line",
    ["The company said it bought 3 shares.", "The company said it bought ３ shares.",
     "The company said revenue was two billion dollars."],
)
def test_n1_english_numbers(line: str) -> None:
    assert {v.rule_id for v in check_line(line, "en")} == {"N1"}


@pytest.mark.parametrize(
    ("line", "lang"),
    [("The company reported its fourth quarter results.", "en"),
     ("The company reported third-quarter deliveries.", "en"),
     ("The company said First Half sales rose.", "en"),
     ("회사는 사분기 실적을 보고했어요", "ko"),
     ("회사는 일분기 실적을 보고했어요", "ko"),
     ("회사는 하반기 생산을 보고했어요", "ko")],
)
def test_n1_ordinal_periods(line: str, lang: str) -> None:
    # D74, owner-approved 2026-11-18: a line does not say which quarter or half.
    assert {v.rule_id for v in check_line(line, lang)} == {"N1"}


@pytest.mark.parametrize(
    ("line", "lang"),
    [("The company said it is the second largest maker.", "en"),
     ("The company said it will first review the plan.", "en"),
     ("회사는 이 분기 실적을 보고했어요", "ko"),
     ("회사는 분기 실적을 보고했어요", "ko"),
     ("회사는 수익이 분기마다 달라진다고 밝혔어요", "ko")],
)
def test_n1_leaves_other_ordinals_and_this_quarter_alone(line: str, lang: str) -> None:
    assert "N1" not in {v.rule_id for v in check_line(line, lang)}


@pytest.mark.parametrize(
    "word",
    ["surge", "surged", "surges", "surging", "soar", "soared", "soaring", "skyrocketed",
     "skyrocketing", "jumped", "jumps", "plunged", "plunging", "slumped", "slumping",
     "tumbled", "tumbling", "crashed", "crashes", "boosted", "boosting", "flawed", "flaws",
     "flawless", "worryingly", "alarmingly", "stunningly", "massively", "strongly",
     "stronger", "strongest", "weaker", "weakest", "weakness", "weakened", "disappointingly",
     "impressively", "blockbusters", "Surged", "STRONG"],
)
def test_n2_english_inflections(word: str) -> None:
    violations = check_line(f"The company said results {word} here.", "en")
    assert "N2" in {v.rule_id for v in violations}


@pytest.mark.parametrize("word", ["surgery", "Armstrong", "jumpsuit", "booster", "jumper"])
def test_n2_word_boundary_keeps_lookalikes_clear(word: str) -> None:
    assert check_line(f"The company said it named {word} in the filing.", "en") == []


def test_n9_warns_but_never_fails() -> None:
    ko = "회사는 사상 최대 배당을 결정했어요"
    assert check_line(ko, "ko") == []
    assert [v.token for v in line_warnings(ko, "ko")] == ["사상", "최대"]

    en = "The company said revenue rose sharply to a record."
    assert check_line(en, "en") == []
    assert [v.token for v in line_warnings(en, "en")] == ["sharply", "record"]


def test_n9_counts_across_a_summary() -> None:
    lines = [
        "회사는 영업이익이 크게 늘었다고 공시했어요",
        "회사는 대폭 늘어난 배당을 결정했어요",
        "회사는 소폭 줄어든 순이익을 보고했어요",
    ]
    assert check_summary(lines, "ko") == []
    warnings = summary_warnings(lines, "ko")
    assert [(v.rule_id, v.line_no, v.token) for v in warnings] == [
        ("N9", 1, "크게"), ("N9", 2, "대폭"), ("N9", 3, "소폭"),
    ]


@pytest.mark.parametrize(
    ("line", "lang"),
    [
        ("회사는 노태문 대표이사가 최대주주의 특수관계인이라고 공시했어요", "ko"),
        ("회사는 최고경영자를 선임했다고 공시했어요", "ko"),
        ("The company said the dividend is payable to shareholders of record.", "en"),
        ("The company said it recorded revenue in the quarter.", "en"),
    ],
)
def test_n9_allow_list_gives_no_warning(line: str, lang: str) -> None:
    assert line_warnings(line, lang) == []


def test_n9_is_not_reported_by_check_functions() -> None:
    lines = ["회사는 사상 최대 배당을 결정했어요", "회사는 크게 늘었다고 밝혔어요", "회사는 적었어요"]
    assert "N9" not in {v.rule_id for v in check_summary(lines, "ko")}


def test_n6_line_count() -> None:
    line = "The company said revenue rose."
    assert check_summary([line] * 3, "en") == []
    for count in (0, 1, 2, 4):
        violations = check_summary([line] * count, "en")
        assert [(v.rule_id, v.line_no) for v in violations] == [("N6", 0)]


def test_n6_length_limits_are_inclusive() -> None:
    ko_head = "회사는 "
    ko_tail = "결정했어요"
    ko_ok = ko_head + "가" * (60 - len(ko_head) - len(ko_tail)) + ko_tail
    assert len(ko_ok) == 60
    assert check_line(ko_ok, "ko") == []
    ko_long = ko_head + "가" * (61 - len(ko_head) - len(ko_tail)) + ko_tail
    assert {v.rule_id for v in check_line(ko_long, "ko")} == {"N6"}

    en_head = "The company said "
    en_ok = en_head + "a" * (140 - len(en_head))
    assert len(en_ok) == 140
    assert check_line(en_ok, "en") == []
    assert {v.rule_id for v in check_line(en_ok + "a", "en")} == {"N6"}


@pytest.mark.parametrize(
    "line",
    [
        "The company said revenue rose!",
        "The company said revenue rose！",
        "The company said `revenue` rose.",
        "The company said [revenue](https://example.com) rose.",
        "- The company said revenue rose.",
        "> The company said revenue rose.",
        "The company said revenue | rose.",
        "The company said revenue rose.\rAgain.",
        "The company said revenue rose 😀.",
    ],
)
def test_n6_shape_violations(line: str) -> None:
    assert {v.rule_id for v in check_line(line, "en")} == {"N6"}


@pytest.mark.parametrize(
    "url",
    [
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260821000616",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000024/",
    ],
)
def test_n5_official_urls_pass(url: str) -> None:
    assert check_source_url(url) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://dart.fss.or.kr/dsaf001/main.do",
        "https://sec.gov/Archives/edgar/data/320193/",
        "https://www.sec.gov.example.com/",
        "https://dart.fss.or.kr.evil.example/",
        "https://opendart.fss.or.kr/api/list.json",
        "https://www.samsung.com/sec/ir/",
        "https://dart.fss.or.kr",
        "",
    ],
)
def test_n5_other_urls_fail(url: str) -> None:
    assert [v.rule_id for v in check_source_url(url)] == ["N5"]


def test_n3_plan_needs_allowed_verb_and_attribution() -> None:
    summary = [
        "회사는 자기주식을 취득하기로 결정했어요",
        "회사는 장내 매수로 취득할 예정이라고 밝혔어요",
        "회사는 소각예정금액을 공시했어요",
    ]
    assert check_summary(summary, "ko", ["삼성전자"]) == []
    unattributed = check_line("회사는 자기주식을 취득할 예정이라고 해요", "ko")
    assert {v.rule_id for v in unattributed} == {"N3", "N4"}


def test_violation_span_points_at_token() -> None:
    line = "The company said revenue surged."
    (violation,) = check_line(line, "en")
    assert violation.rule_id == "N2"
    assert line[slice(*violation.span)] == violation.token == "surged"
    assert (violation.lang, violation.line_no) == ("en", 1)


def test_company_name_counts_as_subject() -> None:
    assert check_line("Microsoft said it issued notes.", "en", 1, ["Microsoft"]) == []
    assert {v.rule_id for v in check_line("Microsoft said it issued notes.", "en")} == {"N4"}
    assert check_line("삼성전자는 배당을 결정했어요", "ko", 1, ["삼성전자"]) == []
    assert check_line("배당을 결정했어요", "ko", 2) == []


@pytest.mark.parametrize(
    ("line", "names"),
    [
        ("Apple Inc. said it issued a press release.", ["Apple"]),
        ("Apple Inc. said it issued a press release.", ["Apple", "Apple Inc."]),
        ("Microsoft Corporation also said it issued notes.", ["Microsoft"]),
        ("  The company said it issued notes.", []),
    ],
)
def test_en_n4_accepts_name_forms_at_line_start(line: str, names: list[str]) -> None:
    assert check_line(line, "en", 1, names) == []


@pytest.mark.parametrize(
    "line",
    ["Banks said Apple reported results.", "After the release, Apple said it issued notes."],
)
def test_en_n4_rejects_company_outside_the_line_start(line: str) -> None:
    assert {v.rule_id for v in check_line(line, "en", 1, ["Apple"])} == {"N4"}


def test_company_name_exempt_from_n2_but_not_n1() -> None:
    assert check_line("Boost Mobile said it filed a report.", "en", 1, ["Boost Mobile"]) == []
    boost = check_line("Boost Mobile said it filed a report.", "en", 1, [])
    assert {v.rule_id for v in boost} == {"N2", "N4"}
    assert {v.rule_id for v in check_line("3M said it filed a report.", "en", 1, ["3M"])} == {
        "N1"
    }


def _lists(node: Any) -> list[list[Any]]:
    if isinstance(node, list):
        return [node, *(found for item in node for found in _lists(item))]
    if isinstance(node, dict):
        return [found for value in node.values() for found in _lists(value)]
    return []


def test_lexicon_contract_schema() -> None:
    lexicon = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    assert isinstance(lexicon["version"], int) and lexicon["version"] >= 1

    ids = [rule["id"] for rule in lexicon["rules"]]
    assert len(ids) == len(set(ids))
    assert ids == RULE_IDS

    for rule in lexicon["rules"]:
        assert rule["title"]
        assert rule["severity"] == ("warn" if rule["id"] == "N9" else "fail")
    for rule_id in ("N2", "N3", "N7", "N9"):
        rule = next(r for r in lexicon["rules"] if r["id"] == rule_id)
        for lang in ("ko", "en"):
            assert rule[lang]["match"] in {"substring", "word", "inflected_word"}
            assert rule[lang]["terms"]
            assert len(rule[lang]["terms"]) == len(set(rule[lang]["terms"]))

    assert all(_lists(lexicon)), "every list in the lexicon is non-empty"


# -- D111: labels, report-type endings, legal 매수/매도 (owner decision 2026-11-28) ---------------
# The lines are the real withheld ones; each source is a passage of the filing it came from.

SAMSUNG = Source(
    "수시공시의무관련사항(공정공시)",
    "1. 정보내용 공시제목 2026년 주주환원 예상 규모 및 시행 방안 관련 수시공시내용 "
    "- 2026년 3분기에는 정규 분기배당을 포함해 30조원 내외 규모의 현금배당을 시행할 계획",
)
LG_CHEM = Source(
    "조회공시요구(풍문또는보도)에대한답변(미확정)",
    "1. 제목 (주)LG화학의 여수 NCC 2공장 매각 착수 보도에 대한 조회공시 답변(재공시) "
    "향후 본건과 관련하여 구체적으로 결정되는 사항이 있을 경우 또는 6개월 이내에 재공시하도록",
)
ISSUE_PRICE = Source(
    "유상증자신주발행가액(안내공시)",
    "② 1차 발행가액 : 1차 발행가액은 신주배정기준일 전 제3거래일 ③ 2차 발행가액 : 2차 "
    "발행가액은 구주주 청약일 전 제3거래일 할인율 15%를 적용 1개월 가중산술평균주가",
)
COSTCO = Source("8-K", "the first 24 weeks of fiscal 2026, ended February 15, 2026")
SHELF = Source(
    "8-K",
    "The offering of the Notes was made pursuant to the Company's Registration Statement on "
    "Form S-3 (File No. 333-295425)",
)
CLARIFICATION = Source("풍문또는보도에대한해명(미확정)", "풍문 또는 보도에 대한 해명")
INQUIRY = Source("조회공시요구(풍문또는보도)에대한답변(미확정)", "조회공시 요구에 대한 답변")


def _rules(line: str, lang: str, source: Source | None, line_no: int = 1) -> list[tuple]:
    return [(v.rule_id, v.token) for v in check_line(line, lang, line_no, source=source)]


@pytest.mark.parametrize(
    ("line", "lang", "source"),
    [
        ("회사는 2026년 주주환원 예상 규모 및 시행 방안에 대해 공시했어요.", "ko", SAMSUNG),
        ("회사는 3분기에 현금배당을 시행할 계획이라고 밝혔어요.", "ko", SAMSUNG),
        ("The company said it plans to implement cash dividends in the third quarter, with "
         "specifics to be decided by the board.", "en", SAMSUNG),
        ("회사는 여수 NCC 2공장 매각 착수 보도에 대해 조회공시 답변을 공시했어요.", "ko", LG_CHEM),
        ("회사는 1차와 2차 발행가액 중 낮은 금액이라고 밝혔어요", "ko", ISSUE_PRICE),
        ("회사는 2026 회계연도 분기 및 연초 이후 영업실적을 보고했어요", "ko", COSTCO),
        ("The company reported its quarterly and year-to-date operating results for fiscal "
         "2026.", "en", COSTCO),
        ("회사는 S-3 양식의 등록 서류에 따라 발행했다고 밝혔어요", "ko", SHELF),
        ("The company stated the offering was made pursuant to its Registration Statement on "
         "Form S-3.", "en", SHELF),
    ],
)  # fmt: skip
def test_a_label_the_source_holds_passes_n1(line: str, lang: str, source: Source) -> None:
    assert _rules(line, lang, source) == []
    # Without the source the label is a digit like any other.
    assert {rule for rule, _ in _rules(line, lang, None)} == {"N1"}


@pytest.mark.parametrize(
    ("line", "lang", "source", "tokens"),
    [
        # A label the source does not hold.
        ("회사는 2025년 주주환원 방안을 공시했어요.", "ko", SAMSUNG, ["2", "0", "2", "5"]),
        ("회사는 4분기에 현금배당을 시행할 계획이라고 밝혔어요.", "ko", SAMSUNG, ["4"]),
        ("The company said it pays the dividend in the fourth quarter.", "en", SAMSUNG,
         ["fourth quarter"]),
        ("회사는 S-1 양식의 등록 서류에 따라 발행했다고 밝혔어요", "ko", SHELF, ["1"]),
        ("회사는 3공장 매각 보도에 대해 조회공시 답변을 공시했어요.", "ko", LG_CHEM, ["3"]),
        # Durations, amounts, percentages, counts and file numbers stay banned, even when the
        # source holds them.
        ("회사는 6개월 이내에 재공시할 예정이라고 밝혔어요.", "ko", LG_CHEM, ["6"]),
        ("회사는 할인율 15%를 적용한다고 밝혔어요", "ko", ISSUE_PRICE, ["1", "5"]),
        ("회사는 1개월 가중산술평균주가를 쓴다고 밝혔어요", "ko", ISSUE_PRICE, ["1"]),
        ("회사는 3분기에 30조원 내외의 현금배당을 시행할 계획이라고 밝혔어요.", "ko", SAMSUNG,
         ["3", "0", "조원"]),
        ("The company said the file number is 333-295425 under Form S-3.", "en", SHELF,
         list("333295425")),
        ("The company said the period covers 24 weeks of fiscal 2026.", "en", COSTCO,
         ["2", "4"]),
        # A bare year, a half and a spelled Korean quarter are not labels.
        ("The company said the plan runs in 2026.", "en", SAMSUNG, ["2", "0", "2", "6"]),
        ("The company said it reports first half results.", "en", SAMSUNG, ["first half"]),
        ("회사는 삼분기에 현금배당을 시행한다고 밝혔어요.", "ko", SAMSUNG, ["삼분기"]),
    ],
)  # fmt: skip
def test_figures_and_absent_labels_still_fail_n1(
    line: str, lang: str, source: Source, tokens: list[str]
) -> None:
    found = _rules(line, lang, source)
    assert {rule for rule, _ in found} == {"N1"}
    assert sorted(token for _, token in found) == sorted(tokens)


@pytest.mark.parametrize(
    ("line", "source"),
    [
        ("회사는 2차전지 사업을 확대한다고 밝혔어요.", Source("x", "2차전지 사업")),
        ("회사는 이사회를 2차례 열었다고 밝혔어요.", Source("x", "2차례 개최")),
        ("회사는 3차원 설계를 도입한다고 밝혔어요.", Source("x", "3차원 설계")),
        ("회사는 2026년간 배당을 시행한다고 밝혔어요.", Source("x", "2026년간 배당")),
        ("회사는 10년 동안 배당을 시행한다고 밝혔어요.", Source("x", "10년 동안 2010년")),
        ("회사는 2공장 두 곳을 짓는다고 밝혔어요.", Source("x", "2공장")),
    ],
)  # fmt: skip
def test_counts_and_durations_that_look_like_labels_fail_n1(line: str, source: Source) -> None:
    assert "N1" in {rule for rule, _ in _rules(line, "ko", source)}


@pytest.mark.parametrize(
    ("line", "source"),
    [
        ("회사는 미국 자회사 베어로보틱스가 나스닥 상장을 도전한다는 보도에 대해 해명했어요.",
         CLARIFICATION),
        ("회사는 배달의민족 인수 컨소시엄 구성 보도에 대해 해명했어요.", CLARIFICATION),
        ("회사는 키옥시아 지분 차익으로 특별배당을 추진한다는 보도에 대해 해명했어요.",
         CLARIFICATION),
        ("회사는 솔리다임의 미국 낸드공장 신설 검토 보도에 대해 해명했어요.", CLARIFICATION),
        ("회사는 일본에 반도체 공장을 짓는다는 보도에 대해 조회공시 요구를 받았어요.", INQUIRY),
        ("회사는 일본에 반도체 공장을 짓는다는 보도에 대해 조회공시요구를 받았어요.", INQUIRY),
        ("회사는 반도체 공장 보도에 대한 조회공시 요구에 답변했어요.", INQUIRY),
    ],
)  # fmt: skip
def test_line_one_of_its_report_type_may_end_in_a_report_ending(line: str, source) -> None:
    assert _rules(line, "ko", source) == []
    assert _rules(line, "ko", None) == [("N4", "")]


@pytest.mark.parametrize(
    ("line", "source", "line_no"),
    [
        # Another report type, or no title at all.
        ("회사는 보도에 대해 해명했어요.", Source("유상증자결정", "유상증자"), 1),
        ("회사는 보도에 대해 해명했어요.", INQUIRY, 1),
        ("회사는 조회공시 요구를 받았어요.", CLARIFICATION, 1),
        ("회사는 조회공시 요구에 답변했어요.", CLARIFICATION, 1),
        # Lines two and three keep the five endings.
        ("회사는 보도에 대해 해명했어요.", CLARIFICATION, 2),
        ("회사는 조회공시 요구를 받았어요.", INQUIRY, 3),
        # Only the inquiry itself was received.
        ("회사는 투자를 받았어요.", INQUIRY, 1),
        ("회사는 투자 제안을 받았어요.", INQUIRY, 1),
    ],
)  # fmt: skip
def test_report_endings_stay_closed_outside_their_report_and_line(line, source, line_no) -> None:
    assert ("N4", "") in _rules(line, "ko", source, line_no)


def test_a_report_ending_opens_no_other_rule() -> None:
    found = _rules("회사는 실적 우려 보도에 대해 해명했어요.", "ko", CLARIFICATION)
    assert found == [("N2", "우려")]
    found = _rules("회사는 주가가 오를 것으로 보도에 대해 해명했어요.", "ko", CLARIFICATION)
    assert {rule for rule, _ in found} == {"N3"}


@pytest.mark.parametrize(
    "line",
    [
        "회사는 스위스법에 따른 강제매수 등으로 잔여지분을 취득해 지분 전부를 확보할 예정이라고 "
        "밝혔어요",
        "회사는 소수주주 지분을 강제 매수한다고 밝혔어요",
        "회사는 PolyPeptide Group AG 공개매수에서 최종 응모 지분율을 기록했다고 보고했어요",
        "회사는 미국 및 캐나다 채권을 인수단에 매도하기로 합의했다고 밝혔어요.",
        "회사는 사채를 투자자에게 매도했다고 공시했어요.",
        "회사는 노트를 인수단에 매도할 예정이라고 밝혔어요.",
    ],
)  # fmt: skip
def test_legal_terms_and_selling_its_notes_pass_n7(line: str) -> None:
    assert _rules(line, "ko", None) == []


@pytest.mark.parametrize(
    "line",
    [
        "회사는 주식을 매수하라고 밝혔어요.",
        "회사는 지금이 매수 기회라고 밝혔어요.",
        "회사는 채권을 매도하세요라고 밝혔어요.",
        "회사는 채권을 매도해야 한다고 밝혔어요.",
        "회사는 채권을 매도할 때라고 밝혔어요.",
        "회사는 자기주식을 매도하기로 결정했어요",
        "회사는 주식을 인수단에 매도하기로 합의했다고 밝혔어요.",
        "회사는 소수주주 지분을 강제로 매수한다고 밝혔어요",
    ],
)  # fmt: skip
def test_buy_and_sell_advice_still_fails_n7(line: str) -> None:
    assert "N7" in {rule for rule, _ in _rules(line, "ko", None)}


def test_check_summary_passes_the_source_to_every_line() -> None:
    lines = [
        "회사는 2026년 주주환원 예상 규모 및 시행 방안에 대해 공시했어요.",
        "회사는 3분기에 현금배당을 시행할 계획이라고 밝혔어요.",
        "회사는 결산 후 나머지 주주환원 규모 및 방안을 최종 결정할 계획이라고 밝혔어요.",
    ]
    assert check_summary(lines, "ko", source=SAMSUNG) == []
    assert {(v.rule_id, v.line_no) for v in check_summary(lines, "ko")} == {("N1", 1), ("N1", 2)}
