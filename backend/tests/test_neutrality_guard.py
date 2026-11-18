"""Neutrality guard (rules N1-N9) against fixtures and the lexicon contract."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.neutrality_guard import (
    LEXICON_PATH,
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
