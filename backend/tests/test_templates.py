"""Template summaries for table filings (D78): wording, direction, guard, cache key, generate."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.build import export, summaries, templates
from app.build.export import BuildOptions, _Build
from app.build.model import EventFactRow, EventRow, event_source_text, summary_input_sha256
from app.build.summaries import Target, generate, read_jsonl, select_targets
from app.build.templates import (
    TEMPLATE_MODEL,
    TEMPLATE_VERSION,
    compare_lines,
    direction,
    event_summary_key,
    event_template,
    template_input_sha256,
)
from app.build.verify import PinnedResponses
from app.clients.dart_events import read_event_document
from app.clients.dart_tables import parse_table_facts, table_for
from app.filings.categories import normalise_dart_name
from app.llm.base import LLMResult
from app.llm.neutrality_guard import check_summary, load_lexicon, summary_warnings
from tests.build_seed import AS_OF, PINNED_DIRS, fixture_build_input

FIXTURES = Path(__file__).parent / "fixtures" / "events"
DOCUMENTS = FIXTURES / "dart" / "document"
CLASSIFIER = FIXTURES / "classifier" / "dart" / "document"
MODEL = "gemini-2.5-flash-lite"
# Digits, and the spelled numbers N1 lists, never appear in a template line.
SPELLED = re.compile(r"\b(one|two|three|four|five|ten|hundred|thousand|million|billion)\b|"
                     r"(?<![가-힣])(?:일|이|사)분기|하나|둘|셋", re.I)  # fmt: skip

CASES = [
    # (document, category, report name)
    (DOCUMENTS / "20261029800228.xml", "earnings", "연결재무제표기준영업(잠정)실적(공정공시)"),
    (DOCUMENTS / "20261029800099.xml", "earnings",
     "[기재정정]연결재무제표기준영업(잠정)실적(공정공시)"),
    (CLASSIFIER / "20260807800028.xml", "earnings", "영업(잠정)실적(공정공시)"),
    (DOCUMENTS / "20260129800345.xml", "earnings", "매출액또는손익구조30%(대규모법인은15%)이상변경"),
    (CLASSIFIER / "20261102800520.xml", "unit_sales", "영업(잠정)실적(공정공시)"),
    (CLASSIFIER / "20261102800493.xml", "unit_sales", "영업(잠정)실적(공정공시)"),
    (DOCUMENTS / "20261029800269.xml", "dividend", "현금ㆍ현물배당결정"),
    (DOCUMENTS / "20261028800045.xml", "dividend", "현금ㆍ현물배당결정"),
    (DOCUMENTS / "20260331802678.xml", "dividend", "[기재정정]현금ㆍ현물배당결정"),
    (DOCUMENTS / "20261029800240.xml", "outlook", "[기재정정]영업실적등에대한전망(공정공시)"),
    (DOCUMENTS / "20261021800395.xml", "outlook",
     "[기재정정]연결재무제표기준영업실적등에대한전망(공정공시)"),
    (DOCUMENTS / "20260105800384.xml", "outlook", "영업실적등에대한전망(공정공시)"),
]  # fmt: skip


def _event(path: Path, category: str, report_nm: str, **changes) -> EventRow:
    document = read_event_document(path.read_bytes())
    table = table_for(category, normalise_dart_name(report_nm)[0])
    facts = tuple(
        EventFactRow(f.key, f.kind, f.unit, f.source_field, f.raw, f.value_decimal, f.value_date,
                     f.value_text, f.error)
        for f in (parse_table_facts(table, document.rows) if table else [])
    )  # fmt: skip
    event = EventRow("DART", path.stem, "00000000", "000000", report_nm, None, "", None, category,
                     None, report_nm.startswith("[기재정정]"), path.stem, None, None,
                     document.text, facts)  # fmt: skip
    return dataclasses.replace(event, **changes)


def _lines(event: EventRow) -> dict[str, list[str]]:
    template = event_template(event)
    assert template is not None, event.filing_key
    return template.lines


# -- direction -----------------------------------------------------------------------------------


def test_direction_compares_decimals_and_says_nothing_from_zero_or_a_loss() -> None:
    assert direction(Decimal("2"), Decimal("1")) == "up"
    assert direction(Decimal("1"), Decimal("2")) == "down"
    assert direction(Decimal("1.0"), Decimal("1.00")) == "same"
    assert direction(Decimal("5"), Decimal("0")) is None
    assert direction(Decimal("5"), Decimal("-3")) is None
    assert direction(Decimal("-5"), Decimal("3")) == "down"
    with pytest.raises(TypeError):
        direction(2.0, Decimal("1"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("current", "prior", "ko", "en"),
    [
        ("2", "1", "회사는 매출액이 전년 같은 기간보다 늘었다고 밝혔어요",
         "The company said revenue increased from the same period a year earlier."),
        ("1", "2", "회사는 매출액이 전년 같은 기간보다 줄었다고 밝혔어요",
         "The company said revenue decreased from the same period a year earlier."),
        ("2", "2", "회사는 매출액이 전년 같은 기간과 같았다고 밝혔어요",
         "The company said revenue was unchanged from the same period a year earlier."),
        ("2", "0", "회사는 매출액과 전년 같은 기간의 매출액을 함께 공시했어요",
         "The company disclosed revenue together with the figure for the same period a year "
         "earlier."),
        ("2", "-1", "회사는 매출액과 전년 같은 기간의 매출액을 함께 공시했어요",
         "The company disclosed revenue together with the figure for the same period a year "
         "earlier."),
    ],
)  # fmt: skip
def test_compare_lines(current, prior, ko, en) -> None:
    assert compare_lines(templates.REVENUE, templates.SAME_PERIOD, Decimal(current),
                         Decimal(prior)) == (ko, en)  # fmt: skip


def test_a_loss_a_year_earlier_gives_no_direction_in_the_summary() -> None:
    event = _event(*CASES[0])
    facts = tuple(dataclasses.replace(f, value_decimal=Decimal("-1"))
                  if f.key == "results_operating_income_year_ago" else f
                  for f in event.facts)  # fmt: skip
    lines = _lines(dataclasses.replace(event, facts=facts))
    assert lines["ko"][2] == "회사는 영업이익과 전년 같은 기간의 영업이익을 함께 공시했어요"
    assert "increased" not in lines["en"][2] and "decreased" not in lines["en"][2]


# -- wording on real filings ---------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c[0].stem for c in CASES])
def test_every_template_passes_the_guard_and_has_no_digits(case) -> None:
    lines = _lines(_event(*case))
    for lang in ("ko", "en"):
        assert len(lines[lang]) == 3
        assert check_summary(lines[lang], lang) == []
        assert summary_warnings(lines[lang], lang) == []
        for line in lines[lang]:
            assert not re.search(r"[0-9]", line), line
            assert not SPELLED.search(line), line
    assert lines["ko"][0].startswith("회사는")
    assert all(line.startswith("The company") for line in lines["en"])


def test_hyundai_results_wording() -> None:
    assert _lines(_event(*CASES[0])) == {
        "ko": ["회사는 연결 기준 잠정 실적을 공시했어요",
               "회사는 매출액이 전년 같은 기간보다 줄었다고 밝혔어요",
               "회사는 영업이익이 전년 같은 기간보다 늘었다고 밝혔어요"],
        "en": ["The company disclosed preliminary results on a consolidated basis.",
               "The company said revenue decreased from the same period a year earlier.",
               "The company said operating income increased from the same period a year "
               "earlier."],
    }  # fmt: skip


def test_corrections_say_the_filing_was_corrected() -> None:
    assert _lines(_event(*CASES[1]))["ko"][0] == "회사는 연결 기준 잠정 실적을 고쳐 다시 공시했어요"
    assert _lines(_event(*CASES[1]))["en"][0] == (
        "The company filed corrected preliminary results on a consolidated basis.")  # fmt: skip
    dividend = _lines(_event(*CASES[8]))
    assert dividend["ko"][0] == "회사는 결산 현금 배당 결정을 고쳐 다시 공시했어요"
    assert dividend["en"][0] == "The company filed a corrected decision on a year-end cash dividend."


def test_unit_sales_and_dividend_wording() -> None:
    assert _lines(_event(*CASES[4])) == {
        "ko": ["회사는 잠정 판매 실적을 공시했어요",
               "회사는 전체 판매 대수가 전년 같은 기간보다 줄었다고 밝혔어요",
               "회사는 누적 판매 대수가 전년 같은 기간보다 줄었다고 밝혔어요"],
        "en": ["The company disclosed preliminary unit sales.",
               "The company said the total number of units sold decreased from the same period "
               "a year earlier.",
               "The company said the cumulative number of units sold decreased from the same "
               "period a year earlier."],
    }  # fmt: skip
    assert _lines(_event(*CASES[6])) == {
        "ko": ["회사는 분기 현금 배당을 결정했어요",
               "회사는 보통주와 종류주의 주당 배당금과 시가배당률을 밝혔어요",
               "회사는 배당금 총액, 배당 기준일과 지급 예정일을 밝혔어요"],
        "en": ["The company decided on a quarterly cash dividend.",
               "The company stated the dividend per share and the dividend yield for common "
               "shares and other share classes.",
               "The company stated the total dividend, the record date and the planned "
               "payment date."],
    }  # fmt: skip
    hynix = _lines(_event(*CASES[7]))
    assert hynix["ko"][1:] == ["회사는 보통주의 주당 배당금과 시가배당률을 밝혔어요",
                               "회사는 배당금 총액과 배당 기준일을 밝혔어요"]  # fmt: skip


def test_outlook_templates_only_attribute_and_never_compare() -> None:
    corrected = _lines(_event(*CASES[9]))
    assert corrected == {
        "ko": ["회사는 영업실적 전망을 고쳐 다시 공시했어요",
               "회사는 판매 목표 전망치를 밝혔어요",
               "회사는 고치기 전과 고친 후의 전망치를 함께 밝혔어요"],
        "en": ["The company filed a corrected outlook for results.",
               "The company stated outlook figures for sales targets.",
               "The company stated the outlook figures before and after the correction."],
    }  # fmt: skip
    original = _lines(_event(*CASES[11]))
    assert original["ko"][0] == "회사는 영업실적 전망을 공시했어요"
    assert original["ko"][2] == "회사는 이 전망이 예측 정보로서 실제 결과와 다를 수 있다고 밝혔어요"
    assert original["en"][2] == (
        "The company said the outlook is projected information and actual results may differ.")
    for case in CASES[9:]:
        for line in _lines(_event(*case))["en"]:
            assert "forecast" not in line.lower()  # N3 blocks forecast*; outlook is used
        for line in _lines(_event(*case))["ko"]:
            assert "실적보다" not in line and "늘었" not in line and "줄었" not in line


def test_an_outlook_without_the_caveat_or_changes_goes_to_the_model() -> None:
    event = _event(*CASES[11], body_text="본문")
    assert event_template(event) is None


def test_missing_facts_send_the_filing_to_the_model() -> None:
    event = _event(*CASES[0])
    without = tuple(f for f in event.facts if f.key != "results_revenue_year_ago")
    assert event_template(dataclasses.replace(event, facts=without)) is None
    assert event_template(dataclasses.replace(event, facts=())) is None
    assert event_template(dataclasses.replace(event, category="buyback")) is None
    assert event_template(dataclasses.replace(event, regulator="SEC")) is None
    errored = tuple(dataclasses.replace(f, error="bad") for f in event.facts)
    assert event_template(dataclasses.replace(event, facts=errored)) is None
    # 장래사업ㆍ경영계획 has no table facts: the model writes it.
    plan = _event(DOCUMENTS / "20261029800102.xml", "outlook", "장래사업ㆍ경영계획(공정공시)")
    assert plan.facts == () and event_template(plan) is None


# -- cache key -----------------------------------------------------------------------------------


def test_the_template_version_and_the_facts_are_part_of_the_cache_key(monkeypatch) -> None:
    event = _event(*CASES[0])
    template = event_template(event)
    assert template is not None
    key = template_input_sha256(template, load_lexicon().version)
    assert key == summary_input_sha256(template.source_text, TEMPLATE_MODEL, "summary",
                                       TEMPLATE_VERSION, load_lexicon().version)  # fmt: skip
    assert template_input_sha256(template, load_lexicon().version + 1) != key
    monkeypatch.setattr(templates, "TEMPLATE_VERSION", "t-next")
    assert template_input_sha256(template, load_lexicon().version) != key
    monkeypatch.undo()
    changed = tuple(dataclasses.replace(f, value_decimal=f.value_decimal + 1)
                    if f.key == "results_revenue_current" else f for f in event.facts)  # fmt: skip
    other = event_template(dataclasses.replace(event, facts=changed))
    assert other is not None and template_input_sha256(other, load_lexicon().version) != key
    # The model, the prompt version and the body text do not change a template's key.
    assert event_summary_key(event, "x", "m1", "p1", 2) == event_summary_key(event, "y", "m2",
                                                                             "p2", 2)  # fmt: skip
    # A filing with no template keeps the model key.
    plain = dataclasses.replace(event, facts=())
    assert event_summary_key(plain, "text", MODEL, "p1", 2) == summary_input_sha256(
        "text", MODEL, "summary", "p1", 2)


def _seed() -> tuple:
    data = fixture_build_input()
    events = tuple(dataclasses.replace(e, body_text=e.body_text or f"본문 {e.filing_key}")
                   for e in data.events)  # fmt: skip
    return dataclasses.replace(data, events=events)


def test_the_exporter_and_the_summary_build_agree_on_the_template_key() -> None:
    data = _seed()
    targets = select_targets(data, AS_OF)
    templated = [t for t in targets if t.template is not None]
    assert [t.filing_id for t in templated] == ["dart:20261029800099"]  # the seeded correction
    build = _Build(data, BuildOptions(AS_OF, "test", llm_model=MODEL,
                                      prompt_version=summaries.PROMPT_VERSION),
                   PinnedResponses(PINNED_DIRS))  # fmt: skip
    build.filing_kinds = {t.filing_id: t.kind for t in targets}
    build.events = {f"{e.regulator.lower()}:{e.filing_key}": e for e in data.events}
    for target in templated:
        key = template_input_sha256(target.template, load_lexicon().version)
        assert export.current_input_sha256(build, target.filing_id, "summary") == key
    for target in targets:
        if target.kind == "event" and target.template is None:
            event = build.events[target.filing_id]
            assert export.current_input_sha256(build, target.filing_id, "summary") == (
                summary_input_sha256(event_source_text(event), MODEL, "summary",
                                     summaries.EVENT_PROMPT_VERSION, load_lexicon().version))  # fmt: skip


# -- generate ------------------------------------------------------------------------------------


class _Model:
    """A model client; every call is recorded and answered from the queue."""

    def __init__(self, *bodies: dict) -> None:
        self.bodies = [json.dumps(b, ensure_ascii=False) for b in bodies]
        self.calls = 0

    async def complete(self, messages, *, response_format=None, temperature=0.2,
                       max_tokens=1024) -> LLMResult:  # fmt: skip
        self.calls += 1
        assert self.bodies, "unexpected model call"
        return LLMResult(self.bodies.pop(0), MODEL, "stop", 10, 10, {})


CLEAN = {
    "ko_line1": "회사는 장래 사업 계획을 공시했어요",
    "ko_line2": "회사는 반도체 투자 계획을 밝혔어요",
    "ko_line3": "회사는 투자 내용이 바뀔 수 있다고 밝혔어요",
    "en_line1": "The company disclosed its business plan.",
    "en_line2": "The company stated its plan for semiconductor investment.",
    "en_line3": "The company said the investment may change.",
}


def _template_target(case=CASES[0]) -> Target:
    event = _event(*case)
    return Target(f"dart:{event.filing_key}", "event", "summary", (), event_source_text(event),
                  None, event.category, event_template(event))  # fmt: skip


def _model_target() -> Target:
    event = _event(DOCUMENTS / "20261029800102.xml", "outlook", "장래사업ㆍ경영계획(공정공시)")
    return Target(f"dart:{event.filing_key}", "event", "summary", (), event_source_text(event),
                  None, "outlook", None)  # fmt: skip


def _run(client, targets, tmp_path, **kwargs):
    return asyncio.run(generate(client, targets, model=MODEL,
                                staged_path=tmp_path / "staged.jsonl",
                                approved_path=tmp_path / "approved.jsonl",
                                calls_path=tmp_path / "calls.jsonl", **kwargs))  # fmt: skip


def test_a_templated_filing_is_staged_with_no_model_call(tmp_path) -> None:
    target = _template_target()
    client = _Model()
    result, stats = _run(client, [target], tmp_path, max_calls=0, limit=0)
    assert client.calls == 0 and stats.calls == 0
    assert [t.filing_id for t, _ in result.templated] == [target.filing_id]
    rows = read_jsonl(tmp_path / "staged.jsonl")
    assert [(r["lang"], r["review_state"]) for r in rows] == [("en", "staged"), ("ko", "staged")]
    for row in rows:
        assert row["model"] == TEMPLATE_MODEL
        assert row["prompt_version"] == TEMPLATE_VERSION
        assert row["reviewer_flags"] is None  # never approved by --all-reviewed
        assert row["violations"] == [] and row["warnings"] == []
        assert row["input_sha256"] == template_input_sha256(target.template,
                                                            load_lexicon().version)  # fmt: skip
        assert [row["line1"], row["line2"], row["line3"]] == target.template.lines[row["lang"]]
    log = read_jsonl(tmp_path / "calls.jsonl")
    assert [(e["purpose"], e["cache"], e["model"]) for e in log] == [
        ("generate", "template", TEMPLATE_MODEL)]
    assert log[0]["tokens_in"] is None

    # The second run finds it in the staged file: a hit, still no call.
    again, _ = _run(client, [target], tmp_path)
    assert (again.cached, again.templated, client.calls) == (1, [], 0)
    assert read_jsonl(tmp_path / "calls.jsonl")[-1]["cache"] == "hit"


def test_a_filing_with_no_template_falls_back_to_the_model(tmp_path) -> None:
    client = _Model(CLEAN, {"flags": []})
    result, stats = _run(client, [_template_target(), _model_target()], tmp_path)
    assert client.calls == stats.calls == 2  # generate and review for the prose filing only
    assert result.generated == 1 and len(result.templated) == 1
    models = {(r["filing_id"], r["model"]) for r in read_jsonl(tmp_path / "staged.jsonl")}
    assert models == {("dart:20261029800228", TEMPLATE_MODEL), ("dart:20261029800102", MODEL)}


def test_a_dry_run_lists_templates_and_writes_nothing(tmp_path) -> None:
    result, stats = _run(None, [_template_target(), _model_target()], tmp_path, dry_run=True)
    assert [t.filing_id for t, _ in result.templated] == ["dart:20261029800228"]
    assert [t.filing_id for t, _ in result.planned] == ["dart:20261029800102"]
    assert stats.calls == 0 and not (tmp_path / "staged.jsonl").exists()
    assert not (tmp_path / "calls.jsonl").exists()


def test_a_template_line_the_guard_rejects_is_withheld(tmp_path) -> None:
    target = _template_target()
    bad = dataclasses.replace(target.template, lines={
        "ko": ["회사는 실적이 급증했다고 밝혔어요", *target.template.lines["ko"][1:]],
        "en": target.template.lines["en"]})  # fmt: skip
    _run(_Model(), [dataclasses.replace(target, template=bad)], tmp_path)
    rows = {r["lang"]: r for r in read_jsonl(tmp_path / "staged.jsonl")}
    # Both languages are withheld together, as a model summary is.
    assert {r["review_state"] for r in rows.values()} == {"withheld"}
    assert rows["ko"]["violations"] and rows["en"]["violations"] == []


def test_the_outlook_prompt_attributes_and_avoids_forecast() -> None:
    prompt = summaries.event_system_prompt("outlook")
    assert "Attribute every outlook" in prompt and "never forecast" in prompt
    assert summaries.CATEGORY_GUIDANCE["outlook"] not in summaries.event_system_prompt()
    clarification = summaries.event_system_prompt("clarification")
    assert "will file again" in clarification and "without the date" in clarification
    for category in ("management", "shareholder_value", "meeting", "operations", "lending"):
        assert summaries.CATEGORY_GUIDANCE[category] in summaries.event_system_prompt(category)
    target = _model_target()
    assert summaries.system_prompt(target) == summaries.event_system_prompt("outlook")
