"""Template summaries for event filings whose content is a regular table (D78).

A DART filing in a templated category whose table facts parsed
(:mod:`app.clients.dart_tables`) gets its three Korean and three English lines from the fixed
wording below, with no model call. The figures stay in the facts; the lines carry no digit and
no spelled number (N1). Direction words compare the table's own current and prior values as
``Decimal``; no percentage is written, and when the prior value is zero or negative the line
says nothing about direction. Outlook lines only attribute the outlook to the company and never
compare it with results.

A template is chosen only from the filing's own row (category, title, correction flag, facts and
stored text), so the summary build and the exporter agree on which filings are templated and on
the cache key (:func:`event_summary_key`). Template rows are staged like model rows; only the
owner approves them (``app.build.approve``).

Bump :data:`TEMPLATE_VERSION` on any change to the wording or to the facts a template reads: it
is part of the cache key, so every template summary is staged again.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.build.model import EventFactRow, EventRow, summary_input_sha256

TEMPLATE_VERSION = "t1-2026-11-19"
TEMPLATE_MODEL = "template"
SECTION = "summary"

# Category -> the fact-key prefixes of the tables a template reads, in the order tried.
TEMPLATED: dict[str, tuple[str, ...]] = {
    "earnings": ("results_", "change_"),
    "unit_sales": ("units_",),
    "dividend": ("dividend_",),
    "outlook": ("outlook_",),
}
# The fixed sentence every 영업실적등에대한전망 form carries ("※ 동 정보는 예측정보로서 ...").
PROJECTION_CAVEAT = "예측정보"


@dataclass(frozen=True)
class TemplateSummary:
    table: str  # the fact-key prefix without "_": results, change, units, dividend, outlook
    lines: dict[str, list[str]]  # lang -> three lines
    source_text: str  # every input the wording depends on, as canonical JSON


class _Missing(Exception):
    """A fact the template needs is absent; the filing goes to the model."""


# -- wording -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Noun:
    subject: str  # with 이/가
    joined: str  # with 과/와
    object: str  # the bare noun with 을/를, after "the same period's"
    en: str


@dataclass(frozen=True)
class _Base:
    ko: str  # 전년 같은 기간
    ko_with: str  # with 과/와
    en: str


SAME_PERIOD = _Base("전년 같은 기간", "전년 같은 기간과", "the same period a year earlier")
PRIOR_YEAR = _Base("직전 사업연도", "직전 사업연도와", "the previous fiscal year")

REVENUE = _Noun("매출액이", "매출액과", "매출액을", "revenue")
OPERATING_INCOME = _Noun("영업이익이", "영업이익과", "영업이익을", "operating income")
TOTAL_UNITS = _Noun("전체 판매 대수가", "전체 판매 대수와", "판매 대수를",
                    "the total number of units sold")  # fmt: skip
CUMULATIVE_UNITS = _Noun("누적 판매 대수가", "누적 판매 대수와", "누적 판매 대수를",
                         "the cumulative number of units sold")  # fmt: skip


def direction(current: Decimal, prior: Decimal) -> str | None:
    """``up``, ``down`` or ``same`` from the two values, or None when ``prior`` is zero or
    negative: a change from a loss or from nothing is not described as a direction."""
    if not isinstance(current, Decimal) or not isinstance(prior, Decimal):
        raise TypeError("direction compares Decimal values")
    if prior <= 0:
        return None
    if current > prior:
        return "up"
    if current < prior:
        return "down"
    return "same"


def compare_lines(noun: _Noun, base: _Base, current: Decimal, prior: Decimal) -> tuple[str, str]:
    """The Korean and English line for one compared figure."""
    match direction(current, prior):
        case "up":
            return (f"회사는 {noun.subject} {base.ko}보다 늘었다고 밝혔어요",
                    f"The company said {noun.en} increased from {base.en}.")  # fmt: skip
        case "down":
            return (f"회사는 {noun.subject} {base.ko}보다 줄었다고 밝혔어요",
                    f"The company said {noun.en} decreased from {base.en}.")  # fmt: skip
        case "same":
            return (f"회사는 {noun.subject} {base.ko_with} 같았다고 밝혔어요",
                    f"The company said {noun.en} was unchanged from {base.en}.")  # fmt: skip
        case _:
            return (f"회사는 {noun.joined} {base.ko}의 {noun.object} 함께 공시했어요",
                    f"The company disclosed {noun.en} together with the figure for "
                    f"{base.en}.")  # fmt: skip


def _has_final_consonant(word: str) -> bool:
    last = word.rstrip()[-1]
    return "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0


def join_ko(words: Sequence[str]) -> str:
    """``A``, ``A과 B``, ``A, B와 C``: the last pair joined by 과/와 by the final sound."""
    if len(words) == 1:
        return words[0]
    head = ", ".join(words[:-1])
    return f"{head}{'과' if _has_final_consonant(words[-2]) else '와'} {words[-1]}"


def join_en(words: Sequence[str]) -> str:
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


def _lines(*pairs: tuple[str, str]) -> dict[str, list[str]]:
    return {"ko": [p[0] for p in pairs], "en": [p[1] for p in pairs]}


# -- facts ---------------------------------------------------------------------------------------


class _Facts:
    def __init__(self, facts: Sequence[EventFactRow]) -> None:
        self.by_key = {f.key: f for f in facts if f.error is None}

    def has(self, key: str) -> bool:
        return key in self.by_key

    def decimal(self, key: str) -> Decimal:
        fact = self.by_key.get(key)
        if fact is None or fact.value_decimal is None:
            raise _Missing(key)
        return fact.value_decimal

    def text(self, key: str) -> str | None:
        fact = self.by_key.get(key)
        return None if fact is None else fact.value_text


def _basis(consolidated: bool | None) -> tuple[str, str]:
    if consolidated is None:
        return "", ""
    if consolidated:
        return "연결 기준 ", " on a consolidated basis"
    return "별도 기준 ", " on a separate basis"


def _results(event: EventRow, facts: _Facts) -> dict[str, list[str]]:
    ko_basis, en_basis = _basis(True if "연결재무제표기준" in event.report_nm else None)
    if event.is_correction:
        first = (f"회사는 {ko_basis}잠정 실적을 고쳐 다시 공시했어요",
                 f"The company filed corrected preliminary results{en_basis}.")  # fmt: skip
    else:
        first = (f"회사는 {ko_basis}잠정 실적을 공시했어요",
                 f"The company disclosed preliminary results{en_basis}.")  # fmt: skip
    return _lines(
        first,
        compare_lines(REVENUE, SAME_PERIOD, facts.decimal("results_revenue_current"),
                      facts.decimal("results_revenue_year_ago")),
        compare_lines(OPERATING_INCOME, SAME_PERIOD,
                      facts.decimal("results_operating_income_current"),
                      facts.decimal("results_operating_income_year_ago")),
    )  # fmt: skip


def _change(event: EventRow, facts: _Facts) -> dict[str, list[str]]:
    statement = {"연결": True, "별도": False}.get(facts.text("change_statement") or "")
    ko_basis, en_basis = _basis(statement)
    if event.is_correction:
        first = (f"회사는 {ko_basis}매출액 또는 손익구조 변동 내용을 고쳐 다시 공시했어요",
                 "The company filed a corrected disclosure of a change in revenue or profit "
                 f"structure{en_basis}.")  # fmt: skip
    else:
        first = (f"회사는 {ko_basis}매출액 또는 손익구조 변동을 공시했어요",
                 "The company disclosed a change in revenue or profit "
                 f"structure{en_basis}.")  # fmt: skip
    return _lines(
        first,
        compare_lines(REVENUE, PRIOR_YEAR, facts.decimal("change_revenue_current"),
                      facts.decimal("change_revenue_prior")),
        compare_lines(OPERATING_INCOME, PRIOR_YEAR,
                      facts.decimal("change_operating_income_current"),
                      facts.decimal("change_operating_income_prior")),
    )  # fmt: skip


def _units(event: EventRow, facts: _Facts) -> dict[str, list[str]]:
    if event.is_correction:
        first = ("회사는 잠정 판매 실적을 고쳐 다시 공시했어요",
                 "The company filed corrected preliminary unit sales.")  # fmt: skip
    else:
        first = ("회사는 잠정 판매 실적을 공시했어요",
                 "The company disclosed preliminary unit sales.")  # fmt: skip
    return _lines(
        first,
        compare_lines(TOTAL_UNITS, SAME_PERIOD, facts.decimal("units_total_current"),
                      facts.decimal("units_total_year_ago")),
        compare_lines(CUMULATIVE_UNITS, SAME_PERIOD, facts.decimal("units_total_cumulative"),
                      facts.decimal("units_total_cumulative_year_ago")),
    )  # fmt: skip


DIVIDEND_KINDS = {
    "분기배당": ("분기 ", "quarterly "),
    "중간배당": ("중간 ", "interim "),
    "결산배당": ("결산 ", "year-end "),
}
DIVIDEND_TYPES = {"현금배당": ("현금 배당", "cash dividend"),
                  "현물배당": ("현물 배당", "dividend in kind")}  # fmt: skip


def _dividend(event: EventRow, facts: _Facts) -> dict[str, list[str]]:
    kind = DIVIDEND_KINDS.get(facts.text("dividend_kind") or "")
    kind_of = DIVIDEND_TYPES.get(facts.text("dividend_type") or "")
    if kind is None or kind_of is None:
        raise _Missing("dividend_kind")
    facts.decimal("dividend_per_share_common")
    ko_name = f"{kind[0]}{kind_of[0]}"
    en_name = f"{kind[1]}{kind_of[1]}"
    article = "an" if en_name[0] in "aeiou" else "a"
    if event.is_correction:
        first = (f"회사는 {ko_name} 결정을 고쳐 다시 공시했어요",
                 f"The company filed a corrected decision on {article} {en_name}.")  # fmt: skip
    else:
        first = (f"회사는 {ko_name}을 결정했어요",
                 f"The company decided on {article} {en_name}.")  # fmt: skip

    preferred = facts.has("dividend_per_share_preferred")
    with_yield = facts.has("dividend_yield_common")
    classes = ("보통주와 종류주", "common shares and other share classes") if preferred else (
        "보통주", "common shares")  # fmt: skip
    second = (f"회사는 {classes[0]}의 주당 배당금{'과 시가배당률' if with_yield else ''}을 "
              "밝혔어요",
              f"The company stated the dividend per share"
              f"{' and the dividend yield' if with_yield else ''} for {classes[1]}.")  # fmt: skip

    stated = [
        (key, ko, en)
        for key, ko, en in (
            ("dividend_total", "배당금 총액", "the total dividend"),
            ("dividend_record_date", "배당 기준일", "the record date"),
            ("dividend_payment_date", "지급 예정일", "the planned payment date"),
        )
        if facts.has(key)
    ]
    if not stated:
        raise _Missing("dividend_total")
    # Every listed Korean noun ends in a consonant, so the object particle is 을.
    third = (f"회사는 {join_ko([s[1] for s in stated])}을 밝혔어요",
             f"The company stated {join_en([s[2] for s in stated])}.")  # fmt: skip
    return _lines(first, second, third)


OUTLOOK_METRICS = (
    ("revenue", "매출액", "revenue"),
    ("operating_income", "영업이익", "operating income"),
    ("pretax_income", "세전이익", "pre-tax income"),
    ("net_income", "당기순이익", "net income"),
)
SALES_TARGET = ("판매 목표", "sales targets")
OTHER_ITEMS = ("기타 항목", "other items")


def _outlook(event: EventRow, facts: _Facts) -> dict[str, list[str]]:
    ko_basis, en_basis = _basis(True if "연결재무제표기준" in event.report_nm else None)
    if event.is_correction:
        first = (f"회사는 {ko_basis}영업실적 전망을 고쳐 다시 공시했어요",
                 f"The company filed a corrected outlook for results{en_basis}.")  # fmt: skip
    else:
        first = (f"회사는 {ko_basis}영업실적 전망을 공시했어요",
                 f"The company disclosed its outlook for results{en_basis}.")  # fmt: skip

    named: list[tuple[str, str]] = [
        (ko, en)
        for key, ko, en in OUTLOOK_METRICS
        if any(facts.has(f"outlook_{key}_y{year}") for year in (1, 2, 3))
    ]
    for n in range(1, 7):
        label = facts.text(f"outlook_item{n}_label")
        if label is None:
            continue
        group = SALES_TARGET if "판매목표" in "".join(label.split()) else OTHER_ITEMS
        if group not in named:
            named.append(group)
    if not named:
        raise _Missing("outlook values")
    second = (f"회사는 {join_ko([n[0] for n in named])} 전망치를 밝혔어요",
              "The company stated outlook figures for "
              f"{join_en([n[1] for n in named])}.")  # fmt: skip

    if event.is_correction and facts.has("outlook_change1_after"):
        third = ("회사는 고치기 전과 고친 후의 전망치를 함께 밝혔어요",
                 "The company stated the outlook figures before and after the "
                 "correction.")  # fmt: skip
    elif PROJECTION_CAVEAT in "".join((event.body_text or "").split()):
        third = ("회사는 이 전망이 예측 정보로서 실제 결과와 다를 수 있다고 밝혔어요",
                 "The company said the outlook is projected information and actual results "
                 "may differ.")  # fmt: skip
    else:
        raise _Missing("caveat")
    return _lines(first, second, third)


_BUILDERS = {
    "results_": _results,
    "change_": _change,
    "units_": _units,
    "dividend_": _dividend,
    "outlook_": _outlook,
}


# -- entry points --------------------------------------------------------------------------------


def _source_text(event: EventRow, prefix: str, facts: Sequence[EventFactRow]) -> str:
    """Every input the wording reads: the table, category, title, correction flag, whether the
    outlook caveat is stated, and the table's facts."""
    rows = sorted(
        [f.key, f.kind, f.unit,
         None if f.value_decimal is None else str(f.value_decimal),
         None if f.value_date is None else f.value_date.isoformat(), f.value_text]
        for f in facts
    )  # fmt: skip
    payload: Mapping[str, object] = {
        "table": prefix.rstrip("_"),
        "category": event.category,
        "report_nm": event.report_nm,
        "is_correction": event.is_correction,
        "projection_caveat": PROJECTION_CAVEAT in "".join((event.body_text or "").split())
        if prefix == "outlook_" else None,
        "facts": rows,
    }  # fmt: skip
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def event_template(event: EventRow) -> TemplateSummary | None:
    """The template summary of ``event``, or None when its category has no template or the
    facts the template needs did not parse (the model then writes the summary)."""
    if event.regulator != "DART" or event.category not in TEMPLATED:
        return None
    usable = [f for f in event.facts if f.error is None]
    for prefix in TEMPLATED[event.category]:
        table_facts = [f for f in usable if f.key.startswith(prefix)]
        if not table_facts:
            continue
        try:
            lines = _BUILDERS[prefix](event, _Facts(table_facts))
        except _Missing:
            return None
        return TemplateSummary(prefix.rstrip("_"), lines, _source_text(event, prefix, table_facts))
    return None


def template_input_sha256(template: TemplateSummary, lexicon_version: int) -> str:
    return summary_input_sha256(template.source_text, TEMPLATE_MODEL, SECTION, TEMPLATE_VERSION,
                                lexicon_version)  # fmt: skip


def event_summary_key(
    event: EventRow, source_text: str | None, llm_model: str, prompt_version: str,
    lexicon_version: int,
) -> str | None:
    """The cache key of an event's summary: the template's when one applies, else the model's
    over ``source_text`` (None when there is none)."""
    template = event_template(event)
    if template is not None:
        return template_input_sha256(template, lexicon_version)
    if source_text is None:
        return None
    return summary_input_sha256(source_text, llm_model, SECTION, prompt_version, lexicon_version)
